// LIVE agents of the dev harness: a real Claude orchestrator + two real Claude
// sub-agents (revenue, tickets) running SQL on the synthetic sqlite datasets. The
// run emits, AS THE MODELS WORK, the same normalized events as the scripted
// scenarios (shared builders of ../events.mjs): timeline steps with orchestrator
// labels, narration, generated_sql (sqlId + captured rows), workspace operations
// (plan.set / plan.step / prov.set / widget.add / note.add) and answer deltas.
// Studio continuity mirrors the real orchestrator: with a [CURRENT STUDIO] (the
// base validated by the mock worker), edit_studio(continue|new) is exposed, the
// first widget published before a decision is refused once, new ids start past
// the carried ones, publish_widget accepts `replaces`, and a later remove emits
// widget.remove. The worker (liveApi) expands studio.continue into studio.carry.
// Next steps mirror it too: final_answer carries next_steps (validated like the
// reducer), ONE suggest.set op goes out right before the answer is streamed, and a
// data turn ending without them is nudged once.
//
// Safety and cost bounds: Haiku only, bounded max_tokens per call, max 12
// orchestrator rounds and 6 rounds per expert call, a hard cap of output (and
// input) tokens per run, a run deadline, a loop detector, SELECT-only SQL in a
// worker with a timeout and a 500-row cap. Every bound ends the run with an honest
// error code, never a silent hang.

import { agentEvent, workspaceOps, generatedSqlEvent, toDeltas } from '../events.mjs'
import { runAgentSql } from './sqlPool.mjs'
import { describeSql } from './evidence.mjs'
import { ClaudeError } from './claude.mjs'

export const LIMITS = Object.freeze({
  orchestratorRounds: 12,
  expertRounds: 6,
  expertCalls: 5,
  maxOutputTokensPerRun: 32000,
  maxInputTokensPerRun: 900000,
  orchestratorMaxTokens: 4000,
  expertMaxTokens: 2500,
  deadlineMs: 240000,
  rowCap: 500,
  rowsToModel: 25,
  // Same widget budget per turn as the real orchestrator (WS_MAX_WIDGETS).
  maxWidgets: 12,
  maxNotes: 6,
})

const LABELS = {
  fr: {
    start: 'Analyse de la demande',
    calling: { revenue: "Consultation de l'expert revenus", tickets: "Consultation de l'expert tickets" },
    done: { revenue: 'Expert revenus : résultat obtenu', tickets: 'Expert tickets : résultat obtenu' },
    failed: { revenue: 'Expert revenus : pas de résultat', tickets: 'Expert tickets : pas de résultat' },
    sql: 'Exécution du SQL sur la source',
    kind: { chart: 'Graphique', table: 'Tableau', kpi: 'KPI' },
    writing: 'Rédaction de la réponse',
  },
  en: {
    start: 'Understanding the request',
    calling: { revenue: 'Consulting the revenue expert', tickets: 'Consulting the tickets expert' },
    done: { revenue: 'Revenue expert: result obtained', tickets: 'Tickets expert: result obtained' },
    failed: { revenue: 'Revenue expert: no result', tickets: 'Tickets expert: no result' },
    sql: 'Running the SQL on the source',
    kind: { chart: 'Chart', table: 'Table', kpi: 'KPI' },
    writing: 'Writing the answer',
  },
}

// --- prompts ------------------------------------------------------------------------

// Compact schema of one dataset for a system prompt: columns, types, sample values.
function schemaBlock(ds) {
  const lines = [`Table public."${ds.table}"  (dataset ${ds.dataset}, ${ds.rows.length} rows)`]
  for (const c of ds.columns) {
    const vals = ds.rows.map((r) => r[c.name]).filter((v) => v != null && v !== '')
    let sample = ''
    if (c.type === 'string') {
      const distinct = [...new Set(vals)]
      sample = distinct.length <= 14
        ? 'values: ' + distinct.join(' | ')
        : `${distinct.length} distinct, e.g. ${distinct.slice(0, 6).join(' | ')}`
    } else if (vals.length) {
      const sorted = [...vals].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0))
      sample = `range ${sorted[0]} .. ${sorted[sorted.length - 1]}${vals.length < ds.rows.length ? ' (NULL when not applicable)' : ''}`
    }
    lines.push(`  - "${c.name}" ${c.type}: ${sample}`)
  }
  return lines.join('\n')
}

const SQL_RULES = `SQL rules (the user must be able to audit and edit your filters):
- SQLite dialect. ONE SELECT statement per run_sql call. Quote every identifier with double quotes and reference tables as public."<table>".
- Keep the WHERE a flat AND of simple column predicates (=, IN, BETWEEN, >=, <, LIKE). Dates are ISO text: filter them with plain comparisons such as "period" >= '2026-01-01' AND "period" < '2026-09-01'. Never wrap a column in a function inside WHERE.
- No CTE or sub-query unless truly unavoidable. Aggregate in SQL (GROUP BY) and give computed columns short snake_case aliases (e.g. actual_revenue, tickets, avg_hours). ROUND money to 2 decimals.
- Write plain hyphens (-), never en or em dashes.
- ORDER BY the main measure and keep results small (at most about 50 rows).
- 1 to 3 queries per question; reuse a result instead of re-running it. If a query fails, read the error and fix it.
- COMPARISON PERIODS: when the question compares figures over several periods (same period last year, previous year, budget on the same months), bound EVERY compared figure to the SAME months (e.g. "period" >= '2025-01-01' AND "period" < '2025-09-01' against the same months of 2026), never a full year against a partial one, and alias each column with the months it covers (e.g. total_2025_01_to_08).
After your queries, reply with a short factual summary (figures with units) that cites the sql_id of every result you rely on and states, per figure, the exact months it covers. Never invent a figure that no query returned.`

function revenueExpertPrompt(datasets) {
  const rev = datasets.find((d) => d.key === 'revenues')
  const opp = datasets.find((d) => d.key === 'opportunities')
  return `You are the REVENUE expert of OWIsMind (Orange Wholesale International data assistant). The data is SYNTHETIC (local test harness). You answer ONE question with the run_sql tool.
Business rules: revenue is in EUR in "revenue". Phase ACTUALS = realised revenue (closed months up to 2026-08); BUDGET (from 2025), FORECAST (2026), HLF (half-year landing, from 2026-04) and Q3F (Q3 forecast, 2026-07 to 2026-09) are plans. Default to Phase = 'ACTUALS' unless the question asks for budget or forecast, and never add different phases together. Offer hierarchy: "SolutionLine" > "Solution" > "Product". Opportunities_Won holds the deals won (amount_eur = total contract value).

${schemaBlock(rev)}

${schemaBlock(opp)}

${SQL_RULES}`
}

