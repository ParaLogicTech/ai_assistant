import asyncio
import logging
import time
from collections.abc import AsyncIterator, Sequence
from itertools import count
from typing import Any, TypeVar

from pydantic_ai import Agent as PydanticAgent
from pydantic_ai import AgentRunResultEvent, RunCancelled
from pydantic_ai.capabilities.abstract import AbstractCapability
from pydantic_ai.messages import (
	FunctionToolCallEvent,
	FunctionToolResultEvent,
	PartDeltaEvent,
	PartStartEvent,
	RetryPromptPart,
	TextPart,
	TextPartDelta,
)
from pydantic_ai.models import Model
from pydantic_ai.run import AgentRunResult
from pydantic_ai.tools import DeferredToolRequests

from ai_assistant.capabilities.cancellation import Cancellation
from ai_assistant.capabilities.error_handling import ErrorAction, ErrorHandling, masked
from ai_assistant.capabilities.hitl import ASK_TOOL_NAME, HITL, Opening
from ai_assistant.capabilities.tools import is_failure
from ai_assistant.core.content import (
	Error,
	Event,
	FormContent,
	FormReply,
	Outcome,
	TextContent,
	content_of,
)
from ai_assistant.core.context import Context
from ai_assistant.core.key_value_store import KeyValueStore
from ai_assistant.core.session import Session

__all__ = ["Agent"]

logger = logging.getLogger(__name__)

C = TypeVar("C", bound=AbstractCapability[Session])

# How often a stream re-reads the stop between deltas, so a long answer can be cut
# short mid-response without a store read per token. Also the pace a wait before a
# retry looks for one.
STREAM_CANCELLATION_CHECK_SECONDS = 0.25


class Agent:
	"""A composable agent over Pydantic AI, built from capabilities.

	A turn has TWO channels: `ainvoke` returns ONE outcome - the answer, the form it
	paused on, or the `Error` it ended in - and `astream` delivers what the turn does
	along the way as `Event`s, ending on an `outcome` event carrying the same block
	`ainvoke` would return.

	Cancellation is core and always installed, since a turn cannot be stopped from
	elsewhere without it. A stop is written through `Cancellation.request`.

	WITH `ErrorHandling` installed a failed attempt may be tried again, as its policy
	decides; without it a turn runs once and a failure ends it, masked. WITH `HITL`
	installed a turn may end on a form, and the next request of the run answers it
	by passing `reply`.
	"""

	def __init__(
		self,
		model: Model,
		*,
		key_value_store: KeyValueStore,
		capabilities: Sequence[AbstractCapability[Session]] = (),
		instructions: str | None = None,
	) -> None:
		"""Builds the agent.

		Args:
			model: What every turn runs on unless it names another and `Models` is
				installed to build it.
			key_value_store: Where a stop is written and read.
			capabilities: The opt-in capabilities this deployment wires.
			instructions: The agent's standing instructions.
		"""

		self.__cancellation = Cancellation(key_value_store)
		self.__errors = _installed(capabilities, ErrorHandling) or ErrorHandling(max_attempts=1)
		self.__hitl = _installed(capabilities, HITL)
		self.agent = PydanticAgent(
			model,
			deps_type=Session,
			# A run that asks a person ends on the call it deferred.
			output_type=[str, DeferredToolRequests],
			instructions=instructions,
			capabilities=[
				self.__cancellation,
				*capabilities,
			],
		)

	async def ainvoke(
		self,
		content: str | Sequence[TextContent],
		context: Context,
		*,
		reply: FormReply | None = None,
	) -> Outcome:
		"""Runs one turn, and returns how it ended. Never raises for a failure.

		Args:
			content: What is said. May be empty beside a `reply`.
			context: The turn's context.
			reply: The answer to, or refusal of, the form the run is waiting on.
		"""

		opening = await self.__open(context, reply)

		if opening.outcome is not None:
			return opening.outcome

		for attempt in count(1):
			session = self.__session(context, opening)

			try:
				result = await self.agent.run(**self.__run_args(content, context, session, opening))
				return await self.__ended(result, context)
			except Exception as exc:
				ending, delay = await self.__failed(exc, context, attempt, can_retry=not session.spoken)

			if ending is None:
				ending = await self.__waited(delay, context)

			if ending is not None:
				return ending

		raise AssertionError("unreachable")

	async def astream(
		self,
		content: str | Sequence[TextContent],
		context: Context,
		*,
		reply: FormReply | None = None,
	) -> AsyncIterator[Event]:
		"""Runs one turn, yielding what it does, and ends on its outcome.

		Yields:
			Event: A `form_submitted`, `form_cancelled` or `form_dismissed` first where
				the run was waiting on a form; then a `text_delta` per piece of the
				answer as it arrives, a `tool_started` and a `tool_ended` around each
				tool call, a `retry_scheduled` before a failed attempt is tried again;
				then exactly one `outcome` whose data is the outcome's content block.
		"""

		opening = await self.__open(context, reply)

		for event in opening.events:
			yield event

		outcome = opening.outcome

		for attempt in count(1):
			if outcome is not None:
				break

			session = self.__session(context, opening)
			# What the person has seen of this attempt, which a retry would say again.
			shown = False

			try:
				async with self.agent.run_stream_events(
					**self.__run_args(content, context, session, opening),
				) as events:
					checked = time.monotonic()

					async for event in events:
						if (said := _said(event)) is not None:
							shown = True
							yield said
						elif isinstance(event, AgentRunResultEvent):
							outcome = await self.__ended(event.result, context)

						if time.monotonic() - checked >= STREAM_CANCELLATION_CHECK_SECONDS:
							checked = time.monotonic()

							if await self.__cancellation.requested(context.request_id):
								raise RunCancelled("The turn was cancelled.")

				if outcome is None:
					raise RuntimeError("The stream ended without a result.")
			except Exception as exc:
				outcome, delay = await self.__failed(
					exc,
					context,
					attempt,
					can_retry=not (session.spoken or shown),
				)

				if outcome is None:
					yield Event(name="retry_scheduled", data={"attempt": attempt, "delay": delay})
					outcome = await self.__waited(delay, context)

		yield Event(name="outcome", data=content_of(outcome).model_dump(mode="json"))

	async def __open(self, context: Context, reply: FormReply | None) -> Opening:
		"""How the turn starts, given the form its run may be waiting on."""

		if self.__hitl is None:
			if reply is None:
				return Opening()

			return Opening(
				outcome=Error(
					type="invalid_request",
					code="invalid_request",
					title="Invalid request",
					detail="This assistant asks no questions, so there is nothing to answer.",
					instance_id=context.request_id,
				),
			)

		try:
			return await self.__hitl.open(context, reply)
		except Exception as exc:
			# A pause that cannot be read is no pause to a new message, which runs without it.
			if reply is None:
				logger.exception("Could not read the pause of run [%s]; running without it.", context.run_id)
				return Opening()

			return Opening(outcome=masked(exc, context))

	@staticmethod
	def __session(context: Context, opening: Opening) -> Session:
		# A resume's messages already carry the run's earlier turns.
		return Session(context=context, history_loaded=opening.messages is not None)

	@staticmethod
	def __run_args(
		content: str | Sequence[TextContent],
		context: Context,
		session: Session,
		opening: Opening,
	) -> dict[str, Any]:
		said = content if isinstance(content, str) else "\n\n".join(block.text for block in content)

		return {
			# Nothing said beside an answer resumes on the answer alone.
			"user_prompt": said or None,
			"deps": session,
			# The NAME, resolved by `Models` through the framework's resolution chain.
			"model": context.model,
			"model_settings": context.model_args or None,
			"conversation_id": context.run_id,
			"message_history": opening.messages,
			"deferred_tool_results": opening.results,
		}

	async def __ended(self, result: AgentRunResult[Any], context: Context) -> TextContent | FormContent:
		"""The outcome of a run that ended: its answer, or the form it paused on."""

		if isinstance(result.output, DeferredToolRequests):
			if self.__hitl is None:
				raise RuntimeError("The run deferred a call, and nothing here can answer it.")

			form = await self.__hitl.pause(context, result.output, result.all_messages_json())

			return FormContent(form=form)

		return TextContent(
			text=result.output,
			metadata={"model_name": result.response.model_name},
		)

	async def __failed(
		self,
		exc: Exception,
		context: Context,
		attempt: int,
		*,
		can_retry: bool,
	) -> tuple[Error | None, float]:
		"""The `Error` an attempt ended the turn in, or `None` and the wait before trying again."""

		if isinstance(exc, RunCancelled):
			# A stop seen mid-stream ends the run outside `wrap_run`, so it is cleared here too.
			await self.__cancellation.consume(context.request_id)

			return _cancelled(context), 0.0

		resolution = await self.__errors.resolve(exc, context, attempt, can_retry=can_retry)

		if resolution.action is ErrorAction.RETRY:
			return None, self.__errors.delay(attempt, resolution)

		# A stop left standing for a retry that will not come would cancel nothing, but
		# is cleared rather than left to its lifetime.
		await self.__cancellation.consume(context.request_id)

		return resolution.error, 0.0

	async def __waited(self, seconds: float, context: Context) -> Error | None:
		"""Waits before a retry, ending the turn `cancelled` where a stop is written meanwhile."""

		deadline = time.monotonic() + seconds

		while True:
			if await self.__cancellation.requested(context.request_id):
				await self.__cancellation.consume(context.request_id)
				return _cancelled(context)

			if (remaining := deadline - time.monotonic()) <= 0:
				return None

			await asyncio.sleep(min(remaining, STREAM_CANCELLATION_CHECK_SECONDS))


