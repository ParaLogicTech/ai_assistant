import math
from datetime import date
from typing import Any

from ai_assistant.core.content import Form, FormField

__all__ = [
	"InvalidAnswerError",
	"answered",
	"declined",
	"problem_with",
	"validated",
]

DECLINED = "The user declined to answer."
DECLINED_WITH_REASON = "The user declined to answer: {reason}"
NOTHING_SUPPLIED = "The user supplied nothing."


class InvalidAnswerError(Exception):
	"""An answer the form will not take, worded for the person: ONE problem, the first,
	since a person fixes one thing at a time.
	"""


def problem_with(form: Form) -> str | None:
	"""What is wrong with a form the model asked, worded for the model, or `None`."""

	if not form.title.strip():
		return "Give the form a title: the question itself, as a short heading."

	if not form.fields:
		return "Give the form at least one field to answer."

	names = [field.name for field in form.fields]

	if twice := sorted({name for name in names if names.count(name) > 1}):
		return f"Field names must be unique; {', '.join(twice)} is used twice."

	for field in form.fields:
		if field.type in ("select", "multiselect") and not field.options:
			return f"[{field.label}] is a {field.type}; give it the options to choose from."

		if field.options and field.default is not None:
			suggested = field.default if isinstance(field.default, list) else [field.default]

			if not set(suggested) <= set(field.options):
				return (
					f"[{field.label}] suggests [{field.default}], which is not one of its options: "
					f"{', '.join(field.options)}. Suggest one of them, or none."
				)

	return None


def validated(form: Form, values: dict[str, Any]) -> dict[str, Any]:
	"""The answers, checked against the form that asked for them.

	A field left out takes its default; one answered with nothing is dropped, so the
	model can tell "accepted the suggestion" from "left it blank".

	Raises:
		InvalidAnswerError: Where an answer is one the form does not admit.
	"""

	fields = {field.name: field for field in form.fields}

	if unknown := [name for name in values if name not in fields]:
		raise InvalidAnswerError(f"The form does not ask for [{unknown[0]}].")

	checked: dict[str, Any] = {}

	for field in form.fields:
		value = values.get(field.name, field.default)

		if _blank(value):
			if field.is_required:
				raise InvalidAnswerError(f"[{field.label}] needs an answer.")

			continue

		checked[field.name] = _checked(field, value)

	return checked


def answered(form: Form, values: dict[str, Any]) -> str:
	"""The answers as the model reads them: under the question, each by its label."""

	if not values:
		return f"{form.title}\n{NOTHING_SUPPLIED}"

	labels = {field.name: field.label for field in form.fields}
	lines = [f"{labels.get(name, name)}: {_shown(value)}" for name, value in values.items()]

	return "\n".join([form.title, *lines])


def declined(form: Form, reason: str | None) -> str:
	"""A refusal as the model reads it, with the reason where one was given."""

	said = DECLINED_WITH_REASON.format(reason=reason) if reason else DECLINED

	return f"{form.title}\n{said}"


def _checked(field: FormField, value: Any) -> Any:
	if field.type == "number":
		# A web form sends a number as text; a truth value is not a number.
		if isinstance(value, bool):
			raise InvalidAnswerError(f"[{field.label}] needs a number.")

		try:
			number = float(value)
		except (TypeError, ValueError):
			raise InvalidAnswerError(f"[{field.label}] needs a number.")

		if not math.isfinite(number):
			raise InvalidAnswerError(f"[{field.label}] needs a number.")

		return number

	if field.type == "boolean":
		if not isinstance(value, bool):
			raise InvalidAnswerError(f"[{field.label}] needs yes or no.")

		return value

	if field.type == "date":
		try:
			return date.fromisoformat(str(value)).isoformat()
		except ValueError:
			raise InvalidAnswerError(f"[{field.label}] needs a date, as YYYY-MM-DD.")

	if field.type == "multiselect":
		chosen = value if isinstance(value, list) else [value]

		if unknown := [one for one in chosen if one not in field.options]:
			raise InvalidAnswerError(
				f"[{field.label}] does not admit [{unknown[0]}]. Choose from: {', '.join(field.options)}.",
			)

		return chosen

	if field.type == "select" and value not in field.options:
		raise InvalidAnswerError(
			f"[{field.label}] does not admit [{value}]. Choose one of: {', '.join(field.options)}.",
		)

	return str(value)


def _blank(value: Any) -> bool:
	return value is None or value == [] or (isinstance(value, str) and not value.strip())


def _shown(value: Any) -> Any:
	"""A value as the model reads it: a whole number as one, a list as a list."""

	if isinstance(value, float) and value.is_integer():
		return int(value)

	if isinstance(value, list):
		return ", ".join(str(one) for one in value)

	if isinstance(value, bool):
		return "yes" if value else "no"

	return value