function ticketsExpertPrompt(datasets) {
  const tix = datasets.find((d) => d.key === 'tickets')
  return `You are the TROUBLE TICKETS expert of OWIsMind (Orange Wholesale International data assistant). The data is SYNTHETIC (local test harness). You answer ONE question with the run_sql tool.
Business rules: one row per ticket ("id"); count tickets with COUNT(DISTINCT "id"). Open tickets = "Status" IN ('Open', 'In Progress'). "resolution_hours" and "closedDate" are NULL while a ticket is not resolved. Severity P1 is the most critical.

${schemaBlock(tix)}

${SQL_RULES}`
}

const ORCHESTRATOR_PROMPT = `You are the OWIsMind orchestrator, the data assistant of Orange Wholesale International. This is a local test harness running on SYNTHETIC data. You hold NO business data: every figure you state must come from an expert result. EARLIER TURNS ARE GROUNDED: the figures of your earlier answers in this conversation and the widgets of a [CURRENT STUDIO] came from real expert queries run in those turns (the history replays only the answers, sometimes with their SQL, not the tool results). Never add a correction, a disclaimer or a doubt about a previous answer or its figures; only when a result of THIS turn actually contradicts one, state both figures with their scope. A published figure (KPI, text, chat) carries the scope stated by the expert's summary or its result column names, NEVER the scope of your own question: when a comparison figure does not cover the same months (e.g. the full year 2025 against January to August 2026), say what it is ("full year 2025") and never call it "same period"; quote a percentage change only when the result holds it.

LANGUAGE (NON-NEGOTIABLE). These instructions are in English; that is NEVER the reply language. The REPLY LANGUAGE is the language of the user's CURRENT (latest) message, stated at the very end of the user's message: obey it. Write in the REPLY LANGUAGE everything the user reads: the final answer, every progress sentence AND every tool argument (plan mission and steps, widget titles, comments, axis labels, text bodies, the scope, notes). The web-app language of the [Context - ...] block is only a tie-break for a message without a clear language. If the user switches language between turns, switch with them. If an expert answers in another language, rewrite its words in the REPLY LANGUAGE, figures, names and scope kept verbatim. The French examples below are illustrations, never a language choice. Never mix two languages in one answer. In French, address the user with 'vous', never 'tu'.

Experts (each call is independent: the expert does not see the conversation, so ask ONE precise, self-contained question):
- call_revenue_expert: DRIVE_Revenues (monthly revenue in EUR by account, partner, distribution type, offer SolutionLine > Solution > Product, Phase ACTUALS / BUDGET / FORECAST / HLF / Q3F, booking type; periods 2024-01 to 2026-09, ACTUALS up to 2026-08) and Opportunities_Won (deals won 2024-01 to 2026-09: amount_eur, contract_months, sales_region, offer).
- call_tickets_expert: TroubleTickets_year (incident tickets 2025-01 to 2026-09: Severity P1 to P4, Status, Category, Product, creationDate, closedDate, resolution_hours).

The web app shows the chat AND a STUDIO beside it (a header with the analysis scope, the plan, the journal and a board of widgets laid out as a dense dashboard). The users are business people, not analysts: they must always know WHERE the answer is, so pick ONE home for it.
- CONVERSATION (a greeting, what you can do, a definition, a clarification question): chat only, no Studio, no next_steps.
- SIMPLE QUESTION (one total, one count, one name, a short list): answer COMPLETELY in the chat (2 to 4 lines) AND publish a MINI-STUDIO from the SAME expert result: the scope text, then 2 or 3 kpi widgets (the figure asked plus the comparison points that come with it: same period last year, budget, previous month) and ONE chart when the figure is a period total (its monthly trend over that period); for a name or a short list, the scope and one table when the result has several rows. Ask the expert for those comparison points and that trend in the SAME question, so nothing has to be computed. No plan, no section text.
- ANALYSIS (several facets or themes, a comparison, an overview, a 360, a diagnosis, "analyse..."): the STUDIO IS THE ANSWER, built as a short written report; the chat only carries a short summary.

How to build the Studio report of an ANALYSIS: an in-depth business report organised by THEME, on a DENSE DASHBOARD: rows of 4 columns filled in the order you publish, no holes. Build it progressively, in this order:
1. PLAN: call set_plan FIRST: a one-sentence mission and one step per business theme (2 or 3 themes, a 4th only without KPIs; one facet = one step).
2. SCOPE, in that SAME round: ONE publish_widget kind "text" with role "scope" (title e.g. "Analysis scope" / "Périmètre de l'analyse"), 1 to 3 sentences: what is analysed, the data sources in business words, the period, any known limit. It is shown in the Studio HEADER, not on the board.
3. KPIs: a group of 3 or 4 kpi widgets published consecutively right after the scope, before any section (one full row). For a review, a 360 or an overview the KPI row is EXPECTED: 3 or 4 headline figures taken verbatim from the first results (e.g. latest full-year actual, year-to-date actual, budget gap, deals won year to date): ask for them in the first expert questions. Skip it only for a single-question analysis. NEVER a single KPI, never a KPI inside a section.
4. ONE SECTION PER BUSINESS THEME, in the plan order: update_plan_step(index, "running"); call the right expert; once its data is back, publish a section "text" widget (title = the theme) IMMEDIATELY followed by its chart or table, in one of two shapes; then update_plan_step(index, "done").
- HERO: the text, then a visual with size "wide" (full width, under its text). At least ONE hero per analysis, on the richest visual.
- PAIR: the text, then a visual without size (they share a row side by side).
ALTERNATE hero and pair sections; never three sections of the same shape in a row.
5. CLOSE with a synthesis "text" widget (title e.g. "Key takeaways" / "Synthèse et points clés", 60 to 100 words): the 2 or 3 decisions or watch points the figures call for.
SECTION TEXTS ARE REAL ANALYSES (about 90 to 140 words): ONE headline sentence in bold first, then the level, the trend, the comparison, the concentration or outliers, and the business implication. You never compute, so ASK the expert, in the SAME question, for the comparison figures the analysis needs (previous period, share of total, delta).
VISUALS: prefer a chart whenever a chart says it; a table only for a list or a ranking a chart cannot show, NEVER a table that duplicates a chart. A time series of more than 12 points or a table of 5 or more columns is always size "wide".
SPACE RULE (a MINI-STUDIO excepted): never a chart or table without its section text, never two texts in a row except the closing synthesis, never a lone KPI on a row. Publish each widget once; never republish a widget already on the board.
Budget: at most 12 widgets in total (scope included), e.g. scope + 4 KPIs + 3 sections of 2 + the synthesis. If a theme gets no data, say so honestly in its section text.
Text widgets are read by non-experts: plain business language, simple markdown (bold, short paragraphs or bullets), NO technical jargon (never SQL, query, table, column, sql_id, expert, agent or dataset names). Every figure is taken verbatim from an expert result, with its scope (phase, period, currency) and formatted (thousands separators, EUR). Never compute a new figure yourself (no total, sum, percentage or change that a result does not hold): ask the expert for it in the same question. Give a text widget a sql_id ONLY when its figures come from that exact result.
Data widgets reference a sql_id returned by an expert and ONLY column names present in that result (chart x = a label column, y = numeric columns), with a clear title (scope + period) and a one-sentence comment. Use add_note only for a check or a limit worth tracing (optional).
6. Finish with final_answer, ALONE once the widgets are in. For an ANALYSIS: 3 to 6 lines of markdown in the REPLY LANGUAGE: the 2 to 4 key takeaways with their exact figures and scope, then ONE line saying the detailed analysis is in the Studio. No paragraph per step, no repetition of the board, never a markdown table. For a SIMPLE QUESTION: 2 to 4 lines, the figures exactly as returned (formatted, with units) and their scope.

EVERY DATA ANSWER (follow-ups, periods, brevity, titles, next steps):
- FOLLOW-UPS: a short reply after an answer ("non que cette année", "que en 2026", "et pour 2025 ?", "en dessous la même chose pour 2025") corrects or extends the PREVIOUS request: restate silently what the user now wants (metric, period, scope) relative to the previous turn, then act. A reply starting with "non" / "no" corrects the previous answer: redo it with the stated constraint and nothing more. "que" / "seulement" / "uniquement" / "only" / "just" restrict to exactly what follows. Never widen a period the user narrowed, never add years. Example: previous turn = monthly chart 2026 vs 2025, user says "non que cette année" -> keep ONLY 2026 (edit_studio continue, replace the chart with a 2026-only chart). When truly ambiguous, ask ONE short question instead of guessing.
- TYPOS: read them in context: "mai" between two clauses is "mais" (but), not the month of May; "la même chose ... pour 2025" = the same widget for 2025, placed after the current one. When the reading is ambiguous, ask ONE short question.
- "This year" / "cette année" = the year of the Today date, from January to the last available month: say that period explicitly in the answer.
- COMPARISONS ALIGNED: to compare two periods, ask the expert for the SAME months in both (e.g. January to August of each year), never a full year against a partial one; say when a year is partial.
- CHAT BREVITY: never list months or items one by one in the chat when a chart or table on the board shows them: the chat gives the 2 to 4 takeaways.
- TITLES: a section text title is the business insight or theme, never its chart's title repeated; a chart title names the measure, the scope and the period.
- NEXT STEPS: finish with final_answer, its next_steps = the 2 or 3 most useful next analyses given THIS question and the data your experts really cover (another period, a breakdown, a comparison, another business theme), each phrased as a request the user can send as is, in the REPLY LANGUAGE, never what is already on the board. The chat answer then ends with ONE short sentence inviting to go further, never a list (the suggestions show as buttons).
Before each tool call, write at most one short sentence in the REPLY LANGUAGE saying what you do next (never a figure-by-figure recap). At most 4 expert calls per question. Never state a figure that no expert returned. Write plain hyphens (-), never en or em dashes.

CURRENT STUDIO (continue it or start a new one). When the user's message carries a [CURRENT STUDIO] note, the Studio on screen was built earlier in THIS conversation from real queries: its widgets are real, never say they do not come from a query. BEFORE publishing any widget, decide with edit_studio:
- CONTINUE when the message refines or extends what is on screen: keep, add, also, below, above, next to, replace, remove, change this chart, the same analysis with another cut ("garde", "rajoute", "ajoute", "en bas", "à côté", "remplace", "enlève", "ce graphique"). Then publish ONLY the new widgets, never re-publish a carried one; change one with publish_widget(replaces=<widget id>); drop what the user no longer wants with remove; update the scope (replaces=<scope widget id>) only if it changed. New widgets follow the Studio report rules above (a section text immediately followed by its visual, hero and pair shapes alternating).
- NEW when the topic is unrelated, when the user asks for a new or separate analysis ("nouvelle analyse", "à part", "repars de zéro"), or when the result would exceed 12 widgets.
- When unsure: CONTINUE if the message refers to the screen (this, the chart, keep, add) or shares its subject; otherwise NEW.
- The note lists widget titles, not their figures: to quote a figure of a carried widget, ask the expert again, never guess or recompute it.
- The final_answer stays the short summary: on continue say what you added ("I added ... to the Studio" / "J'ai complété le Studio (ajout de ...)"); on new say that the detail is in a new Studio ("The detail is in a new Studio" / "Le détail est dans un nouveau Studio").`

