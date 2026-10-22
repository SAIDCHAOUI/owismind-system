// The LIVE half of the mock backend: real Claude runs (or the stub), the sqlite
// datasets behind Source Data, and the Evidence descriptors / re-queries of live
// exchanges. api.mjs owns the routes and the in-memory exchange store; it hands the
// shared helpers in (no circular import) and delegates here when the mode is live.
// Response shapes stay those of the real backend (routes.py, stream_manager.py,
// evidence/service.py), exactly like the scripted half.

import { buildLiveDatasets } from './datasets.mjs'
import { openDatasetDb, structuredRows, structuredAggregate, structuredDistinct } from './sqlite.mjs'
import { createClaudeClient, estimateCost, ClaudeError } from './claude.mjs'
import { createStubFetch } from './stubFetch.mjs'
import { LiveTurn } from './agents.mjs'
import { detectPromptLanguage, buildUserSuffix } from './lang.mjs'
import { usageSummaryEvent } from '../events.mjs'
import { buildStudioBlock, carryingEmit } from '../studio.mjs'

// The harness user (api.mjs ME.user_id 'said.chaoui'), as identity.derive_full_name
// renders it in the backend's context block.
const HARNESS_FULL_NAME = 'Said Chaoui'

export function createLiveBackend(config, deps) {
  const datasets = buildLiveDatasets()
  const byKey = Object.fromEntries(datasets.map((d) => [d.key, d]))
  const db = openDatasetDb(datasets)
  const log = (msg) => console.log('[owi-harness] ' + msg)
  const client = createClaudeClient({
    apiKey: config.mode === 'stub' ? 'stub' : config.apiKey,
    fetchImpl: config.mode === 'stub' ? createStubFetch() : undefined,
    log,
  })

  // --- /agents sources + /source/* (sqlite, SELECT-only, bounded) --------------------

  const sources = datasets.map((d, id) => ({ id, label: d.label, dataset: d.dataset }))

  function handleSource(pathname, body, query) {
    const sourceId = Number(body.source != null ? body.source : query.source) || 0
    const ds = datasets[sourceId] || datasets[0]
    if (pathname.endsWith('/meta')) return { status: 'ok', label: ds.label, columns: ds.columns }
    const scope = { filters: body.filters || [], q: body.q }
    if (pathname.endsWith('/rows')) {
      return { status: 'ok', ...structuredRows(db, ds, { ...scope, sort: body.sort, limit: body.limit, offset: body.offset }) }
    }
    if (pathname.endsWith('/aggregate')) {
      return { status: 'ok', ...structuredAggregate(db, ds, { ...scope, group: body.group, measures: body.measures, limit: body.limit }) }
    }
    // distinct: scope_q is the table-level search; q is the picker's own column search.
    return { status: 'ok', ...structuredDistinct(db, ds, body.column, body.q, { filters: body.filters || [], q: body.scope_q }) }
  }

  // --- live runs ----------------------------------------------------------------------

  function startRun(run, body) {
    const abort = new AbortController()
    Object.assign(run, { live: true, events: [], done: false, error: null, abort })
    // Worker relay: a studio.continue of the agent becomes the studio.carry of the
    // validated base (same seq), never named by the agent (stream_manager._worker).
    const emit = carryingEmit((ev) => run.events.push(ev), run.studioBase)
    emit({ type: 'run_started', exchangeId: run.exchangeId })
    // [CURRENT STUDIO] block + ids (context.build_studio_block) of the validated base.
    const block = run.studioBase ? buildStudioBlock(run.studioBase.doc) : ''
    const studio = block ? { block, ids: run.studioBase.doc.widgets.map((w) => w.id).slice(0, 12) } : null
    const historyLimit = Math.max(0, Math.min(Number(body.history_limit) || 6, 10))
    // Reply language = the language of THIS prompt (routes.py: detect_prompt_language
    // with the web-app language as the tie-break), plus the exact end-of-message
    // context block the DSS agent receives (context.build_user_suffix).
    const webappLang = body.webapp_lang === 'en' ? 'en' : 'fr'
    const promptLang = detectPromptLanguage(run.userText, webappLang)
    const userSuffix = buildUserSuffix({
      fullName: HARNESS_FULL_NAME, now: new Date(), webappLang, promptLang, mode: run.mode,
    })
    // LiveTurn options added for the reply language:
    //   promptLang ('fr' | 'en'): the language the agent MUST answer in (chat reply,
    //     plan, widget titles/subtitles/texts, scope); always wins over `lang`.
    //   userSuffix (string): the backend context block (bracket header, ⟦owi:mode⟧ /
    //     ⟦owi:lang⟧ tokens, the language imperative) to append to the END of the
    //     current user message, as build_completion_messages does in DSS.
    // `lang` stays the web-app language (UI-facing labels only).
    const turn = new LiveTurn({
      client,
      model: config.model,
      datasets,
      message: run.userText,
      history: deps.conversationHistory(run.sessionId, historyLimit),
      lang: webappLang,
      promptLang,
      userSuffix,
      studio,
      emit,
      signal: abort.signal,
      log,
    })
    run.turn = turn
    finishRun(run, turn).catch((e) => {
      log('live run crashed: ' + ((e && e.message) || e))
      run.events.push({ type: 'error', message: 'agent_unavailable' })
      run.error = 'agent_unavailable'
      run.done = true
    })
  }

  async function finishRun(run, turn) {
    let status = 'done'
    let code = null
    let answer = ''
    try {
      answer = (await turn.run()).answer
    } catch (e) {
      code = e instanceof ClaudeError ? e.code : 'agent_unavailable'
      if (!(e instanceof ClaudeError)) log('live run error: ' + ((e && e.stack) || e))
      else log(`live run ended early: ${code}${e.detail ? ' (' + e.detail + ')' : ''}`)
      status = code === 'stopped' ? 'stopped' : 'error'
      answer = turn.answerSoFar
    }
    const u = turn.usage
    const inputTokens = u.input_tokens + u.cache_creation_input_tokens + u.cache_read_input_tokens
    const cost = estimateCost(u)
    // The Mesh usage footer arrives before the terminal frames (cut by a user stop).
    if (status !== 'stopped') run.events.push(usageSummaryEvent(inputTokens, u.output_tokens, cost))
    log(`live run ${status}: ${turn.sqlItems.length} SQL, in=${inputTokens} out=${u.output_tokens} tokens, ~$${cost}`)

    // Persist (mirror of stream_manager: workspace reduced from the run's events).
    const sqlItems = turn.sqlItems
    const filtersBySql = {}
    for (const it of sqlItems) {
      if (it.evidence) filtersBySql[it.sql_id] = it.evidence.explanationSteps.filter((s) => s.kind.startsWith('filter_'))
    }
    const workspace = deps.buildWorkspaceDoc(run.exchangeId, run.events, status, sqlItems)
    deps.persistExchange(run.sessionId, run.exchangeId, run.userText, run.agentKey, run.mode, {
      live: true,
      answer,
      sqlItems,
      usage: { input_tokens: inputTokens, output_tokens: u.output_tokens, total_tokens: inputTokens + u.output_tokens, estimated_cost: cost },
      evidence: null,
      artifacts: [],
      workspace,
      filtersBySql,
    })
    run.persisted = true

    // Terminal frames, exactly as the worker appends them.
    if (status === 'done') {
      run.events.push({ type: 'final_answer', exchangeId: run.exchangeId, text: answer })
      run.events.push({ type: 'run_done', status: 'success' })
    } else if (status === 'stopped') {
      run.events.push({ type: 'final_answer', exchangeId: run.exchangeId, text: answer })
      run.events.push({ type: 'stopped', exchangeId: run.exchangeId })
    } else if (code === 'partial_result' || code === 'deadline_reached') {
      // A safety bound cut the run: keep the partial answer, then a terminal error.
      run.events.push({ type: 'final_answer', exchangeId: run.exchangeId, text: answer })
      run.events.push({ type: 'error', message: code })
      run.error = code
    } else {
      run.events.push({ type: 'error', message: code })
      run.error = code
    }
    run.done = true
  }

  function poll(run, cursorRaw) {
    const cursor = Number(cursorRaw) || 0
    const visible = run.events.slice()
    // The worker strips captured rows from the polled copy (rows stay persistence-only).
    const events = visible.slice(cursor).map((e) => {
      if (e.type !== 'generated_sql' || !e.result) return e
      const { result, ...rest } = e
      return rest
    })
    return { status: 'ok', events, cursor: visible.length, done: run.done, error: run.error }
  }

  function stop(run) {
    if (run.done) return false
    run.abort.abort()
    return true
  }

  // --- Evidence of live exchanges --------------------------------------------------------

  function pickItem(entry, sqlId) {
    const items = entry.sqlItems || []
    if (sqlId) return items.find((it) => it.sql_id === sqlId) || null
    return [...items].reverse().find((it) => it.success && it.evidence)
      || [...items].reverse().find((it) => it.success)
      || null
  }

  function queries(entry, active) {
    return deps.queriesFor(entry, active).map((q, i) => ({ ...q, matched: !!entry.sqlItems[i].evidence }))
  }

  function evidenceMeta(exchangeId, entry, sqlId) {
    const item = pickItem(entry, sqlId)
    if (sqlId && !item) return { missing: true }
    const declared = { level: 'declared', result_captured: false }
    if (!item) {
      return { status: 'ok', exchange_id: exchangeId, available: false, reason: 'no_sql', sql: null, verification: declared, artifacts: [] }
    }
    if (!item.success || !item.evidence) {
      return {
        status: 'ok', exchange_id: exchangeId, available: false,
        reason: item.success ? item.evidenceReason || 'no_matching_dataset' : 'no_successful_sql',
        sql: item.sql || null, sql_id: item.sql_id || null, queries: queries(entry, item), verification: declared, artifacts: [],
      }
    }
    const ev = item.evidence
    const ds = byKey[ev.key]
    const result = { captured: true, columns: item.result.columns, rows: item.result.rows, row_count: item.row_count, truncated: !!item.result.truncated }
    return {
      status: 'ok',
      exchange_id: exchangeId,
      available: true,
      sql_id: item.sql_id,
      dataset: ds.dataset,
      columns: ds.columns.map((c) => ({ name: c.name, type: c.type })),
      chips: ev.chips,
      advanced: ev.advanced,
      sql: item.sql,
      source: { dataset: ds.dataset, schema: 'public', table: ds.table, url: '' },
      sources: [{ dataset: ds.dataset, schema: 'public', table: ds.table, label: ds.dataset }],
      queries: queries(entry, item),
      verification: { level: ev.verification.level, result_captured: true, ...ev.verification },
      explanation: { ok: true, steps: ev.explanationSteps },
      result,
      drilldown: ev.drillColumns.length
        ? { available: true, columns: ev.drillColumns, reason: null }
        : { available: false, columns: [], reason: ev.drillReason || 'no_group_keys' },
      artifacts: [],
    }
  }

  // The base table scoped by the kept chips (a chip re-sent edited inside `filters`
  // applies once, with its edited values), then the user's filters / search / drill.
  function scopedFilters(ev, body, excludeId) {
    const keptIds = Array.isArray(body.kept_ids) ? body.kept_ids : null
    const filterCols = new Set((body.filters || []).map((f) => f.column))
    const chips = ev.chips.filter((c) => c.id !== excludeId && (keptIds == null || keptIds.includes(c.id)) && !filterCols.has(c.column))
    return [...chips, ...(body.filters || [])]
  }

  // rows / aggregate / distinct of a live exchange (sql_id already validated by api.mjs).
  function evidenceRoute(pathname, body, entry) {
    const item = pickItem(entry, body.sql_id)
    if (!item || !item.evidence) return { httpStatus: 409, payload: { status: 'error', error: (item && item.evidenceReason) || 'no_matching_dataset' } }
    const ev = item.evidence
    const ds = byKey[ev.key]
    if (pathname.endsWith('/rows')) {
      const scope = { filters: scopedFilters(ev, body), q: body.q, drill: body.drill }
      return { httpStatus: 200, payload: { status: 'ok', ...structuredRows(db, ds, { ...scope, sort: body.sort, limit: body.limit, offset: body.offset }) } }
    }
    if (pathname.endsWith('/aggregate')) {
      const scope = { filters: scopedFilters(ev, body), q: body.q, drill: body.drill }
      return { httpStatus: 200, payload: { status: 'ok', ...structuredAggregate(db, ds, { ...scope, group: body.group, measures: body.measures, limit: body.limit }) } }
    }
    const scope = { filters: scopedFilters(ev, body, body.exclude_id), q: body.scope_q, drill: body.drill }
    return { httpStatus: 200, payload: { status: 'ok', ...structuredDistinct(db, ds, body.column, body.q, scope) } }
  }

  return { mode: config.mode, model: config.model, sources, handleSource, startRun, poll, stop, evidenceMeta, evidenceRoute }
}
