import { createApp } from "vue";
import App from "./assistant/App.vue";

frappe.provide("ai_assistant");

/** Mounts the assistant's chat into `element`, once per page. */
ai_assistant.mount = function (element) {
	if (element.__ai_assistant_app) {
		return;
	}

	const app = createApp(App);
	app.config.globalProperties.__ = window.__;
	app.config.globalProperties.frappe = window.frappe;
	app.mount(element);

	element.__ai_assistant_app = app;
};
