<template>
	<form class="composer" @submit.prevent="submit">
		<textarea
			ref="input"
			v-model="text"
			rows="1"
			:placeholder="placeholder || __('Message the assistant')"
			@input="resize"
			@keydown.enter.exact.prevent="submit"
		></textarea>

		<button
			v-if="streaming"
			type="button"
			class="send stop"
			:title="__('Stop')"
			@click="$emit('stop')"
		>
			<span class="stop-square"></span>
		</button>
		<button
			v-else
			type="submit"
			class="send"
			:title="busy ? __('Another answer is still running') : __('Send')"
			:disabled="!text.trim() || busy"
			v-html="frappe.utils.icon('up-arrow', 'sm')"
		></button>
	</form>
</template>

<script setup>
import { nextTick, onMounted, ref } from "vue";

const props = defineProps({
	// This thread's answer is running, so the button stops it.
	streaming: { type: Boolean, default: false },
	// Another thread's answer is running, so nothing new can be sent yet.
	busy: { type: Boolean, default: false },
	placeholder: { type: String, default: "" },
});

const emit = defineEmits(["send", "stop"]);

const text = ref("");
const input = ref(null);

// Tall enough for a short paragraph before it scrolls.
const MAX_HEIGHT = 200;

function resize() {
	const element = input.value;
	element.style.height = "auto";
	element.style.height = `${Math.min(element.scrollHeight, MAX_HEIGHT)}px`;
}

function submit() {
	const message = text.value.trim();

	if (!message || props.streaming || props.busy) {
		return;
	}

	emit("send", message);
	text.value = "";
	nextTick(resize);
}

function focus() {
	input.value?.focus();
}

onMounted(focus);

defineExpose({ focus });
</script>

<style scoped>
.composer {
	display: flex;
	align-items: flex-end;
	gap: var(--margin-sm);
	padding: var(--padding-sm) var(--padding-sm) var(--padding-sm) var(--padding-md);
	border: 1px solid var(--border-color);
	border-radius: 24px;
	background: var(--fg-color);
	box-shadow: var(--shadow-sm);
}
textarea {
	flex: 1;
	max-height: 200px;
	padding: 6px 0;
	border: none;
	outline: none;
	resize: none;
	background: transparent;
	color: var(--text-color);
	line-height: 1.5;
}
.send {
	display: flex;
	align-items: center;
	justify-content: center;
	flex-shrink: 0;
	width: 32px;
	height: 32px;
	border: none;
	border-radius: 50%;
	background: var(--text-color);
	color: var(--fg-color);
	--icon-stroke: var(--fg-color);
}
.send:disabled {
	opacity: 0.3;
	cursor: not-allowed;
}
.stop-square {
	width: 10px;
	height: 10px;
	border-radius: 2px;
	background: currentColor;
}
</style>
