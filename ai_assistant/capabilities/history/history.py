import logging
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.capabilities.abstract import AbstractCapability

from ai_assistant.capabilities.history.types import ConversationStore
from ai_assistant.core.session import Session

__all__ = ["History"]

logger = logging.getLogger(__name__)


class History(AbstractCapability[Session]):
	"""What a run has said, carried from one turn to the next.

	`before_model_request` is handed the messages a request is about to carry and may
	replace them, so loading is prepending what was stored.

	ONLY ON THE FIRST REQUEST OF A TURN: a turn that has already called a tool is
	carrying its own messages, and prepending the record again would send each twice.

	NEVER FAILS A TURN. A store that cannot be read means the history is missing, not
	that the turn is impossible, so the turn runs without it.
	"""

	def __init__(self, conversation_store: ConversationStore) -> None:
		self.conversation_store = conversation_store

	async def before_model_request(
		self,
		ctx: RunContext[Session],
		request_context: Any,
	) -> Any:
		"""Puts what this run has said in front of what it is about to say."""

		session = ctx.deps

		if session.history_loaded:
			return request_context

		session.history_loaded = True
		context = session.context

		try:
			held = await self.conversation_store.load(
				context.run_id,
				before_request_id=context.request_id,
			)
		except Exception:
			logger.exception("Could not read the history for run [%s]; running without it.", context.run_id)
			return request_context

		if held:
			request_context.messages = [*held, *request_context.messages]

		return request_context
