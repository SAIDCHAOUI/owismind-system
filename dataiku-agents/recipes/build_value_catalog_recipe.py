# -*- coding: utf-8 -*-
"""
Build DRIVE_Revenues_Value_Catalog (v2).

STATUS (2026-06-18): this recipe builds the RICH value catalog (aliases,
variants, business concepts, short account names). It IS used at runtime: the
`attribute_lookup` tool (tools/attribute_lookup_tool.py, CATALOG_DATASET) reads
it as its alias / suggestions fallback when the fast fact search finds no exact
match. It is NOT the primary grounding path: the sub-agent
(agents/SalesDrive_revenue_expert.py) grounds user terms with INLINE SQL on
DRIVE_Revenues_value_index (built by recipes/build_value_index_recipe.py), and
the sub-agent calls only ONE DSS tool at runtime (revenue_semantic_query). The
old Custom Python tool Drive_Revenues_resolve_filter_value that used to read this
catalog is being deleted; attribute_lookup superseded it. The managed
dataset_lookup tool was removed (2026-06-18). See ../README.md and ../tools/README.md.

Each row maps a user-typed phrase to a real (column, value) filter: account names
(with short aliases for long names), the offer and business column values
themselves, and hand-crafted business-concept aliases ("indirect", "gcp", "roaming
hub") pointing to real DRIVE_Revenues values. The `is_alias` flag marks the
hand-crafted rows.

Output schema (1 row = 1 (variant -> target) edge):
- search_domain         : account | account_group | offer | business | alias
- source_column         : the column of the variant in DRIVE_Revenues (or "alias" for hand-crafted)
- target_column         : the column to filter on at SQL time
- target_value          : the value to filter on at SQL time
- matched_value         : the variant text (what users may type)
- display_value         : the human-readable canonical label
- normalized_value      : matched_value normalized (used for matching)
- frequency             : number of rows in DRIVE_Revenues for this target (or 99999 for aliases)
- canonical_account_name: for account rows
- canonical_carrier_code: for account rows
- parent_group          : for account rows
- is_alias              : 1 if hand-crafted alias, 0 otherwise
"""

import dataiku
import pandas as pd
import unicodedata
import re


# ============================================================
# CONFIG
# ============================================================

INPUT_DATASET = "DRIVE_Revenues"
OUTPUT_DATASET = "DRIVE_Revenues_Value_Catalog"

# Boost frequency given to alias rows so they win over fuzzy matches.
ALIAS_FREQUENCY = 99999

# Stopwords that should never be added as short Account_name aliases.
ACCOUNT_NAME_STOPWORDS = {
    "the", "and", "of", "for", "inc", "ltd", "llc", "sa", "sas", "ag", "gmbh",
    "co", "corp", "corporation", "company", "limited", "group", "holding", "holdings",
    "international", "global", "services", "solutions", "telecom", "communications",
    "communication", "mobile", "wireless", "networks", "network", "telecommunication",
    "telecommunications", "spa", "bv", "nv", "plc", "kg",
}

# Business concept aliases, maintained here in code (not YAML). Each entry maps
# user-typed phrases to canonical (target_column, target_value) tuples.
# IMPORTANT: only target_value strings that ACTUALLY EXIST in DRIVE_Revenues
# (verify a new alias against the source, or it silently matches nothing).
# Format: {"phrases": [...], "targets": [(column, value), ...], "note": "..."}.
BUSINESS_ALIASES = [
    # ---- distribution_type ----
    {
        "phrases": [
            "indirect", "indirect sales", "indirect channel", "indirect customers",
            "clients indirects", "client indirect", "vente indirecte", "ventes indirectes",
            "reseller", "resellers", "distributeur", "distributeurs", "indirect distribution",
        ],
        "targets": [("distribution_type", "Indirect_distribution/Resseler")],
        "note": "Indirect / reseller flows",
    },
    {
        "phrases": [
            "direct", "direct sales", "direct customers", "vente directe", "ventes directes",
            "clients directs", "client direct", "direct distribution",
        ],
        "targets": [("distribution_type", "Direct_distribution")],
        "note": "Direct distribution flows",
    },

    # ---- sales_entity ----
    {
        "phrases": [
            "gcp", "global carrier partners", "internal customers", "filiales orange",
            "orange filiales", "clients internes", "clients orange",
            "orange group customers", "orange internal",
        ],
        "targets": [("sales_entity", "GCP")],
        "note": "GCP = internal Orange group customers",
    },
    {
        "phrases": [
            "gcs", "global carrier services", "external customers", "clients externes",
            "external sales",
        ],
        "targets": [("sales_entity", "GCS")],
        "note": "GCS = external customers",
    },

    # ---- Roaming Hub conceptual umbrella ----
    # Roaming Hub is not a Solution: it spans Product=Open Roaming Hub
    # plus sirano_product values ROAMING HUB FEES / ROAMING HUB IOT.
    {
        "phrases": ["roaming hub", "open roaming hub"],
        "targets": [
            ("Product", "Open Roaming Hub"),
        ],
        "note": "Roaming Hub primary mapping",
    },

    # NOTE: Voice and Messaging do NOT exist as direct categories in DRIVE_Revenues.
    # We deliberately do NOT add them here. The Python resolver will return
    # an `unresolved_known_term` status for these, prompting the orchestrator
    # to clarify with the user. This avoids silent hallucination on totals.
]


