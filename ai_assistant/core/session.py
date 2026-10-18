from dataclasses import dataclass

from ai_assistant.core.context import Context

__all__ = ["Session"]


@dataclass
class Session:
	"""What a run's capabilities and tools read the turn from, as the run's deps."""

	context: Context

	# Whether `History` has put the run's earlier turns in front of this turn yet, so
	# it does so on the turn's first model request only.
	history_loaded: bool = False
