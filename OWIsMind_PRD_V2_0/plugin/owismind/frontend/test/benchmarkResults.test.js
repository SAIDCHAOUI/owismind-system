// Pure benchmark-results helpers - run with `node --test test/*.test.js` (NO install).
// Asserts the donut geometry, the band -> token map, the effective-verdict resolution
// and the defensive normalizer the consultation view depends on.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  clampPct,
  pctFromAccuracy,
  donutGeometry,
  bandToken,
  verdictKind,
  pctText,
  rowKey,
  normalizeResults,
  hasScoredResults,
  distinctModes,
  hasMultipleModes,
  heroVerdictKind,
  modeClass,
  modeColor,
  modeLabel,
  resultPillKind,
  rowAccentKind,
  meterWidth,
  catWidth,
  evolutionKind,
  evolutionClass,
  attemptCount,
  attemptHistory,
  attemptPillKind,
  actualToolsText,
  hasRefVsActual,
  expectedText,
  fmtScore,
  cellIsNumeric,
  formatCell,
} from '../src/composables/benchmarkResults.js'

test('clampPct keeps values in [0,100]', () => {
  assert.equal(clampPct(50), 50)
  assert.equal(clampPct(-5), 0)
  assert.equal(clampPct(150), 100)
  assert.equal(clampPct('abc'), 0)
})

test('pctFromAccuracy scales a 0..1 fraction', () => {
  assert.equal(pctFromAccuracy(0.75), 75)
  assert.equal(pctFromAccuracy(1), 100)
  assert.equal(pctFromAccuracy(0), 0)
  assert.equal(pctFromAccuracy(2), 100) // clamped
  assert.equal(pctFromAccuracy(null), 0)
})

test('donutGeometry - full ring offset is 0, empty ring offset is the whole circumference', () => {
  const g = donutGeometry(100, 52)
  assert.ok(Math.abs(g.circumference - 2 * Math.PI * 52) < 1e-9)
  assert.ok(Math.abs(g.offset - 0) < 1e-9)
  const empty = donutGeometry(0, 52)
  assert.ok(Math.abs(empty.offset - empty.circumference) < 1e-9)
  const half = donutGeometry(50, 52)
  assert.ok(Math.abs(half.offset - half.circumference / 2) < 1e-9)
})

test('bandToken maps bands to charter tokens', () => {
  assert.equal(bandToken('high'), 'var(--success)')
  assert.equal(bandToken('medium'), 'var(--orange)')
  assert.equal(bandToken('low'), 'var(--danger)')
  assert.equal(bandToken('HIGH'), 'var(--success)')
  assert.equal(bandToken('unknown'), 'var(--text-3)')
  assert.equal(bandToken(undefined), 'var(--text-3)')
})

test('verdictKind - effective override wins, then judge, then review', () => {
  assert.equal(verdictKind({ effective_correct: true }), 'correct')
  assert.equal(verdictKind({ effective_correct: false }), 'incorrect')
  assert.equal(verdictKind({ effective_correct: null, effective_verdict: 'correct' }), 'correct')
  assert.equal(verdictKind({ needs_review: true }), 'review')
  assert.equal(verdictKind({ correct: true }), 'correct')
  assert.equal(verdictKind({ correct: false }), 'incorrect')
  assert.equal(verdictKind({}), 'unknown')
  assert.equal(verdictKind(null), 'unknown')
})

test('pctText - number rounds, string passes through, else dash', () => {
  assert.equal(pctText(75), '75%')
  assert.equal(pctText(74.6), '75%')
  assert.equal(pctText('80%'), '80%')
  assert.equal(pctText(''), '-')
  assert.equal(pctText(null), '-')
})

test('rowKey is stable per question x agent x mode', () => {
  assert.equal(rowKey({ question_id: 'q1', agent_key: 'a', mode: 'smart' }), 'q1::a::smart')
  assert.equal(rowKey({ question_id: 'q1', agent_key: 'a' }), 'q1::a::')
  assert.equal(rowKey({}), '::::')
})

