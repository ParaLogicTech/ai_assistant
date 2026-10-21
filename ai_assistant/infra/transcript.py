from typing import Any

import frappe

from ai_assistant.capabilities.models import DEFAULT_MODEL
from ai_assistant.core import Context

__all__ = [
	"MESSAGE",
	"THREAD",
	"open_thread",
	"record_answer",
	"record_question",
	"resolve_form",
]

THREAD = "AI Assistant Thread"
MESSAGE = "AI Assistant Message"

# How much of a thread's first question its title keeps.
TITLE_LENGTH = 80


def open_thread(context: Context, question: str) -> str:
	"""The thread a turn runs in, named by its run id and created on its first turn.

	A run id that names someone else's thread is refused, since the caller chooses it.
	"""

	model = context.model or DEFAULT_MODEL

	if frappe.db.exists(THREAD, context.run_id):
		thread = frappe.get_doc(THREAD, context.run_id)
		thread.check_permission("write")
		thread.model = model
		# Saved even when the model is unchanged, so the thread rises to the top of the list.
		thread.save()
	else:
		thread = frappe.get_doc(
			{
				"doctype": THREAD,
				"title": _title(question),
				"model": model,
			},
		).insert(set_name=context.run_id)

	return thread.name


def record_question(thread: str, context: Context, question: str) -> None:
	"""Saves what was asked, before the turn runs, so it stands even if the turn never ends."""

	_record(
		thread,
		context,
		role="user",
		content=question,
	)


def record_answer(
	thread: str,
	context: Context,
	outcome: dict[str, Any] | None,
	partial: str,
) -> None:
	"""Saves how a turn ended.

	Args:
		thread: The thread the turn ran in.
		context: The turn's context.
		outcome: The outcome's content block, or `None` where the caller went away
			before the turn ended.
		partial: What was streamed before the turn ended, kept where it did not answer.
	"""

	if outcome is not None and outcome["type"] == "text":
		_record(thread, context, role="assistant", content=outcome["text"])
		return

	if outcome is not None and outcome["type"] == "form":
		_record(thread, context, role="assistant", content=partial, status="Paused", form=outcome["form"])
		return

	error = outcome["error"] if outcome is not None else None
	cancelled = error is None or error["type"] == "cancelled"

	_record(
		thread,
		context,
		role="assistant",
		content=partial,
		status="Cancelled" if cancelled else "Failed",
		error=error,
	)


def _record(
	thread: str,
	context: Context,
	*,
	role: str,
	content: str,
	status: str = "Completed",
	error: dict[str, Any] | None = None,
	form: dict[str, Any] | None = None,
) -> None:
	frappe.get_doc(
		{
			"doctype": MESSAGE,
			"thread": thread,
			"role": role,
			"content": content,
			"status": status,
			"error": error,
			"form": form,
			"model": context.model or DEFAULT_MODEL,
			"request_id": context.request_id,
		},
	).insert()

	# A stream's body runs after the request has committed, so each write commits itself.
	frappe.db.commit()


def resolve_form(thread: str, response: dict[str, Any]) -> None:
	"""Saves what became of the form a thread was waiting on, so it reads as answered.

	Args:
		thread: The thread whose waiting form it was.
		response: `{"values": ...}` for an answer, `{"declined": True, "reason": ...}`
			for a refusal, `{"dismissed": True}` where the person moved on, or
			`{"expired": True}` where the question no longer waited.
	"""

	# One form waits per run, so the thread's paused answer is the one it was.
	for name in frappe.get_all(MESSAGE, filters={"thread": thread, "status": "Paused"}, pluck="name"):
		frappe.db.set_value(
			MESSAGE,
			name,
			{
				"status": "Completed",
				"form_response": frappe.as_json(response, indent=None),
			},
		)

	frappe.db.commit()


def _title(question: str) -> str:
	line = " ".join(question.split())

	return line if len(line) <= TITLE_LENGTH else f"{line[: TITLE_LENGTH - 1]}…"
