# Patterns de code prêts à l'emploi (Dataiku + LangChain/LangGraph)

> **À jour : juin 2026** — LangChain 1.x, LangGraph 1.x, Dataiku DSS 14.x. Fiche de référence du skill `agentique-python-dataiku` (parent : `SKILL.md`). Concepts et signatures détaillés ailleurs : `references/langchain-v1.md` (`create_agent`, middleware, structured output), `references/langgraph-v1.md` (StateGraph, reducers, `Send`, persistence), `references/orchestration-multi-agents.md` (superviseur/sous-agents), `references/dataiku-code-agents.md` (LLM Mesh, Code Agents, `DKUChatModel`), `references/prompting-et-determinisme.md` (pipeline UNDERSTAND→…→RENDER, anti « règles par bug »). Ici : **du code minimal, correct, copiable**, chaque snippet annoté de sa **version Python cible** et du pattern du corpus dont il dérive.

---

## 0. Règle d'or : quelle version Python, quel code

L'instance Dataiku a **deux** code environments : **Python 3.9** ET **Python 3.11**. C'est le fait qui décide de TOUT ce qui suit.

| Contexte | Python | `import langchain` / `langgraph` | Comment on appelle un LLM / agent / tool |
|---|---|---|---|
| **Code Agent / recette sur code env 3.11** | 3.11 (≥ 3.10) | ✅ autorisé | `create_agent`, `StateGraph`, `DKUChatModel`, **ou** APIs Mesh natives |
| **Backend webapp OWIsMind** (tout contexte 3.9) | 3.9.23 | ❌ **interdit** (v1 exige ≥ 3.10) | **stdlib + `dataiku` uniquement**, APIs Dataiku natives **directement** |

