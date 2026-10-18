<template>
	<div class="message" :class="message.role">
		<div v-if="message.role === 'user'" class="bubble">{{ message.content }}</div>

		<div v-else class="answer">
			<div v-if="message.tools?.length" class="tools">
				<span v-for="call in message.tools" :key="call.id" class="tool" :class="call.status">
					<span class="tool-state"></span>
					{{ toolLabel(call) }}
				</span>
			</div>

			<div
				v-if="message.content"
				class="markdown"
				:class="{ streaming: message.streaming }"
				v-html="html"
			></div>
			<div v-else-if="message.streaming" class="thinking">
				<span></span><span></span><span></span>
			</div>

			<div v-if="message.status === 'Cancelled'" class="note text-muted">
				{{ __("Stopped") }}
			</div>
			<div v-else-if="message.status === 'Failed'" class="note failed">
				{{ error.detail || __("The answer failed.") }}
				<span v-if="error.instance_id" class="text-muted">({{ error.instance_id }})</span>
			</div>

			<div v-if="!message.streaming && message.content" class="actions">
				<button class="icon-btn" :title="__('Copy')" @click="copy" v-html="copyIcon"></button>
				<span v-if="modelTitle" class="model text-muted">{{ modelTitle }}</span>
			</div>
		</div>
	</div>
</template>

<script setup>
import { computed, ref } from "vue";
import { renderMarkdown } from "../markdown";

const props = defineProps({
	message: { type: Object, required: true },
	models: { type: Array, default: () => [] },
});

const copied = ref(false);

const html = computed(() => renderMarkdown(props.message.content));

const error = computed(() => {
	const value = props.message.error;
	return (typeof value === "string" ? JSON.parse(value || "{}") : value) || {};
});

const modelTitle = computed(
	() => props.models.find((model) => model.id === props.message.model)?.title || props.message.model,
);

const copyIcon = computed(() => frappe.utils.icon(copied.value ? "check" : "duplicate", "sm"));

// The tool as a person reads it, with the DocType it worked on where it named one.
function toolLabel(call) {
	const label = frappe.unscrub(call.name);
	return call.args?.doctype ? `${label} · ${call.args.doctype}` : label;
}

function copy() {
	frappe.utils.copy_to_clipboard(props.message.content);
	copied.value = true;
	setTimeout(() => (copied.value = false), 1500);
}
</script>

<style scoped>
.message {
	display: flex;
	margin-bottom: var(--margin-lg);
}
.message.user {
	justify-content: flex-end;
}
.bubble {
	max-width: 80%;
	padding: var(--padding-sm) var(--padding-md);
	border-radius: 18px;
	background: var(--control-bg);
	color: var(--text-color);
	white-space: pre-wrap;
	word-wrap: break-word;
}
.answer {
	width: 100%;
	min-width: 0;
	color: var(--text-color);
}
.tools {
	display: flex;
	flex-wrap: wrap;
	gap: var(--margin-xs);
	margin-bottom: var(--margin-sm);
}
.tool {
	display: inline-flex;
	align-items: center;
	gap: 6px;
	padding: 2px var(--padding-sm);
	border: 1px solid var(--border-color);
	border-radius: var(--border-radius-full, 999px);
	color: var(--text-muted);
	font-size: var(--text-xs);
}
.tool-state {
	width: 8px;
	height: 8px;
	border-radius: 50%;
}
.tool.running .tool-state {
	border: 1.5px solid var(--text-muted);
	border-top-color: transparent;
	animation: spin 0.8s linear infinite;
}
.tool.done .tool-state {
	background: var(--green-500);
}
.tool.failed .tool-state {
	background: var(--red-500);
}
.markdown {
	line-height: 1.65;
	word-wrap: break-word;
}
.markdown :deep(p) {
	margin: 0 0 var(--margin-sm);
}
.markdown :deep(:is(h1, h2, h3, h4, h5, h6)) {
	margin: var(--margin-md) 0 var(--margin-sm);
	color: var(--text-color);
	font-weight: 600;
	line-height: 1.3;
	letter-spacing: normal;
}
.markdown :deep(h1) {
	font-size: 1.4em;
}
.markdown :deep(h2) {
	font-size: 1.25em;
}
.markdown :deep(:is(h3, h4, h5, h6)) {
	font-size: 1.1em;
}
.markdown :deep(> :first-child) {
	margin-top: 0;
}
.markdown :deep(pre) {
	padding: var(--padding-md);
	border-radius: var(--border-radius-md);
	background: var(--control-bg);
	overflow-x: auto;
}
.markdown :deep(code) {
	padding: 1px 4px;
	border-radius: var(--border-radius-sm);
	background: var(--control-bg);
	font-size: 0.9em;
}
.markdown :deep(pre code) {
	padding: 0;
	background: none;
}
.markdown :deep(table) {
	display: block;
	max-width: 100%;
	margin-bottom: var(--margin-sm);
	overflow-x: auto;
	border-collapse: collapse;
}
.markdown :deep(th),
.markdown :deep(td) {
	padding: 6px var(--padding-sm);
	border: 1px solid var(--border-color);
}
.markdown :deep(blockquote) {
	margin: 0 0 var(--margin-sm);
	padding-left: var(--padding-md);
	border-left: 3px solid var(--border-color);
	color: var(--text-muted);
}
.markdown.streaming > :deep(:last-child)::after {
	content: "▍";
	margin-left: 2px;
	animation: blink 1s steps(1) infinite;
}
.thinking {
	display: flex;
	gap: 4px;
	padding: var(--padding-sm) 0;
}
.thinking span {
	width: 7px;
	height: 7px;
	border-radius: 50%;
	background: var(--text-muted);
	animation: pulse 1.2s infinite ease-in-out;
}
.thinking span:nth-child(2) {
	animation-delay: 0.15s;
}
.thinking span:nth-child(3) {
	animation-delay: 0.3s;
}
.note {
	margin-top: var(--margin-xs);
	font-size: var(--text-sm);
}
.note.failed {
	color: var(--red-600);
}
.actions {
	display: flex;
	align-items: center;
	gap: var(--margin-sm);
	margin-top: var(--margin-xs);
	opacity: 0;
	transition: opacity 0.15s;
}
.message:hover .actions {
	opacity: 1;
}
.model {
	font-size: var(--text-xs);
}
.icon-btn {
	display: flex;
	padding: 4px;
	border: none;
	border-radius: var(--border-radius-sm);
	background: transparent;
	color: var(--text-muted);
}
.icon-btn:hover {
	background: var(--control-bg);
	color: var(--text-color);
}
@keyframes spin {
	to {
		transform: rotate(360deg);
	}
}
@keyframes blink {
	50% {
		opacity: 0;
	}
}
@keyframes pulse {
	0%,
	80%,
	100% {
		opacity: 0.3;
		transform: scale(0.8);
	}
	40% {
		opacity: 1;
		transform: scale(1);
	}
}
</style>
