import frappe
from frappe.model.document import Document


class AIAssistantThread(Document):
	def on_trash(self):
		# A thread's messages are only reachable through it, so they go with it.
		frappe.db.delete("AI Assistant Message", {"thread": self.name})
