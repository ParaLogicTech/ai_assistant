from ai_assistant.core.content import Error

__all__ = ["AgentError"]


class AgentError(Exception):
	"""A failure whose message is safe to show the caller, so it is not masked.

	Raised by a capability that refuses something the caller asked for, such as a
	model it does not know. Any other exception ends the turn on a masked `Error`.
	"""

	type = "invalid_request"
	code = "invalid_request"
	title = "Invalid request"

	def __init__(self, detail: str) -> None:
		super().__init__(detail)
		self.detail = detail

	def to_error(self) -> Error:
		return Error(
			type=self.type,
			code=self.code,
			title=self.title,
			detail=self.detail,
		)
