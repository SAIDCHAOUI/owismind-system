// "Go further" chips under an answer (workspace op suggest.set): the pure send rule,
// kept out of the component so node:test pins it. A chip sends its text through the
// chat store's `send` (the path typing + Enter ends in: tree parent, screen context,
// analytics), never through a parallel request.

/** True when a chip may be sent now (no run in progress, the thread accepts a send). */
export function canPickSuggestion(chat) {
  return !!(chat && chat.canSend && !chat.sending)
}

/**
 * Send one chip text as the next user message. Returns true when it was handed to
 * chat.send, false when it was refused (blank text, run in progress, send blocked).
 */
export function sendSuggestion(chat, text) {
  const t = typeof text === 'string' ? text.trim() : ''
  if (!t || !canPickSuggestion(chat) || typeof chat.send !== 'function') return false
  chat.send(t)
  return true
}
