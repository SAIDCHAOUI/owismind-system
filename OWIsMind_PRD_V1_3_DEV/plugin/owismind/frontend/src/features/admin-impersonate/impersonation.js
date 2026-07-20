// Admin impersonation ("act as user") - sessionStorage state + the request header.
//
// Isolated on purpose: this whole feature must be removable by deleting this folder
// plus a handful of clearly fenced one-liners in the core files. Nothing here imports
// a store or a component, so it is safe to use from the shared backend client.
//
// The target user id lives in sessionStorage (per-tab, cleared when the tab closes):
// an admin clicks a user, we persist the id and reload, and from then on EVERY API
// call carries the `X-OWI-Impersonate` header. The server honours it ONLY when the
// real caller is an admin (otherwise the effective user stays the caller), so the
// frontend just carries the opaque id around - it never grants anything by itself.

// sessionStorage key holding the impersonated user id (empty/absent = not active).
const IMPERSONATE_KEY = 'owismind.impersonate'

// HTTP header the backend reads to resolve the effective (impersonated) user.
export const IMPERSONATE_HEADER = 'X-OWI-Impersonate'

// The currently impersonated user id, or '' when impersonation is off. Best-effort:
// returns '' if sessionStorage is unavailable (private mode / no DOM).
export function getImpersonateTarget() {
  try {
    return sessionStorage.getItem(IMPERSONATE_KEY) || ''
  } catch (e) {
    return ''
  }
}

// Start impersonating `id` (the caller reloads afterwards so every request, and the
// /me identity, pick it up). A falsy id is treated as a clear.
export function setImpersonateTarget(id) {
  try {
    if (id) sessionStorage.setItem(IMPERSONATE_KEY, String(id))
    else sessionStorage.removeItem(IMPERSONATE_KEY)
  } catch (e) {
    /* sessionStorage unavailable - impersonation is best-effort and admin-only. */
  }
}

// Stop impersonating (the banner's Exit button; the caller reloads afterwards).
export function clearImpersonate() {
  try {
    sessionStorage.removeItem(IMPERSONATE_KEY)
  } catch (e) {
    /* nothing to clear if storage is unavailable. */
  }
}

// Headers to merge into every API call: the impersonation header when active, else
// an empty object (so a non-impersonating session carries nothing extra).
export function impersonationHeaders() {
  const target = getImpersonateTarget()
  return target ? { [IMPERSONATE_HEADER]: target } : {}
}
