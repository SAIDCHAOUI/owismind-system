// Pure helpers for the paginated sidebar conversation list (no Vue, unit-tested).

// Append only conversations whose id is not already present (page dedupe).
// Existing entries win (their title/order are preserved as the user scrolls).
export function mergeConversations(existing, incoming) {
  const seen = new Set(existing.map((c) => c.id))
  const out = existing.slice()
  for (const c of incoming) {
    if (!seen.has(c.id)) {
      seen.add(c.id)
      out.push(c)
    }
  }
  return out
}

// Upsert a conversation and move it to the top (after a send: new or bumped).
export function upsertAndBump(list, conv) {
  const rest = list.filter((c) => c.id !== conv.id)
  return [conv, ...rest]
}
