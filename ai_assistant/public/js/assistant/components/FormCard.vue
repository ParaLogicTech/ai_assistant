<template>
	<div class="form-card" :class="{ settled: Boolean(response) }">
		<div class="form-heading">
			<span class="form-icon" v-html="frappe.utils.icon(response ? 'check' : 'edit', 'sm')"></span>
			<span class="form-title">{{ form.title }}</span>
			<span v-if="response" class="form-state" :class="stateClass">{{ stateLabel }}</span>
		</div>
		<div v-if="form.description" class="form-description text-muted">{{ form.description }}</div>

		<!-- What was said, once the form is settled. -->
		<template v-if="response">
			<dl v-if="response.values" class="answers">
				<template v-for="field in form.fields" :key="field.name">
					<dt class="text-muted">{{ field.label }}</dt>
					<dd>{{ shown(field, response.values[field.name]) }}</dd>
				</template>
			</dl>
			<div v-else-if="response.declined && response.reason" class="text-muted reason">
				{{ response.reason }}
			</div>
		</template>

		<form v-else class="form-fields" @submit.prevent="submit">
			<div v-for="field in form.fields" :key="field.name" class="form-field">
				<template v-if="field.type === 'boolean'">
					<label class="check">
						<input v-model="values[field.name]" type="checkbox" :disabled="locked" />
						<span>{{ field.label }}</span>
					</label>
				</template>

				<template v-else>
					<label class="field-label" :for="inputId(field)">
						{{ field.label }}<span v-if="field.is_required" class="required">*</span>
					</label>

					<textarea
						v-if="field.type === 'textarea'"
						:id="inputId(field)"
						v-model="values[field.name]"
						class="form-control"
						rows="3"
						:placeholder="field.placeholder"
						:disabled="locked"
					></textarea>

					<select
						v-else-if="field.type === 'select'"
						:id="inputId(field)"
						v-model="values[field.name]"
						class="form-control"
						:disabled="locked"
					>
						<option value="">{{ field.placeholder || __("Choose…") }}</option>
						<option v-for="option in field.options" :key="option" :value="option">{{ option }}</option>
					</select>

					<div v-else-if="field.type === 'multiselect'" class="choices">
						<label v-for="option in field.options" :key="option" class="check">
							<input v-model="values[field.name]" type="checkbox" :value="option" :disabled="locked" />
							<span>{{ option }}</span>
						</label>
					</div>

					<input
						v-else
						:id="inputId(field)"
						v-model="values[field.name]"
						class="form-control"
						:type="inputType(field)"
						:step="field.type === 'number' ? 'any' : undefined"
						:placeholder="field.placeholder"
						:disabled="locked"
					/>
				</template>

				<div v-if="field.description" class="field-help text-muted">{{ field.description }}</div>
			</div>

			<div v-if="error" class="form-error">{{ error }}</div>

			<div class="form-actions">
				<button type="submit" class="btn btn-primary btn-sm" :disabled="locked">
					{{ submitting ? __("Sending…") : __("Submit") }}
				</button>
				<button type="button" class="btn btn-default btn-sm" :disabled="locked" @click="decline">
					{{ __("Decline") }}
				</button>
			</div>
		</form>
	</div>
</template>

<script setup>
import { computed, reactive, watch } from "vue";

const props = defineProps({
	form: { type: Object, required: true },
	// What became of the form, once it is no longer waiting.
	response: { type: Object, default: null },
	// Why the last answer was refused, or why it could not be sent.
	error: { type: String, default: "" },
	submitting: { type: Boolean, default: false },
	// Another answer is running, so nothing can be sent yet.
	busy: { type: Boolean, default: false },
});

const emit = defineEmits(["submit", "decline"]);

const values = reactive({});
const locked = computed(() => props.submitting || props.busy);

// Pre-filled with the model's best guesses, so accepting one is a click.
watch(
	() => props.form.id,
	() => {
		for (const field of props.form.fields) {
			const guess = field.default;

			if (field.type === "boolean") {
				values[field.name] = Boolean(guess);
			} else if (field.type === "multiselect") {
				values[field.name] = Array.isArray(guess) ? [...guess] : guess ? [guess] : [];
			} else {
				values[field.name] = guess ?? "";
			}
		}
	},
	{ immediate: true },
);

const stateLabel = computed(() => {
	const response = props.response;

	if (response.values) return __("Answered");
	if (response.declined) return __("Declined");
	if (response.expired) return __("Expired");
	return __("Skipped");
});

const stateClass = computed(() => (props.response.values ? "answered" : "passed"));

function inputId(field) {
	return `form-${props.form.id}-${field.name}`;
}

function inputType(field) {
	return { number: "number", date: "date" }[field.type] || "text";
}

function shown(field, value) {
	if (value === undefined || value === null || value === "" || (Array.isArray(value) && !value.length)) {
		return "—";
	}

	if (field.type === "boolean") return value ? __("Yes") : __("No");
	if (Array.isArray(value)) return value.join(", ");
	if (field.type === "date") return frappe.datetime.str_to_user(value);
	return String(value);
}

function submit() {
	if (!locked.value) {
		emit("submit", { ...values });
	}
}

function decline() {
	if (!locked.value) {
		emit("decline");
	}
}
</script>

<style scoped>
.form-card {
	margin: var(--margin-sm) 0;
	padding: var(--padding-md);
	border: 1px solid var(--border-color);
	border-radius: var(--border-radius-md);
	background: var(--fg-color);
	box-shadow: var(--shadow-sm);
}
.form-card.settled {
	box-shadow: none;
	background: var(--subtle-fg, var(--fg-color));
}
.form-heading {
	display: flex;
	align-items: center;
	gap: var(--margin-xs);
	font-weight: 600;
}
.form-icon {
	display: flex;
	color: var(--text-muted);
}
.form-title {
	flex: 1;
	min-width: 0;
}
.form-state {
	padding: 1px var(--padding-sm);
	border-radius: var(--border-radius-full, 999px);
	font-size: var(--text-xs);
	font-weight: 500;
}
.form-state.answered {
	background: var(--green-100);
	color: var(--green-700);
}
.form-state.passed {
	background: var(--control-bg);
	color: var(--text-muted);
}
.form-description {
	margin-top: var(--margin-xs);
	font-size: var(--text-sm);
}
.form-fields {
	display: flex;
	flex-direction: column;
	gap: var(--margin-md);
	margin-top: var(--margin-md);
}
.field-label {
	display: block;
	margin-bottom: var(--margin-xs);
	color: var(--text-color);
	font-size: var(--text-sm);
}
.required {
	margin-left: 2px;
	color: var(--red-500);
}
.field-help {
	margin-top: var(--margin-xs);
	font-size: var(--text-xs);
}
.choices {
	display: flex;
	flex-wrap: wrap;
	gap: var(--margin-xs) var(--margin-md);
}
.check {
	display: inline-flex;
	align-items: center;
	gap: var(--margin-xs);
	margin: 0;
	font-size: var(--text-sm);
	cursor: pointer;
}
.check input {
	margin: 0;
}
.form-error {
	color: var(--red-600);
	font-size: var(--text-sm);
}
.form-actions {
	display: flex;
	gap: var(--margin-sm);
}
.answers {
	display: grid;
	grid-template-columns: max-content minmax(0, 1fr);
	gap: var(--margin-xs) var(--margin-md);
	margin: var(--margin-sm) 0 0;
	font-size: var(--text-sm);
}
.answers dd {
	margin: 0;
	word-wrap: break-word;
}
.reason {
	margin-top: var(--margin-xs);
	font-size: var(--text-sm);
}
</style>
