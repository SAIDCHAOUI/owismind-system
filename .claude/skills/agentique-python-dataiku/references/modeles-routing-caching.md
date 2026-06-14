# Sélection de modèles, routing, fallbacks & prompt caching

> **À jour : juin 2026.** Baseline LangChain 1.x / LangGraph 1.x / Dataiku DSS 14.x. Fiche du skill `agentique-python-dataiku` ; voir `SKILL.md` (parent) pour le cadrage. Réfs croisées : `references/langchain-v1.md` (`init_chat_model`, `create_agent`, middleware), `references/dataiku-code-agents.md` (LLM Mesh, pont `as_langchain_chat_model()`, Code Agents), `references/prompting-et-determinisme.md` (prompts gelés, structured output), `references/eval-tracing-securite-production.md` (suivi tokens/coûts). IDs et tarifs Anthropic : `references/claude-api`.

---

## 0. La couche décision en une phrase

Un agent de prod ne tourne jamais à un seul modèle à un seul prix. **Quatre leviers composables** portent le coût ET la fiabilité ; cette fiche en donne la mécanique en code, **agnostique aux IDs de modèles** (un ID est un *slot*, pas une constante — c'est le sens même de `init_chat_model`).

| Levier | Problème résolu | Mécanisme LangChain |
|---|---|---|
| **Sélection** | Init provider-agnostique en une ligne ; changer de provider sans réécrire | `init_chat_model("provider:model")` |
| **Configuration runtime** | Choisir modèle/params par requête sans ré-instancier | `configurable_fields` + `config["configurable"]` |
| **Routing / tiering** | Modèle cheap pour le facile, cher pour le dur | LLM-as-router (code) ou `wrap_model_call` + `request.override(model=…)` |
| **Fallbacks & retry** | Survivre aux rate-limits, pannes, refus | `with_retry()`, `with_fallbacks()`, `ModelFallbackMiddleware` |
| **Prompt caching** | Ne pas repayer les tokens du même préfixe | Provider-natif (`cache_control`, préfixe auto, context cache) → surfacé via `usage_metadata` |

Structure canonique coût-conscient (corpus ↔ ChatGPT concordent — pattern « Routing » d'Anthropic) : **un petit modèle cheap classe/extrait → un gros modèle cher synthétise.** Tout le reste est la mécanique pour bâtir cela en code.

---

## 0bis. Contrainte Python — DOUBLE CHEMIN (fait dur, non négociable)

L'instance Dataiku a **deux code environments : Python 3.9 ET Python 3.11**.

| Contexte | Python | Règle pour cette fiche |
|---|---|---|
| **Code env 3.11** (≥ 3.10) | 3.11 | `init_chat_model`, `with_fallbacks`, middleware, `usage_metadata` importables. Un **Code Agent** assigné à un code env 3.11 PEUT `import langchain`. |
| **Backend webapp OWIsMind** | **3.9.23** | **stdlib-only, AUCUN import langchain.** Sélection/routing/fallback/caching à implémenter **à la main** sur les APIs Dataiku natives (LLM Mesh `get_llm`/`new_completion`, `get_agent_tool().run()`). |

LangChain/LangGraph v1 **exigent Python ≥ 3.10**. **Ne jamais recommander d'importer langchain en contexte 3.9.** Dans chaque section ci-dessous où ça compte, les **deux chemins** sont donnés : (A) code env 3.11 = API LangChain ; (B) contexte 3.9 = équivalent natif Dataiku ou Python pur.

> **Dataiku — accès aux modèles.** En DSS, on n'utilise **pas** `init_chat_model` pour atteindre les modèles du Mesh : on passe par l'abstraction Mesh (`project.get_llm(...)` → `.as_langchain_chat_model()`, §5). `init_chat_model` vise les connexions provider **directes** ; il **court-circuite** la gouvernance, l'audit et l'auto-throttling du Mesh.

---

## 1. `init_chat_model` — init en une ligne, configurable au runtime

### 1.1 Init provider-agnostique

Point d'entrée unifié ; infère le package d'intégration depuis le préfixe `provider:` ou le nom nu (source : https://docs.langchain.com/oss/python/langchain/models).

```python
from langchain.chat_models import init_chat_model

model = init_chat_model("anthropic:claude-sonnet-4-6")          # provider explicite (id réel/courant)
model = init_chat_model("gpt-5.5")                              # nom nu → provider inféré — gpt-5.5 NON VÉRIFIÉ
model = init_chat_model("google_genai:gemini-2.5-flash-lite")  # Gemini
```

Matrice d'install (source : https://docs.langchain.com/oss/python/langchain/models) — **NO INSTALL côté agent** : c'est l'admin qui provisionne le code env 3.11.

| Provider | Install | Code |
|---|---|---|
| OpenAI | `langchain[openai]` | `init_chat_model("openai:gpt-5.5")` |
| Anthropic | `langchain[anthropic]` | `init_chat_model("anthropic:claude-sonnet-4-6")` |
| Google Gemini | `langchain[google-genai]` | `init_chat_model("google_genai:gemini-2.5-flash-lite")` |
| Azure OpenAI | `langchain[openai]` | `init_chat_model("azure_openai:gpt-5.5", azure_deployment=…)` |
| AWS Bedrock | `langchain[aws]` | `init_chat_model("…", model_provider="bedrock_converse")` |
| OpenRouter | `langchain-openrouter` (classe dédiée) **ou** `langchain[openai]` | classe dédiée `ChatOpenRouter(...)`, **ou** `ChatOpenAI(model=…, base_url="https://openrouter.ai/api/v1", api_key=…)`. ⚠️ `init_chat_model("auto", model_provider="openrouter")` = **NON VÉRIFIÉ** : `"openrouter"` n'est pas un provider standard inféré/dispatché par `init_chat_model` — confirmer avant usage. |

### 1.2 Kwargs par modèle

```python
model = init_chat_model(
    "claude-sonnet-4-6",
    temperature=0.7, timeout=30, max_tokens=1000,
    max_retries=6,   # défaut selon la doc LangChain courante (NON RE-VÉRIFIÉ — l'historique LangChain a été 2 ; confirmer contre la version installée) ; 10–15 pour un agent long sur réseau instable
)
```
(source : https://docs.langchain.com/oss/python/langchain/models)

### 1.3 Modèles configurables au runtime (`configurable_fields`)

Signature vérifiée (source : https://reference.langchain.com/python/langchain/chat_models/init_chat_model) :

```python
init_chat_model(
    model: str | None = None,
    *,
    model_provider: str | None = None,
    configurable_fields: Literal['any'] | list[str] | tuple[str, ...] | None = None,
    config_prefix: str | None = None,
    **kwargs,
) -> BaseChatModel | _ConfigurableModel
```

**Le gotcha par défaut :**
- `model` **fourni** → `configurable_fields` défaut `None` → modèle **fixe**.
- `model` **absent** → `configurable_fields` défaut `("model", "model_provider")` → modèle **configurable**, on choisit le modèle à l'invocation.

```python
configurable_model = init_chat_model(temperature=0)   # modèle+provider configurables par défaut
configurable_model.invoke("hi", config={"configurable": {"model": "claude-sonnet-4-6"}})
configurable_model.invoke("hi", config={"configurable": {"model": "gpt-5-nano"}})   # gpt-5-nano NON VÉRIFIÉ
```

Rendre **plus** de champs configurables + namespacer via `config_prefix` quand plusieurs modèles configurables coexistent (clé runtime = `config["configurable"]["{config_prefix}_{param}"]`) :

```python
first_model = init_chat_model(
    model="gpt-5.4-mini",   # gpt-5.4-mini NON VÉRIFIÉ
    temperature=0,
    configurable_fields=("model", "model_provider", "temperature", "max_tokens"),
    config_prefix="first",  # → clés first_model, first_temperature, …
)
first_model.invoke("…", config={"configurable": {
    "first_model": "claude-sonnet-4-6", "first_temperature": 0.5, "first_max_tokens": 100,
}})
```

Les bindings `bind_tools` / structured-output passent à travers le swap runtime :

```python
model_with_tools = init_chat_model(temperature=0).bind_tools([GetWeather])
model_with_tools.invoke("weather?", config={"configurable": {"model": "claude-sonnet-4-6"}})
```
(source : https://docs.langchain.com/oss/python/langchain/models)

> **SÉCURITÉ — jamais `configurable_fields="any"` avec une config non fiable.** `"any"` rend `api_key` et `base_url` configurables au runtime → un appelant peut rediriger les requêtes ou exfiltrer la clé. **Toujours énumérer une allowlist explicite** (`("model", "temperature", …)`) si le dict de config peut venir d'une entrée non fiable. C'est le **même périmètre de confiance** que la règle OWIsMind « le front ne choisit jamais table/connexion/agent_id » : le front envoie une **clé logique**, le backend résout (source : https://reference.langchain.com/python/langchain/chat_models/init_chat_model).

**Chemin B (3.9).** Pas de `init_chat_model`. La sélection = `project.get_llm(LLM_ID)` (§5) avec `LLM_ID` résolu **server-side** depuis une clé logique whitelistée — jamais reçu du client. La « configuration runtime » = un dict Python `{clé_logique: LLM_ID}` côté serveur.

---

## 2. Routing & tiering coût-conscient

Deux façons de « choisir le bon modèle par requête » : **routing explicite en code** (on classe, puis on dispatche) et **middleware d'agent** (`wrap_model_call` swappe le modèle dans la boucle).

### 2.1 Pattern A — LLM-as-router en code (classifieur cheap → worker cher)

Structure agnostique de « petit décide, gros fait ». Appel structured-output sur un modèle cheap pour classer, puis dispatch :

```python
from typing import Literal
from pydantic import BaseModel
from langchain.chat_models import init_chat_model

router_model  = init_chat_model("claude-haiku-4-5",  temperature=0)  # cheap, rapide — routing/extraction
worker_simple = init_chat_model("claude-sonnet-4-6")                 # mid — la plupart des requêtes
worker_hard   = init_chat_model("claude-opus-4-8")                   # cher — synthèse/raisonnement

class Route(BaseModel):
    tier: Literal["simple", "hard"]

router = router_model.with_structured_output(Route)

def answer(question: str) -> str:
    route = router.invoke(f"Classify difficulty of: {question}")
    model = worker_hard if route.tier == "hard" else worker_simple
    return model.invoke(question).content
```

C'est le pattern « Routing » d'Anthropic (classer l'entrée, dispatcher vers un handler/prompt spécialisé — source : https://www.anthropic.com/research/building-effective-agents). **Garder le prompt du routeur gelé et petit** → ses propres appels restent cheap ET cacheables (§6).

**Alternative provider-native :** OpenRouter route server-side entre providers — on **perd le contrôle/l'observabilité** (on ne voit ni ne fixe le modèle qui a tourné). Accès via sa classe d'intégration dédiée (`ChatOpenRouter`) ou via `ChatOpenAI(base_url="https://openrouter.ai/api/v1", api_key=…)`. ⚠️ **NON VÉRIFIÉ — confirmer que `init_chat_model` dispatche `model_provider="openrouter"`** : `"openrouter"` n'est pas dans les providers standard que `init_chat_model` infère/route, donc `init_chat_model("auto", model_provider="openrouter")` ne tournera probablement pas tel quel. Préférer de toute façon le routing en code quand l'attribution de coût, la gouvernance ou le déterminisme comptent (toujours, en OWIsMind).

> **OWIsMind — c'est exactement l'orchestrateur.** Le projet route déjà par **domaine métier** avec templates déterministes `CAPABILITY_GAP`/`OUT_OF_SCOPE`, l'orchestrateur ne doit « jamais émettre un fait métier ». Un classifieur Haiku-tier (ou un appel Mesh natif en 3.9) alimentant la **résolution whitelist** clé-logique→`agent_id` *est* le Pattern A. Voir `references/orchestration-multi-agents.md`.

### 2.2 Pattern B — modèle dynamique par requête dans un agent (`wrap_model_call`)

Dans `create_agent`, le hook middleware `wrap_model_call` enveloppe l'appel modèle de bout en bout : il peut appeler le handler **zéro fois** (court-circuit), **une fois** (normal) ou **N fois** (retry), et réécrire la requête via `request.override(...)` (source : https://reference.langchain.com/python/langchain/agents/middleware/wrap_model_call).

```python
from langchain.agents import create_agent
from langchain.agents.middleware import wrap_model_call, ModelRequest, ModelResponse
from langchain.chat_models import init_chat_model

basic_model    = init_chat_model("claude-sonnet-4-6")   # défaut cost-effective
advanced_model = init_chat_model("claude-opus-4-8")     # raisonnement complexe

@wrap_model_call
def dynamic_model_selection(request: ModelRequest, handler) -> ModelResponse:
    """Escalade vers le gros modèle quand la conversation grossit."""
    model = advanced_model if len(request.state["messages"]) > 10 else basic_model
    return handler(request.override(model=model))

agent = create_agent(model=basic_model, tools=tools, middleware=[dynamic_model_selection])
```
(source : https://docs.langchain.com/oss/python/langchain/models)

`request.override()` swappe aussi **tools**, **system_message** / **system_prompt** (les deux existent sur `ModelRequest`), `tool_choice`, `messages`, `response_format`, `model_settings` — renvoie un **nouveau** `ModelRequest` immuable (source : https://reference.langchain.com/python/langchain/agents/middleware/types/ModelRequest/override).

> **Contrainte :** un modèle **déjà** `.bind_tools()`-é est **incompatible avec le structured output** dans le swap `wrap_model_call`. Passer des modèles **non bindés** au middleware si vous utilisez le structured output (source : https://docs.langchain.com/oss/python/langchain/models).

`@dynamic_prompt` est la spécialisation prompt-only de `wrap_model_call` (calcule le system prompt depuis l'état) — voir `references/langchain-v1.md`. Utiliser `@dynamic_prompt` pour ne varier que le prompt, `wrap_model_call` quand on varie aussi modèle/tools.

### 2.3 Routeur built-in pour la sélection d'outils : `LLMToolSelectorMiddleware`

LangChain livre un routeur prod pour le **sous-problème tool-selection** : un LLM rapide choisit les outils pertinents d'un large registre, puis on ne binde que ceux-là au modèle principal — « cheap gate, expensive execute » qui réduit AUSSI le prompt (et **protège le cache**, §6.1).

```python
from langchain.agents.middleware import LLMToolSelectorMiddleware

LLMToolSelectorMiddleware(
    model=None,           # défaut = modèle de l'agent ; passer un modèle CHEAP ici pour le tiering
    system_prompt=None,
    max_tools=None,       # plafonne le nb d'outils bindés
    always_include=None,  # outils qui contournent la sélection
)
```
(source : https://docs.langchain.com/oss/python/langchain/middleware/built-in ; https://reference.langchain.com/python/langchain/agents/middleware)

Pour l'orchestrateur OWIsMind (revenue_expert vs tickets vs hors-sujet), le **Pattern A** (router en code) reste préférable à `LLMToolSelectorMiddleware` : routage par domaine métier + templates déterministes, l'attribution de coût et l'honnêteté priment.

**Chemin B (3.9).** Pas de middleware. Le Pattern A se réimplémente trivialement en Python pur : un appel `new_completion()` cheap renvoie un JSON `{"tier": ...}` (parsé/validé à la main, voir `references/prompting-et-determinisme.md` pour le structured output sans Pydantic), puis `if/else` sur le `LLM_ID`/`agent_id` à invoquer.

---

## 3. Fallbacks & retry — survivre aux rate-limits et pannes

Trois couches de portée croissante : **`with_retry()`** (même modèle, erreurs transitoires) → **`with_fallbacks()`** (changer de modèle/provider) → **`ModelFallbackMiddleware`** (chaîne au niveau agent).

### 3.1 Retry built-in (défaut + tuning)

Les chat models LangChain re-tentent avec **backoff exponentiel** par défaut (sources : https://docs.langchain.com/oss/python/langchain/models ; https://reference.langchain.com/python/langchain-core/runnables/base/Runnable/with_retry) :

- `max_retries` défaut = **6 selon la doc LangChain courante** — **NON RE-VÉRIFIÉ** par le re-check de récence (l'historique LangChain a documenté **2**) ; à confirmer contre la version `langchain-core` installée plutôt que de le tenir pour acquis.
- Re-tente : erreurs réseau, **429 rate limit**, **5xx** serveur. **Pas** les erreurs client (401, 404).
- Agent long sur réseau instable : `max_retries=10–15` + un checkpointer pour préserver la progression.

### 3.2 `with_fallbacks()` — changer de modèle/provider sur échec

```python
from langchain.chat_models import init_chat_model

primary  = init_chat_model("anthropic:claude-opus-4-8", max_retries=0)  # cf. AVERTISSEMENT
fallback = init_chat_model("openai:gpt-5.5")                            # gpt-5.5 NON VÉRIFIÉ

model = primary.with_fallbacks([fallback])
model.invoke("…")   # tente primary ; sur erreur, tente fallback
```
(source : https://python.langchain.com/v0.2/docs/how_to/fallbacks/)

> **INTERACTION CRITIQUE — couper les retries sur le primary avec des fallbacks.** Par défaut le modèle wrappé attrape et re-tente lui-même → le premier wrapper « re-tente sans jamais échouer » → **le fallback ne se déclenche jamais**. Mettre `max_retries=0` sur le primary pour qu'un échec persistant **propage** vers le fallback. Règle : backoff built-in **OU** fallbacks, pas les deux qui se battent (source : https://python.langchain.com/v0.2/docs/how_to/fallbacks/).

Usages prod : **redondance cross-provider** (Anthropic primary → OpenAI fallback) ou **load-balancing entre déploiements** (plusieurs déploiements Azure OpenAI) (source : https://clemenssiebler.com/posts/azure_openai_load_balancing_langchain_with_fallbacks/).

### 3.3 `ModelFallbackMiddleware` — chaîne au niveau agent

Tente les modèles dans l'ordre jusqu'au succès — résilience panne, redondance provider, coût (retomber sur un modèle moins cher) (source : https://reference.langchain.com/python/langchain/agents/middleware/model_fallback/ModelFallbackMiddleware).

```python
from langchain.agents import create_agent
from langchain.agents.middleware import ModelFallbackMiddleware

# Signature: ModelFallbackMiddleware(first_model, *additional_models)
# Chaque entrée = id str OU instance BaseChatModel ; tentés dans l'ordre donné.
fallback = ModelFallbackMiddleware(
    "anthropic:claude-sonnet-4-6",   # 1er fallback quand le primary échoue
    "openai:gpt-5.4-mini",           # fallback suivant — gpt-5.4-mini NON VÉRIFIÉ
)
agent = create_agent(model="anthropic:claude-opus-4-8", tools=tools, middleware=[fallback])
```
(source : https://docs.langchain.com/oss/python/langchain/middleware/built-in)

### 3.4 Fallback Anthropic server-side sur refus **[POST-CUTOFF, 2026]**

Distinct de la machinerie LangChain : l'API Anthropic a un param server-side `fallbacks` pour le cas précis d'un **refus du classifieur de sûreté** (HTTP 200 avec `stop_reason: "refusal"`, fréquent sur `claude-fable-5`). Sur un refus de politique, l'API re-sert la requête sur le fallback **dans le même appel**, avec repricing crédit. Opt-in via header bêta `server-side-fallback-2026-06-01` :

```python
response = client.beta.messages.create(
    model="claude-fable-5", max_tokens=16000,
    betas=["server-side-fallback-2026-06-01"],
    fallbacks=[{"model": "claude-opus-4-8"}],
    messages=[{"role": "user", "content": "…"}],
)
# Inspecter les blocs content type=="fallback" pour voir les points de bascule.
```
(source : claude-api skill, model-migration « Migrating to Claude Fable 5 » — voir `references/claude-api`). **Ce n'est PAS un fallback rate-limit** (les rate-limits/overloads sont renvoyés tels quels, jamais en fallback) : c'est de la **récupération de refus**. À n'utiliser que si vous ciblez Fable 5 ; les fallbacks de fiabilité standards restent à la couche LangChain (§3.2–3.3). Indisponible sur Bedrock/Vertex/Foundry (y utiliser le `BetaRefusalFallbackMiddleware` SDK client-side).

### 3.5 Rate limiter (proactif, pas réactif)

Pour rester **sous** un plafond TPM/RPM plutôt que de re-tenter après 429 :

```python
from langchain_core.rate_limiters import InMemoryRateLimiter
from langchain.chat_models import init_chat_model

rate_limiter = InMemoryRateLimiter(requests_per_second=0.1, check_every_n_seconds=0.1, max_bucket_size=10)
model = init_chat_model("openai:gpt-5.5", rate_limiter=rate_limiter)  # gpt-5.5 NON VÉRIFIÉ
```
Thread-safe et partageable ; limite le **débit de requêtes seulement, pas la taille** (pas de limitation par tokens) (source : https://docs.langchain.com/oss/python/langchain/models). Pour OWIsMind, l'auto-throttling de la connexion Mesh (§5.3) est l'équivalent server-side ; ce rate limiter est l'option client-side des connexions provider directes.

**Chemin B (3.9).** Pas de `with_fallbacks`/middleware. Le fallback = un `try/except` Python pur autour de `llm.new_completion().execute()`, basculant sur un second `LLM_ID` ; le retry = boucle avec `time.sleep` à backoff sur exception transitoire. Le rate-limiting est délégué à l'**auto-throttling de la connexion Mesh** (§5.3) — privilégier celui-ci.

---

## 4. Dataiku LLM Mesh — sélection/abstraction de modèle dans un Code Agent

Le Mesh est la **gateway gouvernée** ; en code on choisit un modèle par **LLM ID** à travers lui, pas via `init_chat_model`. Détail dans `references/dataiku-code-agents.md` ; ici, l'angle sélection/routing/fallback/cache.

### 4.1 Lister & sélectionner

```python
import dataiku
project = dataiku.api_client().get_default_project()

for item in project.list_llms():              # DSSLLMListItem
    print(item.id, item.description)
project.list_llms(purpose="TEXT_EMBEDDING_EXTRACTION")   # filtre par usage
llm = project.get_llm("openai:myopenai:gpt-4o")          # handle sur un modèle précis
```
(source : https://developer.dataiku.com/latest/concepts-and-examples/llm-mesh.html)

**Format LLM ID :** `connection_type:connection_name:model_identifier[:extra_params]`, ex. `"openai:myopenai:gpt-4o"`. Le `connection_name` est la gateway définie par l'admin → swapper le provider/modèle sous-jacent = un changement d'un token dans l'ID. Le Mesh **est** l'abstraction « choisir parmi les modèles ».

> **OWIsMind cross-ref :** le projet résout déjà une **clé logique** → `agent_id` server-side (`get_agent_tool(id).run()`, règle whitelist). `get_llm(LLM_ID)` est l'analogue au **niveau modèle** : le front envoie une clé logique, le backend résout l'ID concret. **Jamais d'LLM ID venant du client** — même périmètre que la règle agent_id et que l'avertissement `configurable_fields="any"` (§1.3).

### 4.2 Usage + pont LangChain

```python
# API completion directe (marche en 3.9 ET 3.11)
llm = project.get_llm(LLM_ID)
completion = llm.new_completion()
completion.with_message("Your prompt")
resp = completion.execute()                 # ou .execute_streamed() pour des chunks

# Pont LangChain (code env 3.11 UNIQUEMENT) — applique tous les patterns §1–§3 PAR-DESSUS la gouvernance Mesh
# CHEMIN CONFIRMÉ par la doc : passer par le handle Mesh puis .as_langchain_chat_model()
langchain_chat_model = llm.as_langchain_chat_model()

# Import direct DKUChatModel : NON VÉRIFIÉ. La doc citée documente
# get_llm(...).as_langchain_chat_model() — PAS ce module ni ce constructeur.
# from dataiku.langchain.dku_llm import DKUChatModel   # import path / constructeur UNVERIFIED — confirmer via dir(dataiku.langchain) en DSS
# chat = DKUChatModel(llm_id="openai:myopenai:gpt-4o")  # kwarg llm_id= NON CONFIRMÉ par la source
```
(sources : https://developer.dataiku.com/latest/concepts-and-examples/llm-mesh.html ; https://developer.dataiku.com/latest/tutorials/genai/agents-and-tools/agent/index.html)
> **NON VÉRIFIÉ — `DKUChatModel`.** Le chemin `from dataiku.langchain.dku_llm import DKUChatModel` et le constructeur `DKUChatModel(llm_id=…)` ne sont **pas** documentés par les sources ci-dessus (qui décrivent uniquement `get_llm(...).as_langchain_chat_model()`). Utiliser le pont `.as_langchain_chat_model()` (confirmé) ; ne recourir à l'import direct qu'après l'avoir vérifié en DSS (`dir(dataiku.langchain)`).

Un setup router/tiering Mesh-backed (code env 3.11) = `get_llm(cheap_id).as_langchain_chat_model()` pour le classifieur + `get_llm(expensive_id).as_langchain_chat_model()` pour le worker, puis `with_fallbacks()` / `ModelFallbackMiddleware` sur deux IDs Mesh (redondance cross-provider **à travers** la gateway gouvernée).

### 4.3 Ce que le Mesh expose — et PAS

- **Auto-throttling / rate-limiting :** configuré au **niveau connexion (admin)**, pas dans le code du Code Agent — le Mesh enforce quotas/throttling server-side pour tout ce qui route par lui. Un Code Agent n'appelle aucune API de throttling : il en bénéficie passivement (sources : https://doc.dataiku.com/dss/latest/generative-ai/llm-connections.html ; https://www.dataiku.com/product/key-capabilities/llm-mesh/). **[À vérifier en doc admin 14.x]** les knobs exacts par connexion.
- **Prompt caching :** le guide dev LLM Mesh **ne documente PAS** d'abstraction de caching niveau Mesh. Le cache est la **feature du provider sous-jacent** (préfixe auto OpenAI, `cache_control` Anthropic, context cache Gemini) ; pour l'utiliser il faut atteindre le param provider-natif, que l'API completion Mesh peut ou non passer. **[GAP — vérifier]** si `new_completion()` / `as_langchain_chat_model()` forwarde `cache_control` ou surface `cached_tokens` en DSS 14.x. **Ne pas supposer que le Mesh cache pour vous.**
- **Fallbacks :** aucun fallback Mesh natif documenté ; implémenter à la couche LangChain (§3) sur deux IDs Mesh, ou en `try/except` natif (chemin B).

**Synthèse honnête :** le **Mesh donne la *sélection* gouvernée + le *throttling* connexion ; il ne donne PAS de caching ni de fallback portables** — ceux-ci restent à la couche LangChain/provider.

---

## 5. Prompt caching par provider + comment LangChain le surface

C'est là qu'est l'argent (jusqu'à ~90 % de remise sur le préfixe caché). La mécanique diffère fortement par provider ; la surface unifiée LangChain est `usage_metadata.input_token_details`.

### 5.1 Anthropic — breakpoints `cache_control` explicites

On **choisit** quoi cacher avec `cache_control: {"type": "ephemeral"}` sur un bloc de contenu. Le cache est un **match de préfixe** dans l'ordre de rendu **tools → system → messages** ; tout changement d'octet dans le préfixe invalide tout ce qui suit (sources : claude-api skill `prompt-caching` ; https://platform.claude.com/docs/en/build-with-claude/prompt-caching).

Chiffres vérifiés (juin 2026) :

- **TTL :** 5 min (défaut) ou 1 h (`{"type": "ephemeral", "ttl": "1h"}`).
- **Multiplicateurs de prix :** write 5 min **1,25×** base, write 1 h **2×**, read/refresh **0,1×**. (Opus 4.8 base $5/MTok → write 5 m $6,25, write 1 h $10, read $0,50.)
- **Breakpoints max :** 4/requête. **Lookback :** 20 blocs/breakpoint.
- **Préfixe cacheable minimum (par modèle) :** Opus 4.8 / Sonnet 4.6 = **1 024** ; Haiku 4.5 = **4 096** ; Fable 5 = **512**. Sous le minimum, ça ne cache pas silencieusement (`cache_creation_input_tokens: 0`).
- **Règle d'architecture :** contenu stable d'abord (system prompt **gelé**, liste d'outils déterministe/triée), contenu volatil (timestamps, question par requête) **après** le dernier breakpoint. Un `datetime.now()` ou un `json.dumps` non trié dans le system prompt = le tueur de cache silencieux classique. (Concorde avec la doctrine « prompts gelés » de `references/prompting-et-determinisme.md`.)

```python
response = client.messages.create(
    model="claude-opus-4-8", max_tokens=1024,
    system=[{"type": "text", "text": LARGE_STABLE_PROMPT,
             "cache_control": {"type": "ephemeral"}}],
    messages=[{"role": "user", "content": question}],   # volatil, après le breakpoint
)
print(response.usage.cache_creation_input_tokens)   # écrits (coût 1,25×)
print(response.usage.cache_read_input_tokens)       # servis du cache (0,1×)
print(response.usage.input_tokens)                  # reste non caché (plein tarif)
```

En agent LangChain (code env 3.11), **`AnthropicPromptCachingMiddleware`** câble les breakpoints (system + tools + dernier message user) :

```python
from langchain_anthropic.middleware.prompt_caching import AnthropicPromptCachingMiddleware
from langchain.agents import create_agent

agent = create_agent(
    model="anthropic:claude-sonnet-4-6", tools=tools,
    middleware=[AnthropicPromptCachingMiddleware(
        type="ephemeral",                  # seul ephemeral supporté
        ttl="5m",                          # "5m" | "1h"
        min_messages_to_cache=0,           # ne pas cacher avant N messages
        unsupported_model_behavior="warn", # "ignore" | "warn" | "raise"
    )],
)
```
Tague le dernier bloc system, toutes les définitions d'outils et le dernier bloc message cacheable → tout le préfixe conversationnel cache d'un tour à l'autre (source : https://reference.langchain.com/python/langchain-anthropic/middleware/prompt_caching/AnthropicPromptCachingMiddleware).

### 5.2 OpenAI — caching de préfixe automatique (zéro annotation)

OpenAI cache **automatiquement** — pas de `cache_control`, pas de changement de code (sources : https://developers.openai.com/api/docs/guides/prompt-caching ; https://openai.com/index/api-prompt-caching/) :

- S'active pour les prompts **≥ 1 024 tokens**, cache le plus long préfixe déjà calculé, par **incréments de 128 tokens**.
- **Même règle de structure qu'Anthropic :** contenu statique (instructions, exemples) **d'abord**, contenu variable/user **en dernier**.
- **Compteur de hits :** `usage.prompt_tokens_details.cached_tokens`.
- **`prompt_cache_key`** (str optionnel) : indice de routage pour augmenter le taux de hit (route les requêtes au préfixe commun vers le même serveur de cache).
- **`prompt_cache_retention`** **[POST-CUTOFF]** : `in-memory` (défaut ; ~5–10 min idle, max 1 h) ou **24 h** étendu sur certains modèles.
- **Prix :** remise auto sur tokens cachés — **pas de surcoût de write** (contrairement à Anthropic, on ne paie pas 1,25× pour *créer* le cache). Supporté sur « gpt-4o et plus récent ». *Les IDs gpt-5.x cités ci-dessous restent **NON VÉRIFIÉS**.*

```python
resp = client.responses.create(
    model="gpt-5.5",                                # NON VÉRIFIÉ
    input=[...],                                    # system/instructions statiques d'abord, query user en dernier
    prompt_cache_key="owismind-revenue-router",     # augmente le hit rate pour cette famille de préfixe
)
print(resp.usage.input_tokens_details.cached_tokens)
```

### 5.3 Gemini — implicite (défaut) + explicite (`CachedContent`)

Deux modes (sources : https://ai.google.dev/gemini-api/docs/caching ; https://developers.googleblog.com/gemini-2-5-models-now-support-implicit-caching/) :

- **Implicite** — activé par défaut sur Gemini 2.5+ ; rien à faire, remise répercutée auto (sans garantie). Minimum ~2 048 tokens (2.5 Flash/Pro). **[seuils POST-CUTOFF — vérifier par modèle]**.
- **Explicite** — `client.caches.create(...)` renvoie un `CachedContent` référencé aux appels suivants ; **TTL défaut 1 h** ; facturé sur tokens cachés + durée de stockage ; garantit la remise (**90 % sur 2.5+**).
- **Compteur de hits :** `usage_metadata.cached_content_token_count`.

```python
cache = client.caches.create(model="gemini-2.5-flash", config={"contents": LARGE_CONTEXT, "ttl": "3600s"})
resp = client.models.generate_content(model="gemini-2.5-flash", contents=question,
                                      config={"cached_content": cache.name})
print(resp.usage_metadata.cached_content_token_count)
```

### 5.4 Surface unifiée LangChain — `usage_metadata`

LangChain normalise la comptabilité cache dans `AIMessage.usage_metadata` → dashboards de coût cross-provider (sources : https://reference.langchain.com/python/langchain-core/messages/ai/UsageMetadata ; https://python.langchain.com/api_reference/core/messages/langchain_core.messages.ai.InputTokenDetails.html) :

```python
ai_msg = model.invoke("…")
ai_msg.usage_metadata
# {
#   "input_tokens": ..., "output_tokens": ..., "total_tokens": ...,
#   "input_token_details": {
#       "cache_read":     N,   # HIT — lu du cache (Anthropic cache_read / OpenAI cached_tokens / Gemini cached_content_token_count → tous ici)
#       "cache_creation": M,   # MISS — cache écrit (Anthropic ; OpenAI/Gemini ne facturent pas le write → 0/absent)
#   },
#   "output_token_details": {...},
# }
```

Agréger sur plusieurs modèles/tours via le context manager — directement utile au **suivi tokens/coûts 3 niveaux** existant d'OWIsMind (`webapp_chat_v5` + cumul lifetime + quota mensuel, voir `references/eval-tracing-securite-production.md`) :

```python
from langchain_core.callbacks import get_usage_metadata_callback
with get_usage_metadata_callback() as cb:
    router_model.invoke("…")
    worker_model.invoke("…")
    print(cb.usage_metadata)   # comptes agrégés par modèle, détails cache inclus
```
(source : https://docs.langchain.com/oss/python/langchain/models)

> **Gotcha streaming [POST-CUTOFF, 2026] :** avec `@langchain/anthropic`, les compteurs de tokens cache peuvent être **double-comptés** en streaming car `message_start` ET `message_delta` portent un usage cumulatif (le delta répète les mêmes valeurs). En sommant l'usage des `AIMessageChunk`, **dédupliquer** — ne pas additionner les champs cache de `message_start` et `message_delta` (source : https://github.com/langchain-ai/langchainjs/issues/10249). Pertinent si OWIsMind lit les champs cache du footer streamé plutôt que du message final.

**Chemin B (3.9).** Pas de `usage_metadata` LangChain. Le retour de `completion.execute()` (et le résultat de `get_agent_tool().run()`) expose des compteurs de tokens/usage natifs DSS à mapper soi-même vers les 4 colonnes usage de `webapp_chat_v5`. Pour le cache Anthropic, il faut que l'API completion Mesh forwarde `cache_control` — **[GAP, §4.3]** ; sinon le cache n'est pas atteignable en 3.9 via le Mesh.

---

## 6. Mettre tout ensemble — stack coût/fiabilité pour OWIsMind

Blueprint agnostique aux IDs qui utilise chaque levier (code env 3.11) :

```python
from langchain.chat_models import init_chat_model

# 1. SÉLECTION — clés logiques résolues server-side vers IDs Mesh/provider (JAMAIS depuis le front)
ROUTER_ID   = resolve_model("router")    # cheap, Haiku-tier / connexion Mesh cheap
WORKER_ID   = resolve_model("worker")    # mid, Sonnet-tier
EXPERT_ID   = resolve_model("expert")    # gros, Opus-tier
FALLBACK_ID = resolve_model("fallback")  # redondance cross-provider

# 2. INIT, retries OFF sur les membres derrière un fallback
router = init_chat_model(ROUTER_ID, temperature=0)
expert = init_chat_model(EXPERT_ID, max_retries=0).with_fallbacks([init_chat_model(FALLBACK_ID)])

# 3. ROUTE : classifieur cheap décide le tier (Pattern A, §2.1)
# 4. CACHE : router/system prompts gelés + en premier → le provider cache le préfixe (§5),
#    lire usage_metadata.input_token_details.{cache_read,cache_creation} pour le suivi de coût
```

**En contexte 3.9** : même blueprint, mais `resolve_model` → `project.get_llm(ID)`, `with_fallbacks` → `try/except` natif, routing → appel `new_completion()` cheap + `if/else`, cache → dépend du forward Mesh **[GAP]**.

### Cinq points à retenir
1. **`init_chat_model` + `configurable_fields`** = sélection portable + swap runtime ; **énumérer les champs explicitement** (jamais `"any"` avec config non fiable).
2. **Router cheap → worker cher** est le pattern de coût porteur ; en code (Pattern A) pour le contrôle, ou `wrap_model_call` (Pattern B) dans un agent.
3. **Retry et fallback sont antagonistes** — `max_retries=0` sur le primary sous `with_fallbacks`/`ModelFallbackMiddleware`, sinon le fallback ne se déclenche jamais.
4. **Le caching est provider-natif, pas framework-natif :** Anthropic = `cache_control` explicite (write 1,25×/2×, read 0,1×) ; OpenAI = préfixe auto ≥1 024 tokens (pas de surcoût write) ; Gemini = implicite + `CachedContent` explicite. Tout surface via `usage_metadata.input_token_details.{cache_read,cache_creation}`.
5. **Mesh Dataiku** = sélection gouvernée (`get_llm(ID)`) + throttling connexion, **mais pas de caching/fallback portable documenté** — les superposer via `.as_langchain_chat_model()` (3.11) ou en natif (3.9).

### Hygiène des IDs de modèles
Anthropic **réels/courants** (cf. `references/claude-api`) : `claude-opus-4-8` ($5 / $25 par MTok, 1M ctx), `claude-sonnet-4-6` ($3 / $15, 1M ctx), `claude-haiku-4-5` ($1 / $5, 200K). Utiliser les **strings exactes sans suffixe de date** (Haiku est l'exception : id daté complet). **`gpt-5.5`, `gpt-5.4-mini`, `gpt-5-nano`, `gemini-3.5-flash` = NON VÉRIFIÉS** (non-Anthropic, hors source) — à confirmer contre les catalogues OpenAI/Google avant tout déploiement. Dans le code réel, **pinner les IDs au catalogue live** (`project.list_llms()` en DSS), pas à un snippet de doc.

---

## Sources

- LangChain Models (`init_chat_model`, configurable, rate limiter, sélection dynamique, usage tracking) : https://docs.langchain.com/oss/python/langchain/models
- `init_chat_model` reference (signature, config_prefix, sécurité) : https://reference.langchain.com/python/langchain/chat_models/init_chat_model
- Custom middleware (`wrap_model_call`, `request.override`) : https://docs.langchain.com/oss/python/langchain/middleware/custom · https://reference.langchain.com/python/langchain/agents/middleware/wrap_model_call
- `ModelRequest` / `override` : https://reference.langchain.com/python/langchain/agents/middleware/types/ModelRequest/override
- Middleware built-in (`ModelFallbackMiddleware`, `LLMToolSelectorMiddleware`) : https://docs.langchain.com/oss/python/langchain/middleware/built-in · https://reference.langchain.com/python/langchain/agents/middleware/model_fallback/ModelFallbackMiddleware
- Fallbacks (`with_fallbacks`, caveat `max_retries=0`) : https://python.langchain.com/v0.2/docs/how_to/fallbacks/ · `with_retry` : https://reference.langchain.com/python/langchain-core/runnables/base/Runnable/with_retry
- Load-balancing Azure OpenAI via fallbacks : https://clemenssiebler.com/posts/azure_openai_load_balancing_langchain_with_fallbacks/
- `AnthropicPromptCachingMiddleware` : https://reference.langchain.com/python/langchain-anthropic/middleware/prompt_caching/AnthropicPromptCachingMiddleware
- `UsageMetadata` / `InputTokenDetails` : https://reference.langchain.com/python/langchain-core/messages/ai/UsageMetadata · https://python.langchain.com/api_reference/core/messages/langchain_core.messages.ai.InputTokenDetails.html
- Bug double-comptage cache streaming Anthropic : https://github.com/langchain-ai/langchainjs/issues/10249
- Anthropic prompt caching (TTL, multiplicateurs, minimums, breakpoints) : https://platform.claude.com/docs/en/build-with-claude/prompt-caching
- OpenAI prompt caching (préfixe auto, `cached_tokens`, `prompt_cache_key`, retention) : https://developers.openai.com/api/docs/guides/prompt-caching · https://openai.com/index/api-prompt-caching/
- Gemini context caching : https://ai.google.dev/gemini-api/docs/caching · https://developers.googleblog.com/gemini-2-5-models-now-support-implicit-caching/
- Dataiku LLM Mesh (`get_llm`, `list_llms`, LLM ID, pont `as_langchain_chat_model()`) : https://developer.dataiku.com/latest/concepts-and-examples/llm-mesh.html · agent tutorial : https://developer.dataiku.com/latest/tutorials/genai/agents-and-tools/agent/index.html — NB : ces sources ne documentent **pas** l'import `dataiku.langchain.dku_llm.DKUChatModel` (NON VÉRIFIÉ, cf. §4.2)
- Dataiku LLM connections (throttling admin) : https://doc.dataiku.com/dss/latest/generative-ai/llm-connections.html · https://www.dataiku.com/product/key-capabilities/llm-mesh/
- Anthropic « Building effective agents » (pattern Routing) : https://www.anthropic.com/research/building-effective-agents
- Anthropic Fable 5 server-side refusal fallbacks · IDs/tarifs Anthropic vérifiés : claude-api skill (model-migration, models.md, prompt-caching.md), juin 2026 — `references/claude-api`
