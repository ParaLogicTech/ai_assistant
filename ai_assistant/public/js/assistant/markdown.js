import showdown from "showdown";

const converter = new showdown.Converter({
	tables: true,
	ghCodeBlocks: true,
	strikethrough: true,
	tasklists: true,
	simplifiedAutoLink: true,
	literalMidWordUnderscores: true,
	disableForced4SpacesIndentedSublists: true,
});

// What a model's answer may render as. No images: an image URL in an answer is fetched
// as soon as it renders, which would let injected text leak data through its query.
const ALLOWED_TAGS = new Set([
	"a",
	"b",
	"blockquote",
	"br",
	"code",
	"del",
	"em",
	"h1",
	"h2",
	"h3",
	"h4",
	"h5",
	"h6",
	"hr",
	"i",
	"input",
	"li",
	"ol",
	"p",
	"pre",
	"s",
	"strong",
	"table",
	"tbody",
	"td",
	"th",
	"thead",
	"tr",
	"ul",
]);

// Dropped with everything inside them, rather than unwrapped to their text.
const DROPPED_TAGS = new Set(["script", "style", "iframe", "object", "embed", "template", "svg", "math"]);

const ALLOWED_ATTRIBUTES = {
	a: ["href", "title"],
	code: ["class"],
	input: ["type", "checked", "disabled"],
	td: ["align"],
	th: ["align"],
};

const SAFE_HREF = /^(https?:|mailto:|\/|#)/i;

/** Renders a model's Markdown answer as HTML that is safe to insert. */
export function renderMarkdown(text) {
	return sanitize(converter.makeHtml(text || ""));
}

function sanitize(html) {
	// A template's content is inert: nothing in it runs or loads while it is cleaned.
	const template = document.createElement("template");
	template.innerHTML = html;
	clean(template.content);

	return template.innerHTML;
}

function clean(parent) {
	for (const node of [...parent.childNodes]) {
		if (node.nodeType === Node.TEXT_NODE) {
			continue;
		}

		if (node.nodeType !== Node.ELEMENT_NODE) {
			node.remove();
			continue;
		}

		const tag = node.tagName.toLowerCase();

		if (DROPPED_TAGS.has(tag)) {
			node.remove();
			continue;
		}

		clean(node);

		if (!ALLOWED_TAGS.has(tag)) {
			node.replaceWith(...node.childNodes);
			continue;
		}

		const allowed = ALLOWED_ATTRIBUTES[tag] || [];
		for (const attribute of [...node.attributes]) {
			if (!allowed.includes(attribute.name)) {
				node.removeAttribute(attribute.name);
			}
		}

		if (tag === "input" && node.getAttribute("type") !== "checkbox") {
			node.remove();
		} else if (tag === "input") {
			node.setAttribute("disabled", "");
		}

		if (tag === "a") {
			if (!SAFE_HREF.test((node.getAttribute("href") || "").trim())) {
				node.removeAttribute("href");
			}

			node.setAttribute("target", "_blank");
			node.setAttribute("rel", "noopener noreferrer");
		}
	}
}
