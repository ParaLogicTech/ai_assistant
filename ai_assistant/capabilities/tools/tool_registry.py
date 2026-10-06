import frappe

_TOOL_REGISTRY = {}


def register_tool(name, category, description, parameters=None, doctypes=None):
	"""Decorator to register a tool function.

	Usage:
		@register_tool(
			name="get_sales_analytics",
			category="selling",
			description="Get sales analytics including revenue and orders",
			parameters={
				"from_date": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
				"to_date": {"type": "string", "description": "End date (YYYY-MM-DD)"},
				"company": {"type": "string", "description": "Company name. Defaults to user's default company."},
			},
			doctypes=["Sales Invoice"],
		)
		def get_sales_analytics(from_date=None, to_date=None, company=None):
			...

	Args:
		name: Unique tool name (must match function name).
		category: Tool category key (e.g. "crm", "selling", "buying", "finance", "inventory").
		description: Human-readable description for the LLM.
		parameters: Dict of parameter definitions for OpenAI function calling schema.
		doctypes: List of DocType names the tool accesses. Used for permission checks.
	"""

	def decorator(func):
		_TOOL_REGISTRY[name] = {
			"name": name,
			"category": category,
			"description": description,
			"parameters": parameters or {},
			"doctypes": doctypes or [],
			"function": func,
		}
		return func

	return decorator


def get_all_tools():
	# Load external plugin tools via Frappe hooks
	for module_path in frappe.get_hooks("ai_assistant_tool_modules") or []:
		try:
			frappe.get_module(module_path)
		except Exception as e:
			frappe.log_error(
				message=f"Failed to load AI Chatbot tool plugin: {module_path}: {e}",
				title="Plugin Loader",
			)

	return _TOOL_REGISTRY
