# ADR-0020 - Admin impersonation kept as a fenced, temporary feature for the beta

> Audience: Backend + frontend developer, maintainer. Last updated: 2026-07-06. Summary: why an admin can
> view the app as another user, why it is a deliberately TEMPORARY feature fenced for easy removal, and why
> it is being kept through the beta.

## Status

Accepted (DSS, temporary). Added 2026-06-19 (Run 3), validated in DSS; explicitly KEPT for the beta on
2026-07-06 (Run 5). Lessons L094 to L096.

## Context

During the beta, admins need to reproduce what a specific user sees (their conversations, their state) to
diagnose reports and support them. Impersonation crosses a trust boundary: an admin acting as another
user. It must therefore be strictly bounded, auditable, and trivial to remove once the beta no longer
needs it.

## Decision

- **Impersonation is admin-gated and fenced.** The logic lives in `security/impersonation.py`, and every
  touch point is in clearly delimited blocks: `features/admin-impersonate/` on the front, plus fenced
  sections in `api/routes.py`, `backend.js`, `session.js`, `chat.js`, `ChatView.vue`, `AppLayout.vue`,
  `AdminView.vue`, and the `impersonate.*` i18n keys. This makes the whole feature removable as one unit.
- **Read-oriented, write-safe.** Analytics tracking DROPS the write under impersonation (ADR-0017), so an
  admin viewing-as does not pollute another user's usage data; the same drop-before-write discipline guards
  the sensitive paths.
- **Kept for the beta, scheduled for removal.** The decision on 2026-07-06 was to KEEP impersonation for
  the v1.1 beta (support need), and to remove it later; the fencing is what makes that later removal a
  clean, low-risk operation.

## Reasons

- Support reality: reproducing a user's exact view is the fastest way to diagnose a beta report.
- Fencing over cleverness: because it is a trust-boundary feature with a limited lifetime, isolating it in
  named blocks is worth more than integrating it seamlessly - removal must not require archaeology.
- Write-safety keeps impersonation from corrupting the very data (usage, quotas) an admin might be
  investigating.

## Consequences

Positive:

- Admins can support beta users effectively.
- The feature can be excised in one pass when the beta ends, thanks to the fences.
- Impersonated sessions do not distort analytics or another user's stored state.

Negative or watch points:

- It is a standing trust-boundary surface: it MUST stay admin-only and must not accrete write powers.
- It is technical debt with an expiry: leaving it in past the beta would be a regression against this ADR's
  own intent. Removal is tracked as a follow-up.

## Rejected alternatives

| Alternative | Why rejected |
|---|---|
| No impersonation; debug from logs only | Too slow for beta support; the exact user view is often the only way to reproduce. |
| A permanent, deeply integrated impersonation feature | Standing trust-boundary risk with no clear removal path; the beta need is temporary. |
| Allow writes while impersonating | Would let an admin mutate another user's data and corrupt the analytics being investigated. |

## See also

- [ADR-0017 - Usage analytics in a single SQL events table](0017-usage-analytics-events-table.md) - the drop-before-write under impersonation.
- [Security model (architecture)](../02-architecture/04-security-model.md) - the trust boundary and owner-scoping.
- [Backend - security and validation](../04-backend/06-security-and-validation.md) - where the impersonation resolution and guards live.
- [ADR index](README.md) - all architecture decisions.
