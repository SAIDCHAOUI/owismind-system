### Python code qui call un agent et recup les données live stream en livce et la réponse et la requete sql généré si y en a une : 
'''
import dataiku
import time
import json

try:
    from dataikuapi.dss.llm import DSSLLMStreamedCompletionFooter
except Exception:
    DSSLLMStreamedCompletionFooter = None


client = dataiku.api_client()
project = client.get_default_project()

# OPTION A - vrai live le plus fiable : appeler directement le sous-agent Structured Visual Agent
AGENT_ID = "agent:rNTZ781a"

# OPTION B - tester le Code Agent dispatcher
# AGENT_ID = "agent:TON_CODE_AGENT_ID"

question = "Combien on a fait avec algerie telecom en 2025 ?"

llm = project.get_llm(AGENT_ID)

completion = llm.new_completion()
completion.with_message(question)

t0 = time.perf_counter()
answer = ""
footer_data = None
events = []


def is_footer_chunk(chunk, data):
    if isinstance(data, dict) and data.get("type") == "footer":
        return True

    if DSSLLMStreamedCompletionFooter is not None:
        return isinstance(chunk, DSSLLMStreamedCompletionFooter)

    return False


def find_usage_metadata(obj):
    found = []

    if isinstance(obj, dict):
        if isinstance(obj.get("usageMetadata"), dict):
            found.append(obj["usageMetadata"])

        for value in obj.values():
            found.extend(find_usage_metadata(value))

    elif isinstance(obj, list):
        for item in obj:
            found.extend(find_usage_metadata(item))

    return found


def sum_usage_metadata(usages):
    total = {
        "promptTokens": 0,
        "completionTokens": 0,
        "totalTokens": 0,
        "estimatedCost": 0.0,
    }

    for usage in usages:
        total["promptTokens"] += usage.get("promptTokens", 0) or 0
        total["completionTokens"] += usage.get("completionTokens", 0) or 0
        total["totalTokens"] += usage.get("totalTokens", 0) or 0
        total["estimatedCost"] += usage.get("estimatedCost", 0.0) or 0.0

    return total


def find_generated_sql(obj):
    sql_queries = []

    if isinstance(obj, dict):
        name = obj.get("name")
        outputs = obj.get("outputs", {}) or {}

        if name == "semantic-model-query" and isinstance(outputs, dict):
            sql = outputs.get("sql")
            if sql:
                sql_queries.append({
                    "name": name,
                    "success": outputs.get("success"),
                    "row_count": outputs.get("row_count"),
                    "sql": sql,
                })

        for value in obj.values():
            sql_queries.extend(find_generated_sql(value))

    elif isinstance(obj, list):
        for item in obj:
            sql_queries.extend(find_generated_sql(item))

    return sql_queries


def find_relayed_sql_from_events(events):
    """
    Useful when testing the Code Agent dispatcher.
    SQL may be embedded inside SUB_AGENT_FOOTER eventData.
    """
    sql_queries = []

    for event in events:
        event_data = event.get("eventData", {}) or {}
        generated_sql = event_data.get("generatedSql", [])

        if isinstance(generated_sql, list):
            sql_queries.extend(generated_sql)

    return sql_queries


for chunk in completion.execute_streamed():
    data = getattr(chunk, "data", {}) or {}
    elapsed = round(time.perf_counter() - t0, 2)

    if is_footer_chunk(chunk, data):
        footer_data = data

        row = {
            "t": elapsed,
            "eventKind": "FOOTER",
            "blockId": None,
            "nextBlockId": None,
            "toolName": None,
        }

        print(json.dumps(row, ensure_ascii=False), flush=True)
        continue

    chunk_type = data.get("type")

    if chunk_type == "event":
        event_data = data.get("eventData", {}) or {}

        row = {
            "t": elapsed,
            "eventKind": data.get("eventKind"),
            "blockId": event_data.get("blockId"),
            "nextBlockId": event_data.get("nextBlockId"),
            "toolName": (
                event_data.get("toolName")
                or event_data.get("name")
                or event_data.get("tool")
            ),
        }

        events.append({
            **row,
            "eventData": event_data,
        })

        print(json.dumps(row, ensure_ascii=False), flush=True)

    elif chunk_type in ("content", "text"):
        text = data.get("text", "") or ""
        answer += text

    else:
        # Defensive debug for unknown chunk types
        row = {
            "t": elapsed,
            "eventKind": f"UNKNOWN_CHUNK_TYPE:{chunk_type}",
            "blockId": None,
            "nextBlockId": None,
            "toolName": None,
        }
        print(json.dumps(row, ensure_ascii=False), flush=True)


trace = footer_data.get("trace") if isinstance(footer_data, dict) else None

print("\n--- FINAL ANSWER ---")
print(answer.strip())


print("\n--- EVENT KINDS ---")
for kind in sorted({e.get("eventKind") for e in events if e.get("eventKind")}):
    print(kind)


print("\n--- BLOCK IDS ---")
for block_id in sorted({e.get("blockId") for e in events if e.get("blockId")}):
    print(block_id)


print("\n--- TOOL NAMES ---")
for tool in sorted({e.get("toolName") for e in events if e.get("toolName")}):
    print(tool)


print("\n--- USAGE METADATA SUM ---")
usages = find_usage_metadata(trace) if trace else []
usage_total = sum_usage_metadata(usages)

print(json.dumps({
    "usageMetadataCount": len(usages),
    **usage_total
}, indent=2, ensure_ascii=False))


print("\n--- GENERATED SQL ---")

sql_queries = find_generated_sql(trace) if trace else []

# If testing Code Agent dispatcher, SQL can be relayed inside SUB_AGENT_FOOTER eventData
if not sql_queries:
    sql_queries = find_relayed_sql_from_events(events)

if not sql_queries:
    print("No generated SQL found.")
else:
    for i, item in enumerate(sql_queries, start=1):
        print(f"\nSQL #{i}")
        print("success:", item.get("success"))
        print("row_count:", item.get("row_count"))
        print(item.get("sql"))
'''


