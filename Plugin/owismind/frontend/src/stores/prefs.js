// Pure preference helpers (NO Vue/Pinia import) — unit-testable with node:test and
// reused by the ui store. Keeping the bounds + coercion here means the frontend and
// backend share ONE contract: these mirror security/validation.py on the backend, so
// the persisted preference and the server-side SQL LIMIT can never disagree.

// Agent-context window: how many of the most-recent conversation MESSAGES (user +
// assistant turns) are replayed to the agent as context. Min 10, max 50, default 20.
export const CONTEXT_MESSAGES_MIN = 10
export const CONTEXT_MESSAGES_MAX = 50
export const CONTEXT_MESSAGES_DEFAULT = 20

// Bounds the number of past MESSAGES sent to the agent as context. Mirrors the
// backend validate_history_limit so the persisted pref and the server clamp agree.
// A non-finite value -> DEFAULT; an out-of-range number is clamped to the nearest
// bound (never honoured). Accepts numbers or numeric strings (the value can come
// from localStorage or an <input>).
export function clampContextMessages(value) {
  const n = typeof value === 'number' ? value : parseInt(value, 10)
  if (!Number.isFinite(n)) return CONTEXT_MESSAGES_DEFAULT
  if (n < CONTEXT_MESSAGES_MIN) return CONTEXT_MESSAGES_MIN
  if (n > CONTEXT_MESSAGES_MAX) return CONTEXT_MESSAGES_MAX
  return Math.floor(n)
}
