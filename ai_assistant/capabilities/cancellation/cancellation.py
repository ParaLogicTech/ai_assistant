import logging
from typing import Any

from pydantic_ai import RunCancelled, RunContext
from pydantic_ai.capabilities.abstract import AbstractCapability, WrapRunHandler
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.run import AgentRunResult
from pydantic_ai.tools import ToolDefinition

from ai_assistant.core.key_value_store import KeyValueStore
from ai_assistant.core.session import Session

__all__ = [
	"CANCELLED_VALUE",
	"Cancellation",
	"cancelled_key",
]

logger = logging.getLogger(__name__)

CANCELLATION_KEY_PREFIX = "ai_assistant:cancelled"
CANCELLED_VALUE = "1"

# How long a stop stays readable: long enough that a turn still running finds it,
# short enough that a key nobody consumed does not outlive the run it was about.
DEFAULT_CANCELLATION_TTL_SECONDS = 900


def cancelled_key(request_id: str) -> str:
	"""What a stop for this request is written under, for the writer and the reader alike."""

	return f"{CANCELLATION_KEY_PREFIX}:{request_id}"


class Cancellation(AbstractCapability[Session]):
	"""Stops a turn that something elsewhere asked to stop.

	It reads the shared store before each model request and before each tool call, so a
	stop written by a worker that is not running the turn is still honoured, at the
	next step rather than mid-call. A missing key is "not cancelled", so a store hiccup
	never stops every turn in flight.
	"""

	def __init__(
		self,
		key_value_store: KeyValueStore,
		*,
		ttl_seconds: int = DEFAULT_CANCELLATION_TTL_SECONDS,
	) -> None:
		self.key_value_store = key_value_store
		self.ttl_seconds = ttl_seconds

	async def request(self, request_id: str) -> None:
		"""Asks a turn to stop, by writing where every worker reads."""

		await self.key_value_store.set(
			cancelled_key(request_id),
			CANCELLED_VALUE,
			ttl=self.ttl_seconds,
		)

	async def requested(self, request_id: str) -> bool:
		"""Whether this turn has been asked to stop. Never raises."""

		try:
			return await self.key_value_store.get(cancelled_key(request_id)) == CANCELLED_VALUE
		except Exception:
			logger.exception("Could not read the cancellation for request [%s]; continuing.", request_id)
			return False

	async def consume(self, request_id: str) -> None:
		"""Removes a stop the turn it was about has honoured. Never raises.

		A stop left standing would cancel the next turn reusing the request id.
		"""

		try:
			await self.key_value_store.delete(cancelled_key(request_id))
		except Exception:
			logger.exception("Could not clear the stop for request [%s].", request_id)

	async def wrap_run(
		self,
		ctx: RunContext[Session],
		*,
		handler: WrapRunHandler,
	) -> AgentRunResult[Any]:
		"""Clears a stop once the turn it was about has ended, whether it answered or was cancelled."""

		try:
			result = await handler()
		except RunCancelled:
			await self.consume(ctx.deps.context.request_id)
			raise

		await self.consume(ctx.deps.context.request_id)

		return result

	async def before_model_request(
		self,
		ctx: RunContext[Session],
		request_context: Any,
	) -> Any:
		"""Ends the turn where a stop has been written, before paying for a model call."""

		await self.__check(ctx)

		return request_context

	async def before_tool_execute(
		self,
		ctx: RunContext[Session],
		*,
		call: ToolCallPart,
		tool_def: ToolDefinition,
		args: Any,
	) -> Any:
		"""Ends the turn where a stop has been written, before a tool's side effects happen."""

		del call, tool_def

		await self.__check(ctx)

		return args

	async def __check(self, ctx: RunContext[Session]) -> None:
		request_id = ctx.deps.context.request_id

		if await self.requested(request_id):
			logger.info("Request [%s] was cancelled; ending the turn.", request_id)
			raise RunCancelled("The turn was cancelled.")
