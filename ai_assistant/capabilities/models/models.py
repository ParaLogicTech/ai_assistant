from pydantic_ai.capabilities.abstract import AbstractCapability
from pydantic_ai.models import Model, ModelResolutionContext

from ai_assistant.capabilities.models.registry import MODEL_REGISTRY
from ai_assistant.capabilities.models.types import ModelFactory
from ai_assistant.core.errors import AgentError
from ai_assistant.core.session import Session

__all__ = [
	"Models",
	"UnknownModelError",
]


class UnknownModelError(AgentError):
	"""A turn named a model the registry does not hold."""

	code = "unknown_model"
	title = "Unknown model"

	def __init__(self, model: str) -> None:
		super().__init__(f"Unknown model [{model}]. Available: {', '.join(MODEL_REGISTRY)}.")


class Models(AbstractCapability[Session]):
	"""The models a turn may name, built by the deployment's factory.

	The agent runs every turn on the model it was handed; with this installed, a turn
	that names a model in `Context.model` runs on that one instead. The agent hands
	the run the NAME, and the framework asks this for the model through its
	resolution chain.
	"""

	def __init__(self, model_factory: ModelFactory) -> None:
		self.model_factory = model_factory

	async def resolve_model_id(
		self,
		ctx: ModelResolutionContext[Session],
		*,
		model_id: str,
	) -> Model | None:
		"""The model a name means, built by the factory."""

		del ctx

		return self.model_factory.get(model_id)
