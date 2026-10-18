import uuid
from dataclasses import dataclass, field
from typing import Any

__all__ = ["Context"]


@dataclass
class Context:
	"""Runtime context for a single agent turn.

	Carried alongside a turn rather than written into its messages, so the ids that
	address a run are never something the model can read, restate, or get wrong.
	Constructible with no arguments, so a caller with nothing to say about a turn
	says nothing.
	"""

	# ID of the agent's current run, which may span several turns.
	run_id: str = field(default_factory=lambda: str(uuid.uuid4()))

	# ID of the current request, one turn within a run. Also what `cancel` names.
	request_id: str = field(default_factory=lambda: str(uuid.uuid4()))

	# The model this turn runs on, as a registry id, overriding the agent's own for
	# this turn alone.
	model: str | None = None

	# Parameters for this turn's model call, such as `temperature` or `max_tokens`.
	model_args: dict[str, Any] = field(default_factory=dict)
