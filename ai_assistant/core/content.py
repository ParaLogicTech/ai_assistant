import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

__all__ = [
	"Error",
	"ErrorContent",
	"Event",
	"Outcome",
	"Resource",
	"TextContent",
	"content_of",
]


class Resource(BaseModel):
	"""A model that crosses a boundary on its own, and so carries who it is.

	An id, a creation time and a metadata dict, so each block a caller receives can be
	told apart, ordered and annotated without restating the three.
	"""

	id: str = Field(
		default_factory=lambda: str(uuid.uuid4()),
		description="Unique id of the model instance.",
	)
	created_at: datetime = Field(
		default_factory=lambda: datetime.now(timezone.utc),
		description="UTC timestamp of when the model instance was created.",
	)
	metadata: dict[str, Any] = Field(
		default_factory=dict,
		description="Free-form annotations on the block.",
	)


class Error(BaseModel):
	"""A failure, as the caller is allowed to see it.

	Masked by default: a provider's own sentence names models, quotas and hosts, so it
	goes to the log under the turn's ids and only `detail` crosses the boundary.
	"""

	type: str = Field(description="What kind of failure this is, as a stable string to branch on.")
	code: str = Field(default="internal", description="A stable snake_case identifier for this failure.")
	title: str = Field(description="A short heading for the failure.")
	detail: str = Field(description="What the caller is told. Safe to display.")
	instance_id: str | None = Field(
		default=None,
		description="The request id of the turn this error ended.",
	)


class TextContent(Resource):
	"""A content block carrying text: what a caller says, or a prose answer."""

	type: Literal["text"] = "text"
	text: str = Field(description="Text content.")


class ErrorContent(Resource):
	"""A content block carrying the failure a turn ended in."""

	type: Literal["error"] = "error"
	error: Error = Field(description="The failure, masked.")


class Event(Resource):
	"""What one thing the agent did along the way, as a name and its data."""

	name: str = Field(description="What happened.")
	data: Any = Field(default_factory=dict, description="What the event carries.")


# How a turn ends: the answer, or the error it ended in.
Outcome = TextContent | Error


def content_of(outcome: Outcome) -> TextContent | ErrorContent:
	"""Writes an outcome down as a content block whose `type` says what it is."""

	if isinstance(outcome, Error):
		return ErrorContent(error=outcome)

	return outcome
