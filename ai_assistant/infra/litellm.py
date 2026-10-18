import httpx
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from ai_assistant.capabilities.models import MODEL_REGISTRY, ModelSpec, UnknownModelError

__all__ = ["LiteLLMModelFactory"]


class LiteLLMModelFactory:
	"""Builds registry models served by a LiteLLM gateway, over its OpenAI-compatible API.

	The HTTP client is the caller's, and lives for one request: a Frappe worker runs
	each turn on an event loop of its own, and a pooled connection opened on one loop
	cannot be reused from the next.
	"""

	def __init__(
		self,
		base_url: str,
		api_key: str,
		*,
		http_client: httpx.AsyncClient,
		registry: dict[str, ModelSpec] = MODEL_REGISTRY,
	) -> None:
		self.provider = OpenAIProvider(
			base_url=base_url,
			api_key=api_key,
			http_client=http_client,
		)
		self.registry = registry
		self.__built: dict[str, Model] = {}

	def get(self, model: str) -> Model:
		"""Builds the model for a registry id, once per factory."""

		if (spec := self.registry.get(model)) is None:
			raise UnknownModelError(model)

		if model not in self.__built:
			self.__built[model] = OpenAIChatModel(spec.provider_model, provider=self.provider)

		return self.__built[model]
