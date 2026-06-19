# ADR-0013 - Agent profiles are admin-authored (no hardcoded copy)

> Audience: Developer, administrator. Last updated: 2026-06-19. Summary: why the display
> copy for each agent (tagline, description, capabilities, tool list, icon, badge) is authored
> by an administrator through the Admin UI, validated and bounded server-side, stored inside the
> enabled-agents JSON in `webapp_settings_v1`, and exposed via `/agents` without ever leaking
> a raw agent id.

## Status

Accepted. Coded in `security/validation.py` (`validate_agent_meta`), `api/routes.py`
(`/admin/agents` POST and `/agents` GET). A profile is optional: an agent without an authored
profile renders a "profile to complete" placeholder card client-side - the empty profile is
never a crash.

## Context and problem

OWIsMind surfaces a library of available AI agents to end users. Each card in that library shows
a tagline, a description, a list of capabilities, a tool inventory, an icon and a badge (for
example "beta"). Two prior approaches were considered and both rejected:

1. **Hardcode the copy in a frontend module.** An `agentMeta.js` file initially held per-agent
   descriptions as JavaScript constants. This was brittle: agent labels change, new agents are
   added, and any update to display text required a code change and a full frontend rebuild + zip
   upload + DSS deploy. More critically, the frontend copy risked going stale (a description
   written at dev time for a prototype agent that has since been renamed or restructured).

2. **Derive copy from the DSS agent's own metadata.** The LLM Mesh `agent:bHrWLyOL` record
   carries only a raw technical label ("OWIsMind_orchestrator"), not business-ready marketing
   copy. Surfacing that label verbatim is correct for a raw admin view but inadequate as a
   user-facing agent card.

The core constraint is rule #4: the frontend must never receive a raw `agent_id` or
`project_key`. A copy file keyed by agent id would require sending the id to the front, or
encoding it into a logical key - both of which leak the technical identifier. The copy must
therefore live on the server side, keyed by the opaque `logical_key`.

## Decision

The agent profile is an admin-authored block of **display text only**. Administrators write it
through "Administration > Agents > Edit profile" in the web app. The backend processes, bounds
and stores it server-side; the frontend receives only safe display fields keyed by the opaque
logical key.

### Fields and server-side bounds

The profile is a bounded dict with six fields:

| Field | Type | Bound | Fallback |
|---|---|---|---|
| `tagline` | string | 120 chars | `""` |
| `description` | string | 700 chars | `""` |
| `capabilities` | list of strings | 8 items x 120 chars | `[]` |
| `tools` | list of strings | 16 items x 48 chars | `[]` |
| `icon` | string (whitelist) | `ALLOWED_AGENT_ICONS` (20 values) | `"robot"` |
| `badge` | string (whitelist) | `ALLOWED_AGENT_BADGES` (`""`, `"default"`, `"new"`, `"beta"`) | `""` |

All bounds are enforced by `validate_agent_meta` in `security/validation.py`. This function
**never raises**: every field is clamped or set to its fallback on any invalid or absent input,
so a malformed admin payload degrades gracefully instead of breaking the whitelist save. The
`_clean_str` helper collapses control characters (including newlines, tabs and Unicode line
separators U+2028/2029) into spaces before capping length, so layout-breaking characters cannot
sneak into the stored JSON.

The icon whitelist (`ALLOWED_AGENT_ICONS`) is a curated subset of the frontend icon registry:

```python
ALLOWED_AGENT_ICONS = frozenset({
    "robot", "sparkle", "sparkles", "trendUp", "alert", "thumbsUp", "layers",
    "chart", "database", "users", "route", "message", "wallet", "shield",
    "globe", "sliders", "bookOpen", "tool", "tag", "grid",
})
```

An unknown icon name falls back to `"robot"`. This guard means that even if a future admin
sends an icon name not in the registry, the frontend renders the default glpyh rather than
displaying a broken icon or raising an exception.

### Storage: piggybacking on the enabled-agents JSON

The profile is NOT stored in a new table. It is stored as a `"profile"` sub-key inside the
per-agent entry of the `enabled_agents` JSON, which lives in `webapp_settings_v1` under the
setting key `"enabled_agents"`. This is the existing key that already holds the
`(project_key, agent_id, logical_key, label)` tuple for each enabled agent.

The `validate_agent_meta` call happens at `/admin/agents` POST time in `routes.py` (inside the
loop that re-validates each agent against the live DSS listings). The validated profile is
embedded directly in the persisted enabled-agents list:

```python
enabled.append({
    "logical_key": logical_key,
    "project_key": project_key,
    "agent_id": agent_id,
    "label": available[agent_id],
    "profile": validate_agent_meta(meta_by_pair.get((project_key, agent_id))),
})
settings.set_enabled_agents(enabled, updated_by=identity["user_id"])
```

A profile save therefore requires no new migration, no `ALTER`, and no new table (`_v1` naming
rule preserved). The cost is that the entire enabled-agents list is re-written on each save
(acceptable: the list is bounded to `MAX_ENABLED_AGENTS = 50`).

### Exposure via `/agents`, no id leak

The `/agents` GET route (available to any authenticated user) projects only the public-safe
fields from each enabled agent entry. The raw `agent_id` and `project_key` are stripped:

```python
public.append({
    "key": key,           # opaque logical key only
    "label": a.get("label"),
    "tagline": profile.get("tagline", ""),
    "description": profile.get("description", ""),
    "capabilities": profile.get("capabilities", []),
    "tools": profile.get("tools", []),
    "icon": profile.get("icon", "robot"),
    "badge": profile.get("badge", ""),
})
```

No `agent_id`, no `project_key`, no internal reference reaches the browser. The chat front
references an agent solely by `key` (the opaque logical key), consistent with ADR-0004.

### Behavior when no profile is authored

An agent whose profile is absent (or whose every field is blank after sanitization) is a valid
state. The frontend's agent library card renders a "profile to complete" placeholder. This avoids
any hardcoded fallback text (the `agentMeta.js` pattern that was removed) and clearly signals
to the administrator that the agent needs an editorial pass before the library is shown to users.

## Rationale

- **No rebuild required to update copy.** An admin changes the tagline and saves: the next
  `/agents` GET delivers the new text, with no frontend build, no zip upload, no backend restart.
- **No leak of internal agent ids.** Storing the profile alongside the logical-key entry means the
  display copy never needs to be keyed by `agent_id` client-side.
- **`validate_agent_meta` never raises.** On the admin whitelist-save path, a crash on display copy
  would block the entire whitelist update (a far more critical operation). Clamping always succeeds.
- **Existing table, no migration.** Piggybacking on `webapp_settings_v1` avoids a new table, stays
  within the `_vN` no-ALTER discipline, and keeps the enabled-agents lifecycle in one place.
- **Icon whitelist is tidy, not just a loose string.** The `ALLOWED_AGENT_ICONS` guard protects the
  frontend icon registry from unexpected names without needing a live cross-check.

## Consequences

Positive:

- Live copy editable by an admin: zero code change, zero rebuild for text updates.
- Consistent with ADR-0004 (no raw agent id ever reaches the frontend).
- `validate_agent_meta` is pure and unit-testable outside DSS: every bound and fallback can be
  exercised in the test suite.
- An empty profile renders an honest placeholder, never stale hardcoded text.

Negative or watch points:

- The admin must fill in each agent's profile before the library feels complete. Until then users
  see the placeholder card (an acceptable trade-off: an empty, honest card beats stale hardcoded copy).
- The entire `enabled_agents` JSON is re-written on each save. This is bounded (max 50 agents) but
  means a profile edit re-validates all selected agents against live DSS listings (a read-only,
  bounded call, but a call nonetheless).
- Adding a new icon requires updating both `ALLOWED_AGENT_ICONS` in `validation.py` AND the
  frontend icon registry (two files, one backend restart after the python-lib change).

## Rejected alternatives

| Alternative | Why rejected |
|---|---|
| `agentMeta.js` hardcoded in the frontend | Stale-prone; requires a full rebuild to update any copy; removed on 2026-06-18. |
| A new `webapp_agent_profiles_v1` table | No gain over piggybacking on `webapp_settings_v1`; adds a migration and a new table lifecycle. |
| Derive copy from the DSS agent's own technical label | Produces raw internal labels ("OWIsMind_orchestrator"), not user-facing prose. |
| Store the profile keyed by `agent_id` | Would require sending the `agent_id` to the frontend (violates ADR-0004). |
| `validate_agent_meta` raises on invalid input | Would break the whitelist save if any display field is malformed; a pure clamping function is safer on this path. |

## See also

- [ADR-0004 - Server-side agent whitelist](0004-whitelist-agents-serveur.md) - the opaque
  logical key that makes it safe to expose the profile without leaking technical ids.
- [Backend - security and validation](../04-backend/06-security-and-validation.md) - the
  `validate_agent_meta` function in `security/validation.py` and the bounds table.
- [Agent system - overview](../05-agents/01-agent-system-overview.md) - the agent registry and
  the enabled-agents whitelist concept.
- [ADR index](README.md) - all architecture decisions.
- [Documentation portal](../README.md) - back to the general table of contents.
