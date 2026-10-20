<template>
	<div class="ai-assistant" :class="{ 'sidebar-hidden': !sidebarOpen }">
		<ThreadList
			v-if="sidebarOpen"
			class="sidebar"
			:threads="threads"
			:active="activeThread"
			@new="newChat"
			@open="openThread"
			@rename="rename"
			@remove="remove"
		/>

		<main class="chat">
			<header class="chat-header">
				<button
					class="icon-btn"
					:title="sidebarOpen ? __('Hide conversations') : __('Show conversations')"
					@click="sidebarOpen = !sidebarOpen"
					v-html="frappe.utils.icon('sidebar-collapse', 'md')"
				></button>
				<button
					v-if="!sidebarOpen"
					class="icon-btn"
					:title="__('New chat')"
					@click="newChat"
					v-html="frappe.utils.icon('add', 'md')"
				></button>

				<select v-model="selectedModel" class="model-select" :title="__('Model')">
					<option v-for="model in models" :key="model.id" :value="model.id">
						{{ model.title }}
					</option>
				</select>

				<span class="thread-heading text-muted">{{ activeTitle }}</span>
			</header>

			<div ref="scroller" class="messages" @scroll="onScroll">
				<div class="column">
					<div v-if="loading" class="placeholder text-muted">{{ __("Loading…") }}</div>
					<div v-else-if="!messages.length" class="welcome">
						<h2>{{ __("How can I help you today?") }}</h2>
					</div>
					<ChatMessage
						v-for="message in messages"
						:key="message.name"
						:message="message"
						:models="models"
						:busy="Boolean(running)"
						@reply="(reply) => respond(message, reply)"
					/>
				</div>
			</div>

			<div class="composer-wrap">
				<div class="column">
					<Composer
						ref="composer"
						:streaming="isStreamingHere"
						:busy="Boolean(running) && !isStreamingHere"
						:placeholder="waitingForm ? __('Answer the question above, or send a message to skip it') : ''"
						@send="send"
						@stop="stop"
					/>
					<div class="disclaimer text-muted">
						{{ __("Answers can be wrong. Check anything important.") }}
					</div>
				</div>
			</div>
		</main>
	</div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref } from "vue";
import * as api from "./api";
import ChatMessage from "./components/ChatMessage.vue";
import Composer from "./components/Composer.vue";
import ThreadList from "./components/ThreadList.vue";

// How close to the bottom counts as following the answer as it streams.
const FOLLOW_THRESHOLD = 80;

const threads = ref([]);
const activeThread = ref(null);
const messages = ref([]);
const models = ref([]);
const selectedModel = ref(null);
const loading = ref(false);
const sidebarOpen = ref(window.innerWidth > 768);
// The turn being streamed, as `{ runId, requestId }`, or `null`.
const running = ref(null);

const scroller = ref(null);
const composer = ref(null);
let following = true;

const isStreamingHere = computed(() => Boolean(running.value) && running.value.runId === activeThread.value);

// A form the thread is waiting on: sending a message passes it over.
const waitingForm = computed(() => messages.value.some((message) => message.status === "Paused"));

const activeTitle = computed(() => threads.value.find((thread) => thread.name === activeThread.value)?.title || "");

onMounted(async () => {
	const [registry] = await Promise.all([api.getModels(), refreshThreads()]);
	models.value = registry.models;
	selectedModel.value = registry.default;
});

async function refreshThreads() {
	threads.value = await api.listThreads();
}

function newChat() {
	activeThread.value = null;
	messages.value = [];
	composer.value?.focus();
}

async function openThread(name) {
	if (name === activeThread.value) {
		return;
	}

	activeThread.value = name;
	loading.value = true;
	messages.value = [];

	try {
		const rows = await api.listMessages(name);

		// The thread may have changed while this loaded.
		if (activeThread.value === name) {
			messages.value = rows;
			selectedModel.value = threads.value.find((thread) => thread.name === name)?.model || selectedModel.value;
			scrollToBottom(true);
		}
	} finally {
		loading.value = false;
	}
}