- LangChain/LangGraph v1 **exigent Python ≥ 3.10** (Python 3.9 EOL oct. 2025) → ils tournent **seulement** dans un code env 3.11 (source : https://docs.langchain.com/oss/python/migrate/langgraph-v1).
- **Ne JAMAIS recommander `import langchain` dans un contexte 3.9.** En 3.9, on parle au LLM Mesh / aux agents / aux tools via l'API Dataiku (`project.get_llm(...)`, `project.get_agent_tool(...)`) — voir §4–§5.
- Un **Code Agent DSS** (le fichier collé dans « Code agent ») subclasse `dataiku.llm.python.BaseLLM` et est **standalone** : `stdlib + dataiku` seulement, jamais d'import du plugin (corpus §0). Lui assigner un code env 3.11 lui permet d'`import langchain`, mais il reste standalone — il n'importe toujours pas le plugin.

> Marqueurs de modèle dans ce fichier : ids Anthropic réels (`claude-opus-4-8`, `claude-sonnet-4-6`, `claude-haiku-4-5`). `gpt-5.5` et `gemini-3.5-flash` apparaissent dans les exemples LangChain mais sont **UNVERIFIED** (non-Anthropic) — substituer un id de votre LLM Mesh ou un id Anthropic réel (source recency : `gap-version-recency-recheck-2026.md`).

---

## 1. [Python 3.11] `DKUChatModel` + `create_agent` — orchestrateur minimal

Chemin LangChain v1 dans un Code Agent (ou recette) en code env 3.11. Point d'entrée DSS : envelopper un LLM du Mesh en chat model LangChain via `DKUChatModel`, puis le passer à `create_agent`. Dérive du starter ChatGPT (réconcilié avec la signature `create_agent` du corpus `langchain-agents-create-agent.md`).

```python
# PYTHON 3.11 code env ONLY (LangChain v1 requires >= 3.10).
# Derives from: _chatgpt-source starter + langchain-agents-create-agent.md §5.
from dataiku.langchain.dku_llm import DKUChatModel   # UNVERIFIED import path — confirm in DSS docs
from langchain.agents import create_agent            # v1 factory (NOT create_react_agent)
from langchain.tools import tool

# 1) LLM Mesh model as a LangChain chat model. llm_id = a registered LLM Mesh id.
llm = DKUChatModel(llm_id="YOUR_LLM_MESH_ID", temperature=0)

# 2) A descriptive tool: docstring = description seen by the model; type hints = input schema.
@tool
def get_revenue(scenario: str, period: str) -> str:
    """Return total revenue for a scenario (ACTUALS/BUDGET/FORECAST) and an ISO period (YYYY or YYYY-MM)."""
    rows = run_sql(scenario, period)          # your deterministic query
    return format_rows(rows)

# 3) Compile the agent. system_prompt (NOT prompt=). Empty tools -> model-only agent.
agent = create_agent(
    model=llm,
    tools=[get_revenue],
    system_prompt=(
        "You are the main orchestrator. Delegate to specialists when the task leaves your domain. "
        "Prefer structured outputs, surface uncertainty, and avoid unnecessary tool calls."
    ),
)

# 4) Invoke. Input/output are MESSAGE LISTS (no intermediate_steps).
out = agent.invoke({"messages": [{"role": "user", "content": "Budget revenue 2026?"}]})
answer = out["messages"][-1].content
# Raise the loop bound per-invocation if needed (default recursion_limit = 25, NOT 1000):
# out = agent.invoke({...}, config={"recursion_limit": 100})
```

**UNVERIFIED / à confirmer en DSS :**
- `from dataiku.langchain.dku_llm import DKUChatModel` — chemin d'import non confirmé contre la doc publiée (corpus le marque à vérifier ; voir `references/dataiku-code-agents.md`). Introspecter en DSS (`dir(...)`) avant de s'y fier.
- `create_agent` lui-même est **vérifié** : `from langchain.agents import create_agent`, paramètre `system_prompt` (pas `prompt`), retourne un `CompiledStateGraph` (source : https://reference.langchain.com/python/langchain/agents/factory/create_agent). La fausse rumeur « create_agent retiré en 1.1.0 » était un venv périmé (source : https://forum.langchain.com/t/create-agent-no-longer-exists-in-langchain-agents-v1-1-0/2350).

**Pièges vérifiés :** `recursion_limit` par défaut = **25** (le relever via `config=`, jamais en changeant un défaut) ; lire la réponse dans `out["messages"][-1].content` (pas d'`intermediate_steps`) (source recency : `gap-version-recency-recheck-2026.md` §3.2 ; corpus `langchain-agents-create-agent.md` §8.2).

> En 3.9, ce snippet **ne marche pas** (import interdit) → utiliser le chemin natif §4.

---

## 2. [Python 3.11] Tool avec `ToolRuntime` + idempotence

Un tool de qualité est **descriptif, minimal, gouvernable, robuste**. `ToolRuntime` (injecté, **invisible au modèle**) donne accès à l'état, au store, au thread/run et au contexte par-run (user id, project key) — la séparation propre entre données par-run et mémoire conversationnelle. L'idempotence est **non négociable** : un nœud LangGraph peut être **réexécuté depuis le début** après reprise/retry (checkpoints aux frontières de super-steps), donc tout effet de bord (écriture SQL, appel API) doit être sûr à rejouer (corpus `_chatgpt-source.md` ; `gap-version-recency-recheck-2026.md` §2.4).

```python
# PYTHON 3.11 code env ONLY.
# Derives from: _chatgpt-source (tools, ToolRuntime, idempotence) + tools-et-tool-design.md.
from langchain.tools import tool, ToolRuntime
from langchain.messages import ToolMessage

@tool
def upsert_forecast(period: str, amount: float, runtime: ToolRuntime) -> str:
    """Persist a forecast for an ISO period (YYYY-MM). Idempotent: re-running with the
    same period overwrites, never duplicates. Use ONLY for forecast scenarios."""
    # ToolRuntime is injected by the framework; the model never sees/sets it.
    user_id = runtime.context.user_id            # per-run context (governance / row-level identity)
    op_key = f"forecast:{user_id}:{period}"       # natural idempotency key

    # IDEMPOTENT WRITE: dedupe by op_key OR use UPSERT semantics so a replay is a no-op.
    if already_applied(op_key):                    # checkpoint replay -> short-circuit
        return f"forecast for {period} already set (idempotent no-op)"
    db_upsert(user_id, period, amount, op_key=op_key)   # ON CONFLICT ... DO UPDATE
    return f"forecast {period} = {amount} (op {op_key})"
```

**Discipline tool (corpus) :**
- **Docstring = description** lue par le modèle ; **type hints = schéma d'entrée**. Soigner les deux ; le modèle choisit le tool sur la docstring.
- **Robustesse** : convertir les exceptions en message intelligible pour le modèle plutôt que de planter — soit via middleware `wrap_tool_call`, soit en renvoyant un `ToolMessage` d'erreur exploitable (corpus `langchain-agents-create-agent.md` §7.1 ; `_chatgpt-source.md`).
- **Isoler les tools** comme composants versionnés/testables (en DSS : Custom Python Tool) plutôt que d'empiler la logique dans l'orchestrateur (corpus `_chatgpt-source.md`).
- **Idempotence par clé naturelle** + UPSERT : la seule défense correcte contre le rejeu de nœud (`gap-version-recency-recheck-2026.md` §2.4 ; `_chatgpt-source.md`).

---

## 3. [Python 3.11] LangGraph `StateGraph` brut — superviseur + fan-out `Send` + reducer

Descendre au `StateGraph` quand la **topologie** est le sujet : branches déterministes, parallélisme map-reduce, état partagé typé. Le superviseur route, les workers s'exécutent **en parallèle** via `Send`, un **reducer** (`operator.add`) agrège leurs sorties sans collision d'écriture concurrente (corpus `langchain-agents-create-agent.md` §9 ; structure superviseur du `_chatgpt-source.md` ; primitives `references/langgraph-v1.md`).

```python
# PYTHON 3.11 code env ONLY.
# Derives from: langchain-agents-create-agent.md §9 (StateGraph) + _chatgpt-source supervisor/subgraphs.
import operator
from typing import Annotated, TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.types import Send

class State(TypedDict):
    question: str
    domains: list[str]                                   # set by the supervisor
    # REDUCER: parallel workers append; operator.add concatenates lists safely.
    partials: Annotated[list[dict], operator.add]
    answer: str

def supervisor(state: State) -> dict:
    # Deterministic (or 1 strict-JSON LLM call) routing decision. No business fact authored here.
    return {"domains": pick_domains(state["question"])}

def fan_out(state: State) -> list[Send]:
    # CONDITIONAL EDGE as a path function returning Send objects -> one worker per domain, in parallel.
    return [Send("worker", {"question": state["question"], "domain": d}) for d in state["domains"]]

def worker(state: dict) -> dict:
    res = run_domain_agent(state["domain"], state["question"])   # a sub-agent / tool call
    return {"partials": [res]}                                   # reducer merges across branches

def synthesize(state: State) -> dict:
    return {"answer": compose(state["question"], state["partials"])}  # final write, single node

g = StateGraph(State)
g.add_node("supervisor", supervisor)
g.add_node("worker", worker)
g.add_node("synthesize", synthesize)
g.add_edge(START, "supervisor")
# add_conditional_edges signature is (source, path, path_map=None) — NO then= param.
g.add_conditional_edges("supervisor", fan_out)      # path returns a list[Send] -> fan-out
g.add_edge("worker", "synthesize")                  # all worker branches join here
g.add_edge("synthesize", END)
graph = g.compile()                                 # add checkpointer=... for durability

# Invoke; raise the loop bound here if a deep graph needs it. Stream durability default = "async";
# pass durability= explicitly when it matters.
out = graph.invoke({"question": "360 on roaming"}, config={"recursion_limit": 50})
```

**Pièges vérifiés (recency) :**
- `add_conditional_edges(source, path, path_map=None)` — **pas de paramètre `then=`** (corrigé : `gap-version-recency-recheck-2026.md` §2.5).
- `recursion_limit` défaut **25** ; relever via `config={"recursion_limit": N}`.
- `durability` défaut **`"async"`** ; passer `durability=` explicitement sur `invoke`/`stream` là où c'est sensible (`gap-version-recency-recheck-2026.md` §3.1).
- Le **reducer** est la seule façon correcte d'agréger des écritures parallèles sur une même clé d'état ; sans lui, deux branches écrasent la même valeur.

**Pont vers OWIsMind (corpus §8) :** le projet n'utilise PAS LangGraph (3.9), mais il fait l'**équivalent à la main** : fan-out sur un pool de threads borné (`MAX_PARALLEL_AGENTS = 3`), les workers **ne touchent jamais** trace/usage/yield (poussent dans une `queue.Queue`), et **toute** l'agrégation (trace, usage, SQL) se fait sur le **thread principal** après chaque step — parce que `SpanBuilder`/accumulateurs ne sont **pas supposés thread-safe**. C'est le reducer + le « single writer », rejoués sans LangGraph.

---

## 4. [Python 3.9] Appeler un agent / tool LLM Mesh — APIs Dataiku natives (sans LangChain)

Le chemin **3.9 / stdlib-only** : aucun `import langchain`. On parle au Mesh directement. C'est le pattern validé DSS d'OWIsMind (`get_agent_tool().run()` + appel d'agent streamé) (corpus `owismind-project-patterns.md` §0, §4.2 ; `docs/cadrage/code_samples_dataiku.md`).

### 4a. Appeler un sous-agent depuis du code (orchestrateur → sous-agent), streamé

```python
# PYTHON 3.9 (stdlib + dataiku only). NEVER import langchain here.
# Derives from: owismind-project-patterns.md §0 (orchestrator -> sub-agent) + docs/cadrage/code_samples_dataiku.md.
import dataiku
project = dataiku.api_client().get_default_project()

def call_subagent(agent_id, instruction, context_msg=None, pass_context=False):
    """agent_id like 'agent:AKQaQ0Am'. Returns (answer_text, sub_trace)."""
    completion = project.get_llm(agent_id).new_completion()
    if pass_context and context_msg:                      # opt-in only (conversational memory)
        completion.with_message(context_msg, role="system")
    completion.with_message(instruction)                  # the current instruction

    answer_parts, sub_trace = [], None
    for chunk in completion.execute_streamed():
        data = getattr(chunk, "data", {}) or {}
        ctype = data.get("type") or getattr(chunk, "type", None)
        if ctype == "footer":                             # final footer carries the full trace
            sub_trace = data.get("trace")                 # usage (usageMetadata) + generated SQL spans
            continue
        if ctype == "event":
            relay_or_capture(data)                        # drive the timeline (liveness)
        elif ctype in ("content", "text"):
            answer_parts.append(data.get("text", ""))
    return "".join(answer_parts), sub_trace
```

Détection du **footer** : par `data["type"] == "footer"` **et** (quand le SDK l'expose) `isinstance(chunk, DSSLLMStreamedCompletionFooter)` — **import gardé**, les builds SDK diffèrent et certains émettent le footer sans champ `type` (corpus §0, ORCH-07). `footer.trace` est le **seul** endroit pour récupérer l'usage et le SQL généré.

### 4b. Appeler un tool managé directement et lire SQL + lignes du **retour**

Lire la sortie du **return value** rend la capture Evidence **déterministe** (au lieu de deviner des clés de trace) — décision validée L047.

```python
# PYTHON 3.9 (stdlib + dataiku only).
# Derives from: owismind-project-patterns.md §4.2 (get_agent_tool().run()).
def get_tool(project, tool_id, expected_name=None):
    """One-shot fallback: validate id via get_descriptor(), else name-match (covers a recreated id)."""
    try:
        t = project.get_agent_tool(tool_id)
        t.get_descriptor()                                # raises if the id is stale
        return t
    except Exception:
        for item in project.list_agent_tools():           # match by name when id changed
            if item.get("name") == expected_name:
                return project.get_agent_tool(item["id"])
        raise

def run_semantic_tool(project, tool_id, question, expected_name="semantic-model-query"):
    tool = get_tool(project, tool_id, expected_name)
    desc = tool.get_descriptor()
    input_key = pick_input_key(desc)                      # auto-detect from inputSchema; observed: "question"
    result = tool.run({input_key: question})              # SQL + rows are in the RETURN value
    payload = extract_semantic_payload(result)            # see §6 RENDER for agent-mode extraction
    return payload                                        # {answer, rows, columns, sql, row_count}
```

**Pièges (corpus) :** l'`input_key` se **détecte** dans `descriptor.inputSchema` (codé en dur = fragile) ; le fallback id→nom couvre un tool recréé dont l'id a changé. En **mode Agent**, le tool renvoie un **transcript multi-messages** (préambule → exploration de schéma → requêtes-sonde → réponse finale) → l'extraction prend **la DERNIÈRE** occurrence par priorité de clés (cf. §6).

---

## 5. [Python 3.9] Streaming vers un frontend : polling-via-thread

SSE est **abandonné** en DSS : le proxy nginx interne bufferise le long `text/event-stream`, donc tout arrive à la fin. Le pattern robuste sur runtime sync 3.9 Flask est le **polling-via-thread** : `/chat/start` lance UN thread daemon, `/chat/poll` renvoie les events depuis un curseur, `/chat/stop` pose un flag coopératif (corpus `gap-streaming-agents-to-web-frontend.md` §0, §2, §6 ; `owismind-project-patterns.md` §0 transport).

```python
# PYTHON 3.9 (stdlib + dataiku only). Sync Flask/WSGI runtime.
# Derives from: gap-streaming-agents-to-web-frontend.md §2/§6/§7 (stream_manager.py shape).
import threading, time
from uuid import uuid4

_LOCK = threading.Lock()
_RUNS = {}                          # run_id -> run state
MAX_CONCURRENT_RUNS = 8             # bound live threads + LLM connections (instance safety)

def start_run(project_key, agent_id, messages, user_id):
    run_id = uuid4().hex
    with _LOCK:
        if sum(1 for s in _RUNS.values() if not s["done"]) >= MAX_CONCURRENT_RUNS:
            raise CapacityError()                          # route -> HTTP 503 "busy"
        _RUNS[run_id] = {"events": [], "done": False, "error": None, "user_id": user_id,
                         "last_poll_at": None, "stop_requested": False}
    threading.Thread(target=_worker, args=(run_id, project_key, agent_id, messages, user_id),
                     daemon=True).start()
    return run_id

def _worker(run_id, project_key, agent_id, messages, user_id):
    try:
        for ev in run_agent_streamed(project_key, agent_id, messages):   # normalised dicts (§4a)
            with _LOCK:
                if _RUNS[run_id]["stop_requested"]:        # cooperative stop, checked BETWEEN chunks
                    break
                _RUNS[run_id]["events"].append(ev)
        _persist_answer_usage_trace(run_id)                # phase 2: store answer + usage + trace
    except Exception:
        with _LOCK: _RUNS[run_id]["error"] = "agent_unavailable"
    finally:
        with _LOCK:
            _RUNS[run_id]["done"] = True                   # set AFTER terminal events appended (no lost-frame race)

def poll(run_id, user_id, cursor):
    with _LOCK:
        s = _RUNS.get(run_id)
        if s is None or s["user_id"] != user_id:           # owner-scoped; None -> 404
            return None
        s["last_poll_at"] = time.monotonic()               # heartbeat -> abandonment detection
        evs = s["events"]
        return {"events": evs[cursor:], "cursor": len(evs), "done": s["done"], "error": s["error"]}
```

**À copier (corpus) :**
- **Le `done` est posé sous le MÊME lock, APRÈS les events terminaux** : un poll qui voit `done` voit aussi `final_answer` (pas de course sur la dernière frame).
- **Whitelister** les champs relayés au navigateur (jamais le dict event brut : il porte agent ids, instructions, SQL interne). OWIsMind ne copie que `label / stepIndex / stepCount / agentKey / status`, chacun borné.
- **Liveness = events** (timeline), **pas** streaming de tokens : la réponse arrive en **un bloc à la fin** (le proxy bufferise). Concevoir des events fins, pas un stream de l'intérieur des tools.
- **Borne tout** : `MAX_LIVE_EVENTS`, `MAX_ANSWER_CHARS`, `MAX_RUN_SECONDS`, abandon dérivé de `last_poll_at` (onglet fermé → couper le run, libérer le slot, arrêter de payer des tokens sans consommateur).
- **Annulation coopérative seulement** : on stoppe *entre* chunks (le Mesh n'expose **aucune** API de cancel) ; un `stopped` est un terminal **propre** (réponse partielle + marqueur discret), pas une erreur.

**Footer usage (corpus §9) :** sommer chaque `usageMetadata` de la trace (plusieurs appels LLM sous-agents/tools par tour), émettre **un** event `usage_summary` final ; persistance best-effort (un échec d'écriture usage ne doit **jamais** casser la réponse). Côté LangChain (3.11) l'équivalent est le `usage_metadata` **final agrégé** — ne pas sommer par-chunk (certains providers gonflent les totaux).

---

## 6. Le squelette déterministe UNDERSTAND → RESOLVE → COMPOSE → QUERY → RENDER

Pipeline central des agents OWIsMind, **agnostique du runtime** (le même découpage tient en 3.9 natif comme en 3.11). **Le LLM ne fait que la linguistique et une phrase vérifiée ; tout ce qui porte est du Python déterministe.** « Le LLM ne décide plus rien pendant l'exécution » — il planifie **une fois** (JSON strict), le code exécute (corpus `owismind-project-patterns.md` §1, §3 ; `references/prompting-et-determinisme.md`).

| Stage | LLM fait | CODE fait (déterministe) |
|---|---|---|
| **UNDERSTAND** | 1 appel JSON strict (scope, intent, scénarios, période, axe, top-N, **termes** bruts) | valide/dégrade le JSON contre le **profil** (jamais une valeur inventée) |
| **RESOLVE** | rien | ancre chaque terme sur un **value index** par SQL (exact → fuzzy) ; politique d'ambiguïté |
| **COMPOSE** | rien | construit le SQL **ou** la question sémantique depuis des **templates gelés** |
| **QUERY** | rien (sauf intent `custom` : SQL gardé) | exécute / appelle le tool ; capture SQL + lignes |
| **RENDER** | **une** phrase d'accroche, chaque chiffre vérifié | formate table et montants par code ; fallback déterministe |

```python
# RUNTIME-AGNOSTIC skeleton. In a 3.9 Code Agent: stdlib + dataiku only.
# Derives from: owismind-project-patterns.md §1 (the 5-stage pipeline) + prompting-et-determinisme.md.

def answer(query, profile, project, tool_id):
    user_q = query["messages"][-1]["content"]                  # last user message = the instruction

    # 1) UNDERSTAND — strict JSON; enums ANCHORED on the profile so the model can't invent a value.
    schema = build_understand_schema(profile)                  # scenarios enum = profile's real values
    raw = call_json_llm(build_understand_prompt(profile), user_q, schema)   # 2 attempts: native JSON -> prompt-only
    u = validate_understanding(raw, profile)                    # degrade unknowns -> "custom"; never trust invented values

    # 2) RESOLVE — ground each term on the value index by SQL (exact -> LIKE+fuzzy -> bounded slice).
    resolved = resolve_terms(u["terms"], project, profile)     # _norm() FROZEN & shared with the index recipe
    if needs_clarification(resolved):                          # ambiguity policy (deterministic, 3 steps)
        return clarify(resolved)                               # ends with a parseable "VALUE (Column)" round-trip

    # 3) COMPOSE — frozen templates. User question LEADS; grouped exact values -> IN per column (never AND intra-column).
    semantic_q = build_semantic_question(user_q, u, resolved, profile)

    # 4) QUERY — call the managed tool; read SQL + rows from the RETURN value (§4b).
    payload = run_semantic_tool(project, tool_id, semantic_q)  # {answer, rows, columns, sql, row_count}

    # 5) RENDER — table & numbers by code; ONE LLM headline, verified number-by-number.
    table = build_table(payload["rows"], payload["columns"])
    allowed = allowed_number_set(payload["rows"])              # every figure that may appear
    headline = write_headline_llm(user_q, payload)
    if not verify_headline(headline, allowed):                # any cited number not in the set -> reject whole headline
        headline = deterministic_headline(payload)            # safe fallback
    return headline + "\n\n" + table
```

**Invariants (corpus, non négociables) :**
- **Le SQL appartient au Semantic Model** (tool en mode Agent) : extraction = **priorité de clés** (`answer`/`output_text` > `completion` > `text` > `result`) puis **DERNIÈRE** occurrence (jamais la première = préambule) ; `rows`/`row_count` = **dernière** aussi (les requêtes-sonde précèdent le résultat final).
- **Question sémantique : question user EN TÊTE, verbatim**, puis hint d'intent, puis valeurs exactes **groupées par colonne → `IN`** (jamais `Product = A AND Product = B` = bug AND impossible) ; règle énumération → OR + une ligne par item.
- **Prédicats temporels cast-safe** : `LEFT(CAST(col AS text), n)` (pas `LEFT(date, 10)` qui n'existe pas en PostgreSQL) ; un échec de template self-repair en tombant sur le chemin LLM gardé avec l'erreur DB en contexte.
- **Read-only** : `SET LOCAL statement_timeout TO '30000'` + `SET LOCAL transaction_read_only TO on` en pre-queries.
- **SQL guard** (intent `custom` seulement) : 1 statement, commence `SELECT`/`WITH`, pas de DML/DDL, **une** table whitelistée, `LIMIT` imposé et plafonné ; `EXPLAIN` dry-run + ≤ 2 réparations.
- **Anti « règles par bug » (P3)** : jamais de valeur métier en dur dans la logique — l'expertise vient du **profil** et du **value index** (artefacts Flow) ; les invariants métier vivent dans des **tests anti-dérive** (import croisé de `KNOWN_PHASES`/`KNOWN_BLOCK_IDS`), pas dans l'agent.

---

## 7. Structured output avec récupération

Texte libre = exception, JSON/Pydantic = norme (corpus `_chatgpt-source.md`). Deux chemins selon la version Python.

### 7a. [Python 3.11] `create_agent(response_format=...)` + `handle_errors`

`response_format` peuple `result["structured_response"]`. Trois stratégies : **`ProviderStrategy`** (API native du provider — la plus fiable, pas d'appel-tool en plus ; `strict=True` requiert LangChain ≥ 1.2) ; **`ToolStrategy`** (schéma → tool, portable mais +1 invocation) ; **`AutoStrategy`** (par défaut quand on passe le schéma directement : natif si supporté, sinon tool). En cas d'échec de validation, l'agent **réessaie automatiquement** avec le feedback d'erreur (corpus `langchain-agents-create-agent.md` §6).

```python
# PYTHON 3.11 code env ONLY.
# Derives from: langchain-agents-create-agent.md §6 (response_format + handle_errors).
from pydantic import BaseModel, Field
from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy   # or ProviderStrategy, AutoStrategy

class Answer(BaseModel):
    summary: str = Field(description="One-line summary")
    confidence: float

# AutoStrategy: pass the schema directly. Force ProviderStrategy for reliability on supporting models,
# ToolStrategy for portability + retry control:
agent = create_agent(
    model=llm,
    tools=tools,
    response_format=ToolStrategy(Answer, handle_errors="Return valid JSON for the Answer schema."),
)
out = agent.invoke({"messages": [{"role": "user", "content": "..."}]})
out["structured_response"]      # -> Answer instance (validated)
```

`handle_errors` accepte `True` (message par défaut), une str, un type d'exception, un tuple de types, un callable `e -> message`, ou `False` (lève tout). **Caveat cross-model vérifié :** `tools` + `response_format` ne se comporte pas identiquement partout (issues ouvertes sur certains Gemini 3, friction 1.0.x) — **tester votre modèle exact** (sources : https://github.com/langchain-ai/langchain/issues/34463 ; https://forum.langchain.com/t/create-agent-toolstrategy-tools-structured-output-not-working-across-models-langchain-1-0-2/2293).

### 7b. [Python 3.9] JSON natif → fallback prompt → parse tolérant (récupération à la main)

Sans LangChain, on rejoue `ProviderStrategy` vs `ToolStrategy` manuellement : **2 tentatives** (mode JSON natif, puis prompt-only), parse tolérant aux fences/objets imbriqués, **validation/dégradation contre le profil** (corpus `owismind-project-patterns.md` §1 UNDERSTAND, `_call_json_llm` / `_safe_json_parse`).

```python
# PYTHON 3.9 (stdlib + dataiku only).
# Derives from: owismind-project-patterns.md §1 (_call_json_llm 2-attempt + _safe_json_parse).
import json, re

def call_json_llm(project, llm_id, system_prompt, user_q, schema):
    """2 attempts: native JSON mode, then prompt-only fallback. Returns a dict or {}."""
    # Attempt 1: provider-native structured output (if the Mesh model supports it).
    try:
        c = project.get_llm(llm_id).new_completion()
        c.with_message(system_prompt, role="system")
        c.with_message(user_q)
        c.with_json_output(schema=schema)                  # native JSON mode (ProviderStrategy-equivalent)
        return safe_json_parse(c.execute().text)
    except Exception:
        pass
    # Attempt 2: prompt-only fallback (ToolStrategy-equivalent: ask for JSON, parse leniently).
    c = project.get_llm(llm_id).new_completion()
    c.with_message(system_prompt + "\nReturn ONLY a JSON object matching the schema.", role="system")
    c.with_message(user_q)
    return safe_json_parse(c.execute().text)

def safe_json_parse(text):
    """Tolerant: strips code fences, extracts the first balanced {...}. Returns {} on failure (honest, never invented)."""
    if not text:
        return {}
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, flags=re.DOTALL)    # embedded object
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return {}
        return {}

# RECOVERY = validate/degrade against the profile, NOT against hardcoded business values:
u = validate_understanding(call_json_llm(...), profile)    # unknown intent -> "custom", missing axis -> "custom", etc.
```

**La vraie récupération est la dégradation déterministe** (`validate_understanding`), pas seulement le re-prompt : intent hors `KNOWN_INTENTS` → `"custom"` ; `breakdown`/`top_n` sans axe résoluble → `"custom"` ; `compare_scenarios` avec **un** scénario → préfixer le scénario par défaut **lu du profil** (généralise « gap vs budget » → ACTUALS-vs-BUDGET, **zéro hardcoding**). Absence/échec → JSON vide honnête, jamais une valeur fabriquée (corpus §1, P3).

---

## 8. Récap décisionnel des patterns

| Besoin | Python | Pattern | §  |
|---|---|---|---|
| Boucle modèle+tools rapide | 3.11 | `DKUChatModel` + `create_agent` | §1 |
| Tool gouvernable + sûr au rejeu | 3.11 | `ToolRuntime` + idempotence (UPSERT par clé) | §2 |
| Topologie explicite, parallélisme | 3.11 | `StateGraph` + `Send` + reducer | §3 |
| Appeler agent/tool côté backend | 3.9 | `get_llm().execute_streamed()` / `get_agent_tool().run()` | §4 |
| Streamer vers le navigateur | 3.9 | polling-via-thread (`/start`/`/poll`/`/stop`) | §5 |
| Pipeline NL→résultat déterministe | 3.9 ou 3.11 | UNDERSTAND→RESOLVE→COMPOSE→QUERY→RENDER | §6 |
| Sortie structurée fiable | 3.11 | `response_format` + `handle_errors` | §7a |
| Sortie structurée sans LangChain | 3.9 | 2 tentatives JSON + parse tolérant + dégradation profil | §7b |

> **Fil rouge des 8 sections :** le déterminisme est le défaut, le LLM est l'exception ; toute sortie LLM est **validée/dégradée** contre une source de vérité (profil, value index) ou **vérifiée chiffre par chiffre** avant affichage. Et toujours : **3.9 = pas de langchain**, **3.11 = langchain/langgraph OK** (corpus `owismind-project-patterns.md` §10 ; correction utilisateur autoritaire).
