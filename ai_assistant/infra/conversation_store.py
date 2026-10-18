import frappe
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, UserPromptPart

from ai_assistant.infra.transcript import MESSAGE

__all__ = ["FrappeConversationStore"]


class FrappeConversationStore:
	"""A `ConversationStore` over a thread's saved messages, which is what a person reads too.

	A question goes to the model only with the answer it got: one whose answer failed
	with nothing said is left out, so the model is never handed two questions in a row
	with no reply between.
	"""

	async def load(self, run_id: str, *, before_request_id: str) -> list[ModelMessage]:
		rows = frappe.get_all(
			MESSAGE,
			filters={
				"thread": run_id,
				"request_id": ["!=", before_request_id],
			},
			fields=["role", "content"],
			order_by="creation asc",
		)

		messages: list[ModelMessage] = []
		question: str | None = None

		for row in rows:
			if row.role == "user":
				question = row.content
			elif question is not None and row.content:
				messages.append(ModelRequest(parts=[UserPromptPart(content=question)]))
				messages.append(ModelResponse(parts=[TextPart(content=row.content)]))
				question = None

		return messages
