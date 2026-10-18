import logging
import time
from collections.abc import AsyncIterator, Sequence
from typing import Any

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

from ai_assistant.capabilities.cancellation import Cancellation
from ai_assistant.capabilities.tools import is_failure
from ai_assistant.core.content import Error, Event, Outcome, TextContent, content_of
from ai_assistant.core.context import Context
from ai_assistant.core.errors import AgentError
from ai_assistant.core.key_value_store import KeyValueStore
from ai_assistant.core.session import Session

__all__ = ["Agent"]

logger = logging.getLogger(__name__)

# How often a stream re-reads the stop between deltas, so a long answer can be cut
# short mid-response without a store read per token.
STREAM_CANCELLATION_CHECK_SECONDS = 0.25


class Agent:
	"""A composable agent over Pydantic AI, built from capabilities.

	A turn has TWO channels: `ainvoke` returns ONE outcome - the answer, or the `Error`
	it ended in - and `astream` delivers what the turn does along the way as `Event`s,
	ending on an `outcome` event carrying the same block `ainvoke` would return.

	Cancellation is core and always installed, since a turn cannot be stopped from
	elsewhere without it. A stop is written through `Cancellation.request`.
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
		self.agent = PydanticAgent(
			model,
			deps_type=Session,
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
	) -> Outcome:
		"""Runs one turn, and returns how it ended. Never raises for a failure."""

		try:
			result = await self.agent.run(**self.__run_args(content, context))
		except Exception as exc:
			return await self.__failed(exc, context)

		return self.__answer(result)

	async def astream(
		self,
		content: str | Sequence[TextContent],
		context: Context,
	) -> AsyncIterator[Event]:
		"""Runs one turn, yielding what it does, and ends on its outcome.

		Yields:
			Event: A `text_delta` per piece of the answer as it arrives, a `tool_started`
				and a `tool_ended` around each tool call, then exactly one `outcome`
				whose data is the outcome's content block.
		"""

		outcome: Outcome | None = None

		try:
			async with self.agent.run_stream_events(**self.__run_args(content, context)) as events:
				checked = time.monotonic()

				async for event in events:
					if (text := _text_of(event)) is not None:
						yield Event(name="text_delta", data={"text": text})
					elif isinstance(event, FunctionToolCallEvent):
						yield Event(
							name="tool_started",
							data={
								"id": event.part.tool_call_id,
								"name": event.part.tool_name,
								"args": event.part.args_as_dict(),
							},
						)
					elif isinstance(event, FunctionToolResultEvent):
						yield Event(
							name="tool_ended",
							data={
								"id": event.part.tool_call_id,
								"name": event.part.tool_name,
								# A call the model got wrong is answered with a retry prompt.
								"failed": isinstance(event.part, RetryPromptPart)
								or is_failure(event.part.content),
							},
						)
					elif isinstance(event, AgentRunResultEvent):
						outcome = self.__answer(event.result)

					if time.monotonic() - checked >= STREAM_CANCELLATION_CHECK_SECONDS:
						checked = time.monotonic()

						if await self.__cancellation.requested(context.request_id):
							raise RunCancelled("The turn was cancelled.")
		except Exception as exc:
			outcome = await self.__failed(exc, context)

		if outcome is None:
			outcome = await self.__failed(RuntimeError("The stream ended without a result."), context)

		yield Event(name="outcome", data=content_of(outcome).model_dump(mode="json"))

	@staticmethod
	def __run_args(
		content: str | Sequence[TextContent],
		context: Context,
	) -> dict[str, Any]:
		said = content if isinstance(content, str) else "\n\n".join(block.text for block in content)

		return {
			"user_prompt": said,
			"deps": Session(context=context),
			# The NAME, resolved by `Models` through the framework's resolution chain.
			"model": context.model,
			"model_settings": context.model_args or None,
			"conversation_id": context.run_id,
		}

	@staticmethod
	def __answer(result: AgentRunResult[Any]) -> TextContent:
		return TextContent(
			text=result.output,
			metadata={"model_name": result.response.model_name},
		)

	async def __failed(self, exc: Exception, context: Context) -> Error:
		"""The `Error` a turn ended in, masked unless it is safe to show."""

		if isinstance(exc, RunCancelled):
			# A stop seen mid-stream ends the run outside `wrap_run`, so it is cleared here too.
			await self.__cancellation.consume(context.request_id)

			return Error(
				type="cancelled",
				code="cancelled",
				title="Cancelled",
				detail="The turn was cancelled.",
				instance_id=context.request_id,
			)

		if (refused := _agent_error(exc)) is not None:
			error = refused.to_error()
			error.instance_id = context.request_id

			return error

		logger.exception("Request [%s] of run [%s] failed.", context.request_id, context.run_id)

		return Error(
			type="internal",
			code="internal",
			title="Something went wrong",
			detail="The turn failed. Try again, or quote the instance id to support.",
			instance_id=context.request_id,
		)


def _text_of(event: Any) -> str | None:
	"""The answer text an event adds, where it adds any."""

	if isinstance(event, PartStartEvent) and isinstance(event.part, TextPart):
		return event.part.content or None

	if isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta):
		return event.delta.content_delta or None

	return None


def _agent_error(exc: BaseException) -> AgentError | None:
	"""The `AgentError` behind an exception, where the framework wrapped one."""

	seen: set[int] = set()
	current: BaseException | None = exc

	while current is not None and id(current) not in seen:
		if isinstance(current, AgentError):
			return current

		seen.add(id(current))
		current = current.__cause__ or current.__context__

	return None
