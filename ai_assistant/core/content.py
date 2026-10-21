import uuid
from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

__all__ = [
	"Error",
	"ErrorContent",
	"Event",
	"FieldType",
	"Form",
	"FormCancellation",
	"FormContent",
	"FormField",
	"FormReply",
	"FormSubmission",
	"Outcome",
	"Resource",
	"TextContent",
	"content_of",
]

# What one input on a form renders as.
FieldType = Literal["text", "textarea", "number", "boolean", "date", "select", "multiselect"]


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


class FormField(BaseModel):
	"""One input on a form: what a person is shown, and what an answer is checked against."""

	name: str = Field(description="The key the answer arrives under.")
	label: str = Field(description="What the input is called, as the person reads it.")
	type: FieldType = Field(default="text", description="What the input renders as.")
	description: str | None = Field(default=None, description="Help text beneath the input.")
	placeholder: str | None = Field(default=None, description="Ghost text in an empty input.")
	default: Any = Field(
		default=None,
		description="Your best guess at the answer, pre-filled so the person can accept it with a click.",
	)
	is_required: bool = Field(default=False, description="Whether an answer must be given.")
	options: list[str] = Field(
		default_factory=list,
		description="The only answers a select or multiselect admits. Ignored for any other type.",
	)


class Form(Resource):
	"""A question a turn stopped on, waiting for a person.

	The id is the form's own, minted as it is asked, so an answer names the question
	it is for and one arriving after the run moved on is told apart.
	"""

	title: str = Field(description="The question itself, as a short heading.")
	description: str | None = Field(default=None, description="What the answer is for.")
	fields: list[FormField] = Field(default_factory=list, description="The inputs to answer.")
	error: str | None = Field(
		default=None,
		description="Why an answer was refused, where the form is handed back to be fixed.",
	)


class FormContent(Resource):
	"""A content block carrying the question a turn paused on."""

	type: Literal["form"] = "form"
	form: Form = Field(description="What the person is asked.")


class FormSubmission(BaseModel):
	"""An answer to the form a run is waiting on."""

	type: Literal["form_submission"] = "form_submission"
	form_id: str = Field(description="The form this answers.")
	values: dict[str, Any] = Field(
		default_factory=dict,
		description="The answers, by field name. A field left out takes its default.",
	)


class FormCancellation(BaseModel):
	"""A refusal to answer the form a run is waiting on.

	NOT A STOP: the run goes on, and the model is told the person declined. Stopping
	the turn is `cancel`.
	"""

	type: Literal["form_cancellation"] = "form_cancellation"
	form_id: str = Field(description="The form being declined.")
	reason: str | None = Field(default=None, description="Why, where the person said.")


# What a person says to a waiting form.
FormReply = Annotated[FormSubmission | FormCancellation, Field(discriminator="type")]


class Event(Resource):
	"""What one thing the agent did along the way, as a name and its data."""

	name: str = Field(description="What happened.")
	data: Any = Field(default_factory=dict, description="What the event carries.")


# How a turn ends: the answer, the question it paused on, or the error it ended in.
Outcome = TextContent | FormContent | Error


def content_of(outcome: Outcome) -> TextContent | FormContent | ErrorContent:
	"""Writes an outcome down as a content block whose `type` says what it is."""

	if isinstance(outcome, Error):
		return ErrorContent(error=outcome)

	return outcome
