<template>
	<aside class="thread-list">
		<button class="new-chat btn btn-default btn-sm" @click="$emit('new')">
			<span v-html="frappe.utils.icon('add', 'sm')"></span>
			{{ __("New chat") }}
		</button>

		<div class="groups">
			<div v-if="!threads.length" class="empty text-muted">{{ __("No conversations yet") }}</div>

			<section v-for="group in groups" :key="group.label">
				<div class="group-label">{{ group.label }}</div>
				<div
					v-for="thread in group.threads"
					:key="thread.name"
					class="thread"
					:class="{ active: thread.name === active }"
					:title="thread.title"
					@click="$emit('open', thread.name)"
				>
					<span class="thread-title">{{ thread.title }}</span>
					<span class="thread-actions">
						<button
							class="icon-btn"
							:title="__('Rename')"
							@click.stop="$emit('rename', thread)"
							v-html="frappe.utils.icon('edit', 'sm')"
						></button>
						<button
							class="icon-btn"
							:title="__('Delete')"
							@click.stop="$emit('remove', thread)"
							v-html="frappe.utils.icon('delete', 'sm')"
						></button>
					</span>
				</div>
			</section>
		</div>
	</aside>
</template>

<script setup>
import { computed } from "vue";

const props = defineProps({
	threads: { type: Array, required: true },
	active: { type: String, default: null },
});

defineEmits(["new", "open", "rename", "remove"]);

// Threads arrive newest first, so each group keeps that order.
const groups = computed(() => {
	const today = moment().startOf("day");
	const week = moment(today).subtract(7, "days");
	const buckets = [
		{ label: __("Today"), threads: [] },
		{ label: __("Previous 7 days"), threads: [] },
		{ label: __("Older"), threads: [] },
	];

	for (const thread of props.threads) {
		const modified = moment(thread.modified);
		const bucket = modified.isSameOrAfter(today) ? 0 : modified.isSameOrAfter(week) ? 1 : 2;
		buckets[bucket].threads.push(thread);
	}

	return buckets.filter((bucket) => bucket.threads.length);
});
</script>

<style scoped>
.thread-list {
	display: flex;
	flex-direction: column;
	height: 100%;
	padding: var(--padding-sm);
	border-right: 1px solid var(--border-color);
	background: var(--subtle-fg);
}
.new-chat {
	display: flex;
	align-items: center;
	justify-content: center;
	gap: var(--margin-xs);
	width: 100%;
	margin-bottom: var(--margin-sm);
}
.groups {
	flex: 1;
	overflow-y: auto;
}
.empty {
	padding: var(--padding-sm);
	font-size: var(--text-sm);
}
.group-label {
	padding: var(--padding-sm) var(--padding-sm) var(--padding-xs);
	color: var(--text-muted);
	font-size: var(--text-xs);
	font-weight: 600;
}
.thread {
	display: flex;
	align-items: center;
	gap: var(--margin-xs);
	padding: 6px var(--padding-sm);
	border-radius: var(--border-radius);
	color: var(--text-color);
	font-size: var(--text-sm);
	cursor: pointer;
}
.thread:hover {
	background: var(--fg-hover-color);
}
.thread.active {
	background: var(--fg-color);
	box-shadow: var(--shadow-sm);
}
.thread-title {
	flex: 1;
	overflow: hidden;
	white-space: nowrap;
	text-overflow: ellipsis;
}
.thread-actions {
	display: none;
	gap: 2px;
}
.thread:hover .thread-actions,
.thread.active .thread-actions {
	display: flex;
}
.icon-btn {
	display: flex;
	padding: 2px;
	border: none;
	border-radius: var(--border-radius-sm);
	background: transparent;
	color: var(--text-muted);
}
.icon-btn:hover {
	background: var(--control-bg);
	color: var(--text-color);
}
</style>
