from dataclasses import dataclass

import frappe
from frappe import _

__all__ = [
	"LLMSettings",
	"llm_settings",
]


@dataclass(frozen=True)
class LLMSettings:
	"""Where the model gateway is, from the site's config."""

	base_url: str
	api_key: str


def llm_settings() -> LLMSettings:
	"""Reads the gateway settings, set with `bench --site <site> set-config`."""

	base_url = frappe.conf.get("ai_assistant_llm_base_url")
	api_key = frappe.conf.get("ai_assistant_llm_api_key")

	if not base_url or not api_key:
		frappe.throw(
			_("Set ai_assistant_llm_base_url and ai_assistant_llm_api_key in the site config."),
			title=_("AI Assistant is not configured"),
		)

	return LLMSettings(base_url=base_url, api_key=api_key)