async function send(text) {
	const isNew = !activeThread.value;
	const runId = activeThread.value || api.newId();
	const requestId = api.newId();
	const model = selectedModel.value;

	activeThread.value = runId;
	running.value = { runId, requestId };

	messages.value.push({ name: `${requestId}-q`, role: "user", content: text, model });
	messages.value.push({ name: `${requestId}-a`, role: "assistant", content: "", model, streaming: true, tools: [] });
	// The reactive copy, so each change re-renders.
	const reply = messages.value[messages.value.length - 1];
	scrollToBottom(true);

	if (isNew) {
		threads.value.unshift({ name: runId, title: text, model, modified: frappe.datetime.now_datetime() });
	}

	try {
		await api.stream({ content: text, context: { run_id: runId, request_id: requestId, model } }, (event) => {
			if (event.name === "form_dismissed") {
				settleForms({ dismissed: true });
			} else {
				follow(reply, event);
			}
		});

		lost(reply);
	} catch (error) {
		settle(reply, { type: "error", error: { type: "internal", detail: error.message } });
	} finally {
		running.value = null;
		refreshThreads();
	}
}

/**
 * Answers or declines the form `message` paused on, and follows the turn it resumes.
 *
 * The reply's own answer appears once the run resumes: a form handed back to fix, or
 * one no longer waiting, resumes nothing and stays where it is.
 */
async function respond(message, reply) {
	if (running.value) {
		return;
	}

	const runId = activeThread.value;
	const requestId = api.newId();
	const model = selectedModel.value;
	let answer = null;

	running.value = { runId, requestId };
	message.submitting = true;
	message.formError = null;

	try {
		await api.stream({ reply, context: { run_id: runId, request_id: requestId, model } }, (event) => {
			if (event.name === "form_submitted" || event.name === "form_cancelled") {
				settleForms(reply.type === "form_submission" ? { values: reply.values } : { declined: true });
				messages.value.push({
					name: `${requestId}-a`,
					role: "assistant",
					content: "",
					model,
					streaming: true,
					tools: [],
				});
				answer = messages.value[messages.value.length - 1];
				scrollToBottom(true);
			} else if (answer) {
				follow(answer, event);
			} else if (event.name === "outcome") {
				handedBack(message, event.data);
			}
		});

		if (answer) {
			lost(answer);
		}
	} catch (error) {
		if (answer) {
			settle(answer, { type: "error", error: { type: "internal", detail: error.message } });
		} else {
			message.formError = error.message;
		}
	} finally {
		message.submitting = false;
		running.value = null;
		refreshThreads();
	}
}

// Applies one event of a running turn to the answer it is building.
function follow(reply, event) {
	if (event.name === "text_delta") {
		reply.retrying = null;
		reply.content += event.data.text;
		scrollToBottom();
	} else if (event.name === "tool_started") {
		reply.tools.push({ ...event.data, status: "running" });
		scrollToBottom();
	} else if (event.name === "tool_ended") {
		const call = reply.tools.find((tool) => tool.id === event.data.id);
		if (call) {
			call.status = event.data.failed ? "failed" : "done";
		}
	} else if (event.name === "retry_scheduled") {
		reply.retrying = event.data.attempt + 1;
	} else if (event.name === "outcome") {
		settle(reply, event.data);
	}
}

// A form that resumed nothing: handed back to fix, or no longer waiting.
function handedBack(message, outcome) {
	if (outcome.type === "form") {
		message.form = outcome.form;
		message.formError = outcome.form.error;
	} else if (outcome.error?.type === "question_expired") {
		settleForms({ expired: true });
	} else {
		message.formError = outcome.error?.detail || __("The answer could not be sent.");
	}
}

// Marks the thread's waiting form as no longer waiting, with what became of it.
function settleForms(response) {
	for (const message of messages.value) {
		if (message.status === "Paused") {
			message.status = "Completed";
			message.form_response = response;
		}
	}
}

// A stream that ended without saying how its turn ended.
function lost(reply) {
	if (reply.streaming) {
		settle(reply, { type: "error", error: { type: "internal", detail: __("The connection was lost.") } });
	}
}

