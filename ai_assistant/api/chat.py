import frappe
from ai_assistant.capabilities.tools.tool_registry import get_all_tools


@frappe.whitelist()
def test():
	return get_all_tools()
