from dataclasses import dataclass

__all__ = [
	"DEFAULT_MODEL",
	"MODEL_REGISTRY",
	"ModelSpec",
]


@dataclass(frozen=True)
class ModelSpec:
	"""One model a turn may name."""

	# What a turn names it by, in `Context.model`.
	id: str

	# What the gateway serves it as.
	provider_model: str

	# How it is shown to a person.
	title: str


MODEL_REGISTRY: dict[str, ModelSpec] = {
	spec.id: spec
	for spec in (
		ModelSpec(
			id="haiku",
			provider_model="claude-haiku-4-5",
			title="Claude Haiku 4.5",
		),
		ModelSpec(
			id="sonnet",
			provider_model="claude-sonnet-4-5",
			title="Claude Sonnet 4.5",
		),
	)
}

# What a turn runs on when it names no model.
DEFAULT_MODEL = "haiku"