### crée une table sql lié au projet.
# crée une table sql lié au projet.
import dataiku
from dataiku import SQLExecutor2

CONNECTION_NAME = "SQL_owi"
SCHEMA_NAME = "public"

# PROJECT_KEY = dataiku.default_project_key()  # recup le projet key du notebook OWISMIND_DEV dans ce notebook
PROJECT_KEY = "OWISMIND_LAB"

LOGICAL_TABLE_NAME = "webapp_storage_probe_good"
PHYSICAL_TABLE_NAME = f'{PROJECT_KEY}_{LOGICAL_TABLE_NAME}'

FULL_TABLE_NAME = f'{SCHEMA_NAME}."{PHYSICAL_TABLE_NAME}"'

executor = SQLExecutor2(connection=CONNECTION_NAME)

create_table_sql = f"""
CREATE TABLE {FULL_TABLE_NAME} (
    probe_id VARCHAR(64) NOT NULL,
    note VARCHAR(255) NOT NULL
)
"""

result = executor.query_to_df(
    "SELECT 1 AS table_creation_committed",
    pre_queries=[create_table_sql],
    post_queries=["COMMIT"]
)

print("PROJECT_KEY =", PROJECT_KEY)
print("PHYSICAL_TABLE_NAME =", PHYSICAL_TABLE_NAME)
display(result)

# Modifier une table 
from uuid import uuid4
from dataiku import SQLExecutor2

CONNECTION_NAME = "SQL_owi"
SCHEMA_NAME = "public"

PROJECT_KEY = dataiku.default_project_key()
LOGICAL_TABLE_NAME = "webapp_storage_probe_good"
PHYSICAL_TABLE_NAME = f'{PROJECT_KEY}_{LOGICAL_TABLE_NAME}'
FULL_TABLE_NAME = f'{SCHEMA_NAME}."{PHYSICAL_TABLE_NAME}"'

executor = SQLExecutor2(connection=CONNECTION_NAME)

probe_id = uuid4().hex

insert_sql = f"""
INSERT INTO {FULL_TABLE_NAME} (probe_id, note)
VALUES ('{probe_id}', 'direct project-prefixed storage test from DSS notebook')
"""

executor.query_to_df(
    "SELECT 1 AS insert_committed",
    pre_queries=[insert_sql],
    post_queries=["COMMIT"]
)

df = executor.query_to_df(f"""
SELECT probe_id, note
FROM {FULL_TABLE_NAME}
WHERE probe_id = '{probe_id}'
""")

display(df)
