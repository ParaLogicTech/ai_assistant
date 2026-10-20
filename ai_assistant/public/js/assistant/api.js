const AGENT = "ai_assistant.api.agent";
const THREAD = "AI Assistant Thread";
const MESSAGE = "AI Assistant Message";

function call(method, args = {}, type = "POST") {
	return frappe.call({ method, args, type }).then((r) => r.message);
}

/**
 * A random UUID v4, for a new thread's run id and each turn's request id.
 *
 * Not `crypto.randomUUID`, which browsers offer only on HTTPS or localhost, and a
 * self-hosted site is often served over plain HTTP.
 */
export function newId() {
	const bytes = crypto.getRandomValues(new Uint8Array(16));
	bytes[6] = (bytes[6] & 0x0f) | 0x40;
	bytes[8] = (bytes[8] & 0x3f) | 0x80;
	const hex = [...bytes].map((byte) => byte.toString(16).padStart(2, "0")).join("");

	return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export function getModels() {
	return call(`${AGENT}.models`, {}, "GET");
}

export function listThreads() {
	return call("frappe.client.get_list", {
		doctype: THREAD,
		fields: ["name", "title", "model", "modified"],
		// Explicit, since an Administrator would otherwise see every user's threads.
		filters: { owner: frappe.session.user },
		order_by: "modified desc",
		limit_page_length: 200,
	});
}

export function listMessages(thread) {
	return call("frappe.client.get_list", {
		doctype: MESSAGE,
		fields: ["name", "role", "content", "status", "model", "error", "form", "form_response"],
		filters: { thread },
		order_by: "creation asc",
		limit_page_length: 0,
	});
}

export function renameThread(name, title) {
	return call("frappe.client.set_value", {
		doctype: THREAD,
		name,
		fieldname: "title",
		value: title,
	});
}

export function deleteThread(name) {
	return call("frappe.client.delete", { doctype: THREAD, name });
}

export function cancel(requestId) {
	return call(`${AGENT}.cancel`, { request_id: requestId });
}

/**
 * Runs one turn as a stream, handing each event to `onEvent` as it arrives.
 *
 * `reply` answers or declines the form the run is waiting on, as a `form_submission`
 * or a `form_cancellation`; `content` may then be left out.
 *
 * Resolves once the stream ends. Rejects where the request is refused before it
 * starts, with the server's own message.
 */
export async function stream({ content, context, reply }, onEvent) {
	const response = await fetch(`/api/method/${AGENT}.stream`, {
		method: "POST",
		headers: {
			Accept: "text/event-stream",
			"Content-Type": "application/json",
			"X-Frappe-CSRF-Token": frappe.csrf_token,
		},
		body: JSON.stringify({ content, context, reply }),
	});

	if (!response.ok) {
		throw new Error(await refusal(response));
	}

	const reader = response.body.getReader();
	const decoder = new TextDecoder();
	let buffer = "";

	for (;;) {
		const { done, value } = await reader.read();

		if (done) {
			break;
		}

		buffer += decoder.decode(value, { stream: true });

		let end;
		while ((end = buffer.indexOf("\n\n")) >= 0) {
			const event = parseEvent(buffer.slice(0, end));
			buffer = buffer.slice(end + 2);

			if (event) {
				onEvent(event);
			}
		}
	}
}

function parseEvent(raw) {
	const data = raw
		.split("\n")
		.filter((line) => line.startsWith("data:"))
		.map((line) => line.slice(5).trimStart())
		.join("\n");

	return data ? JSON.parse(data) : null;
}

async function refusal(response) {
	try {
		const body = await response.json();

		if (body._server_messages) {
			const [first] = JSON.parse(body._server_messages);
			return JSON.parse(first).message;
		}

		return body.exc_type || response.statusText;
	} catch {
		return response.statusText;
	}
}