// --- tool definitions -------------------------------------------------------------------

const STEP_INDEX = { type: 'integer', minimum: 1, description: 'Plan step index (1-based) this action belongs to.' }

const ORCHESTRATOR_TOOLS = [
  {
    name: 'set_plan',
    description: 'Declare the analysis plan before any expert call (analysis only). Call once per question, and publish the scope text widget (role "scope") in the same round.',
    input_schema: {
      type: 'object',
      properties: {
        mission: { type: 'string', description: 'One sentence: what the analysis will establish, in the REPLY LANGUAGE.' },
        steps: { type: 'array', items: { type: 'string' }, minItems: 1, maxItems: 6, description: 'Short step labels, in order, in the REPLY LANGUAGE.' },
      },
      required: ['mission', 'steps'],
    },
  },
  {
    name: 'update_plan_step',
    description: 'Mark a plan step as running, done or error.',
    input_schema: {
      type: 'object',
      properties: { index: STEP_INDEX, status: { type: 'string', enum: ['running', 'done', 'error'] } },
      required: ['index', 'status'],
    },
  },
  {
    name: 'call_revenue_expert',
    description: 'Ask the revenue expert (DRIVE_Revenues + Opportunities_Won) one precise question. Returns its summary and the results (sql_id, columns, first rows).',
    input_schema: {
      type: 'object',
      properties: { question: { type: 'string' }, step_index: STEP_INDEX },
      required: ['question'],
    },
  },
  {
    name: 'call_tickets_expert',
    description: 'Ask the trouble tickets expert (TroubleTickets_year) one precise question. Returns its summary and the results (sql_id, columns, first rows).',
    input_schema: {
      type: 'object',
      properties: { question: { type: 'string' }, step_index: STEP_INDEX },
      required: ['question'],
    },
  },
  {
    name: 'publish_widget',
    description: 'Publish a widget on the Studio board, a dense dashboard laid out in rows of 4 columns in publishing order. chart/table/kpi need the sql_id of an expert result and exact column names of that result. kpi only in a group (3 or 4 in an analysis, 2 or 3 in a mini-Studio) published consecutively right after the scope, never alone. text (needs text) is a block of the Studio report: role "scope" = the analysis scope shown in the Studio header (once, first); role "section" (default) = the analysis of a business theme, published IMMEDIATELY BEFORE its chart / table, or the closing synthesis; sql_id only when its figures come from that result. size "wide" = a HERO visual (full width, under its text), mandatory for a time series of more than 12 points or a table of 5+ columns; without size, the visual sits beside its text. Title, comment, labels and text in the REPLY LANGUAGE.',
    input_schema: {
      type: 'object',
      properties: {
        kind: { type: 'string', enum: ['chart', 'table', 'kpi', 'text'] },
        title: { type: 'string' },
        comment: { type: 'string', description: 'One short sentence under the title.' },
        step_index: STEP_INDEX,
        sql_id: { type: 'string' },
        chart: {
          type: 'object',
          properties: {
            type: { type: 'string', enum: ['bar', 'line', 'pie', 'donut'] },
            x: { type: 'string' },
            y: { type: 'array', items: { type: 'string' } },
            style: { type: 'string', enum: ['grouped', 'stacked', 'horizontal', 'area', 'smooth'] },
            x_label: { type: 'string' },
            y_label: { type: 'string' },
            unit: { type: 'string' },
          },
          required: ['type', 'x', 'y'],
        },
        kpi: {
          type: 'object',
          properties: {
            label: { type: 'string' },
            value: { type: 'string', description: 'Result column holding the value (first row).' },
            delta_pct: { type: 'string', description: 'Optional result column holding a % change.' },
            unit: { type: 'string' },
          },
          required: ['label', 'value'],
        },
        size: { type: 'string', enum: ['normal', 'wide'], description: 'Chart / table only: "wide" = HERO visual, full width under its text (always for a time series of more than 12 points or a table of 5+ columns); omit for a visual beside its text.' },
        role: { type: 'string', enum: ['section', 'scope'], description: 'Text only: "scope" = the analysis scope in the Studio header; "section" (default) = on the board, beside its visual.' },
        text: { type: 'string', description: 'Markdown body of a text widget, in the REPLY LANGUAGE: a section = about 90 to 140 words (bold headline first), the synthesis = 60 to 100 words, the scope = 1 to 3 sentences.' },
        replaces: { type: 'string', description: 'Optional: id of a widget already on the board (e.g. "w2" of the CURRENT STUDIO) that this one replaces, at the same position.' },
      },
      required: ['kind', 'title'],
    },
  },
  {
    name: 'add_note',
    description: 'Optional: add a short note (a check or a limit worth tracing) to the Studio journal. The explanation the user reads belongs in text widgets.',
    input_schema: {
      type: 'object',
      properties: {
        kind: { type: 'string', enum: ['find', 'check', 'note'] },
        title: { type: 'string' },
        text: { type: 'string' },
        sql_id: { type: 'string' },
        step_index: STEP_INDEX,
      },
      required: ['kind', 'title'],
    },
  },
  {
    name: 'final_answer',
    description: 'Deliver your answer to the user and END the turn, once the data and the widgets of this turn are in. markdown = the chat answer, in the REPLY LANGUAGE. next_steps = the 2 or 3 most useful next analyses, each a short request the user can send as is, in the REPLY LANGUAGE (shown as clickable suggestions under the answer). Omit next_steps only for a greeting, a capability question or a clarification.',
    input_schema: {
      type: 'object',
      properties: {
        markdown: { type: 'string', description: 'The chat answer (markdown), in the REPLY LANGUAGE.' },
        next_steps: {
          type: 'array',
          items: { type: 'string' },
          maxItems: 3,
          description: "2 or 3 next analyses, 8 to 120 characters each, in the REPLY LANGUAGE, phrased as a request the user can send as is (e.g. 'Compare 2026 to the budget month by month' / 'Comparer 2026 au budget mois par mois'); never a figure, never a yes/no question, never what is already on the board.",
        },
      },
      required: ['markdown'],
    },
  },
]

