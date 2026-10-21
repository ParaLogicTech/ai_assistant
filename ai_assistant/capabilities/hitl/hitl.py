import logging
from dataclasses import dataclass, field

from pydantic import BaseModel, Field
from pydantic_ai import ModelRetry, RunContext, Tool
from pydantic_ai.capabilities.abstract import AbstractCapability
from pydantic_ai.exceptions import CallDeferred
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter
from pydantic_ai.tools import DeferredToolRequests, DeferredToolResults
from pydantic_ai.toolsets import AbstractToolset, FunctionToolset

from ai_assistant.capabilities.hitl.forms import (
	InvalidAnswerError,
	answered,
	declined,
	problem_with,
	validated,
)
from ai_assistant.core.content import (
	Error,
	Event,
	Form,
	FormCancellation,
	FormContent,
	FormField,
	FormReply,
	FormSubmission,
	Outcome,
)
from ai_assistant.core.context import Context
from ai_assistant.core.key_value_store import KeyValueStore
from ai_assistant.core.session import Session

__all__ = [
	"ASK_TOOL_NAME",
	"HITL",
	"Opening",
	"Pause",
]

logger = logging.getLogger(__name__)

ASK_TOOL_NAME = "request_input"
HITL_TOOLSET_ID = "ai_assistant.hitl"
PAUSE_KEY_PREFIX = "ai_assistant:pause"

# How long a run stays answerable after it stops to ask. Kept in the cache, so a
# pause is not durable: one lost is a question that expired.
DEFAULT_PAUSE_TTL_SECONDS = 24 * 60 * 60

ASK_TOOL_DESCRIPTION = """\
Ask the user for something only they can tell you, as a form they fill in. The run pauses \
until they answer, and their answer comes back as this call's result.

This is the ONLY way to ask the user anything: a question written in your reply text is \
never answered. Use it when you are missing something a person decides or knows: which of \
several things they meant, a value you would otherwise guess, a confirmation before \
something that cannot be undone. Do not use it for anything a tool could tell you.

Where the answer is one of the records you found, offer them as a `select` field's \
`options` instead of listing them in your reply.

ONE FORM PER CALL, and one call at a time: ask everything you need now in this one form.

Make answering cheap. Offer `options` wherever the answer is one of a few things, and \
pre-fill `default` with your best guess. Ask for the fewest fields that unblock you."""

EXPIRED_DETAIL = "That question is no longer waiting for an answer."


def pause_key(run_id: str) -> str:
	return f"{PAUSE_KEY_PREFIX}:{run_id}"


class Question(BaseModel):
	"""The form the model asks, without what is minted for it: an id, an error."""

	title: str = Field(
		description='The question itself, as a short heading, such as "Which customer did you mean?".',
	)
	description: str | None = Field(default=None, description="What the answer is for, beneath the heading.")
	fields: list[FormField] = Field(
		description="What to ask for, one input each - the fewest that unblock you.",
	)


class Pause(BaseModel):
	"""A run stopped on a question: what it asked, and the turn so far to go on from."""

	form: Form
	tool_call_id: str = Field(description="The deferred call the answer resumes.")
	request_id: str = Field(description="The request the turn paused in.")
	messages: str = Field(description="The turn's messages, as `ModelMessagesTypeAdapter` JSON.")


@dataclass
class Opening:
	"""How a turn starts, given what was said to the form its run waits on."""

	# Reported before the turn runs: a form answered, declined or passed over.
	events: list[Event] = field(default_factory=list)

	# Where the turn ends before running: an answer to nothing, or one handed back.
	outcome: Outcome | None = None

	# Where the turn resumes a pause: the messages it goes on from, and the answer.
	messages: list[ModelMessage] | None = None
	results: DeferredToolResults | None = None


