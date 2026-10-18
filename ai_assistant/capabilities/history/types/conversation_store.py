from typing import Protocol, runtime_checkable

from pydantic_ai.messages import ModelMessage

__all__ = ["ConversationStore"]


@runtime_checkable
class ConversationStore(Protocol):
	"""Where a run's conversation is read from between turns.

	KEYED BY RUN, since a run is the conversation; each turn has its own request id.
	Writing the conversation is the deployment's, since what it keeps is also what a
	person reads back, partial answers included.
	"""

	async def load(self, run_id: str, *, before_request_id: str) -> list[ModelMessage]:
		"""The messages this run said before a turn.

		Args:
			run_id: The run whose conversation to read.
			before_request_id: The turn about to run, whose own messages are left out
				since the run is about to say them.

		Returns:
			list[ModelMessage]: What was said, oldest first. Empty for a run that has
				said nothing yet.
		"""

		...