// Exposed only when the run carries a CURRENT STUDIO (mirror of STUDIO_TOOL_SPEC).
const EDIT_STUDIO_TOOL = {
  name: 'edit_studio',
  description: 'Decide what happens to the CURRENT STUDIO (listed in the [CURRENT STUDIO] note) BEFORE publishing any widget. mode "continue" keeps its widgets on the board (built from real queries of this conversation): then publish ONLY the new widgets, use publish_widget(replaces=<widget id>) to change one, and "remove" for the widgets the user no longer wants. mode "new" starts an empty Studio for this answer (the previous one stays with its own answer).',
  input_schema: {
    type: 'object',
    properties: {
      mode: { type: 'string', enum: ['continue', 'new'] },
      remove: { type: 'array', items: { type: 'string' }, maxItems: 12, description: 'continue only: ids of CURRENT STUDIO widgets to drop (e.g. ["w3"]).' },
    },
    required: ['mode'],
  },
}

const RUN_SQL_TOOL = {
  name: 'run_sql',
  description: 'Run ONE read-only SQLite SELECT on the tables of your system prompt. Returns sql_id, columns, row_count and the first rows (or the error).',
  input_schema: {
    type: 'object',
    properties: {
      sql: { type: 'string' },
      purpose: { type: 'string', description: 'One sentence: what this query measures.' },
    },
    required: ['sql', 'purpose'],
  },
}