class HITL(AbstractCapability[Session]):
	"""The model's line to a person: it asks one form, the turn stops, and the next
	request of the run answers it and goes on from where it stopped.

	SIMPLE BY DESIGN. One form waits per run at a time, kept in the shared cache
	with a lifetime and no engine behind it. An answer is taken once: the pause is
	cleared as it resumes, so a resume that fails does not ask again. A new message
	sent while a form waits passes over it.
	"""

	def __init__(
		self,
		key_value_store: KeyValueStore,
		*,
		pause_ttl_seconds: int = DEFAULT_PAUSE_TTL_SECONDS,
	) -> None:
		self.key_value_store = key_value_store
		self.pause_ttl_seconds = pause_ttl_seconds

	def get_toolset(self) -> AbstractToolset[Session] | None:
		return FunctionToolset(tools=[_ask_tool()], id=HITL_TOOLSET_ID)

	async def pause(
		self,
		context: Context,
		requests: DeferredToolRequests,
		messages: bytes,
	) -> Form:
		"""Keeps the question a run ended on, and returns it to hand the person.

		Raises:
			RuntimeError: Where the run deferred a call that is not a question, which
				nothing here can answer.
		"""

		asked = [call for call in requests.calls if call.tool_name == ASK_TOOL_NAME]

		if requests.approvals or len(asked) != 1 or len(requests.calls) != 1:
			raise RuntimeError(f"The run deferred calls nothing can answer: {requests}.")

		call = asked[0]
		form = Form.model_validate(requests.metadata[call.tool_call_id]["form"])
		pause = Pause(
			form=form,
			tool_call_id=call.tool_call_id,
			request_id=context.request_id,
			messages=messages.decode(),
		)

		await self.key_value_store.set(
			pause_key(context.run_id),
			pause.model_dump_json(),
			ttl=self.pause_ttl_seconds,
		)

		return form

	async def open(self, context: Context, reply: FormReply | None) -> Opening:
		"""How a turn starts, given what was said to the form its run waits on, if anything."""

		pause = await self.__pending(context.run_id)

		if reply is None:
			if pause is None:
				return Opening()

			# Moving on passes the question over, so it is never answered late.
			await self.__clear(context.run_id)

			return Opening(events=[Event(name="form_dismissed", data={"form_id": pause.form.id})])

		if pause is None or pause.form.id != reply.form_id:
			return Opening(
				outcome=Error(
					type="question_expired",
					code="question_expired",
					title="Nothing to answer",
					detail=EXPIRED_DETAIL,
					instance_id=context.request_id,
				),
			)

		if isinstance(reply, FormCancellation):
			result = declined(pause.form, reply.reason)
			event = Event(name="form_cancelled", data={"form_id": pause.form.id, "reason": reply.reason})
		else:
			try:
				values = validated(pause.form, reply.values)
			except InvalidAnswerError as refused:
				# Handed back to fix, the same form under the same id, still waiting.
				return Opening(
					outcome=FormContent(form=pause.form.model_copy(update={"error": str(refused)})),
				)

			result = answered(pause.form, values)
			# The names and never the values, which may be anything a person was asked.
			event = Event(name="form_submitted", data={"form_id": pause.form.id, "fields": list(values)})

		await self.__clear(context.run_id)

		return Opening(
			events=[event],
			messages=ModelMessagesTypeAdapter.validate_json(pause.messages),
			results=DeferredToolResults(calls={pause.tool_call_id: result}),
		)

	async def __pending(self, run_id: str) -> Pause | None:
		raw = await self.key_value_store.get(pause_key(run_id))

		if raw is None:
			return None

		try:
			return Pause.model_validate_json(raw)
		except ValueError:
			logger.exception("The pause of run [%s] could not be read; dropping it.", run_id)
			await self.__clear(run_id)
			return None

	async def __clear(self, run_id: str) -> None:
		await self.key_value_store.delete(pause_key(run_id))


def _ask_tool() -> Tool[Session]:
	async def request_input(ctx: RunContext[Session], form: Question) -> str:
		"""Asks the user for what only they can say, pausing the run for it.

		Args:
			form: What to ask, as one form.
		"""

		session = ctx.deps

		# One question at a time: a second is answered here, and asked once the first is.
		if session.asking is not None:
			return (
				f'The user has not answered "{session.asking.title}" yet. '
				"Ask this once they have, folded into a single form where you can."
			)

		asked = Form(title=form.title.strip(), description=form.description, fields=form.fields)

		if (problem := problem_with(asked)) is not None:
			raise ModelRetry(problem)

		session.asking = asked

		raise CallDeferred(metadata={"form": asked.model_dump(mode="json")})

	# Run alone, so what the model called before it has run by the time the person is asked.
	return Tool(
		request_input,
		name=ASK_TOOL_NAME,
		description=ASK_TOOL_DESCRIPTION,
		sequential=True,
	)
