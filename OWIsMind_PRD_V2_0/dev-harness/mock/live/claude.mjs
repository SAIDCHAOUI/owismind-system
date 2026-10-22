// Minimal Claude Messages API client over fetch (Node 24 built-in). The harness
// installs nothing, so the official SDK is not available here: this is raw HTTP
// against POST /v1/messages with bounded retries (429 / 5xx / network, max 2,
// exponential backoff honouring retry-after), a per-call timeout and cooperative
// cancellation. Errors carry a machine `code` the run maps to the UI's runError.*.

const API_URL = 'https://api.anthropic.com/v1/messages'

// USD per million tokens (Claude Haiku 5.5, prompts <= 100K tokens).
export const PRICING = { input: 0.1, output: 0.5, cacheWrite: 0.125, cacheRead: 0.01 }

export function estimateCost(usage) {
  const u = usage || {}
  const usd = ((u.input_tokens || 0) * PRICING.input
    + (u.output_tokens || 0) * PRICING.output
    + (u.cache_creation_input_tokens || 0) * PRICING.cacheWrite
    + (u.cache_read_input_tokens || 0) * PRICING.cacheRead) / 1e6
  return Math.round(usd * 1e6) / 1e6
}

export class ClaudeError extends Error {
  constructor(code, detail, status) {
    super(code)
    this.code = code
    this.detail = detail || ''
    this.status = status || null
  }
}

const sleep = (ms, signal) => new Promise((resolve, reject) => {
  if (signal && signal.aborted) return reject(new ClaudeError('stopped'))
  const t = setTimeout(resolve, ms)
  if (signal) signal.addEventListener('abort', () => { clearTimeout(t); reject(new ClaudeError('stopped')) }, { once: true })
})

export function createClaudeClient({ apiKey, fetchImpl, timeoutMs = 60000, maxRetries = 2, log = () => {} }) {
  const doFetch = fetchImpl || globalThis.fetch
  async function create(body, signal) {
    let attempt = 0
    for (;;) {
      if (signal && signal.aborted) throw new ClaudeError('stopped')
      const callSignal = signal
        ? AbortSignal.any([signal, AbortSignal.timeout(timeoutMs)])
        : AbortSignal.timeout(timeoutMs)
      let res
      try {
        res = await doFetch(API_URL, {
          method: 'POST',
          headers: {
            'content-type': 'application/json',
            'x-api-key': apiKey,
            'anthropic-version': '2023-06-01',
          },
          body: JSON.stringify(body),
          signal: callSignal,
        })
      } catch (e) {
        if (signal && signal.aborted) throw new ClaudeError('stopped')
        const timedOut = e && (e.name === 'TimeoutError' || e.name === 'AbortError')
        if (attempt < maxRetries) {
          log(`claude: network ${timedOut ? 'timeout' : 'error'}, retry ${attempt + 1}/${maxRetries}`)
          await sleep(1000 * 2 ** attempt, signal)
          attempt += 1
          continue
        }
        throw new ClaudeError(timedOut ? 'deadline_reached' : 'agent_unavailable', 'network')
      }
      if (res.ok) return res.json()
      let errType = ''
      try {
        const j = await res.json()
        errType = (j && j.error && `${j.error.type}: ${String(j.error.message || '').slice(0, 200)}`) || ''
      } catch {
        errType = ''
      }
      const retryable = res.status === 429 || res.status >= 500
      if (retryable && attempt < maxRetries) {
        const ra = Number(res.headers.get('retry-after'))
        const wait = Number.isFinite(ra) && ra > 0 ? Math.min(ra * 1000, 15000) : Math.min(1000 * 2 ** attempt + Math.random() * 250, 8000)
        log(`claude: HTTP ${res.status}, retry ${attempt + 1}/${maxRetries} in ${Math.round(wait)} ms`)
        await sleep(wait, signal)
        attempt += 1
        continue
      }
      log(`claude: HTTP ${res.status} ${errType}`)
      throw new ClaudeError(res.status === 429 ? 'rate_limited' : 'agent_unavailable', errType, res.status)
    }
  }
  return { create }
}
