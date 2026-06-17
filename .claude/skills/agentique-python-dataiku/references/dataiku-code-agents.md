# Dataiku DSS : LLM Mesh, agents visuels/code, tools managés & le double chemin Python

> À jour : juin 2026 (Dataiku DSS 14.x — 14.0 = juin 2025 … 14.6.2 = 11 juin 2026 ; LangChain 1.x / LangGraph 1.x). Référence du skill `agentique-python-dataiku` — parent : `SKILL.md`. Pour le framework pur, voir `references/langchain-v1.md`, `references/langgraph-v1.md`, `references/orchestration-multi-agents.md`.

---

## 0. Modèle mental : le LLM Mesh comme passerelle gouvernée

Le **LLM Mesh** est le backbone GenAI de DSS : une abstraction unique et gouvernée au-dessus de tous les providers (OpenAI, Anthropic, Azure AI Foundry, AWS Bedrock, Google Vertex, Databricks, Snowflake Cortex, Hugging Face self-hosted, …). Toute capacité GenAI de DSS — Prompt Studio, prompt recipes, RAG, agents, Answers, Agent Connect, l'API Python — consomme les modèles *à travers* le Mesh, jamais via les SDK vendeurs. On y gagne, transversalement : permissions centralisées, caching, suivi de coût, rate limiting, guardrails, audit. (sources : https://doc.dataiku.com/dss/latest/generative-ai/introduction.html · https://doc.dataiku.com/dss/latest/generative-ai/llm-connections.html)

L'idée architecturale décisive pour qui construit des agents : **un agent DSS est lui-même un citoyen de première classe du Mesh**, exposé comme un *« Virtual LLM »* et consommé avec **la même completion API** qu'un modèle de base. Un Code Agent que vous écrivez est donc appelable depuis Prompt Studio, les prompt recipes, Answers, Agent Connect, l'API Python ou des clients distants — audit/guardrails appliqués uniformément. (source : https://doc.dataiku.com/dss/latest/agents/introduction.html) Le corpus et la source ChatGPT concordent pleinement sur ce point ; c'est le pivot du raisonnement entreprise.

Capacités natives du Mesh utiles à l'agent builder : completions, **embeddings**, **multimodal** (image inline), **streaming**, requêtes via les bridges LangChain, et une **OpenAI-compatible API** consommable avec le client Python OpenAI standard (utile pour brancher un outillage tiers tout en restant dans la gouvernance). (source ChatGPT, à corroborer page LLM Mesh ; cohérent avec https://developer.dataiku.com/latest/concepts-and-examples/llm-mesh.html)

---

## 1. ⚠️ Le double chemin Python (fait dur — à rappeler partout où la version compte)

L'instance Dataiku dispose de **DEUX code environments : Python 3.9 ET Python 3.11**. La règle qui en découle est non négociable :

| Contexte | Python | LangChain / LangGraph | Comment appeler le Mesh |
|---|---|---|---|
| **Code Agent** avec code env 3.11 (≥ 3.10) | 3.11 | **OK** — `import langchain` / `langgraph` autorisé | bridges (`as_langchain_chat_model`, `bind_tools`) **ou** API native |
| **Backend webapp OWIsMind** (Flask) | **3.9.23** | **INTERDIT** — LangChain/LangGraph v1 exigent ≥ 3.10 | **stdlib + `dataiku` uniquement**, API native Mesh/agents/tools |

- LangChain/LangGraph v1 **requièrent Python ≥ 3.10** → ils ne tournent **que** dans un code env 3.11. Un Code Agent auquel on assigne un code env 3.11 **peut** importer langchain/langgraph.
- Le backend webapp tourne en **3.9.23** → en tout contexte 3.9 : **stdlib-only, AUCUN import langchain**, on appelle LLM Mesh / agents / tools via les API Dataiku natives directement.
- **Ne JAMAIS recommander d'importer langchain dans un contexte 3.9.** Toujours présenter **les deux chemins** quand c'est pertinent.

Conséquence pratique vécue dans OWIsMind : les Code Agents du projet (orchestrateur, Dataset Expert, SalesDrive) sont écrits **stdlib + `dataiku` seulement**, sans dépendance LangChain, parce qu'ils sont *collés tels quels* dans DSS et doivent rester portables d'un env à l'autre — voir `references/orchestration-multi-agents.md` et §5 ici. Le 3.9 du backend ne contraint **pas** le code env attaché à un Code Agent ; ce sont deux périmètres distincts. (sources : https://doc.dataiku.com/dss/latest/generative-ai/agents/code-agents.html · corpus OWIsMind L006/CLAUDE.md rule 8)

---

## 2. Taxonomie des agents DSS