test('normalizeResults - safe defaults for a missing / partial payload', () => {
  const empty = normalizeResults(null)
  assert.equal(empty.benchmark_id, '')
  assert.equal(empty.benchmark_name, '')
  assert.deepEqual(empty.benchmarks, [])
  assert.deepEqual(empty.configs, [])
  assert.deepEqual(empty.detail, [])
  assert.deepEqual(empty.categories, [])
  assert.equal(empty.kpis.n_scored, 0)
  assert.equal(empty.kpis.band, '')

  const r = normalizeResults({
    benchmark_id: 7,
    benchmark_name: 'said',
    benchmarks: [{ benchmark_id: '7', benchmark_name: 'said', last_run_timestamp: 't', n_questions: 6 }],
    kpis: { accuracy: 0.5, accuracy_pct: 50, n_correct: 3, n_scored: 6, band: 'medium', total_cost_str: '$1.20' },
    configs: [{ mode: 'smart' }],
    categories: [{ bucket: 'revenue', accuracy: 0.5 }],
    detail: [{ question_id: 'q1' }],
  })
  assert.equal(r.benchmark_id, '7') // coerced to string
  assert.equal(r.benchmark_name, 'said')
  assert.equal(r.benchmarks.length, 1)
  assert.equal(r.kpis.accuracy, 0.5)
  assert.equal(r.kpis.total_cost_str, '$1.20')
  assert.equal(r.configs.length, 1)
  assert.equal(r.detail.length, 1)
})

test('normalizeResults - detail passthrough keeps the v2 per-attempt fields', () => {
  const r = normalizeResults({
    benchmark_id: 'b1',
    detail: [
      {
        question_id: 'q1',
        agent_key: 'orchestrator',
        mode: 'smart',
        run_id: 'run-42',
        attempt_no: 3,
        n_attempts: 3,
        delta: 'improved',
        expected_sql: 'SELECT 1',
        expected_tool: 'show_chart',
        actual_tools: 'chart,table',
        attempts: [
          { attempt_no: 1, run_timestamp: 't1', judge_score: 2, verdict: 'incorrect', correct: false },
          { attempt_no: 2, run_timestamp: 't2', judge_score: 4, verdict: 'correct', correct: true },
          { attempt_no: 3, run_timestamp: 't3', judge_score: 5, verdict: 'correct', correct: true },
        ],
      },
    ],
  })
  const row = r.detail[0]
  assert.equal(row.run_id, 'run-42')
  assert.equal(row.attempt_no, 3)
  assert.equal(row.n_attempts, 3)
  assert.equal(row.delta, 'improved')
  assert.equal(row.expected_sql, 'SELECT 1')
  assert.equal(row.expected_tool, 'show_chart')
  assert.equal(row.actual_tools, 'chart,table')
  assert.equal(row.attempts.length, 3)
  assert.equal(row.attempts[2].judge_score, 5)
})

test('hasScoredResults - true only when something is scored', () => {
  assert.equal(hasScoredResults(null), false)
  assert.equal(hasScoredResults(normalizeResults({})), false)
  assert.equal(hasScoredResults(normalizeResults({ kpis: { n_scored: 4 } })), true)
  assert.equal(hasScoredResults(normalizeResults({ detail: [{ question_id: 'q' }] })), true)
  assert.equal(hasScoredResults(normalizeResults({ configs: [{ mode: 'smart' }] })), true)
})

// --- Conditional modes -------------------------------------------------------
test('distinctModes - unique lower-cased non-blank modes across configs', () => {
  assert.equal(distinctModes(null).size, 0)
  assert.equal(distinctModes({ configs: [] }).size, 0)
  assert.equal(distinctModes({ configs: [{ mode: 'Smart' }, { mode: 'smart' }] }).size, 1)
  assert.equal(distinctModes({ configs: [{ mode: 'Smart' }, { mode: 'Pro' }] }).size, 2)
  assert.equal(distinctModes({ configs: [{ mode: '' }, { mode: null }, {}] }).size, 0)
})

