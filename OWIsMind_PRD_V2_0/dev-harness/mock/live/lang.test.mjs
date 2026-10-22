// Parity tests of the harness reply-language port against the backend's
// plugin/owismind/python-lib/owismind/agents/context.py.
// Run: node --test OWIsMind_PRD_V2_0/dev-harness/mock/live/lang.test.mjs
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import {
  FR_WORDS, EN_WORDS, NEUTRAL_WORDS, detectPromptLanguage, detectPromptLanguageScored, buildUserSuffix,
} from './lang.mjs'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const PYLIB = path.resolve(HERE, '../../../plugin/owismind/python-lib')
const CONTEXT_PY = path.join(PYLIB, 'owismind/agents/context.py')

const FRENCH = [
  "Quelle est l'évolution des revenus ?", 'montre les revenus du client', 'tu peux rajouter le forecast ?',
  "Peux-tu me faire une revue complète du chiffre d'affaires ?", 'Compare les ACTUALS et le budget pour la phase 2',
  'pourquoi le CA baisse en mars ?', 'merci', 'bonjour', "c'est quoi le total EMEA ?",
  "qu'est-ce qui explique cette hausse", "et pour l'année dernière ?", "aujourd'hui", 'l’évolution',
]
const ENGLISH = [
  'can you do for me a complete review of the revenues please ?', 'What is the revenue trend?',
  'add the budget series', 'show me the top 10 clients by revenue in 2025', 'thanks', 'hello',
  "what's the total for EMEA?", "I'd like to see the open tickets", "don't include the cancelled deals",
  "let's look at the quarterly numbers", 'what’s up',
]
const NEUTRAL = ['42', 'ok', '', '   ', 'revenue 2025 EMEA', 'revenus EVPL 2026', 'ACTUALS budget total', 'valeur 2025', 'montre the revenue']

function pyWords(name) {
  const src = readFileSync(CONTEXT_PY, 'utf8')
  const m = new RegExp(name + ' = frozenset\\("""([\\s\\S]*?)"""').exec(src)
  assert.ok(m, `${name} not found in context.py`)
  return new Set(m[1].split(/\s+/).filter(Boolean))
}

test('word lists are identical to context.py', () => {
  assert.deepEqual([...FR_WORDS].sort(), [...pyWords('_FR_WORDS')].sort())
  assert.deepEqual([...EN_WORDS].sort(), [...pyWords('_EN_WORDS')].sort())
  assert.deepEqual([...NEUTRAL_WORDS].sort(), [...pyWords('_NEUTRAL_WORDS')].sort())
})

test('corpus: French, English, neutral fallback', () => {
  for (const m of FRENCH) assert.equal(detectPromptLanguage(m, 'en'), 'fr', m)
  for (const m of ENGLISH) assert.equal(detectPromptLanguage(m, 'fr'), 'en', m)
  for (const m of NEUTRAL) {
    assert.equal(detectPromptLanguage(m, 'en'), 'en', m)
    assert.equal(detectPromptLanguage(m, 'fr'), 'fr', m)
  }
  assert.equal(detectPromptLanguage('42', 'toString'), 'fr')
})

test('suffix: language rule and header', () => {
  const s = buildUserSuffix({
    fullName: 'Said Chaoui', now: new Date(2026, 5, 9, 14, 30), webappLang: 'fr', promptLang: 'en', mode: 'smart',
  })
  const lines = s.split('\n')
  assert.equal(lines[2], '[Context - User: Said Chaoui · Today: Tuesday, June 09, 2026 at 14:30 · Web app language: French] ⟦owi:mode=smart⟧⟦owi:lang=en⟧')
  assert.match(lines[3], /^IMPORTANT - reply in English/)
  assert.match(lines[3], /every tool argument \(plan steps, widget titles, subtitles, texts, scope\)/)
  assert.match(lines[3], /The web-app language \(French\) is NOT the reply language\./)
})

// Same answers and same suffix text as the Python module (skipped without python3).
const py = spawnSync('python3', ['--version'])
test('parity with the Python implementation', { skip: py.status !== 0 && 'python3 not available' }, () => {
  const messages = [...FRENCH, ...ENGLISH, ...NEUTRAL]
  const suffixCases = [
    ['Said Chaoui', 'fr', 'en', 'smart'], ['X', 'en', 'fr', 'claude'], [null, 'fr', 'fr', null],
    ['X', null, 'en', 'pro'], ['X', 'zz', 'zz', 'turbo'], ['X', 'en', null, null],
  ]
  const script = [
    'import json, sys',
    'from datetime import datetime',
    'from owismind.agents.context import detect_prompt_language_scored, build_user_suffix',
    'data = json.load(sys.stdin)',
    'now = datetime(2026, 6, 9, 14, 30)',
    'out = {"detect": [list(detect_prompt_language_scored(m)) for m in data["messages"]],',
    '       "suffix": [build_user_suffix(n, now, webapp_lang=w, prompt_lang=p, mode=m) for n, w, p, m in data["suffix"]]}',
    'sys.stdout.write(json.dumps(out))',
  ].join('\n')
  const r = spawnSync('python3', ['-c', script], {
    input: JSON.stringify({ messages, suffix: suffixCases }),
    env: { ...process.env, PYTHONPATH: PYLIB },
    encoding: 'utf8',
  })
  assert.equal(r.status, 0, r.stderr)
  const out = JSON.parse(r.stdout)
  messages.forEach((m, i) => assert.deepEqual(detectPromptLanguageScored(m), out.detect[i], m))
  suffixCases.forEach(([fullName, webappLang, promptLang, mode], i) => {
    const js = buildUserSuffix({ fullName, now: new Date(2026, 5, 9, 14, 30), webappLang, promptLang, mode })
    assert.equal(js, out.suffix[i])
  })
})