L'agent est *« un système motorisé par des modèles GenAI capable d'utiliser des tools pour interpréter/traiter de la donnée, décider et agir »* — le LLM est un « cerveau » central qui appelle des **tools** pour faire le travail (et doit donc supporter le **tool calling**). (source : https://doc.dataiku.com/dss/latest/agents/introduction.html)

| Type | Code | Modèle de contrôle | Quand l'utiliser |
|---|---|---|---|
| **Simple Visual Agent** | Non | Le LLM choisit seul les tools depuis leurs descriptions, appelle, synthétise | Assistant single-tool monté vite ; non-développeurs |
| **Structured Visual Agent** | Low-code (blocs Python) | **Blocs séquentiels** déterministes (router, Python, tool, LLM) | Flux de contrôle déterministe entre étapes, mais scaffolding visuel (14.0+) |
| **Code Agent** | Python complet | Vous écrivez tout (LangChain/LangGraph **ou** raw) ; tools managés ou vôtres | Contrôle maximal : orchestration, prompting, streaming, routing multi-agent |
| **Custom Agent (plugin)** | Plugin | Un *type* d'agent réutilisable packagé | Vous livrez un agent métier configurable en UI par d'autres |
| (consommation) **Agents tiers / externes** | — | DSS appelle des agents Snowflake Cortex, Databricks, Bedrock, Vertex, ou via A2A | Réutiliser des agents construits hors DSS (14.0+) |

Chaque agent — quel que soit le type — devient un **Virtual LLM réutilisable dans le Mesh**. OWIsMind est sur la ligne **Code Agent** (`agent:MODpGFcC`, `agent:AKQaQ0Am`), pilotée par un orchestrateur maison, avec le tool managé **Semantic Model Query** (`v4oqA6R`) pour le NL2SQL.

Aide à la décision « quel niveau » :
- Assistant rapide sur quelques tools, no-code → **Simple Visual Agent**.
- Étapes déterministes/guardrails entre appels LLM, mais visuel → **Structured Visual Agent**.
- Contrôle total orchestration/prompting/streaming/multi-agent → **Code Agent** ← OWIsMind.
- NL→SQL sur données gouvernées → **Semantic Model + Semantic Model Query tool** (mode Agent), pas le legacy SQL Q&A (§6).

---

## 3. Contrat d'authoring d'un Code Agent

Un Code Agent est une classe Python implémentant le contrat de completion LLM ; DSS l'emballe en Virtual LLM.

### 3.1 Prérequis & création
- **Code env Python ≥ 3.10** requis (donc le code env **3.11**, jamais le 3.9 — §1). (source : https://doc.dataiku.com/dss/latest/generative-ai/agents/code-agents.html)
- Création depuis le Flow : **+ Other > Generative AI > Code Agent**. DSS génère des starters (tools embarqués, tools de project-lib, custom tools). Le starter est **volontairement incomplet** : remplacer `REPLACE_WITH_YOUR_CONNECTION_NAME` et choisir le code env dans Settings. (source : https://developer.dataiku.com/latest/tutorials/genai/agents-and-tools/code-agent/index.html)

### 3.2 La classe de base et le contrat synchrone `process()`
La base est `from dataiku.llm.python import BaseLLM`, qui déclare `process` + `aprocess` + `process_stream` + `aprocess_stream`. (CONFIRMÉ — recency file §4.3)

```python
from dataiku.llm.python import BaseLLM

class MyLLM(BaseLLM):
    def process(self, query, settings, trace):           # SingleCompletionQuery, CompletionSettings, SpanBuilder
        last = query["messages"][-1]["content"]          # le tour courant = DERNIER message
        # ... orchestrer (LLM + tools) ...
        return {                                          # CompletionResponse = dict littéral
            "text": resp_text,                           # SEUL champ requis
            "promptTokens": 46,                           # optionnels
            "completionTokens": 10,
            "estimatedCost": 0.13,
            "toolCalls": [],
        }
```
(sources : https://doc.dataiku.com/dss/latest/generative-ai/agents/code-agents.html · https://developer.dataiku.com/latest/concepts-and-examples/agents.html · recency §4.3)

**Paramètres de `process(self, query, settings, trace)` :**
- **`query`** (`SingleCompletionQuery`, dict-like) — `query["messages"]` (liste `{"role","content"}`) + `query["context"]`. Le tour courant est `query["messages"][-1]["content"]` ; filtrer les tours vides via `[m for m in query["messages"] if m.get("content")]`. Dans le pattern OWIsMind, les messages `role=="system"` portent le **contexte injecté par l'orchestrateur**.
- **`settings`** (`CompletionSettings`) — réglages de completion du caller (temperature, max tokens…) à forwarder à votre appel LLM interne.
- **`trace`** (`SpanBuilder`) — handle d'observabilité ; spans imbriqués via `trace.subspan("label")`, porte `inputs`/`outputs`/`attributes`, supporte `to_dict()` et `append_trace()` pour composer une trace de sous-agent. (source : https://developer.dataiku.com/latest/concepts-and-examples/agents.html)

**Valeur de retour :** dict contenant **au moins `"text"`** (oublier `"text"` casse les consumers). Extras non streamés → `response.artifacts` ; sources → `response.additionalInformation.sources`.

### 3.3 Appeler le Mesh depuis l'agent (API native — chemin 3.9 ET 3.11)
```python
import dataiku
llm = dataiku.api_client().get_default_project().get_llm(LLM_ID)   # base model OU "agent:XXXX"
resp = (llm.new_completion()
          .with_message("system message", "system")                # role = 2e positionnel
          .with_message(prompt)                                     # role défaut = user
          .execute())
resp_text = resp.text
```
`with_message(content, role)` accepte le role en 2e positionnel **ou** en keyword `role="system"` (les deux marchent). C'est le **seul chemin valide en 3.9**. (sources : https://doc.dataiku.com/dss/latest/generative-ai/agents/code-agents.html · https://developer.dataiku.com/latest/concepts-and-examples/llm-mesh.html)

### 3.4 Streaming — `process_stream()` (contrat chat UX)
`BaseLLM` déclare les hooks sync et async :
```python
def process_stream(self, query, settings, trace):     # -> Iterator[StreamCompletionResponse]
    for delta in ...:
        yield {"chunk": {"text": delta}}              # delta texte

async def aprocess_stream(self, query, settings, trace):  # -> AsyncIterator[...]
    ...
```
(source : https://developer.dataiku.com/latest/concepts-and-examples/agents.html)

- **Format chunk texte** : `{"chunk": {"text": content}}`. En enrobant un agent LangChain/LangGraph streamé, on itère ses événements et on émet un `{"chunk": {"text": …}}` par token. Les chunks de tool-call peuvent arriver **partiels**, avec un champ **`index`** pour reconstruire l'appel complet.
- En mode streamé, **les sources arrivent dans le footer** (avec un `finishReason`) ; en non-streamé elles sont dans `response.additionalInformation.sources` / `response.artifacts`.
- **Bonne pratique : implémenter les deux** — `process()` pour la correction batch/éval, `process_stream()` pour la chat UI.

> **Réalité transport OWIsMind (à graver).** Le SSE est **abandonné** : le proxy interne DSS *bufferise* les longs streams HTTP, donc **le texte de réponse arrive en un seul bloc à la fin**. La webapp utilise du **polling-via-thread** (`/chat/start` → `/chat/poll` ~500 ms). Le signal exploitable en direct n'est pas le token streaming, ce sont les **événements** émis par l'agent. Concevoir les agents pour émettre des *events* fins (liveness) plutôt que du token streaming des internals de tools. (corpus OWIsMind L019 · GUIDE §5)

### 3.5 Chunk « event » (extension OWIsMind, au-dessus du contrat)
Au-delà du chunk texte, le pattern OWIsMind ajoute un second type de chunk qui pilote la timeline de la webapp :
```python
yield {"chunk": {"type": "event", "eventKind": KIND, "eventData": {"label": "...", "stepIndex": i}}}
```
Kinds figés (jamais renommés, on ajoute seulement) : `START, PLANNING, PLAN_READY, DIRECT_ANSWER, CALLING_AGENT, AGENT_DONE, RUNNING_TOOL, TOOL_DONE, WRITING_ANSWER, DONE, ERROR, SUB_AGENT_*`. Les labels humains (langue de l'user) sont injectés à l'exécution dans `eventData["label"]`. (corpus OWIsMind §0/§5)

### 3.6 Appeler un agent DEPUIS du code (orchestrateur → sous-agent) — snippet validé DSS
```python
completion = project.get_llm(cfg["agent_id"]).new_completion()    # "agent:AKQaQ0Am"
if cfg["pass_context"]:                                           # contexte conversationnel opt-in
    completion.with_message(context_msg, role="system")
completion.with_message(step["instruction"])
for chunk in completion.execute_streamed():
    data = getattr(chunk, "data", {}) or {}
    if _is_footer(chunk, data):       # le footer FINAL porte toute la trace
        sub_trace = data.get("trace"); continue
    ctype = data.get("type") or getattr(chunk, "type", None)
    if ctype == "event":              ...   # relay ou capture
    elif ctype in ("content", "text"): answer_parts.append(data.get("text", ""))
```
Le **footer** se reconnaît par `data.get("type") == "footer"` OU, quand le SDK l'expose, `isinstance(chunk, DSSLLMStreamedCompletionFooter)` — import **gardé** car les builds SDK diffèrent (certains émettent le footer sans champ `type`). `footer.trace` est le **seul** endroit pour récupérer l'**usage** (`usageMetadata`) et les spans **SQL générée**. (corpus OWIsMind §0 · `docs/cadrage/code_samples_dataiku.md:123-167`)

### 3.7 Tools définis dans un Code Agent (style LangChain — chemin 3.11 uniquement)
```python
from langchain_core.tools import tool
from langchain_core.messages import ToolMessage

@tool
def get_weather(city: str) -> str:
    """Return the current weather for a city."""   # docstring = description vue par le LLM ; type hints = schéma
    return f"It is sunny in {city}"
```
Trois patterns de sourcing : **embedded** (`@tool` dans le fichier agent), **project library** (importer depuis la lib projet → testable/réutilisable), **Dataiku managed tools** (cf. §4). La boucle raw classique : `bind_tools`, invoquer, inspecter `ai_msg.tool_calls`, exécuter chaque tool, append `ToolMessage(content=…, tool_call_id=…)`, ré-invoquer jusqu'à plus d'appels, retourner `{"text": final.content}`. (source : https://developer.dataiku.com/latest/tutorials/genai/agents-and-tools/code-agent/index.html)

> Rappel §1 : tout le bloc 3.7 est **interdit en code env 3.9**. En 3.9, on appelle les tools via `tool.run({...})` (API native, §4.2).

### 3.8 Tracing & observabilité
```python
with trace.subspan("Invoke the LLM") as sp:
    sp.attributes["messages"] = str(messages)
    ai_msg = llm.invoke(messages)
```
Pour un agent LangChain (3.11), brancher le pont `LangchainToDKUTracer(dku_trace=trace)` en `config={"callbacks": [tracer]}` pour que les runs LangChain alimentent la trace DSS. Le Trace Explorer rend la trace JSON hiérarchique ; compatibilité bidirectionnelle LangChain/LangSmith documentée. Cette instrumentation alimente Agent Logging (14.5), Agent Review et Agent Evaluation (14.3+). (sources : https://developer.dataiku.com/latest/concepts-and-examples/agents.html · ChatGPT obs.) Détail Evidence/usage OWIsMind → `references/orchestration-multi-agents.md`.

### 3.9 Human-in-the-loop / validation de tool (approval gates)
Quand un agent doit obtenir une approbation avant d'exécuter un tool, la réponse porte un tableau **`toolValidationRequests`** ; chaque entrée : `id` (obligatoire), `toolCall` (`function.name` + `function.arguments` JSON), `allowEditingInputs` (bool). Reprise après approbation : `completion.with_tool_validation_response(tvreq["id"], validated=True)`. HITL pour Visual Agents livré en **14.0.0** ; trajectoire conversationnelle + HITL améliorés en **14.3.0**. (source : https://developer.dataiku.com/latest/concepts-and-examples/agents.html · release notes 14)

### 3.10 Le bridge DKUChatModel (⚠️ chemin d'import NON VÉRIFIÉ)
La source ChatGPT propose, pour amorcer LangChain dans un Code Agent, un modèle du Mesh exposé comme chat model LangChain via `DKUChatModel` :
```python
# ⚠️ import path UNVERIFIED — confirmer en DSS avant usage (dir(dataiku.langchain...) / doc 14.x)
import dataiku
from dataiku.langchain.dku_llm import DKUChatModel     # NON CONFIRMÉ par le corpus
from langchain.agents import create_agent              # v1 : create_agent (PAS create_react_agent)

llm = DKUChatModel(llm_id="YOUR_LLM_ID", temperature=0)
agent = create_agent(model=llm, tools=[], system_prompt="...")
```
**Statut : UNVERIFIED.** Le corpus n'atteste pas `from dataiku.langchain.dku_llm import DKUChatModel`. Le chemin **confirmé** pour obtenir un chat model LangChain depuis le Mesh est la méthode bridge sur l'objet LLM : `llm.as_langchain_chat_model()` (§4.4). **Préférer `as_langchain_chat_model()`** ; ne traiter `DKUChatModel` qu'après vérification runtime (`dir()` du module). Note v1 : `create_agent` (de `langchain.agents`) remplace `langgraph.prebuilt.create_react_agent`, **déprécié** en LangGraph v1 (voir `references/langchain-v1.md`).

---

## 4. Tools managés & l'API `run()`

Les tools « décrivent leurs inputs attendus et exécutent une tâche précise », avec sécurité, audit, config visuelle. Tools managés livrés : Knowledge Bank (RAG), **Dataset Lookup**, **ML model prediction**, **Send email**, **Web search**, **Semantic Model Query** (NL2SQL), **SQL Question Answering** (legacy, superseded), tools **MCP** (local/remote). On peut aussi écrire des **Custom Python tools** ou convertir tout tool DSS en `StructuredTool` LangChain. (sources : https://doc.dataiku.com/dss/latest/agents/tools/using-tools.html · introduction.html)

### 4.1 Contrat d'un Custom Python tool
```python
from dataiku.llm.agent_tools import BaseAgentTool

class MyTool(BaseAgentTool):
    def set_config(self, config, plugin_config):
        self.config = config; self.plugin_config = plugin_config

    def get_descriptor(self, tool):
        return {
            "description": "Tool description explaining functionality",     # vu par le LLM
            "inputSchema": {                                               # JSON Schema
                "type": "object",
                "properties": {"parameter_name": {"type": "string", "description": "..."}},
            },
        }

    def invoke(self, input, trace):
        args = input["input"]            # les arguments du LLM vivent sous "input"
        return {"output": "result_string"}   # convention : clé "output"
```
**`get_descriptor`** (`description` + `inputSchema`) est ce que le LLM lit pour décider d'appeler — **traitez-le comme du prompt engineering** (descriptions précises, enums, required). Un `context` optionnel est passé hors-bande (non exposé au LLM). (source : https://developer.dataiku.com/latest/tutorials/genai/agents-and-tools/custom-python-tool/index.html)

### 4.2 Appeler n'importe quel tool : `run()` (chemin 3.9 ET 3.11)
```python
import dataiku
project = dataiku.api_client().get_default_project()
tool = project.get_agent_tool("my-tool-1")        # ou un id 'v4oqA6R'
result = tool.run({"prompt": "Do you know Dataiku?"})
result["output"]
```
Signature complète :
```python
DSSAgentTool.run(input, context=None, subtool_name=None, memory_fragment=None,
                 tool_validation_responses=None, tool_validation_requests=None)
```
- **`input`** — arguments typés (doivent matcher `inputSchema`).
- **`context`** — JSON **hors-bande** non exposé au LLM → idéal pour tenant id, filtres row-level, secrets. **Ne jamais mettre secrets/filtres dans `input`** (le LLM peut les voir/altérer).
- **`subtool_name`** — choisir un sous-tool (ex. un serveur MCP qui expose plusieurs tools).

Dataset Lookup — filtres structurés (verbatim) : `tool.run({"filter": {"operator": "EQUALS", "column": "company_name", "value": "Dataiku"}})` → `output["output"]["rows"]`. Opérateurs : `EQUALS, NOT_EQUALS, GREATER_THAN, LESS_THAN, DEFINED, NOT_DEFINED, CONTAINS, MATCHES` (regex) + combinateurs `AND`/`OR`. (sources : https://developer.dataiku.com/latest/api-reference/python/agents.html · https://doc.dataiku.com/dss/latest/agents/tools/using-tools.html)

> **Pattern OWIsMind (validé DSS, L047).** L'agent appelle le tool via `get_agent_tool(id).run({...})` et lit **SQL + rows depuis la valeur de retour** (pas en devinant des clés de trace) → capture déterministe pour l'Evidence. Résolution de tool gardée : valider l'id via `get_descriptor()`, sinon name-match via `list_agent_tools()` (couvre un tool recréé dont l'id a changé). La **clé d'input est auto-détectée** depuis `inputSchema` (clé réelle observée : `question`).

### 4.3 Pont vers un `StructuredTool` LangChain (chemin 3.11)
```python
lctool = tool.as_langchain_structured_tool(context=None)
lctool.invoke({"filter": {"operator": "EQUALS", "column": "company_name", "value": "Dataiku"}})
llm_with_tools = llm.bind_tools([lctool])     # boucle agentique LangChain en gardant la gouvernance Mesh
```
C'est le bridge qui réutilise les tools managés DSS dans une orchestration LangChain/LangGraph arbitraire. **Interdit en 3.9** → y rester en `tool.run()`. (source : https://doc.dataiku.com/dss/latest/agents/tools/using-tools.html)

### 4.4 Bridges Mesh ↔ LangChain (chemin 3.11)
```python
langchain_llm  = llm.as_langchain_llm()           # interface LLM
langchain_chat = llm.as_langchain_chat_model()    # interface chat — à utiliser pour tool calling / agents
```
Garde votre code LangChain provider-agnostique **et** dans la gouvernance Mesh (coût/audit/guardrails). (source : https://developer.dataiku.com/latest/concepts-and-examples/llm-mesh.html)

### 4.5 Inspecter un tool
`tool.get_descriptor()` → `{name, description, inputSchema}` — à utiliser à l'orchestration pour énumérer/valider les capacités.

---

## 5. Semantic Models & NL2SQL — « le semantic model garde le SQL »

### 5.1 Ce qu'est un Semantic Model
*« Une fondation de contexte métier entre les datasets structurés et les LLM qui les interrogent »*, qui traduit le langage naturel en SQL précis et exécutable. C'est le foyer durable et gouvernable du sens métier dont le NL2SQL a besoin. Composants : **Entities** (tables ↔ concepts métier, avec filtres — ex. filtre « Actual Revenue Only »), **Attributes** (mappés aux colonnes : expression SQL, type, description), **Glossary** (termes métier : nom, description, **synonymes** — là où l'on corrige un synonyme pointant le mauvais produit). (sources : https://doc.dataiku.com/dss/latest/semantic-models/index.html · https://doc.dataiku.com/dss/latest/semantic-models/create-and-manage.html)

Introduits en **14.4.0 (9 février 2026)**. (CONFIRMÉ — recency §4.1)

### 5.2 Semantic Model Query tool (le tool NL2SQL)
*« Tool qui exploite un Semantic Model pour traduire des requêtes en langage naturel en SQL, et fournit des réponses fondées sur l'exécution du SQL. »* Il **supplante en grande partie** le legacy SQL Question Answering tool. Étant un agent tool normal : `tool.run({...})` + `as_langchain_structured_tool()`. (sources : https://doc.dataiku.com/dss/latest/agents/tools/semantic-model-query.html · sql-question-answering.html)

### 5.3 Config scriptable du Semantic Model — ⚠️ NON VÉRIFIÉ (project-internal)
La mémoire OWIsMind affirme un point d'entrée `project.get_semantic_model('2O2KcHw')` retournant un objet avec `get_raw()` / `save()` / `versions` (pour versionner le JSON au repo et corriger descriptions/filtres/synonymes par code). **Statut : UNVERIFIED.** Le client Python expose bien les classes `DSSSemanticModel` / `DSSSemanticModelListItem` / `DSSSemanticModelVersion` / `DSSSemanticModelVersionSettings` (`dataikuapi.dss.semantic_model`), et le pattern standard DSS `get_settings()` → `get_raw()` (référence live mutable) → `save()` est plausible. **Mais** la méthode `project.get_semantic_model(...)` **ne figure pas** dans la référence publique de la classe project (le mot « semantic » est absent de `projects.html`). **À traiter comme interne au projet : confirmer en runtime DSS (`dir(project)` / introspection de `dataikuapi`) avant de s'en servir — ne pas citer comme fait documenté.** (recency §4.2)

### 5.4 Décision NL2SQL d'OWIsMind (le levier réel)
Garder l'**ownership du SQL dans le Semantic Model Query tool** (mode Agent) ; un **Dataset Expert** générique sert de tour de contrôle UNDERSTAND → RESOLVE → COMPOSE → QUERY → RENDER. Le levier de précision NL2SQL, ce sont les **artefacts du Semantic Model** (entities/attributes/glossary/filters), **jamais des valeurs métier en dur dans le code** (règle P3). Deux corollaires durement gagnés (L052) :
- **Composition de la question** : *la QUESTION USER MÈNE* (verbatim en tête) + intent hint + **valeurs groupées par colonne en `IN`** (jamais `Product = A AND Product = B`, qui rend 0 ligne) + règle énumération → OR/une-ligne-par-item + note de destination (résultat tabulaire avec alias, jamais une réponse en prose).
- **Extraction du retour en mode Agent** : la sortie est un transcript multi-messages (raisonnement → exploration de schéma → probes → réponse finale). Prendre la réponse = **priorité de clés puis DERNIÈRE occurrence** (jamais la première = préambule). Détails : `references/prompting-et-determinisme.md` et `references/orchestration-multi-agents.md`.

---

## 6. MCP (Model Context Protocol)

DSS est **consumer** (utiliser des tools MCP externes dans des agents) **et publisher** (exposer des agents/fonctions DSS comme tools MCP).

| Forme | Version | Notes |
|---|---|---|
| **Local MCP** tool | **14.2.0** (form agent-tool 14.2.1+) | lance un serveur MCP local, expose sélectivement ses tools |
| **Remote MCP** tool / connection | **14.3.0** | connexion à un serveur MCP distant ; **tous les tools désactivés par défaut** — activer un par un ; auth souvent **OAuth** (discovery, dynamic client registration, refresh rotation) |
| Remote MCP multi-type + **Embedded Resources** | **14.6.2** (11 juin 2026) | — |
| Publier des agents DSS comme **MCP Tools** | 14.1/14.2 | via Code Studios / Webapps |

(CONFIRMÉ versions — recency §4.1 ; sources : https://doc.dataiku.com/dss/latest/agents/tools/local-mcp.html · remote-mcp.html · https://developer.dataiku.com/latest/tutorials/genai/agents-and-tools/mcp/index.html) **Anti-pattern :** laisser tous les tools MCP activés — chaque tool en trop dégrade le routing et élargit la surface d'attaque.

---

## 7. Exposition & consommation des agents

- **Virtual LLM (Python)** — `project.get_llm("agent:4agXpWVO").new_completion().with_message("…").execute().text` : API **identique** à un base model (c'est tout l'intérêt).
- **UIs DSS** — Prompt Studio, Prompt recipes, Answers, Agent Connect, LLM Mesh API.
- **A2A server** (agent-to-agent) — DSS expose ses agents à des clients A2A tiers en **JSON-RPC** + **HTTP-SSE**, avec streaming (14.0.0).
- **REST / webapp** — agent emballé en API endpoint (API node) ou webapp (Dash/Flask/Vue). **Forme OWIsMind exactement** : front Vue + backend Flask appelant l'agent via le Mesh.
- **Slack** — interaction sur Slack (14.4.0).

**Answers vs Agent Connect** : *Answers* = chatbot unique sur votre connaissance/donnée (RAG, NL2SQL…) ; *Agent Connect* = **router** multi-agent (un point d'entrée qui dispatche). Quand plusieurs services matchent, Agent Connect **fan-out concurrent via thread pool** puis **combine** les réponses — conceptuellement identique au fan-out parallèle de l'orchestrateur v3 d'OWIsMind (`references/orchestration-multi-agents.md`). (sources : agents/introduction.html · release notes 14 · https://www.dataiku.com/stories/blog/ai-agents-with-dataiku)

---

## 8. Gouvernance du Mesh : guardrails, coût, rate limiting, logging

- **Guardrails (LLM Guard Services)** — screening prompts ET réponses : **PII** (detect/redact), **prompt-injection**, **toxicity**, **topics boundaries**, **bias**, **custom guardrails**. Config aux niveaux **connection / agent / usage-time**. Comme ils sont dans le Mesh, ils s'appliquent **aussi aux agents et tools**. (source : https://doc.dataiku.com/dss/latest/generative-ai/guardrails/index.html)
- **Cost Guard / quotas** — scope par provider/projet/connection/users ; montant en **USD** + période de reset ; **blocage** optionnel au dépassement + **alertes** email ; **Fallback Quota** ; une requête peut matcher plusieurs quotas (tous incrémentés). Customiser les quotas requiert la licence **Advanced LLM Mesh**. Non cost-trackés (mais blocables) : SageMaker, Databricks Mosaic AI, Snowflake Cortex. (source : https://doc.dataiku.com/dss/latest/generative-ai/cost-control.html)
- **Rate limiting** — Administration > Settings > LLM Mesh > Rate Limiting ; par modèle et par provider, en **RPM**. (source : https://doc.dataiku.com/dss/latest/generative-ai/rate-limiting.html)
- **Agent Logging** (14.5.0) — écrit en dataset : input user, réponse finale, tool calls, métadonnées, traces, trajectoires. **Interaction logging** scriptable : `DSSAgentInteractionLoggingSelection.enable(dataset_name)` / `inherit()` / `disable()`, modes `MODE_INHERIT|MODE_EXPLICIT|MODE_NONE`. (source : https://developer.dataiku.com/latest/api-reference/python/agents.html)

> Pour le quota OWIsMind « $50/mois par user » : soit app-side (`webapp_usage_monthly_v1`), soit quotas Mesh filtrés par user/connection (blocage + audit gratuits, mais licence Advanced + config admin).

**Évaluation & review** (utile à connaître) : **Evaluate Agent recipe** (note la réponse finale **et la trajectoire** : tool calls, guardrails) vers un evaluation store (14.3) ; **Agent Review** (cas de test + référence + attentes comportementales, LLM-as-a-judge + feedback humain). **Tool calling avec l'identité de l'user final** possible pour la sécurité row-level. (source ChatGPT obs./gouv., cohérent release notes 14)

---

## 9. Carte des versions DSS 14.x (jalons agent/GenAI)

| Version | Date | Jalons |
|---|---|---|
| 14.0.0 | 2025-06-27 | Visual Agents partout ; **Structured Visual Agents** ; **HITL approval** ; Agent Review ; agents tiers ; reranking RAG ; **A2A server** (JSON-RPC + SSE) |
| 14.1.0 | 2025-08-12 | **Agent Hub** ; MCP commence ; Governance Policies |
| 14.2.0 | 2025-10-17 | MCP complet ; **Local MCP** tool |
| 14.3.0 | 2025-12-11 | **Agent Evaluation** ; Extract Content recipe ; HITL trajectoire ; **Remote MCP** |
| 14.4.0 | 2026-02-09 | **Semantic Models** (majeur) ; **Slack** ; reranking étendu |
| 14.5.0 | 2026-04-14 | **Agent Logging** ; extraction de champs structurés (documents) ; vector stores externes |
| 14.6.0 | 2026-05-25 | SharePoint dans Agent Hub ; pgvector & Snowflake Cortex Search |
| 14.6.2 | 2026-06-11 | Remote MCP multi-type fields ; **Embedded Resources** |

Versions clés CONFIRMÉES (recency §4.1) : Semantic Models **14.4.0**, Local MCP **14.2.0**, extraction de champs structurés **14.5.0**. (source : https://doc.dataiku.com/dss/latest/release_notes/14.html) Vérifier tout flag mineur contre *votre* instance ; les signatures d'API (§3–§5) sont les faits porteurs, pas les dates.

---

## 10. Pièges & anti-patterns (Dataiku-spécifiques)

- **Mauvaise version Python.** Code Agents = **3.10+** (code env 3.11) ; un env 3.9 ne les fait pas tourner. **Ne jamais importer langchain en 3.9** (§1).
- **Lire `messages[0]`** au lieu de `messages[-1]` (tour courant) ; oublier de filtrer les tours vides.
- **Oublier `"text"`** dans le retour de `process()`.
- **Extraire le PREMIER bloc texte** d'une sortie mode-Agent : c'est souvent le préambule — prendre le **DERNIER** avec ordre de priorité de clés (L052).
- **`AND` intra-colonne** pour une énumération → 0 ligne ; grouper par colonne en `IN`/`OR` (L052).
- **Tous les tools MCP activés** : off par défaut, n'activer que le nécessaire.
- **Secrets/filtres dans `input`** : utiliser `context` (hors-bande).
- **Bypass du Mesh** avec les SDK vendeurs : plus de cost tracking/guardrails/audit/quotas.
- **Cost tracking universel supposé** : SageMaker / Databricks Mosaic AI / Snowflake Cortex non trackés.
- **Hardcoder une valeur métier** pour « fixer » une requête : le fix vit dans les artefacts du Semantic Model / descripteurs de tool, pas dans du code à branches (P3).
- **Citer `DKUChatModel` / `project.get_semantic_model` comme acquis** : les deux sont **UNVERIFIED** — préférer `as_langchain_chat_model()` et confirmer la config semantic model en runtime.

---

## 11. Cheat sheet API

```python
import dataiku
project = dataiku.api_client().get_default_project()

# --- Mesh : modèles (3.9 ET 3.11) ---
project.list_llms(purpose=None)                  # purpose="TEXT_EMBEDDING_EXTRACTION" pour les embeddings
llm = project.get_llm("agent:XXXX" | "BASE_MODEL_ID" | "EMBED_ID")
c = llm.new_completion()
c.with_message(content, role="user"|"system"|"assistant")
c.settings["temperature"|"maxOutputTokens"|"topP"|"topK"] = ...
r = c.execute(); r.text; r.success
for chunk in c.execute_streamed(): chunk.data["text"]
mp = c.new_multipart_message(); mp.with_text(...); mp.with_inline_image(bytes); mp.add()
e = llm.new_embeddings(); e.add_text(...); e.execute().get_embeddings()

# --- Bridges LangChain (3.11 SEULEMENT) ---
llm.as_langchain_chat_model(); llm.as_langchain_llm(); llm.bind_tools([lctool])

# --- Tools (3.9 ET 3.11) ---
tool = project.get_agent_tool("id")
tool.run(input, context=None, subtool_name=None, memory_fragment=None,
         tool_validation_responses=None, tool_validation_requests=None)
tool.get_descriptor()                            # {name, description, inputSchema}
tool.as_langchain_structured_tool(context=None)  # 3.11 seulement

# --- Contrat Code Agent ---
from dataiku.llm.python import BaseLLM
class MyLLM(BaseLLM):
    def process(self, query, settings, trace): return {"text": ...}     # query["messages"][-1]["content"]
    def process_stream(self, query, settings, trace): yield {"chunk": {"text": ...}}

# --- Contrat Custom tool ---
from dataiku.llm.agent_tools import BaseAgentTool
class MyTool(BaseAgentTool):
    def set_config(self, config, plugin_config): ...
    def get_descriptor(self, tool): return {"description": ..., "inputSchema": {...}}
    def invoke(self, input, trace): args = input["input"]; return {"output": ...}

# --- Admin agent ---
agent = project.get_agent("id"); agent.get_settings(); agent.wake_up(); agent.status()
```

---

## 12. Sources principales

- LLM Mesh / GenAI : https://doc.dataiku.com/dss/latest/generative-ai/introduction.html · llm-connections.html · https://developer.dataiku.com/latest/concepts-and-examples/llm-mesh.html
- Agents intro/types : https://doc.dataiku.com/dss/latest/agents/introduction.html
- Code Agents : https://doc.dataiku.com/dss/latest/generative-ai/agents/code-agents.html · https://developer.dataiku.com/latest/tutorials/genai/agents-and-tools/code-agent/index.html · https://developer.dataiku.com/latest/concepts-and-examples/agents.html
- Tools : https://doc.dataiku.com/dss/latest/agents/tools/using-tools.html · custom-python-tool · https://developer.dataiku.com/latest/api-reference/python/agents.html
- Semantic Models / NL2SQL : https://doc.dataiku.com/dss/latest/semantic-models/index.html · create-and-manage.html · agents/tools/semantic-model-query.html
- MCP : agents/tools/local-mcp.html · remote-mcp.html · https://developer.dataiku.com/latest/tutorials/genai/agents-and-tools/mcp/index.html
- Guardrails / coût / rate : generative-ai/guardrails/index.html · cost-control.html · rate-limiting.html
- Release notes : https://doc.dataiku.com/dss/latest/release_notes/14.html
- Recency/versions (autoritatif) : `docs/agentic-research/gap-version-recency-recheck-2026.md`
- Ground truth OWIsMind : `docs/agentic-research/owismind-project-patterns.md` (+ `memory/LESSONS.md` L006/L019/L047/L048/L050/L051/L052)
