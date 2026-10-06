import frappe
import ai_assistant


@ai_assistant.register_tool(
	name="global_search",
	category="operations",
	description="Search for documents of any DocType globally by search text. Useful for looking up specific document name from vague name.",
	parameters={
		"query": {"type": "string", "description": "Search text to match anything searchable"},
		"doctype": {"type": "string", "description": "Filter by DocType"},
		"limit": {"type": "integer", "description": "Maximum results to return (default 20)"},
	},
	doctypes=[],
)
def global_search(query=None, doctype=None, limit=20):
	from frappe.utils.global_search import search

	out = frappe._dict({
		"search_results": [],
		"message": "",
		"count": 0,
	})

	if not query:
		query.message = "Please provide a search query."
		return []

	results = search(query, doctype=doctype, limit=limit)
	out.search_results = results
	out.count = len(results)

	return out
