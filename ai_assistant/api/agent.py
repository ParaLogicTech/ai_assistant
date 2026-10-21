import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import fields
from typing import Any

import frappe
import httpx
from frappe import _
from pydantic import TypeAdapter, ValidationError
from werkzeug.wrappers import Response

from ai_assistant.agent import Agent
from ai_assistant.capabilities.cancellation import Cancellation
from ai_assistant.capabilities.error_handling import ErrorHandling
from ai_assistant.capabilities.history import History
from ai_assistant.capabilities.hitl import HITL
from ai_assistant.capabilities.models import DEFAULT_MODEL, MODEL_REGISTRY, Models
from ai_assistant.capabilities.tools import Tools
from ai_assistant.config.llm import LLMSettings, llm_settings
from ai_assistant.core import Context, Event, FormReply, FormSubmission, TextContent
from ai_assistant.infra.conversation_store import FrappeConversationStore
from ai_assistant.infra.key_value_store import FrappeCacheStore
from ai_assistant.infra.litellm import LiteLLMModelFactory
from ai_assistant.infra.tools import site_tools
from ai_assistant.infra.transcript import THREAD, open_thread, record_answer, record_question, resolve_form

# A turn's model call may run long; connecting should not.
HTTP_TIMEOUT = httpx.Timeout(120.0, connect=10.0)

# The agent's standing instructions, filled in per turn.
INSTRUCTIONS = """\
You are the AI assistant inside {site}, a Frappe site. You are helping {user}. Today is {today}.

Read the site's data with your tools rather than guessing, and say so when they cannot answer. \
Describe a DocType before listing its documents if you do not know its fields. \
If a tool says something is not permitted, tell the user rather than working around it.

Asking the user:
- Ask every question through the `request_input` tool, which shows the user a form. Never ask a \
question in your reply text, and never end a reply waiting on an answer the user would have to type.
- Ask when the request leaves out something only the user can decide: which record they mean, a \
period, an amount, a choice between readings of what they said. Ask before anything you cannot undo.
- Look first, then ask: read what you can with your tools, and offer what you found as a select's \
`options` (the matching customers, the open orders) rather than listing them in your reply. Keep \
options to the likeliest ten or so, and pre-fill `default` with your best guess.
- Do not ask for what a tool can tell you, and do not ask when the request is already clear.

Answer in Markdown, concisely, and lead with the answer."""

_BLOCKS = TypeAdapter(list[TextContent])
_REPLY = TypeAdapter(FormReply)
_CONTEXT = TypeAdapter(Context)
_CONTEXT_FIELDS = frozenset(field.name for field in fields(Context))

# The events that end the form a run was waiting on.
_FORM_ENDINGS = frozenset({"form_submitted", "form_cancelled", "form_dismissed"})


@frappe.whitelist(methods=["POST"])
def invoke(
	content: str | list[dict[str, Any]] | None = None,
	context: str | dict[str, Any] | None = None,
	reply: str | dict[str, Any] | None = None,
) -> dict[str, Any]:
	"""Runs one turn of the thread `context.run_id` names, and returns how it ended.

	Args:
		content: What is said. May be left out beside a `reply`.
		context: The turn's context.
		reply: A `form_submission` or `form_cancellation` of the form the run waits on.

	Returns:
		dict: The outcome as a content block whose `type` says what it is: `text`,
			`form` where the turn paused to ask, or `error`.
	"""

	said, turn, answer = _parsed(content, context, reply)
	settings = llm_settings()
	thread = _opened(said, turn, answer)

	# Driven as a stream, so the waiting form is resolved on record as `stream` does.
	outcome: dict[str, Any] = {}

	for event in _recorded(_iterate(_streamed(settings, said, turn, answer)), thread, turn, answer):
		if event.name == "outcome":
			outcome = event.data

	return outcome


@frappe.whitelist(methods=["POST"])
def stream(
	content: str | list[dict[str, Any]] | None = None,
	context: str | dict[str, Any] | None = None,
	reply: str | dict[str, Any] | None = None,
) -> Response:
	"""Runs one turn as server-sent events, ending on an `outcome` event holding what `invoke` returns."""

	said, turn, answer = _parsed(content, context, reply)
	settings = llm_settings()
	thread = _opened(said, turn, answer)

	return Response(
		_sse(_recorded(_iterate(_streamed(settings, said, turn, answer)), thread, turn, answer)),
		mimetype="text/event-stream",
		headers={
			"Cache-Control": "no-cache",
			"X-Accel-Buffering": "no",
		},
	)


@frappe.whitelist(methods=["POST"])
def cancel(request_id: str) -> None:
	"""Asks a turn to stop. It lands at the turn's next step, mid-answer while streaming,
	or during the wait before a retry.
	"""

	_check_user()

	if not request_id:
		frappe.throw(_("request_id is required."))

	# The stop is only a write to the shared store, so no model or client is built for it.
	asyncio.run(Cancellation(FrappeCacheStore()).request(request_id))


@frappe.whitelist(methods=["GET"])
def models() -> dict[str, Any]:
	"""The models a turn may name in `context.model`, and the one it runs on when it names none."""

	_check_user()

	return {
		"default": DEFAULT_MODEL,
		"models": [{"id": spec.id, "title": spec.title} for spec in MODEL_REGISTRY.values()],
	}


