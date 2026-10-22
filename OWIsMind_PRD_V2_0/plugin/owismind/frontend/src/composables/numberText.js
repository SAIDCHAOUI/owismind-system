// Figures that never split across a line or a column break. A narrative text written
// by the agent groups digits with REGULAR spaces ("8 593 242,88 EUR"): each space is a
// break opportunity, so a multi-column text widget could end column 1 on "8 593" and
// start column 2 on "242,88 EUR". keepNumbersTogether rewrites the markdown SOURCE
// (strings in, strings out, before rendering):
//   - the regular spaces between digit groups become narrow no-break spaces (U+202F,
//     the French typographic thousands separator): 1 to 3 digits, then one or more
//     groups of exactly 3 digits, never glued to another digit ("2025 2026" and
//     "12 3456" are left alone);
//   - the regular space between a figure and its unit becomes a no-break space
//     (U+00A0) for EUR / USD / currency signs / % / k / M / Md / pts..., when the unit
//     is a whole token ("3 Mois" is left alone);
//   - code (fenced blocks and inline code spans) is never touched.
// Pure, idempotent, never throws.

const NNBSP = ' '
const NBSP = ' '

const DIGIT_GROUPS_RE = /(?<!\d)\d{1,3}(?: \d{3})+(?!\d)/g
const UNIT_RE =
  /(\d) (?=(?:EUR|USD|GBP|CHF|€|\$|£|%|‰|kEUR|MEUR|MdEUR|k€|M€|Md€|k|K|M|Md|Mds|Mrd|Mrds|bn|pts?|pp)(?![\p{L}\p{N}]))/gu
// Fenced code blocks (``` or ~~~, possibly unterminated) and inline code spans.
const CODE_RE = /(```[\s\S]*?(?:```|$)|~~~[\s\S]*?(?:~~~|$)|`[^`\n]*`)/

function joinProse(part) {
  return part
    .replace(DIGIT_GROUPS_RE, (m) => m.replace(/ /g, NNBSP))
    .replace(UNIT_RE, '$1' + NBSP)
}

/** The text with its figures (digit groups + unit) bound together, code untouched. */
export function keepNumbersTogether(text) {
  if (typeof text !== 'string' || !text) return ''
  // split() with a capturing group: odd indices are the code chunks, kept verbatim.
  return text
    .split(CODE_RE)
    .map((part, i) => (i % 2 ? part : joinProse(part)))
    .join('')
}
