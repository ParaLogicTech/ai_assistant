import json
from typing import Any

import frappe
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, UserPromptPart

from ai_assistant.capabilities.hitl import answered, declined
from ai_assistant.core import Form
from ai_assistant.infra.transcript import MESSAGE

__all__ = ["FrappeConversationStore"]


class FrappeConversationStore:
	"""A `ConversationStore` over a thread's saved messages, which is what a person reads too.

	A question goes to the model only with the answer it got: one whose answer failed
	with nothing said is left out, so the model is never handed two questions in a row
	with no reply between.

	A turn that paused to ask reads as the assistant asking and the person answering,
	and the answer after it as the reply to that, so the turn keeps its order.
	"""

	async def load(self, run_id: str, *, before_request_id: str) -> list[ModelMessage]:
		rows = frappe.get_all(
			MESSAGE,
			filters={
				"thread": run_id,
				"request_id": ["!=", before_request_id],
			},
			fields=["role", "content", "form", "form_response"],
			order_by="creation asc",
		)

		messages: list[ModelMessage] = []
		# What the person said that has had no reply yet.
		said: str | None = None
		# What they said to a form, which a question asked after it follows.
		owed: str | None = None

		for row in rows:
			if row.role == "user":
				said = f"{owed}\n\n{row.content}" if owed else row.content
				owed = None
				continue

			if said is None:
				continue

			form = _json(row.form)
			response = _json(row.form_response)
			reply = row.content or ""

			if form is None or response is None:
				if reply:
					messages.append(ModelRequest(parts=[UserPromptPart(content=said)]))
					messages.append(ModelResponse(parts=[TextPart(content=reply)]))
					said = owed = None

				continue

			asked = Form.model_validate(form)
			messages.append(ModelRequest(parts=[UserPromptPart(content=said)]))
			messages.append(
				ModelResponse(parts=[TextPart(content=f"{reply}\n\nI asked: {asked.title}".strip())]),
			)
			said = owed = _answer(asked, response)

		return messages


def _answer(form: Form, response: dict[str, Any]) -> str:
	"""What the person said to a form, as the model reads it."""

	if "values" in response:
		return answered(form, response["values"])

	if response.get("declined"):
		return declined(form, response.get("reason"))

	return f"{form.title}\nThe user moved on without answering."


def _json(value: Any) -> Any:
	return json.loads(value) if isinstance(value, str) and value else value or None