@asynccontextmanager
async def _agent(settings: LLMSettings) -> AsyncIterator[Agent]:
	"""The site's agent, over an HTTP client that lives for this request only."""

	async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as http_client:
		factory = LiteLLMModelFactory(
			settings.base_url,
			settings.api_key,
			http_client=http_client,
		)

		yield Agent(
			factory.get(DEFAULT_MODEL),
			key_value_store=FrappeCacheStore(),
			capabilities=[
				ErrorHandling(),
				HITL(FrappeCacheStore()),
				Models(factory),
				History(FrappeConversationStore()),
				Tools(site_tools()),
			],
			instructions=INSTRUCTIONS.format(
				site=frappe.local.site,
				user=frappe.utils.get_fullname(frappe.session.user),
				today=frappe.utils.formatdate(frappe.utils.today(), "EEEE, d MMMM yyyy"),
			),
		)


async def _streamed(
	settings: LLMSettings,
	said: str | list[TextContent],
	context: Context,
	reply: FormReply | None,
) -> AsyncIterator[Event]:
	async with _agent(settings) as agent:
		async for event in agent.astream(said, context, reply=reply):
			yield event


def _iterate(events: AsyncIterator[Event]) -> Iterator[Event]:
	"""Drives an async stream from WSGI's sync response body, on one loop for its whole life.

	ONE LOOP, because the stream's HTTP connection is bound to the loop it opened on.
	Closed on the way out too, so a client that disconnects mid-answer ends the run.
	"""

	loop = asyncio.new_event_loop()

	try:
		while True:
			try:
				yield loop.run_until_complete(anext(events))
			except StopAsyncIteration:
				return
	finally:
		loop.run_until_complete(events.aclose())
		loop.run_until_complete(loop.shutdown_asyncgens())
		loop.close()


def _recorded(
	events: Iterator[Event],
	thread: str,
	context: Context,
	reply: FormReply | None,
) -> Iterator[Event]:
	"""Passes a stream through, saving how its turn ended.

	SAVED BEFORE THE OUTCOME IS SENT, so a client that reloads the thread on seeing it
	finds the answer there. A client that goes away first still leaves what was
	streamed to it on record, as a cancelled answer.

	A REPLY THAT RESUMED NOTHING records no answer: a form handed back to fix is still
	the one on record, and one that expired is marked so.
	"""

	partial: list[str] = []
	# Whether this turn answers on record: a new message always does, a reply once it resumed.
	answering = reply is None
	recorded = False

	try:
		for event in events:
			if event.name == "text_delta":
				partial.append(event.data["text"])
			elif event.name in _FORM_ENDINGS:
				resolve_form(thread, _response(event, reply))
				answering = True
			elif event.name == "outcome":
				if answering:
					record_answer(thread, context, event.data, "".join(partial))
				elif event.data["type"] == "error" and event.data["error"]["type"] == "question_expired":
					resolve_form(thread, {"expired": True})

				recorded = True

			yield event
	finally:
		if answering and not recorded:
			record_answer(thread, context, None, "".join(partial))


def _response(event: Event, reply: FormReply | None) -> dict[str, Any]:
	"""What became of the waiting form, as it is kept on record."""

	if event.name == "form_submitted" and isinstance(reply, FormSubmission):
		return {"values": {name: reply.values.get(name) for name in event.data["fields"]}}

	if event.name == "form_cancelled":
		return {"declined": True, "reason": event.data.get("reason")}

	return {"dismissed": True}


def _sse(events: Iterator[Event]) -> Iterator[str]:
	for event in events:
		yield f"event: {event.name}\ndata: {event.model_dump_json()}\n\n"


def _opened(said: str | list[TextContent], context: Context, reply: FormReply | None) -> str:
	"""Opens the turn's thread and saves its question, returning the thread's name.

	A reply alone asks nothing new, so only what is said beside it is saved.
	"""

	question = said if isinstance(said, str) else "\n\n".join(block.text for block in said)

	if reply is not None and not frappe.db.exists(THREAD, context.run_id):
		frappe.throw(_("There is no conversation to answer in."), frappe.DoesNotExistError)

	thread = open_thread(context, question)

	if question:
		record_question(thread, context, question)

	return thread


def _check_user() -> None:
	"""Refuses website users: a model call costs money, and the desk is where the assistant lives."""

	if frappe.get_cached_value("User", frappe.session.user, "user_type") != "System User":
		frappe.throw(_("The AI Assistant is available to desk users only."), frappe.PermissionError)


def _parsed(
	content: str | list[dict[str, Any]] | None,
	context: str | dict[str, Any] | None,
	reply: str | dict[str, Any] | None,
) -> tuple[str | list[TextContent], Context, FormReply | None]:
	"""What is said, the turn's context and any reply to a form, validated before any model is built."""

	_check_user()

	answer = None

	if reply:
		try:
			answer = _REPLY.validate_python(frappe.parse_json(reply) if isinstance(reply, str) else reply)
		except ValidationError as exc:
			frappe.throw(_("Invalid reply: {0}").format(exc))

	if isinstance(content, list):
		try:
			said = _BLOCKS.validate_python(content)
		except ValidationError as exc:
			frappe.throw(_("Invalid content: {0}").format(exc))
	elif isinstance(content, str) and content.strip():
		said = content
	elif answer is not None:
		# A reply needs nothing said beside it.
		said = ""
	else:
		frappe.throw(_("content must be a non-empty string or a list of text blocks."))

	raw = frappe.parse_json(context) if isinstance(context, str) else (context or {})

	if not isinstance(raw, dict):
		frappe.throw(_("context must be an object."))

	if unknown := set(raw) - _CONTEXT_FIELDS:
		frappe.throw(_("Unknown context fields: {0}").format(", ".join(sorted(unknown))))

	try:
		turn = _CONTEXT.validate_python(raw)
	except ValidationError as exc:
		frappe.throw(_("Invalid context: {0}").format(exc))

	return said, turn, answer