# ============================================================
# HELPERS
# ============================================================

def get_series(frame, col):
    if col not in frame.columns:
        return pd.Series(dtype="object")
    obj = frame[col]
    if isinstance(obj, pd.DataFrame):
        obj = obj.iloc[:, 0]
    return obj


def clean_value(x):
    if isinstance(x, pd.Series):
        x = x.dropna()
        if x.empty:
            return ""
        x = x.iloc[0]
    if isinstance(x, (list, tuple)):
        if len(x) == 0:
            return ""
        x = x[0]
    if pd.isna(x):
        return ""
    s = str(x).strip()
    if re.match(r"^\d+\.0$", s):
        s = s[:-2]
    return s


def norm(x):
    s = clean_value(x)
    if not s:
        return ""
    s = s.lower()
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def most_frequent(frame, key_col, val_col):
    if key_col not in frame.columns or val_col not in frame.columns:
        return {}
    tmp = pd.DataFrame({
        key_col: get_series(frame, key_col).apply(clean_value),
        val_col: get_series(frame, val_col).apply(clean_value),
    })
    tmp = tmp[(tmp[key_col] != "") & (tmp[val_col] != "")]
    if tmp.empty:
        return {}
    return (
        tmp.groupby([key_col, val_col]).size().reset_index(name="n")
        .sort_values([key_col, "n"], ascending=[True, False])
        .drop_duplicates(key_col).set_index(key_col)[val_col].to_dict()
    )


# ============================================================
# ROW BUILDER
# ============================================================

rows = []


def add_row(
    search_domain, source_column, target_column, target_value,
    matched_value, display_value, frequency,
    canonical_account_name="", canonical_carrier_code="", parent_group="",
    is_alias=False,
):
    matched_value = clean_value(matched_value)
    if not matched_value:
        return
    target_value = clean_value(target_value)
    display_value = clean_value(display_value) or matched_value
    rows.append({
        "search_domain": clean_value(search_domain),
        "source_column": clean_value(source_column),
        "target_column": clean_value(target_column),
        "target_value": target_value,
        "matched_value": matched_value,
        "display_value": display_value,
        "normalized_value": norm(matched_value),
        "frequency": int(frequency),
        "canonical_account_name": clean_value(canonical_account_name),
        "canonical_carrier_code": clean_value(canonical_carrier_code),
        "parent_group": clean_value(parent_group),
        "is_alias": 1 if is_alias else 0,
    })


# ============================================================
# READ DATA
# ============================================================

df = dataiku.Dataset(INPUT_DATASET).get_dataframe(infer_with_pandas=False, int_as_float=False)


# ============================================================
# 1. ACCOUNT RESOLVER (with short-name aliases for long Account_name)
# ============================================================

