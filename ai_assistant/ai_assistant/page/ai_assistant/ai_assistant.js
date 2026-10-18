frappe.pages["ai-assistant"].on_page_load = function (wrapper) {
	frappe.ui.make_app_page({
		parent: wrapper,
		title: __("AI Assistant"),
		single_column: true,
	});

	// The chat is full height and has its own header, so the standard one is hidden.
	$(wrapper).find(".page-head").addClass("hidden");

	frappe.require("ai_assistant.bundle.js").then(() => {
		ai_assistant.mount($(wrapper).find(".layout-main-section").get(0));
	});
};