test('hasMultipleModes - true only above one distinct mode', () => {
  assert.equal(hasMultipleModes(null), false)
  assert.equal(hasMultipleModes({ configs: [{ mode: 'Smart' }] }), false)
  assert.equal(hasMultipleModes({ configs: [{ mode: 'Smart' }, { mode: 'smart' }] }), false)
  assert.equal(hasMultipleModes({ configs: [{ mode: 'Smart' }, { mode: 'Pro' }] }), true)
  assert.equal(hasMultipleModes({ configs: [] }), false)
})

// --- Band / mode / verdict meta ----------------------------------------------
test('heroVerdictKind - band to hero pill kind', () => {
  assert.equal(heroVerdictKind('high'), 'good')
  assert.equal(heroVerdictKind('medium'), 'mid')
  assert.equal(heroVerdictKind('low'), 'bad')
  assert.equal(heroVerdictKind('HIGH'), 'good')
  assert.equal(heroVerdictKind('nope'), 'plaus')
  assert.equal(heroVerdictKind(undefined), 'plaus')
})

test('modeClass - mode to badge class', () => {
  assert.equal(modeClass('Smart'), 'mode-smart')
  assert.equal(modeClass('pro'), 'mode-pro')
  assert.equal(modeClass('CLAUDE'), 'mode-claude')
  assert.equal(modeClass('other'), 'mode-default')
  assert.equal(modeClass(null), 'mode-default')
})

test('modeColor - mode to token expression', () => {
  assert.equal(modeColor('smart'), 'var(--success)')
  assert.equal(modeColor('pro'), 'var(--orange)')
  assert.equal(modeColor('claude'), 'var(--danger)')
  assert.equal(modeColor(''), 'var(--text-3)')
})

test('modeLabel - display label, blank falls back to Standard', () => {
  assert.equal(modeLabel('Smart'), 'Smart')
  assert.equal(modeLabel('  Pro '), 'Pro')
  assert.equal(modeLabel(''), 'Standard')
  assert.equal(modeLabel(null), 'Standard')
})

test('resultPillKind - effective verdict to pill kind', () => {
  assert.equal(resultPillKind({ effective_correct: true }), 'ok')
  assert.equal(resultPillKind({ effective_correct: false }), 'bad')
  assert.equal(resultPillKind({ needs_review: true }), 'plaus')
  assert.equal(resultPillKind({}), 'plaus')
})

test('rowAccentKind - danger for incorrect, warn for review, else none', () => {
  assert.equal(rowAccentKind({ effective_correct: false }), 'danger')
  assert.equal(rowAccentKind({ correct: false }), 'danger')
  assert.equal(rowAccentKind({ needs_review: true }), 'warn')
  assert.equal(rowAccentKind({ effective_correct: true }), '')
  assert.equal(rowAccentKind({}), '')
  assert.equal(rowAccentKind(null), '')
})

// --- Meters ------------------------------------------------------------------
test('meterWidth / catWidth - accuracy fraction to CSS width', () => {
  assert.equal(meterWidth(0.5), '50%')
  assert.equal(meterWidth(2), '100%')
  assert.equal(meterWidth(null), '0%')
  assert.equal(catWidth({ accuracy: 0.25 }), '25%')
  assert.equal(catWidth(null), '0%')
})

// --- Evolution ---------------------------------------------------------------
test('evolutionKind / evolutionClass - delta to kind + pill class', () => {
  assert.equal(evolutionKind({ delta: 'improved' }), 'improved')
  assert.equal(evolutionKind({ delta: 'REGRESSED' }), 'regressed')
  assert.equal(evolutionKind({ delta: 'weird' }), '')
  assert.equal(evolutionKind({}), '')
  assert.equal(evolutionClass({ delta: 'improved' }), 'evo-up')
  assert.equal(evolutionClass({ delta: 'regressed' }), 'evo-down')
  assert.equal(evolutionClass({ delta: 'same' }), 'evo-flat')
  assert.equal(evolutionClass({}), 'evo-flat')
})