// --- the turn -------------------------------------------------------------------------------

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
// Model text reaches the UI: the project bans the em dash (U+2014) and en dash (U+2013)
// everywhere, so they are normalized to '-' on the way in.
const DASHES = new RegExp('[\\u2013\\u2014]', 'g')
const clean = (s) => String(s == null ? '' : s).replace(DASHES, '-')
const clip = (s, n) => clean(s).trim().slice(0, n)
// Every machine control token (mode, lang, studio, prior...) is stripped from the
// text the model sees (mirror of the orchestrator's _CTRL_TOKEN_RE).
const CTRL_TOKENS = new RegExp('\u27e6owi:[a-z_]+=[^\u27e7]*\u27e7', 'g')
const stripTokens = (s) => String(s == null ? '' : s).replace(CTRL_TOKENS, '').trimEnd()
// Identity of a widget for the duplicate guard (mirror of _Workspace.widget_signature).
const normSig = (s) => String(s == null ? '' : s).split(/\s+/).filter(Boolean).join(' ').toLowerCase()
// Next steps (mirror of _ws_next_steps / the reducer's suggestion_items): strings
// only, trimmed, 8 to 120 chars (dropped, never cut), case / whitespace dedupe, max 3.
const SUGGEST = Object.freeze({ maxItems: 3, minChars: 8, maxChars: 120 })
function nextSteps(value) {
  const out = []
  const seen = new Set()
  for (const raw of Array.isArray(value) ? value : []) {
    if (typeof raw !== 'string') continue
    const item = clean(raw).trim()
    const n = [...item].length
    if (n < SUGGEST.minChars || n > SUGGEST.maxChars) continue
    const key = normSig(item)
    if (seen.has(key)) continue
    seen.add(key)
    out.push(item)
    if (out.length >= SUGGEST.maxItems) break
  }
  return out
}
// A short answer ending on a question is a clarification: never nudged.
const isClarification = (t) => { const s = String(t || '').trim(); return !!s && s.length <= 400 && s.endsWith('?') }
// One-time nudge (mirror of _STEPS_NUDGE_MSG) when a data turn ends without next steps.
const STEPS_NUDGE = 'Not delivered yet: this answer has no next_steps. Call final_answer again with the SAME markdown and next_steps = the 2 or 3 most useful next analyses (another period, a breakdown, a comparison, another business theme your experts cover), each a short request the user can send as is, in the REPLY LANGUAGE, never what is already on the board.'
function widgetSignature(p) {
  const head = `${p.kind}|${normSig(p.title)}`
  if (p.sql_id) return `${head}|sql|${p.sql_id}`
  if (p.kind === 'text') return `${head}|text|${normSig(p.text)}`
  return `${head}|none|`
}

export class LiveTurn {
  /**
   * @param {object} o
   * @param {{create:Function}} o.client   Claude Messages client (claude.mjs or a stub)
   * @param {string} o.model
   * @param {Array} o.datasets              buildLiveDatasets()
   * @param {string} o.message              the user's message
   * @param {Array} o.history               [{user, assistant}] previous turns
   * @param {string} o.lang                 'fr' | 'en' (web-app language, fallback only)
   * @param {string} [o.promptLang]         'fr' | 'en' (REPLY LANGUAGE = the language of
   *                                         this message; drives the timeline labels and
   *                                         the experts' USER LANGUAGE, wins over `lang`)
   * @param {string} [o.userSuffix]         the backend context block ([Context - ...],
   *                                         ⟦owi:mode/lang⟧ tokens, language imperative)
   * @param {{ids:string[], block:string}} [o.studio]  the CURRENT STUDIO (validated base)
   * @param {Function} o.emit               (event) => void, appends to the live feed
   * @param {AbortSignal} o.signal          cooperative stop
   * @param {Function} [o.log]
   */
  constructor(o) {
    Object.assign(this, o)
    // Reply language of THIS turn (backend token), the web-app language as fallback:
    // same rule as the orchestrator (token_lang or fallback) for the timeline labels.
    this.replyLang = ['fr', 'en'].includes(o.promptLang) ? o.promptLang : (o.lang === 'en' ? 'en' : 'fr')
    this.labels = LABELS[this.replyLang]
    this.startedAt = Date.now()
    this.usage = { input_tokens: 0, output_tokens: 0, cache_creation_input_tokens: 0, cache_read_input_tokens: 0 }
    this.sqlItems = []
    this.expertCalls = 0
    this.widgetCount = 0
    this.noteCount = 0
    this.plan = null
    this.answerSoFar = ''
    this.ws = workspaceOps()
    this.wsCount = 0
    this.toolSignatures = new Map()
    this.expertPrompts = { revenue: revenueExpertPrompt(o.datasets), tickets: ticketsExpertPrompt(o.datasets) }
    // Mirror of the orchestrator's context_msg (a system message to the specialist):
    // pins the language of any message the expert addresses to the user.
    this.expertContext = `USER LANGUAGE: ${this.replyLang} - write any message addressed to the user (clarification, no-data, out-of-scope) in THIS language.${this.replyLang === 'fr' ? " Address the user with 'vous'." : ''}`
    // Studio continuity bookkeeping (mirror of the orchestrator's _Workspace).
    this.studio = o.studio && Array.isArray(o.studio.ids) && o.studio.ids.length ? o.studio : null
    this.studioIds = this.studio ? this.studio.ids.slice(0, LIMITS.maxWidgets) : []
    this.decision = null
    this.guardUsed = false
    this.carried = []
    this.ownWidgets = []
    this.widgetSigs = new Map()   // own widget id -> duplicate-guard signature
    this.stepsNudged = false      // the missing-next_steps nudge fired once
    this.draft = ''               // answer written before that nudge (fallback)
    this.batchHasExpert = false   // final_answer next to an expert call is refused
    this.nextWidget = 1 + Math.max(0, ...this.studioIds.map((id) => Number((/^w(\d+)$/.exec(id) || [])[1]) || 0))
    this.log = o.log || (() => {})
  }

  elapsed() {
    return Math.round((Date.now() - this.startedAt) / 100) / 10
  }

  step(label, extra) {
    this.emit(agentEvent(this.elapsed(), label, extra))
  }

  wsOp(op, payload) {
    // The backend caps workspace events per run (80): never exceed it.
    if (this.wsCount >= 78) return
    this.wsCount += 1
    this.emit(this.ws(this.elapsed(), op, payload))
  }

  checkBounds() {
    if (this.signal && this.signal.aborted) throw new ClaudeError('stopped')
    if (Date.now() - this.startedAt > LIMITS.deadlineMs) throw new ClaudeError('deadline_reached', 'run deadline')
    if (this.usage.output_tokens > LIMITS.maxOutputTokensPerRun) throw new ClaudeError('partial_result', 'output token cap')
    if (this.usage.input_tokens + this.usage.cache_read_input_tokens + this.usage.cache_creation_input_tokens > LIMITS.maxInputTokensPerRun) {
      throw new ClaudeError('partial_result', 'input token cap')
    }
  }

  async callModel(body) {
    this.checkBounds()
    const resp = await this.client.create({
      model: this.model,
      output_config: { effort: 'low' },
      cache_control: { type: 'ephemeral' },
      ...body,
    }, this.signal)
    const u = (resp && resp.usage) || {}
    for (const k of Object.keys(this.usage)) this.usage[k] += Number(u[k]) || 0
    if (resp && resp.stop_reason === 'refusal') throw new ClaudeError('agent_unavailable', 'refusal')
    return resp
  }

  // Same tool + same input 3 times = the model is looping: stop honestly.
  guardLoop(name, input) {
    const sig = name + ':' + JSON.stringify(input)
    const n = (this.toolSignatures.get(sig) || 0) + 1
    this.toolSignatures.set(sig, n)
    if (n >= 3) throw new ClaudeError('partial_result', 'tool loop: ' + name)
  }

