"""What a Frappe app writes tools with.

An app offers tools by decorating plain functions with `tool` and listing their module
under the `ai_assistant_tools` hook in its `hooks.py`.
"""

from ai_assistant.infra.tools import ToolFailure, tool

__all__ = [
	"ToolFailure",
	"tool",
]
