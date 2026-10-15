// Markdown rendering for the agent answer - the ONLY place untrusted (LLM) text
// becomes HTML, so it is sanitized. markdown-it with raw HTML
// DISABLED (so any HTML in the answer is escaped, not interpreted), then a
// DOMPurify pass as defense in depth. Links open in a new tab safely.
import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'

const md = new MarkdownIt({
  html: false, // never interpret raw HTML from the model
  linkify: true,
  breaks: true,
  typographer: false,
})

// Harden links: target=_blank + rel=noopener noreferrer.
DOMPurify.addHook('afterSanitizeAttributes', (node) => {
  if (node.tagName === 'A') {
    node.setAttribute('target', '_blank')
    node.setAttribute('rel', 'noopener noreferrer')
  }
})

/** Render markdown to a SANITIZED HTML string safe for v-html. */
export function renderMarkdown(text) {
  if (!text) return ''
  const raw = md.render(String(text))
  return DOMPurify.sanitize(raw, { USE_PROFILES: { html: true } })
}
