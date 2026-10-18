from typing import Protocol, runtime_checkable

from pydantic_ai.models import Model

__all__ = ["ModelFactory"]


@runtime_checkable
class ModelFactory(Protocol):
	"""How a deployment builds the model a turn names.

	Deterministic and no I/O: a client is built, not called. A name the factory
	cannot build is refused by raising, and the turn then ends on an `Error`.
	"""

	def get(self, model: str) -> Model:
		"""Builds the model for a registry id."""

		...