test('attemptCount / attemptHistory - defensive', () => {
  assert.equal(attemptCount({ n_attempts: 3 }), 3)
  assert.equal(attemptCount({ n_attempts: 0 }), 1)
  assert.equal(attemptCount({}), 1)
  assert.equal(attemptCount(null), 1)
  assert.deepEqual(attemptHistory({ attempts: [{ attempt_no: 1 }] }), [{ attempt_no: 1 }])
  assert.deepEqual(attemptHistory({}), [])
  assert.deepEqual(attemptHistory(null), [])
})

test('attemptPillKind - correct flag then verdict', () => {
  assert.equal(attemptPillKind({ correct: true }), 'ok')
  assert.equal(attemptPillKind({ correct: false }), 'bad')
  assert.equal(attemptPillKind({ verdict: 'correct' }), 'ok')
  assert.equal(attemptPillKind({ verdict: 'incorrect' }), 'bad')
  assert.equal(attemptPillKind({}), 'plaus')
  assert.equal(attemptPillKind(null), 'plaus')
})

// --- Reference vs produced ---------------------------------------------------
test('actualToolsText - array or scalar to readable list', () => {
  assert.equal(actualToolsText({ actual_tools: ['a', 'b'] }), 'a, b')
  assert.equal(actualToolsText({ actual_tools: ['a', null, ' '] }), 'a')
  assert.equal(actualToolsText({ actual_tools: 'chart,table' }), 'chart,table')
  assert.equal(actualToolsText({}), '')
  assert.equal(actualToolsText(null), '')
})

test('hasRefVsActual - any reference material triggers the tab', () => {
  assert.equal(hasRefVsActual({ expected_sql: 'SELECT 1' }), true)
  assert.equal(hasRefVsActual({ expected_tool: 't' }), true)
  assert.equal(hasRefVsActual({ actual_tools: ['x'] }), true)
  assert.equal(hasRefVsActual({}), false)
  assert.equal(hasRefVsActual(null), false)
})

test('expectedText - value with optional type', () => {
  assert.equal(expectedText({ expected_value: '1284300', expected_value_type: 'currency' }), '1284300 (currency)')
  assert.equal(expectedText({ expected_value: 42 }), '42')
  assert.equal(expectedText({ expected_value: '' }), '')
  assert.equal(expectedText({}), '')
  assert.equal(expectedText(null), '')
})

// --- Formatting --------------------------------------------------------------
test('fmtScore - two decimals or dash', () => {
  assert.equal(fmtScore(4), '4.00')
  assert.equal(fmtScore(3.5), '3.50')
  assert.equal(fmtScore(null), '-')
  assert.equal(fmtScore('4'), '-')
})

test('cellIsNumeric - only finite number types', () => {
  assert.equal(cellIsNumeric(12), true)
  assert.equal(cellIsNumeric(0), true)
  assert.equal(cellIsNumeric('12'), false)
  assert.equal(cellIsNumeric(null), false)
  assert.equal(cellIsNumeric(NaN), false)
})

test('formatCell - group large magnitudes, keep years / ids / text literal', () => {
  assert.equal(formatCell(null), '')
  assert.equal(formatCell(2025), '2025') // year stays literal
  assert.equal(formatCell(42), '42') // small int stays literal
  assert.equal(formatCell(1284300, 'en'), '1,284,300')
  assert.equal(formatCell(12.5, 'en'), '12.5')
  assert.equal(formatCell('Acme Corp'), 'Acme Corp')
  assert.equal(formatCell('2025-03-31'), '2025-03-31') // date string untouched
})
