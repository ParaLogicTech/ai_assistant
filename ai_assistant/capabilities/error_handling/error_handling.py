import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from pydantic_ai import RunContext
from pydantic_ai.capabilities.abstract import AbstractCapability
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.tools import ToolDefinition

from ai_assistant.core.content import Error
from ai_assistant.core.context import Context
from ai_assistant.core.errors import AgentError
from ai_assistant.core.session import Session

__all__ = [
	"DefaultExceptionHandler",
	"ErrorAction",
	"ErrorHandling",
	"ErrorResolution",
	"ExceptionHandler",
	"masked",
	"retryable",
]

logger = logging.getLogger(__name__)

DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BACKOFF_BASE_SECONDS = 1.0
DEFAULT_BACKOFF_MULTIPLIER = 2.0

# The statuses of a provider's answer worth trying again: a timeout, a rate limit,
# and the server-side failures that are usually gone a moment later.
RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})


class ErrorAction(str, Enum):
	"""What a handler decided about a failure: end the turn, or try it again."""

	FAIL = "fail"
	RETRY = "retry"


@dataclass
class ErrorResolution:
	"""What a handler decided about one failure, and what the caller is told."""

	# What the caller is told, already masked.
	error: Error

	action: ErrorAction = ErrorAction.FAIL

	# How long to wait before the retry, where the handler wants its own wait rather
	# than the backoff.
	delay_seconds: float | None = None


@runtime_checkable
class ExceptionHandler(Protocol):
	"""How a deployment decides what one failure means.

	THE POLICY, not the mechanism: where a failure is caught, how a retry is paced
	and what the caller is handed are `ErrorHandling`'s; whether this exception is
	worth another attempt is the deployment's, which knows its flaky backends.
	"""

	async def handle(
		self,
		error: Exception,
		context: Context,
		attempt: int,
		*,
		can_retry: bool,
	) -> ErrorResolution:
		"""Decides what to do about one failure.

		Args:
			error: What was raised, unmasked.
			context: The turn it was raised in.
			attempt: Which attempt failed, from one.
			can_retry: Whether another attempt can follow: false once the attempt had
				an effect or showed the person anything, and on the last attempt. A
				`RETRY` answered where it is false is taken as `FAIL`.
		"""

		...


def retryable(error: BaseException) -> bool:
	"""Whether a failure is worth trying again: a timeout, a lost connection, or a
	provider's answer that is usually gone a moment later. Advice, for a handler.
	"""

	if isinstance(error, TimeoutError | ConnectionError):
		return True

	if isinstance(error, ModelHTTPError):
		return error.status_code in RETRYABLE_STATUS_CODES

	# A transport failure with no status, such as a dropped connection.
	return isinstance(error, ModelAPIError)


def masked(error: BaseException, context: Context) -> Error:
	"""The `Error` a failure is shown as: its own words where it is safe to show, else
	a generic one, with what was raised sent to the log under the turn's ids.
	"""

	if (refused := _agent_error(error)) is not None:
		shown = refused.to_error()
		shown.instance_id = context.request_id

		return shown

	logger.error(
		"Request [%s] of run [%s] failed.",
		context.request_id,
		context.run_id,
		exc_info=error,
	)

	return Error(
		type="internal",
		code="internal",
		title="Something went wrong",
		detail="The turn failed. Try again, or quote the instance id to support.",
		instance_id=context.request_id,
	)


class DefaultExceptionHandler:
	"""Retries what `retryable` advises where a retry can follow, and fails the rest, masked."""

	async def handle(
		self,
		error: Exception,
		context: Context,
		attempt: int,
		*,
		can_retry: bool,
	) -> ErrorResolution:
		del attempt

		if can_retry and retryable(error):
			return ErrorResolution(error=masked(error, context), action=ErrorAction.RETRY)

		return ErrorResolution(error=masked(error, context))


class ErrorHandling(AbstractCapability[Session]):
	"""What a failure means: whether the turn is tried again, after how long, and what
	the caller is told.

	THE AGENT RUNS THE LOOP and asks this once per failed attempt, since a run cannot
	be re-entered from inside its own hooks. Without it installed, a turn runs once
	and fails masked.

	AN ATTEMPT THAT HAD AN EFFECT IS FINAL. A retry runs the turn again from the top,
	so a tool that ran would run twice and what was streamed would be said twice: this
	marks the session as a tool returns, and the agent counts what it streamed.
	"""

	def __init__(
		self,
		handler: ExceptionHandler | None = None,
		*,
		max_attempts: int = DEFAULT_MAX_ATTEMPTS,
		backoff_base_seconds: float = DEFAULT_BACKOFF_BASE_SECONDS,
		backoff_multiplier: float = DEFAULT_BACKOFF_MULTIPLIER,
	) -> None:
		if max_attempts < 1:
			raise ValueError("max_attempts must be at least 1.")

		self.handler = handler or DefaultExceptionHandler()
		self.max_attempts = max_attempts
		self.backoff_base_seconds = backoff_base_seconds
		self.backoff_multiplier = backoff_multiplier

	async def resolve(
		self,
		error: Exception,
		context: Context,
		attempt: int,
		*,
		can_retry: bool,
	) -> ErrorResolution:
		"""Asks the handler about one failure. Never raises: a broken handler fails the turn, masked."""

		can_retry = can_retry and attempt < self.max_attempts

		try:
			resolution = await self.handler.handle(error, context, attempt, can_retry=can_retry)
		except Exception:
			logger.exception("The exception handler failed on request [%s].", context.request_id)
			return ErrorResolution(error=masked(error, context))

		if resolution.action is ErrorAction.RETRY and not can_retry:
			resolution.action = ErrorAction.FAIL

		return resolution

	def delay(self, attempt: int, resolution: ErrorResolution) -> float:
		"""How long to wait before the attempt after `attempt`: the handler's, or the backoff."""

		if resolution.delay_seconds is not None:
			return resolution.delay_seconds

		return self.backoff_base_seconds * self.backoff_multiplier ** max(attempt - 1, 0)

	async def after_tool_execute(
		self,
		ctx: RunContext[Session],
		*,
		call: ToolCallPart,
		tool_def: ToolDefinition,
		args: Any,
		result: Any,
	) -> Any:
		"""Marks the attempt as having had an effect, since the tool's work is done."""

		del call, tool_def, args

		ctx.deps.spoken = True

		return result


def _agent_error(exc: BaseException) -> AgentError | None:
	"""The `AgentError` behind an exception, where the framework wrapped one."""

	seen: set[int] = set()
	current: BaseException | None = exc

	while current is not None and id(current) not in seen:
		if isinstance(current, AgentError):
			return current

		seen.add(id(current))
		current = current.__cause__ or current.__context__

	return None
