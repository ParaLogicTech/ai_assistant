import functools
import json
import logging
from collections.abc import Callable
from typing import Any, TypeVar, overload

import frappe
from pydantic_ai import Tool

from ai_assistant.capabilities.tools import failure
from ai_assistant.core.session import Session

__all__ = [
	"TOOLS_HOOK",
	"ToolFailure",
	"site_tools",
	"tool",
]

logger = logging.getLogger(__name__)

# The hook an app lists its tool modules under, in its `hooks.py`.
TOOLS_HOOK = "ai_assistant_tools"

# The attribute `tool` marks a function with, holding the name the model calls it by.
_MARK = "__ai_assistant_tool__"

# Frappe errors whose message is written for the person using the site, and so is
# safe, and useful, for the model to read and correct course on.
_SAFE_ERRORS = (
	frappe.DoesNotExistError,
	frappe.PermissionError,
	frappe.ValidationError,
)

F = TypeVar("F", bound=Callable[..., Any])


class ToolFailure(Exception):
	"""Raised by a tool to tell the model why it could not do what was asked.

	The message is shown to the model as it is, so it should say what to do instead -
	which field names exist, which DocType was meant.
	"""


@overload
def tool(function: F) -> F: ...


@overload
def tool(*, name: str | None = None) -> Callable[[F], F]: ...


def tool(function: F | None = None, *, name: str | None = None) -> F | Callable[[F], F]:
	"""Marks a function as a tool the agent may call.

	The function is a plain, synchronous Frappe function: it runs as the person using
	the assistant, so every permission check it makes applies. Its parameters' type
	hints become the tool's schema and its Google-style docstring its description, so
	both are what the model reads.

	The function is returned unchanged, so it can still be called and tested directly.
	A module of tools is offered to the agent by listing it under the
	`ai_assistant_tools` hook.

	Args:
		function: The function, when used bare as `@tool`.
		name: What the model calls the tool, where not the function's own name.
	"""

	def mark(target: F) -> F:
		setattr(target, _MARK, name or target.__name__)
		return target

	return mark(function) if function is not None else mark


def site_tools() -> list[Tool[Session]]:
	"""The tools of every app installed on this site, from their `ai_assistant_tools` hooks.

	PER SITE, rather than collected into a registry as modules are imported: a bench
	serves several sites from one process, and an app installed on one of them must not
	lend its tools to the others.
	"""

	tools: dict[str, Tool[Session]] = {}

	for path in frappe.get_hooks(TOOLS_HOOK):
		module = frappe.get_module(path)

		for member in vars(module).values():
			# Only what the module itself defines, not tools it imported from another.
			if getattr(member, "__module__", None) != module.__name__:
				continue

			if (tool_name := getattr(member, _MARK, None)) is None:
				continue

			if tool_name in tools:
				logger.warning("Tool [%s] in [%s] is already defined; keeping the first.", tool_name, path)
				continue

			tools[tool_name] = Tool(_in_turn(member), name=tool_name, docstring_format="google")

	return list(tools.values())


def _in_turn(function: Callable[..., Any]) -> Callable[..., Any]:
	"""The tool as the agent runs it: on the turn's own thread, and never raising.

	ASYNC, though the function is not, so the framework calls it in place rather than
	in a worker thread, where it would share the request's database connection with
	whatever else ran there. Parallel calls therefore run one after another.
	"""

	@functools.wraps(function)
	async def run(*args: Any, **kwargs: Any) -> Any:
		# `frappe.throw` queues its message for the HTTP response as well; a tool's
		# failure goes to the model instead, so it is taken back off.
		messages = frappe.local.message_log
		queued = len(messages)

		try:
			return _plain(function(*args, **kwargs))
		except ToolFailure as exc:
			return failure("invalid_request", str(exc))
		except _SAFE_ERRORS as exc:
			del messages[queued:]
			return failure(type(exc).__name__, _message(exc))
		except Exception:
			del messages[queued:]
			logger.exception("Tool [%s] failed.", function.__name__)
			return failure("internal", "The tool failed. Try another way, or tell the user.")

	return run


def _plain(result: Any) -> Any:
	"""A tool's result as plain JSON values.

	Frappe hands back `frappe._dict`, which answers every missing attribute with `None` -
	including the serializer pydantic looks for, which then fails on it. Its own encoder
	also knows the dates and decimals a document holds.
	"""

	return json.loads(frappe.as_json(result, indent=None))


def _message(exc: Exception) -> str:
	return frappe.utils.strip_html_tags(str(exc.args[0]) if exc.args else type(exc).__name__)