function settle(reply, outcome) {
	reply.streaming = false;
	reply.retrying = null;

	if (outcome.type === "text") {
		reply.content = outcome.text;
		reply.status = "Completed";
		return;
	}

	if (outcome.type === "form") {
		reply.status = "Paused";
		reply.form = outcome.form;
		scrollToBottom();
		return;
	}

	reply.status = outcome.error.type === "cancelled" ? "Cancelled" : "Failed";
	reply.error = outcome.error;
}

function stop() {
	// The stream keeps reading, and ends on the turn's own `cancelled` outcome.
	if (running.value) {
		api.cancel(running.value.requestId);
	}
}

function rename(thread) {
	frappe.prompt(
		{ fieldname: "title", fieldtype: "Data", label: __("Title"), default: thread.title, reqd: 1 },
		async ({ title }) => {
			await api.renameThread(thread.name, title);
			refreshThreads();
		},
		__("Rename conversation"),
		__("Save"),
	);
}

function remove(thread) {
	frappe.confirm(__("Delete <b>{0}</b>?", [frappe.utils.escape_html(thread.title)]), async () => {
		await api.deleteThread(thread.name);

		if (thread.name === activeThread.value) {
			newChat();
		}

		refreshThreads();
	});
}

function onScroll() {
	const element = scroller.value;
	following = element.scrollHeight - element.scrollTop - element.clientHeight < FOLLOW_THRESHOLD;
}

function scrollToBottom(force = false) {
	if (!force && !following) {
		return;
	}

	following = true;
	nextTick(() => {
		scroller.value.scrollTop = scroller.value.scrollHeight;
	});
}
</script>

<style scoped>
.ai-assistant {
	position: fixed;
	inset: var(--navbar-height, 48px) 0 0 0;
	display: grid;
	grid-template-columns: 260px minmax(0, 1fr);
	background: var(--bg-color);
	z-index: 1;
}
.ai-assistant.sidebar-hidden {
	grid-template-columns: minmax(0, 1fr);
}
.sidebar {
	min-height: 0;
}
.chat {
	display: flex;
	flex-direction: column;
	min-height: 0;
	background: var(--fg-color);
}
.chat-header {
	display: flex;
	align-items: center;
	gap: var(--margin-sm);
	padding: var(--padding-sm) var(--padding-md);
	border-bottom: 1px solid var(--border-color);
}
.model-select {
	padding: 4px var(--padding-sm);
	border: none;
	border-radius: var(--border-radius);
	background: transparent;
	color: var(--text-color);
	font-weight: 600;
	cursor: pointer;
}
.model-select:hover {
	background: var(--control-bg);
}
.thread-heading {
	overflow: hidden;
	white-space: nowrap;
	text-overflow: ellipsis;
	font-size: var(--text-sm);
}
.messages {
	flex: 1;
	overflow-y: auto;
}
.column {
	max-width: 768px;
	margin: 0 auto;
	padding: 0 var(--padding-md);
}
.messages .column {
	padding-top: var(--padding-lg);
}
.welcome {
	display: flex;
	align-items: center;
	justify-content: center;
	min-height: 50vh;
}
.welcome h2 {
	color: var(--text-color);
	font-weight: 600;
}
.placeholder {
	padding: var(--padding-lg) 0;
	text-align: center;
}
.composer-wrap {
	padding-bottom: var(--padding-sm);
}
.disclaimer {
	padding-top: var(--padding-xs);
	font-size: var(--text-xs);
	text-align: center;
}
.icon-btn {
	display: flex;
	padding: 4px;
	border: none;
	border-radius: var(--border-radius);
	background: transparent;
	color: var(--text-muted);
}
.icon-btn:hover {
	background: var(--control-bg);
	color: var(--text-color);
}
@media (max-width: 768px) {
	.ai-assistant {
		grid-template-columns: minmax(0, 1fr);
	}
	.sidebar {
		position: absolute;
		inset: 0 auto 0 0;
		width: 260px;
		z-index: 2;
		box-shadow: var(--shadow-lg);
	}
}
</style>
