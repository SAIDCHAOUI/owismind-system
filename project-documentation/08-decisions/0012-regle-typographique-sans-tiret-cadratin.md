# ADR-0012 - Typographic rule: no em dash

> Audience: every contributor (code, documentation, agents, commit messages, chat responses).
> Last updated: 2026-06-18. Summary: why the em dash `—` (U+2014) and the en dash `–` (U+2013)
> are banned everywhere in OWIsMind, and how to verify that none has slipped into the
> repository.

## Status

Accepted and validated in DSS. This is the project's NON-NEGOTIABLE rule number 9, loaded in every session via
`CLAUDE.md` and the automatic memory `no-em-dash-ever.md`. User decision of 2026-06-17, initial sweep
performed and verified (lesson L084: 0 residual, 0 corruption).

> Assumed exception: this file is the ONLY document in the documentation set allowed to quote `—` and `–`,
> and only inside backticks, because it is the ADR that names and defines the rule. Everywhere else,
> these two characters are forbidden, including on this page outside the naming backticks.

## Context and problem

The em dash `—` (U+2014) and the en dash `–` (U+2013) are perceived as a typographic AI
SIGNATURE. Language models produce them abundantly for asides and pauses,
where a human more often writes a hyphen, a colon, a comma or parentheses. In
a project where part of the content (code, comments, documentation, chat responses) is generated or
assisted by AI, the presence of these glyphs betrays that origin and harms the project's identity.

User feedback (Run 7b, 2026-06-17, lesson L084) was decisive: these two dashes must disappear,
forever, from EVERYWHERE. Not only from text visible to the end user, but also from the code,
the comments, the project memory (`memory/`), the commit messages and the responses produced
in the chat. The rule allows no functional exception.

A technical trap appeared during implementation. The first sweep attempted to replace the
glyphs with `perl -CSD -i -pe 's/\x{2014}|\x{2013}/-/g'`. This command raised "Malformed
UTF-8 character" errors on files that carry OTHER multibyte glyphs: the Code Agents contain
control tokens such as `⟦owi:mode⟧` and logical symbols (`⊥`, `⇒`). The concrete risk was
to rewrite those bytes into the replacement character U+FFFD and corrupt tokens the agent
depends on. Empirically no corruption occurred this time, but the approach proved fragile.

## Decision

Ban `—` (U+2014) and `–` (U+2013) in EVERY character written within the project's scope. The scope
is exhaustive:

| Surface | Concerned | Expected replacement |
|---|---|---|
| i18n strings and interface text | yes | `-`, `:`, `,` or parentheses depending on meaning |
| Source code (frontend, backend, agents) | yes | same |
| Code comments | yes | same |
| Project memory (`memory/`, sessions) | yes | same |
| Commit messages | yes | same |
| Responses produced in the chat | yes | same |
| Documentation (`project-documentation/`, `docs/`) | yes | same |

Substitution rule according to intent:

- pause or aside: a simple hyphen `-`, or parentheses;
- enumeration or definition: a colon `:`;
- juxtaposition: a comma `,`.

The sweep must be BYTE-SAFE. We operate at the byte level (`LC_ALL=C`, replacement with `sed` on the
byte sequence), and we NEVER use `perl -CSD` on files that carry other multibyte glyphs,
so as not to risk a U+FFFD corruption. Excluded from the sweep are generated outputs
(`Plugin/owismind/resource/owismind-app/`, `Plugin/ready-for-dataiku/`, `body.html`), the
vendored dependencies and `.claude/`.

The rule lives in two places loaded in every session:

- `CLAUDE.md`, section "Regles NON NEGOCIABLES", point 9: the authoritative wording ("JAMAIS de tiret
  cadratin ... ni de tiret demi-cadratin ... bannis a tout jamais, PARTOUT");
- the automatic memory `no-em-dash-ever.md` (one of the `memory/` files in the agent repository), which recalls
  the rule at the start of every conversation.

## How to verify (grep)

Verification is done on the UTF-8 BYTE SEQUENCES of the two glyphs, not on the characters, which
avoids any terminal-encoding mishap. In UTF-8, `—` (U+2014) and `–` (U+2013) both start
with `\xe2\x80\x9` and differ only on the last half-byte (`3` for `–`, `4` for `—`). A single
class therefore covers both.

| Verification | Command | Expected result |
|---|---|---|
| No em dash or en dash | `grep -rlP '\xe2\x80\x9[34]' .` | no output (empty list) |
| No U+FFFD corruption introduced by a sweep | `grep -rlP '\xef\xbf\xbd' .` | no output (0 corrupted file) |

The `-l` lists the offending files (more readable than a dump of lines); the `-P` enables the
hexadecimal classes of PCRE. To target a precise surface, restrict the path (for example the
i18n files, the `.vue` files, or `dataiku-agents/`). After the sweep, the full verification adds a cycle of
compilation / build / tests (py_compile, Vite build, test suites) to confirm that nothing broke
in addition to the double grep.

A pre-commit git hook that would automatically reject a commit containing `—` or `–` has been PROPOSED but
is NOT installed to date (see `memory/CONTEXT.md`). The rule therefore remains enforced by discipline and
by the manual verification above, not by an automatic guardrail.

> IN FLUX: as long as the pre-commit hook is not installed, nothing technically prevents a glyph from
> getting through. The double grep verification before commit is the only effective barrier; apply it.

## Reasons

- The rule protects the project's identity: it is an absolute user decision, not a negotiable
  style preference.
- The verification is purely DETERMINISTIC and inexpensive: two greps by byte sequence, with no
  encoding ambiguity and no LLM in the loop.
- The choice of a byte-safe sweep (rather than `perl -CSD`) protects the agents' control tokens, which
  are themselves multibyte and carry functional meaning.

## Consequences

Positive:

- Validated in DSS: sweep passed, 0 residual `—`/`–` in i18n and `.vue`, 0 U+FFFD, special tokens intact
  (L084).
- Homogeneous identity: the whole corpus (code, doc, memory, commits, chat) speaks the same typography.
- Verifiable in one command, integrable into any pre-commit check or review.

Negative or points of attention:

- Every tool, agent or contributor must respect the rule; a single lapse reintroduces the signature.
- The documents that DEFINE the rule must quote `—` and `–` (necessarily), hence the assumed exception
  of this ADR (and of the dedicated section in the writing conventions).
- Absence of an automatic guardrail: the pre-commit hook remains to be installed; until then, vigilance and the
  double grep act as the safety net.
- Encoding vigilance required on the sweep tools: never process at the character level any
  files with multibyte glyphs, under penalty of corruption.

## Rejected alternatives

| Alternative | Why rejected |
|---|---|
| Tolerate the em dash in the code and commit messages (ban it only in the UI) | Refused: the rule is EVERYWHERE. The AI signature also shows in a comment or a commit, and the user forbids it with no functional exception. |
| Sweep with `perl -CSD -i -pe 's/\x{2014}|\x{2013}/-/g'` | Raises "Malformed UTF-8 character" and risks corrupting into U+FFFD the files with multibyte glyphs (`⟦owi:mode⟧`, `⊥`, `⇒`). Replaced by a byte-safe sweep (`LC_ALL=C`, `sed` byte). |
| Mechanically substitute `—`/`–` with `-` everywhere without looking at the meaning | Produces poor typography: depending on intent, the right replacement is `:`, `,` or parentheses, not systematically a hyphen. |
| Rely on a pre-commit hook as the sole guarantee | The hook is not installed (a proposal that went nowhere); the rule cannot depend on a nonexistent mechanism. The manual double grep remains the reference barrier. |

## See also

- [Contributing - conventions and rules](../09-maintenance/01-contributing-and-conventions.md) - the
  project's non-negotiable rules, including this typographic rule applied to every contributor.
- [Known gotchas and lessons](../09-maintenance/03-known-gotchas-and-lessons.md) - the trap of the
  `perl -CSD` sweep on multibyte glyphs and the other cross-cutting gotchas.
- [ADR index](README.md) - the complete list of architecture decisions and their status.
- [Documentation portal](../README.md) - back to the general table of contents.