if "diamond_id" in df.columns and "Account_name" in df.columns:
    base = pd.DataFrame({
        "diamond_id": get_series(df, "diamond_id").apply(clean_value),
        "Account_name": get_series(df, "Account_name").apply(clean_value),
        "carrier_code": get_series(df, "carrier_code").apply(clean_value)
            if "carrier_code" in df.columns else "",
        "Parent_Group": get_series(df, "Parent_Group").apply(clean_value)
            if "Parent_Group" in df.columns else "",
    })
    base = base[base["diamond_id"] != ""]

    account_name_map = most_frequent(base, "diamond_id", "Account_name")
    carrier_code_map = most_frequent(base, "diamond_id", "carrier_code")
    parent_group_map = most_frequent(base, "diamond_id", "Parent_Group")

    for col in ["Account_name", "carrier_code", "diamond_id", "Parent_Group"]:
        if col not in base.columns:
            continue
        tmp = pd.DataFrame({
            "diamond_id": base["diamond_id"].apply(clean_value),
            col: base[col].apply(clean_value),
        })
        tmp = tmp[(tmp["diamond_id"] != "") & (tmp[col] != "")]
        if tmp.empty:
            continue
        if col == "diamond_id":
            counts = tmp.groupby("diamond_id").size().reset_index(name="frequency")
            counts[col] = counts["diamond_id"]
        else:
            counts = tmp.groupby(["diamond_id", col]).size().reset_index(name="frequency")

        for _, r in counts.iterrows():
            diamond_id = clean_value(r["diamond_id"])
            matched_value = clean_value(r[col])
            canonical_account_name = account_name_map.get(diamond_id, matched_value)
            canonical_carrier_code = carrier_code_map.get(diamond_id, "")
            parent_group = parent_group_map.get(diamond_id, "")

            # When we resolve a Parent_Group phrase to a child diamond_id,
            # this is implicitly an alias (the user typed the parent name,
            # we point them to a child account). Flag it so the resolver
            # can prefer canonical Account_name matches.
            is_parent_alias = (col == "Parent_Group" and matched_value != canonical_account_name)

            add_row(
                search_domain="account",
                source_column=col,
                target_column="diamond_id",
                target_value=diamond_id,
                matched_value=matched_value,
                display_value=canonical_account_name,
                frequency=r["frequency"],
                canonical_account_name=canonical_account_name,
                canonical_carrier_code=canonical_carrier_code,
                parent_group=parent_group,
                is_alias=is_parent_alias,
            )

    # ----- Short-name aliases for long Account_name -----
    # For each Account_name longer than ~2 tokens, we add additional rows where
    # `matched_value` is a short distinctive prefix or significant token, so that
    # users typing "Telesat" or "Telroaming" hit the catalog directly without fuzzy.
    for diamond_id, full_name in account_name_map.items():
        norm_name = norm(full_name)
        if not norm_name:
            continue
        tokens = [t for t in norm_name.split(" ") if t and t not in ACCOUNT_NAME_STOPWORDS]
        if len(tokens) < 2:
            continue  # short name, no alias needed
        # Take first 1 and first 2 significant tokens as aliases.
        candidates = set()
        if len(tokens[0]) >= 4:
            candidates.add(tokens[0])
        if len(tokens) >= 2:
            two = (tokens[0] + " " + tokens[1]).strip()
            if len(two) >= 5:
                candidates.add(two)
        for cand in candidates:
            if cand == norm_name:
                continue  # already covered by the canonical row
            add_row(
                search_domain="alias",
                source_column="alias_account_short",
                target_column="diamond_id",
                target_value=diamond_id,
                matched_value=cand,
                display_value=full_name,
                frequency=ALIAS_FREQUENCY,
                canonical_account_name=full_name,
                canonical_carrier_code=carrier_code_map.get(diamond_id, ""),
                parent_group=parent_group_map.get(diamond_id, ""),
                is_alias=True,
            )

    # Parent_Group resolver for explicit group/subsidiaries questions.
    if "Parent_Group" in base.columns:
        grp = base["Parent_Group"].apply(clean_value)
        grp = grp[grp != ""]
        if not grp.empty:
            counts = grp.value_counts().reset_index()
            counts.columns = ["Parent_Group", "frequency"]
            for _, r in counts.iterrows():
                parent_group = clean_value(r["Parent_Group"])
                add_row(
                    search_domain="account_group",
                    source_column="Parent_Group",
                    target_column="Parent_Group",
                    target_value=parent_group,
                    matched_value=parent_group,
                    display_value=parent_group,
                    frequency=r["frequency"],
                    parent_group=parent_group,
                )


# ============================================================
# 2. OFFER RESOLVER
# ============================================================

for col in ["Product", "Solution", "SolutionLine", "sirano_product"]:
    if col not in df.columns:
        continue
    values = get_series(df, col).dropna().apply(clean_value)
    values = values[values != ""]
    if values.empty:
        continue
    counts = values.value_counts().reset_index()
    counts.columns = [col, "frequency"]
    for _, r in counts.iterrows():
        value = clean_value(r[col])
        add_row(
            search_domain="offer",
            source_column=col,
            target_column=col,
            target_value=value,
            matched_value=value,
            display_value=value,
            frequency=r["frequency"],
        )


# ============================================================
# 3. BUSINESS / SCENARIO RESOLVER
# ============================================================

for col in ["Phase", "booking_type", "distribution_type", "sales_entity", "sales_zone"]:
    if col not in df.columns:
        continue
    values = get_series(df, col).dropna().apply(clean_value)
    values = values[values != ""]
    if values.empty:
        continue
    counts = values.value_counts().reset_index()
    counts.columns = [col, "frequency"]
    for _, r in counts.iterrows():
        value = clean_value(r[col])
        add_row(
            search_domain="business",
            source_column=col,
            target_column=col,
            target_value=value,
            matched_value=value,
            display_value=value,
            frequency=r["frequency"],
        )


# ============================================================
# 4. BUSINESS CONCEPT ALIASES (hand-crafted, in code)
# ============================================================

for entry in BUSINESS_ALIASES:
    phrases = entry.get("phrases", [])
    targets = entry.get("targets", [])
    for phrase in phrases:
        for target_column, target_value in targets:
            add_row(
                search_domain="alias",
                source_column="alias_business",
                target_column=target_column,
                target_value=target_value,
                matched_value=phrase,
                display_value=target_value,
                frequency=ALIAS_FREQUENCY,
                is_alias=True,
            )


# ============================================================
# 5. FINAL CATALOG
# ============================================================

catalog = pd.DataFrame(rows)

if not catalog.empty:
    catalog = catalog[catalog["normalized_value"] != ""]
    catalog = catalog.drop_duplicates(
        subset=["search_domain", "source_column", "target_column",
                "target_value", "normalized_value"]
    )
    catalog = catalog[[
        "search_domain", "source_column", "target_column", "target_value",
        "matched_value", "display_value", "normalized_value", "frequency",
        "canonical_account_name", "canonical_carrier_code", "parent_group",
        "is_alias",
    ]]
    catalog = catalog.sort_values(
        ["search_domain", "source_column", "normalized_value", "frequency"],
        ascending=[True, True, True, False],
    )

dataiku.Dataset(OUTPUT_DATASET).write_with_schema(catalog)
