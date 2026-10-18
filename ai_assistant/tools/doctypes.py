from typing import Any

import frappe
from frappe.model import DEFAULT_FIELDS, display_fieldtypes, table_fields

from ai_assistant.tools import ToolFailure, tool

# The most rows one call returns, so a broad query cannot flood the model's context.
MAX_ROWS = 100


@tool
def describe_doctype(doctype: str) -> dict[str, Any]:
	"""Describes a DocType: its fields, their types, and the DocTypes they link to.

	Call this before listing documents of a DocType whose fields you do not know yet,
	to learn the exact field names to filter and fetch by.

	Args:
		doctype: The DocType's name, such as "Customer" or "Sales Invoice".
	"""

	meta = _readable_meta(doctype)
	readable = _readable_levels(meta)

	return {
		"doctype": doctype,
		"title_field": meta.title_field or "name",
		"is_submittable": bool(meta.is_submittable),
		"fields": [
			{
				"fieldname": field.fieldname,
				"label": field.label,
				"fieldtype": field.fieldtype,
				# What a Link or a table points at, or a Select's choices.
				"options": field.options or None,
			}
			for field in meta.fields
			if field.fieldtype not in display_fieldtypes and field.permlevel in readable
		],
	}


@tool
def list_documents(
	doctype: str,
	fields: list[str] | None = None,
	filters: dict[str, Any] | list[list[Any]] | None = None,
	order_by: str | None = None,
	limit: int = 20,
) -> dict[str, Any]:
	"""Lists documents of a DocType that the user can read.

	Args:
		doctype: The DocType's name, such as "Customer".
		fields: Field names to return. Defaults to the name and title. Only names that
			`describe_doctype` lists, plus standard ones such as "creation" and "modified".
		filters: Conditions, as {"fieldname": value} or as
			[["fieldname", "operator", value], ...] with operators such as "=", "!=", ">",
			"<", ">=", "<=", "like", "in", "not in", "between" and "is" ("set" / "not set").
		order_by: Such as "modified desc" or "grand_total desc". Defaults to newest first.
		limit: How many documents to return, at most 100.
	"""

	meta = _readable_meta(doctype)
	readable = _readable_fieldnames(meta)
	fields = fields or list(dict.fromkeys(["name", meta.title_field or "name"]))

	if unknown := [fieldname for fieldname in fields if fieldname not in readable]:
		raise ToolFailure(
			f"{', '.join(unknown)} are not fields of {doctype} that you can read. "
			"Call describe_doctype for its fields.",
		)

	rows = frappe.get_list(
		doctype,
		fields=fields,
		filters=filters,
		order_by=order_by or "modified desc",
		limit_page_length=min(max(limit, 1), MAX_ROWS),
	)
	total = frappe.get_list(doctype, fields=["count(name) as total"], filters=filters)[0].total

	return {
		"doctype": doctype,
		"total_matching": total,
		"returned": len(rows),
		"rows": rows,
	}


def _readable_meta(doctype: str):
	"""The DocType's meta, where it exists and the user may read it."""

	if not frappe.db.exists("DocType", doctype):
		raise ToolFailure(f'There is no DocType named "{doctype}".')

	if not frappe.has_permission(doctype, "read"):
		raise frappe.PermissionError(f"You are not permitted to read {doctype}.")

	return frappe.get_meta(doctype)


def _readable_levels(meta) -> set[int]:
	return set(meta.get_permlevel_access("read")) | {0}


def _readable_fieldnames(meta) -> set[str]:
	readable = _readable_levels(meta)

	return set(DEFAULT_FIELDS) | {
		field.fieldname
		for field in meta.fields
		if field.fieldtype not in display_fieldtypes
		and field.fieldtype not in table_fields
		and field.permlevel in readable
	}