  planStepId(index) {
    if (!this.plan || !Number.isInteger(index)) return null
    const s = this.plan[index - 1]
    return s ? s.id : null
  }

  /** Run the whole turn; resolves with { answer }. Throws ClaudeError on a bound. */
  async run() {
    this.step(this.labels.start, { eventKind: 'START' })
    const messages = []
    for (const h of this.history || []) {
      if (!h.user || !h.assistant) continue
      messages.push({ role: 'user', content: stripTokens(h.user) }, { role: 'assistant', content: h.assistant })
    }
    // Backend order: the message, the [CURRENT STUDIO] block, then the context block
    // with the language imperative LAST (highest recency). The model reads the human
    // blocks only: every machine token is stripped, as the orchestrator does.
    const studioNote = this.studio ? this.studio.block : ''
    messages.push({ role: 'user', content: stripTokens(this.message + studioNote + (this.userSuffix || '')) })
    const tools = this.studio ? [...ORCHESTRATOR_TOOLS, EDIT_STUDIO_TOOL] : ORCHESTRATOR_TOOLS
    for (let round = 1; round <= LIMITS.orchestratorRounds; round++) {
      const resp = await this.callModel({
        max_tokens: LIMITS.orchestratorMaxTokens,
        system: ORCHESTRATOR_PROMPT,
        tools,
        messages,
      })
      const content = Array.isArray(resp.content) ? resp.content : []
      messages.push({ role: 'assistant', content })
      const text = content.filter((b) => b.type === 'text').map((b) => b.text).join(' ').trim()
      const uses = content.filter((b) => b.type === 'tool_use')
      if (text && uses.length) this.emit({ type: 'narration', text: clip(text, 280) })
      if (!uses.length) {
        if (resp.stop_reason === 'max_tokens') {
          messages.push({ role: 'user', content: 'Your output was cut. Be concise and call final_answer now.' })
          continue
        }
        if (text) {
          // A plain-text answer on a data turn: nudged once for its next steps.
          if (this.needsNudge(text)) {
            this.stepsNudged = true
            this.draft = clean(text)
            messages.push({ role: 'user', content: STEPS_NUDGE })
            continue
          }
          return this.finish(clean(text), [])
        }
        if (this.draft) return this.finish(this.draft, [])
        messages.push({ role: 'user', content: 'Call final_answer with your answer.' })
        continue
      }
      const results = []
      let final = null
      let finalSteps = []
      this.batchHasExpert = uses.some((u) => u.name === 'call_revenue_expert' || u.name === 'call_tickets_expert')
      for (const tu of uses) {
        this.guardLoop(tu.name, tu.input)
        const out = await this.orchestratorTool(tu.name, tu.input || {})
        if (out.final != null) {
          final = out.final
          finalSteps = out.steps || []
        }
        results.push({
          type: 'tool_result',
          tool_use_id: tu.id,
          content: typeof out.content === 'string' ? out.content : JSON.stringify(out.content),
          ...(out.isError ? { is_error: true } : {}),
        })
      }
      if (final != null) return this.finish(final, finalSteps)
      messages.push({ role: 'user', content: results })
    }
    throw new ClaudeError('partial_result', 'orchestrator round cap')
  }

  async orchestratorTool(name, input) {
    const err = (msg) => ({ content: 'Error: ' + msg, isError: true })
    switch (name) {
      case 'set_plan': {
        if (this.plan) return err('the plan is already set; use update_plan_step.')
        const steps = (Array.isArray(input.steps) ? input.steps : []).map((s) => clip(s, 140)).filter(Boolean).slice(0, 6)
        if (!steps.length) return err('steps must be a non-empty list of labels.')
        this.plan = steps.map((label, i) => ({ id: 'p' + (i + 1), label, status: 'todo' }))
        this.wsOp('plan.set', {
          mission: clip(input.mission, 240) || steps[0],
          origin: 'model',
          steps: this.plan.map(({ id, label }) => ({ id, label })),
        })
        return { content: `Plan set with steps ${this.plan.map((s, i) => `${i + 1}=${s.id}`).join(', ')}.` }
      }
      case 'update_plan_step': {
        const stepId = this.planStepId(input.index)
        if (!stepId) return err('unknown step index.')
        if (!['running', 'done', 'error'].includes(input.status)) return err('status must be running, done or error.')
        this.plan[input.index - 1].status = input.status
        this.wsOp('plan.step', { step_id: stepId, status: input.status })
        return { content: 'ok' }
      }
      case 'call_revenue_expert':
      case 'call_tickets_expert': {
        if (this.expertCalls >= LIMITS.expertCalls) return err('expert call budget reached; answer with the results you have.')
        const question = clip(input.question, 2000)
        if (!question) return err('question is required.')
        const key = name === 'call_revenue_expert' ? 'revenue' : 'tickets'
        return { content: await this.runExpert(key, question, input.step_index) }
      }
      case 'publish_widget':
        return this.publishWidget(input, err)
      case 'edit_studio':
        return this.editStudio(input, err)
      case 'add_note': {
        if (this.noteCount >= LIMITS.maxNotes) return err('note budget reached.')
        const title = clip(input.title, 140)
        if (!title || !['find', 'check', 'note'].includes(input.kind)) return err('kind (find|check|note) and title are required.')
        const payload = { id: 'n' + (++this.noteCount), kind: input.kind, title }
        const stepId = this.planStepId(input.step_index)
        if (stepId) payload.step_id = stepId
        if (input.text) payload.text = clip(input.text, 1200)
        if (input.sql_id && this.sqlItems.some((it) => it.sql_id === input.sql_id)) payload.sql_id = input.sql_id
        this.wsOp('note.add', payload)
        return { content: 'ok' }
      }
      case 'final_answer': {
        if (this.batchHasExpert) return err('Answer NOT delivered: the expert results of this batch came after it. Read them, publish the widgets, then call final_answer.')
        const md = clean(input.markdown).trim()
        if (!md) return err('markdown is required.')
        const steps = nextSteps(input.next_steps)
        if (!steps.length && this.needsNudge(md)) {
          this.stepsNudged = true
          this.draft = md
          return { content: STEPS_NUDGE }
        }
        return { content: 'Answer delivered.', final: md, steps }
      }
      default:
        return err('unknown tool ' + name)
    }
  }

  // A turn that used data (a successful expert SQL) and still has no next steps
  // gets ONE nudge; greetings, capability questions and clarifications never do.
  needsNudge(text) {
    return !this.stepsNudged && this.sqlItems.some((it) => it.success) && !isClarification(text)
  }

  boardIds() {
    return [...this.carried, ...this.ownWidgets]
  }

  capacityLeft() {
    return Math.max(0, LIMITS.maxWidgets - this.carried.length - this.ownWidgets.length)
  }

