# Agents and Administration

> Audience: business users (agents library) and administrators (Administration console). Last updated:
> 2026-06-19. Summary: how any user can browse the agent library and read an agent's profile, and
> how an administrator enables agents, authors their profile, manages users, and manages monthly
> budgets and quotas.

OWIsMind exposes a growing set of AI agents. This page covers two connected features:

1. The **Agents library** (`/agents`) - available to all users: browse the agents that are active on
   your instance and read their editorial profiles.
2. The **Administration console** (`/admin`) - visible only to administrators: enable agents, author
   their profiles, manage users and control monthly budgets.

---

## Part 1 - The Agents library (all users)

### Opening the library

Click **Agents** in the sidebar (icon and label `rail.agents` / `ag.title`) to open the agent
library. It shows all agents currently enabled for your account by the administrator. The list always
comes from the server: if an agent does not appear here, it is not available on your instance.

If no agents are enabled, the page shows an honest empty state: "No agent is enabled for your
account. Please contact an administrator." (`ag.no_agents`).

### Browsing: the card grid

The library opens on a grid of cards. Above the grid, a search bar (key `ag.search`) lets you filter
by name, tagline or description; a count line ("N agent(s)") updates live. Cards are arranged in an
auto-fill grid (minimum 320px wide), each with:

- a **square icon tile** (orange glyph on a white square with a 1px border);
- an optional **badge** (Default, New, Beta) in the top-right corner;
- the **agent name** (bold, 16px);
- a **tagline** (short punchline in orange text, AA-safe);
- a **description** (up to 3 lines, clipped with "..." if longer);
- a footer line with the number of documented tools, or "View profile" if none.

Click any card to open the **detail view** for that agent.

> **Zero hardcoded content.** Every profile (tagline, description, capabilities, tools, icon, badge)
> is authored by an administrator in the Administration console. If an administrator has not filled
> in a profile yet, the card description reads: "This agent's profile has not been filled in by an
> administrator yet." (`ag.meta_missing`). This is an honest state, never invented content.

### Detail view: reading an agent's profile

Clicking a card navigates to `/agents/<key>` and shows the full editorial profile:

- a **hero header** with a large icon tile (56x56), the agent name and tagline;
- a **description paragraph** (up to 700 characters);
- a **two-column grid** if the admin authored capabilities and/or tools:
  - "What this agent does" (`ag.capabilities`): a bullet list with an orange check icon per item
    (up to 8 items, each up to 120 characters);
  - "Exposed tools" (`ag.tools`): chip-style labels in monospace (up to 16 items, each up to 48 characters).
- a **"Start a conversation"** button (`ag.start`) that pre-selects this agent in the chat input and
  navigates to `/chat`.

A "Back to all agents" link (`ag.back`) returns you to the grid.

### Starting from the library

The "Start a conversation" button in the detail view pre-selects the agent for your next exchange.
You are taken to the Chat page with that agent already selected in the agent picker. From there you
can type your question and send it as usual.

---

## Part 2 - The Administration console (administrators only)

### Who is an administrator?

The first user to open OWIsMind after the webapp is configured becomes the administrator and gains
access to the Administration console. All subsequent users are standard users. An administrator can
promote other users to admin (or revoke that status) from the Users tab.

The Administration console is server-gated: the backend checks whether the authenticated user has
the admin flag before serving any admin route. The client-side router also guards the `/admin` route
(`meta.requiresAdmin`). If you are an admin, an "Administration" entry appears in the sidebar menu.

### Opening the console and its tabs

The Administration page (`admin.title`: "Administration", eyebrow `admin.eyebrow`: "Admin console")
is tabbed. The five tabs are:

| Tab label | Key | What you manage there |
|---|---|---|
| Overview | `admin.tab.overview` | KPI tiles (user count, exposed agents, SQL connection), storage details. |
| Agents | `admin.tab.agents` | Enable/disable agents; author each agent's editorial profile. |
| Users | `admin.tab.users` | Promote or demote users to/from administrator. |
| Quotas & budgets | `admin.tab.quotas` | Global monthly limit, temporary global boost, per-user overrides. |
| Activity log | `admin.tab.activity` | (Coming soon - no backend yet.) |

### Overview tab

Displays three KPI tiles at the top (user count, number of exposed agents, SQL connection name) and
a Storage section below with the technical details of the configured storage: SQL connection name,
project key, table prefix, namespace and the list of tables. A note explains how to change the
connection (webapp Settings tab, then restart the backend).

### Agents tab: enabling agents and authoring profiles

This tab has two panels:

**Selecting agents to expose.** Choose a Dataiku project from the dropdown (`admin.agents.pick_project`).
The list of agents found in that project appears below (`admin.agents.in_project`). Tick an agent
(or click "Add") to add it to the enabled list on the right. The enabled list shows all currently
exposed agents across all projects. Click "Remove" (`admin.agents.remove`) to remove one. At the
top of the enabled list, the count shows "Exposed agents (N)" (`admin.agents.enabled_count`).

**Authoring an agent profile.** For each agent in the enabled list, a status chip shows either
"Profile to complete" (`admin.agents.no_profile`) or "Profile filled in" (`admin.agents.has_profile`).
Click **Edit profile** (`admin.agents.configure`) to open the profile editor modal.

The modal ("Agent profile", `admin.agents.editor_title`) contains:

| Field | Key | Constraint |
|---|---|---|
| Agent (read-only, the Dataiku label) | `admin.agents.f_label` | Not editable. |
| Icon | `admin.agents.f_icon` | Choose from the allowed icon set (same whitelist as the front registry). |
| Badge | `admin.agents.f_badge` | None / Default / New / Beta. |
| Tagline | `admin.agents.f_tagline` | Up to 120 characters. |
| Description | `admin.agents.f_desc` | Up to 700 characters. |
| Capabilities | `admin.agents.f_caps` | One per line, up to 8 items of 120 characters each. |
| Exposed tools | `admin.agents.f_tools` | One per line, up to 16 items of 48 characters each. |

A live **preview** pane inside the modal shows how the card will look in the library as you type.
Click **Done** (`admin.agents.editor_done`) to apply the changes locally. The changes are not
committed to the server until you click **Save selection** (`admin.agents.save`) in the main tab.

Once you save, the profile is stored server-side inside the `enabled_agents` JSON in the
`webapp_settings_v1` settings table - no new table is created. The backend's
`security/validation.py::validate_agent_meta()` sanitizes every field on write (never raises; bounds
and strips control characters; icon must be in the server-side whitelist; badge must be one of
`default`, `new`, `beta`, or empty). The profile is returned via `GET /agents` without leaking the
Dataiku `agent_id` or the source project.

> **Honesty contract.** The profile is the ONLY source of the agent card content. There is no
> fallback copy hardcoded anywhere in the frontend (the file `agentMeta.js` was deleted). An agent
> whose profile has not been authored shows an honest "profile to complete" state.

### Users tab

Lists every user who has ever opened the webapp. For each user, the table shows: display name,
groups, and an admin toggle (Make admin / Revoke admin). You cannot revoke admin from yourself if
you are the last administrator ("Not allowed: at least one admin must remain.",
`admin.users.last_admin_error`). You cannot promote a user who has never opened the webapp (they
have no row in the users table yet).

### Quotas & budgets tab

This tab manages the monthly per-user budget system (Feature B, `storage/budget.py`).

> IN FLUX: the budget enforcement is coded and ready but has not yet been confirmed live on the DSS
> instance. The UI described here is present in the deployed frontend.

#### Global settings panel

The first panel, "Global settings" (`admin.quotas.global_title`), controls the baseline for all
users:

- **Default monthly limit ($)** (`admin.quotas.default_limit`): the credit every user gets unless
  overridden. Default value: $50.
- **Enforce the limit** toggle (`admin.quotas.enabled`): when on, requests are blocked (HTTP 402)
  once the monthly spend reaches the limit. When off, spending is tracked and displayed but never
  blocked (`admin.quotas.enabled_hint`).

Click **Save configuration** (`admin.quotas.save`) to apply.

#### Temporary global boost panel

The second panel, "Temporary boost (all users)" (`admin.quotas.temp_title`), lets you raise every
user's limit for a limited time (for example during a busy reporting period):

- **Temporary limit ($)** (`admin.quotas.temp_amount`): the limit to apply to all users during the
  boost period.
- **Duration (days)** (`admin.quotas.temp_days`): after this many days, the limit automatically
  reverts to the global default (or the user's personal override if one is active).

Click **Apply boost** (`admin.quotas.temp_apply`) to activate. The current boost is shown as
"Global boost active: $X until [date]." (`admin.quotas.temp_active`). Click **Remove the global
boost** (`admin.quotas.temp_clear`) to cancel it early.

#### Per-user limits table

The third section, "Per-user limits" (`admin.quotas.users_title`), lists all users with their
current-month spend, their effective limit, the remaining amount, and the source of their limit
(Default / Global boost / Custom / Temporary). "Blocked" is shown in red for users whose budget is
exhausted.

To update one or several users at once:

1. Tick the checkbox beside each user you want to update (or use "All" to select everyone).
2. In the panel that appears ("Apply to the N selected user(s)"), fill in:
   - **New limit ($)** (`admin.quotas.limit_amount`): the override amount.
   - **Duration**: Permanent (no expiry) or Temporary (choose 7, 30 or 90 days).
   - **Note** (optional, `admin.quotas.note`): a free-text admin note stored with the override.
3. Click **Apply limit** (`admin.quotas.apply`) to save.

To clear a personal override and revert one or several users to the global default, tick their
checkboxes and click **Reset to default** (`admin.quotas.clear`).

The per-user override is stored in the `webapp_user_quota_v1` table (created lazily on first use),
with columns: `user_id`, `limit_usd`, `expires_at` (NULL = permanent), `note`, `updated_at`,
`updated_by`. The backend resolves each user's effective limit with this priority: an ACTIVE per-user
override wins over an ACTIVE global temp boost, which wins over the global default. "Active" means
`expires_at > now()` (or `expires_at IS NULL` for permanent overrides).

**Admins are subject to the same budget rules as regular users.** Being an admin does not grant an
unlimited budget.

### Limit resolution summary

| Priority | Rule | Active condition |
|---|---|---|
| 1 (highest) | Per-user override | Row exists in `webapp_user_quota_v1` and `expires_at > now()` or NULL |
| 2 | Global temporary boost | `monthly_budget` config has a `temp` field and its expiry is in the future |
| 3 (lowest) | Global default | Always; the `default_limit_usd` from `webapp_settings_v1` key `monthly_budget` |

---

## See also
- [Getting started](01-getting-started.md) - opening the application and the navigation structure.
- [My account and budget](05-account-and-budget.md) - the user-side view of the budget gauge and usage.
- [FAQ and troubleshooting](04-faq-and-troubleshooting.md) - budget-reached and agent-unavailable scenarios.
- [Backend - agents and routing](../05-agents/02-orchestrator.md) - the orchestrator and the honesty firewall (technical).
- [Backend - security model](../02-architecture/04-security-model.md) - how agent keys are whitelisted and profiles never leak raw agent_id.
