from dataclasses import dataclass

from ai_assistant.core.content import Form
from ai_assistant.core.context import Context

__all__ = ["Session"]


@dataclass
class Session:
	"""What a run's capabilities and tools read the turn from, as the run's deps.

	ONE PER ATTEMPT, so a retried turn starts with nothing said and nothing asked.
	"""

	context: Context

	# Whether `History` has put the run's earlier turns in front of this turn yet, so
	# it does so on the turn's first model request only. Set from the start on a
	# resume, whose messages already carry them.
	history_loaded: bool = False

	# Whether this attempt has had an effect a retry would repeat: a tool that ran.
	spoken: bool = False

	# The form this attempt has asked, so a second ask in the same step is told to
	# wait rather than stacking a second question on the person.
	asking: Form | None = None