  studioText(lead) {
    const next = Array.from({ length: Math.min(3, this.capacityLeft()) }, (_, i) => 'w' + (this.nextWidget + i))
    return `${lead} Carried widgets kept as they are (NEVER re-publish them): ${this.carried.join(', ') || '(none)'}. Your new widgets get the next ids (${next.join(', ') || '-'}...), appended below. Capacity left: ${this.capacityLeft()} of ${LIMITS.maxWidgets}. Change one with publish_widget(replaces=<id>), drop one with edit_studio(mode="continue", remove=[<id>]).`
  }

  editStudio(input, err) {
    if (!this.studioIds.length) return err('there is no CURRENT STUDIO in this conversation: just publish your widgets.')
    const remove = (Array.isArray(input.remove) ? input.remove : []).map((id) => String(id).trim())
    if (input.mode === 'new') {
      if (this.decision === 'continue') return err('this turn already CONTINUES the Studio: use remove or replaces instead.')
      this.decision = 'new'
      return { content: `New Studio: you start from an empty board (${this.capacityLeft()} widgets free); the previous Studio stays with its own answer.` }
    }
    if (input.mode !== 'continue') return err('mode must be "continue" or "new".')
    if (this.decision === 'new') return err('this turn already started a NEW Studio; keep publishing on it.')
    if (this.decision === 'continue') {
      const removed = []
      for (const id of remove) {
        if (!this.boardIds().includes(id) || removed.includes(id)) continue
        this.wsOp('widget.remove', { id })
        removed.push(id)
        this.carried = this.carried.filter((x) => x !== id)
        this.ownWidgets = this.ownWidgets.filter((x) => x !== id)
      }
      return { content: this.studioText(`Studio updated${removed.length ? ' (removed ' + removed.join(', ') + ')' : ''}.`) }
    }
    const dropped = [...new Set(remove.filter((id) => this.studioIds.includes(id)))].slice(0, 12)
    const kept = this.studioIds.filter((id) => !dropped.includes(id))
    if (kept.length + this.ownWidgets.length > LIMITS.maxWidgets) return err('board full: remove widgets or use mode new.')
    this.wsOp('studio.continue', dropped.length ? { remove: dropped } : {})
    this.decision = 'continue'
    this.carried = kept
    return { content: this.studioText('Continuing the CURRENT STUDIO.') }
  }

  publishWidget(input, err) {
    // Continuity guard: with a CURRENT STUDIO, the first widget published before
    // any edit_studio decision is refused once (forces continue / new); a second
    // attempt without a decision proceeds as a new Studio.
    if (this.studioIds.length && this.decision == null) {
      if (!this.guardUsed) {
        this.guardUsed = true
        return err(`Decide first: edit_studio(mode=continue|new). The CURRENT STUDIO holds ${this.studioIds.join(', ')}; then publish this widget again.`)
      }
      this.decision = 'new'
    }
    const replaces = typeof input.replaces === 'string' ? input.replaces.trim() : ''
    if (replaces && !this.boardIds().includes(replaces)) {
      return err(`unknown widget id to replace "${replaces.slice(0, 40)}". On the board: ${this.boardIds().join(', ') || '(none)'}.`)
    }
    if (!replaces && this.capacityLeft() <= 0) return err('widget budget reached (replace or remove one).')
    const kind = input.kind
    const title = clip(input.title, 200)
    if (!['chart', 'table', 'kpi', 'text'].includes(kind) || !title) return err('kind and title are required.')
    const payload = { id: 'w' + this.nextWidget, kind, title }
    const stepId = this.planStepId(input.step_index)
    if (stepId) payload.step_id = stepId
    if (input.comment) payload.comment = clip(input.comment, 280)
    if (kind === 'text') {
      const body = clip(input.text, 4000)
      if (!body) return err('a text widget needs text.')
      payload.text = body
      if (['section', 'scope'].includes(input.role)) payload.role = input.role
      // Same rule as the real orchestrator: a text widget carries a sql_id only
      // when that result exists in this run (never a guessed id).
      const bound = this.sqlItems.find((it) => it.sql_id === input.sql_id && it.success)
      if (bound) payload.sql_id = bound.sql_id
    } else {
      const item = this.sqlItems.find((it) => it.sql_id === input.sql_id)
      if (!item) return err(`unknown sql_id "${input.sql_id}". Known: ${this.sqlItems.filter((i) => i.success).map((i) => i.sql_id).join(', ') || 'none'}.`)
      if (!item.success || !item.result) return err(`sql_id ${input.sql_id} failed; it has no rows.`)
      const cols = item.result.columns
      const canon = (name) => cols.find((c) => String(c).toLowerCase() === String(name || '').trim().toLowerCase()) || null
      payload.sql_id = item.sql_id
      // Same layout hint rule as the backend contract: size on a chart / table only.
      if ((kind === 'chart' || kind === 'table') && ['normal', 'wide'].includes(input.size)) payload.size = input.size
      if (kind === 'chart') {
        const c = input.chart || {}
        const x = canon(c.x)
        const ys = (Array.isArray(c.y) ? c.y : [c.y]).map(canon).filter(Boolean).slice(0, 8)
        if (!['bar', 'line', 'pie', 'donut'].includes(c.type)) return err('chart.type must be bar, line, pie or donut.')
        if (!x || !ys.length) return err(`chart.x and chart.y must be columns of ${item.sql_id}: ${cols.join(', ')}.`)
        const chart = { type: c.type, x, y: ys }
        if (['grouped', 'stacked', 'horizontal', 'area', 'smooth'].includes(c.style)) chart.style = c.style
        if (c.x_label) chart.x_label = clip(c.x_label, 80)
        if (c.y_label) chart.y_label = clip(c.y_label, 80)
        if (c.unit) chart.unit = clip(c.unit, 16)
        payload.chart = chart
      } else if (kind === 'kpi') {
        const k = input.kpi || {}
        const value = canon(k.value)
        if (!value) return err(`kpi.value must be a column of ${item.sql_id}: ${cols.join(', ')}.`)
        const kpi = { label: clip(k.label, 120) || title, value }
        const delta = canon(k.delta_pct)
        if (delta) kpi.delta_pct = delta
        if (k.unit) kpi.unit = clip(k.unit, 16)
        payload.kpi = kpi
      }
    }
    // Duplicate guard (mirror of the orchestrator's _Workspace.find_duplicate): the
    // same widget already published in THIS run (kind + normalised title + sql_id,
    // or the same body for an unbound text) is not published again, not even
    // through a replace of ANOTHER widget (re-publishing the replaced one in place
    // is fine). A replace re-registers the signature below.
    const sig = widgetSignature(payload)
    const dup = this.ownWidgets.find((id) => id !== replaces && this.widgetSigs.get(id) === sig)
    if (dup && replaces) return { content: `Widget ${dup} already shows this on the board, not duplicated: ${replaces} stays as it is (drop it with edit_studio remove if needed).` }
    if (dup) return { content: `Widget ${dup} is already on the board, not duplicated. Move on to the next widget.` }
    this.widgetSigs.set(payload.id, sig)
    this.widgetCount += 1
    this.nextWidget += 1
    if (replaces) {
      payload.replaces = replaces
      if (this.carried.includes(replaces)) {
        this.carried = this.carried.filter((x) => x !== replaces)
        this.ownWidgets.push(payload.id)
      } else {
        this.ownWidgets = this.ownWidgets.map((x) => (x === replaces ? payload.id : x))
      }
    } else this.ownWidgets.push(payload.id)
    // The real orchestrator emits a timeline artifact step for data widgets only;
    // a text widget travels on the workspace channel alone.
    if (kind !== 'text') this.step(`${this.labels.kind[kind]} : ${title}`, { eventKind: 'ARTIFACT' })
    this.wsOp('widget.add', payload)
    const left = this.capacityLeft()
    return {
      content: kind === 'text'
        ? `Text block ${payload.id} published in the Studio (${left} widget(s) left).`
        : `Widget ${payload.id} published in the Studio (${left} widget(s) left). Do not repeat its rows in the chat.`,
    }
  }

