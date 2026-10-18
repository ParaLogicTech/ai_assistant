from collections.abc import Sequence
from typing import Any

from pydantic_ai import Tool
from pydantic_ai.capabilities.abstract import AbstractCapability
from pydantic_ai.toolsets import AbstractToolset, FunctionToolset

from ai_assistant.core.session import Session

__all__ = [
	"TOOLS_TOOLSET_ID",
	"Tools",
	"failure",
	"is_failure",
]

# Names the toolset, as the other capabilities' toolsets are named.
TOOLS_TOOLSET_ID = "ai_assistant.tools"


def failure(code: str, detail: str) -> dict[str, Any]:
	"""What a tool hands the model instead of a result, so the model can correct course.

	RETURNED, NOT RAISED: a tool that fails ends nothing, since the model can usually
	recover - naming a real field, asking the person - where a raised error would end
	the turn.
	"""

	return {"error": {"code": code, "detail": detail}}


def is_failure(result: Any) -> bool:
	"""Whether a tool's result is a `failure`."""

	return isinstance(result, dict) and set(result) == {"error"}


class Tools(AbstractCapability[Session]):
	"""The tools a deployment hands the agent, offered to the model as one toolset.

	WHAT THE TOOLS ARE is the deployment's: this neither finds nor builds them, so
	where they come from - a hook, a registry, a list in code - stays at the call
	site that wires the agent.
	"""

	def __init__(self, tools: Sequence[Tool[Session]]) -> None:
		self.tools = list(tools)

	def get_toolset(self) -> AbstractToolset[Session] | None:
		"""The tools, or nothing where there are none to offer."""

		return FunctionToolset(tools=self.tools, id=TOOLS_TOOLSET_ID) if self.tools else None
