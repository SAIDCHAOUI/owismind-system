---
name: get-physical-table-quote-mismatch
description: wizard.get_physical_table returns a double-quoted literal that guided_store.quote_table rejects; tests mask it by mocking
metadata:
  type: project
---

`owismind_factory.wizard.get_physical_table(project, ds)` ALWAYS returns a
DOUBLE-QUOTED literal: `'"%s"' % table` (e.g. `'"OWISMIND_PRD_V1_2_owismind_agent_catalog_v1"'`).
`owismind_factory.guided_store.quote_table(t)` gates on `_IDENTIFIER_RE =
^[A-Za-z_][A-Za-z0-9_]*$` and RAISES `GuidedStoreError` on any string starting
with `"`. So `quote_table(get_physical_table(...))` ALWAYS raises in production.

Two consumers feed one into the other:
- `guided_store.table_has_rows` (first_build row check): catches GuidedStoreError,
  returns None ("cannot verify"), which the caller TOLERATES -> latent, benign.
- `removal.delete_catalog_rows` (capability removal, added 2026-07-22): calls
  `quote_table(table)` UNwrapped -> GuidedStoreError propagates -> caught by
  `ctx.act` -> catalog_cleanup stage FAILS every real run -> removal run stuck at
  stage 10/12, capabilities.json entry + hub files + catalog rows never cleaned.
  NOT benign.

**Both removal catalog unit tests MASK it**: `test_delete_catalog_rows_parametrized...`
monkeypatches `wizard.get_physical_table` to return a BARE name; `..._no_dataset`
returns before reaching it. So green tests do NOT prove the SQL path works.

**How to verify** DSS-free: stub dataiku.sql, build a fake project whose
`get_dataset().get_settings().get_raw()` returns `{"params":{"table":"${projectKey}_x"}}`,
call the REAL `wizard.get_physical_table` then `guided_store.quote_table` on its output.

Minimal fix in delete_catalog_rows: strip the surrounding quotes before quote_table
(`bare = table[1:-1] if table[:1]=='"' and table[-1:]=='"' else table`). Deeper
option (make get_physical_table return bare) would break `wizard.substitute_golden_tables`
which uses the quoted literal directly in SQL.