def _installed(capabilities: Sequence[AbstractCapability[Session]], kind: type[C]) -> C | None:
	"""The one capability of a kind the deployment listed, refusing two."""

	found = [capability for capability in capabilities if isinstance(capability, kind)]

	if len(found) > 1:
		raise ValueError(f"Only one {kind.__name__} may be installed.")

	return found[0] if found else None


def _cancelled(context: Context) -> Error:
	return Error(
		type="cancelled",
		code="cancelled",
		title="Cancelled",
		detail="The turn was cancelled.",
		instance_id=context.request_id,
	)


def _said(event: Any) -> Event | None:
	"""What a framework event shows the person, where it shows anything.

	The ask tool's own call is not shown: its question is the turn's outcome.
	"""

	if (text := _text_of(event)) is not None:
		return Event(name="text_delta", data={"text": text})

	if isinstance(event, FunctionToolCallEvent) and event.part.tool_name != ASK_TOOL_NAME:
		return Event(
			name="tool_started",
			data={
				"id": event.part.tool_call_id,
				"name": event.part.tool_name,
				"args": event.part.args_as_dict(),
			},
		)

	if isinstance(event, FunctionToolResultEvent) and event.part.tool_name != ASK_TOOL_NAME:
		return Event(
			name="tool_ended",
			data={
				"id": event.part.tool_call_id,
				"name": event.part.tool_name,
				# A call the model got wrong is answered with a retry prompt.
				"failed": isinstance(event.part, RetryPromptPart) or is_failure(event.part.content),
			},
		)

	return None


def _text_of(event: Any) -> str | None:
	"""The answer text an event adds, where it adds any."""

	if isinstance(event, PartStartEvent) and isinstance(event.part, TextPart):
		return event.part.content or None

	if isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta):
		return event.delta.content_delta or None

	return None
