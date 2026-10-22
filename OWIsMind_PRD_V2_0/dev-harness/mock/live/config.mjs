// Harness mode resolution. `live` = real Claude agents over the synthetic sqlite
// datasets; `scripted` = the timed scripted scenarios (the historical behaviour);
// `stub` = the live code path driven by a canned fake model (no network, no cost).
//
// Key lookup: dev-harness/.env (parsed here, no dotenv) then the process env var.
// The key is NEVER logged: only the resolved mode is printed.

import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const ENV_FILE = resolve(dirname(fileURLToPath(import.meta.url)), '../../.env')

export const LIVE_MODEL = 'claude-haiku-5-5'

// Minimal KEY=VALUE parser: comments, blank lines, optional `export `, quotes.
export function parseEnv(text) {
  const out = {}
  for (const raw of String(text || '').split(/\r?\n/)) {
    const line = raw.trim()
    if (!line || line.startsWith('#')) continue
    const m = line.match(/^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/)
    if (!m) continue
    let value = m[2].trim()
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1)
    } else {
      value = value.replace(/\s+#.*$/, '')
    }
    out[m[1]] = value
  }
  return out
}

export function loadHarnessConfig() {
  let fileEnv = {}
  try {
    fileEnv = parseEnv(readFileSync(ENV_FILE, 'utf8'))
  } catch {
    fileEnv = {}
  }
  const apiKey = (fileEnv.ANTHROPIC_API_KEY || process.env.ANTHROPIC_API_KEY || '').trim()
  const forced = String(process.env.OWI_HARNESS_MODE || fileEnv.OWI_HARNESS_MODE || '').trim().toLowerCase()
  let mode = apiKey ? 'live' : 'scripted'
  if (forced === 'scripted' || forced === 'stub') mode = forced
  if (forced === 'live' && !apiKey) mode = 'scripted'
  return { mode, apiKey: mode === 'live' ? apiKey : '', model: LIVE_MODEL, envFile: ENV_FILE }
}