  async runExpert(key, question, stepIndexArg) {
    const callNo = ++this.expertCalls
    const stepId = this.planStepId(stepIndexArg)
    this.step(this.labels.calling[key], {
      eventKind: 'CALLING_AGENT', agentKey: key, stepIndex: callNo,
      ...(this.plan ? { stepCount: this.plan.length } : {}),
    })
    const messages = [{ role: 'user', content: question }]
    const mine = []
    let summary = ''
    let qn = 0
    for (let round = 1; round <= LIMITS.expertRounds; round++) {
      const resp = await this.callModel({
        max_tokens: LIMITS.expertMaxTokens,
        system: `${this.expertPrompts[key]}\n\n${this.expertContext}`,
        tools: [RUN_SQL_TOOL],
        messages,
      })
      const content = Array.isArray(resp.content) ? resp.content : []
      messages.push({ role: 'assistant', content })
      const uses = content.filter((b) => b.type === 'tool_use')
      const text = content.filter((b) => b.type === 'text').map((b) => b.text).join('\n').trim()
      if (!uses.length) {
        summary = text
        break
      }
      const results = []
      for (const tu of uses) {
        if (tu.name !== 'run_sql') {
          results.push({ type: 'tool_result', tool_use_id: tu.id, content: 'Error: unknown tool', is_error: true })
          continue
        }
        this.guardLoop('run_sql', tu.input)
        if (qn >= 4) {
          results.push({ type: 'tool_result', tool_use_id: tu.id, content: 'Error: query budget reached; summarize now.', is_error: true })
          continue
        }
        const sqlId = `s${callNo}q${++qn}`
        const out = await this.runSql(key, callNo, sqlId, stepId, tu.input || {}, question)
        mine.push(out.item)
        results.push({ type: 'tool_result', tool_use_id: tu.id, content: JSON.stringify(out.forModel), ...(out.item.success ? {} : { is_error: true }) })
      }
      messages.push({ role: 'user', content: results })
      if (round === LIMITS.expertRounds) summary = text || 'Stopped after the maximum number of rounds.'
    }
    const ok = mine.filter((it) => it.success)
    this.step(ok.length ? this.labels.done[key] : this.labels.failed[key], {
      eventKind: 'AGENT_DONE', agentKey: key, status: ok.length ? 'ok' : 'error',
    })
    return JSON.stringify({
      expert: key,
      summary: clip(summary, 3000),
      results: ok.map((it) => ({
        sql_id: it.sql_id,
        columns: it.result.columns,
        row_count: it.row_count,
        truncated: !!it.result.truncated,
        rows: it.result.rows.slice(0, 15),
      })),
      failed_sql_ids: mine.filter((it) => !it.success).map((it) => it.sql_id),
    })
  }

  async runSql(key, callNo, sqlId, stepId, input, question) {
    const sql = String(input.sql || '').trim()
    this.step(this.labels.sql, { eventKind: 'RUNNING_TOOL', toolName: 'semantic-model-query' })
    const t0 = Date.now()
    const r = await runAgentSql(sql, { cap: LIMITS.rowCap, timeoutMs: 5000 })
    const duration = Date.now() - t0
    const item = { sql, success: !!r.ok, row_count: r.ok ? r.rows.length : null, sql_id: sqlId, step_index: callNo, agent_key: key }
    if (r.ok) {
      item.result = { columns: r.columns, rows: r.rows, truncated: !!r.truncated }
      const ev = describeSql(sql, this.datasets)
      if (ev.unavailable) item.evidenceReason = ev.unavailable
      else item.evidence = ev
    } else item.error = r.error
    this.sqlItems.push(item)
    this.emit(generatedSqlEvent({
      sqlIndex: this.sqlItems.length, success: item.success, rowCount: item.row_count, sql,
      sqlId, stepIndex: callNo, agentKey: key, result: item.result,
    }))
    this.wsOp('prov.set', {
      sql_id: sqlId, agent_key: key, tool: 'semantic-model-query',
      task: clip(input.purpose || question, 800),
      ...(stepId ? { step_id: stepId } : {}),
      duration_ms: duration, ...(item.row_count != null ? { row_count: item.row_count } : {}), success: item.success,
    })
    const forModel = r.ok
      ? { sql_id: sqlId, ok: true, columns: r.columns, row_count: r.rows.length, truncated: !!r.truncated, rows: r.rows.slice(0, LIMITS.rowsToModel) }
      : { sql_id: sqlId, ok: false, error: r.error }
    return { item, forModel }
  }

  // Close the steps left running (never a step that did not start), emit the next
  // steps (ONE suggest.set right before the answer), then stream the answer as
  // small deltas (the Mesh cadence).
  async finish(answer, steps) {
    for (const s of this.plan || []) {
      if (s.status === 'running') {
        s.status = 'done'
        this.wsOp('plan.step', { step_id: s.id, status: 'done' })
      }
    }
    this.step(this.labels.writing, { eventKind: 'WRITING_ANSWER' })
    const items = nextSteps(steps)
    if (items.length) this.wsOp('suggest.set', { items })
    for (const delta of toDeltas(answer)) {
      if (this.signal && this.signal.aborted) throw new ClaudeError('stopped')
      this.answerSoFar += delta
      this.emit({ type: 'answer_delta', text: delta })
      await sleep(18)
    }
    return { answer }
  }
}
