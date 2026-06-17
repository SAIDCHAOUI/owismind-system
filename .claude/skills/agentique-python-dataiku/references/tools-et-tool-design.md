# Outils & design de tools (l'ACI : la surface la plus rentable)

> **À jour : juin 2026.** Baseline LangChain 1.x / LangGraph 1.x / Dataiku DSS 14.x. Référence consultée à la demande ; `SKILL.md` est le parent. Voir aussi `references/langchain-v1.md`, `references/langgraph-v1.md`, `references/dataiku-code-agents.md`, `references/orchestration-multi-agents.md`, `references/eval-tracing-securite-production.md`, `references/anti-patterns-deprecations-versions.md`.

L'**ACI** (Agent-Computer Interface) — noms, descriptions, schémas et formats de retour des tools — est la surface la plus rentable de tout le système. Anthropic a atteint le SOTA sur SWE-bench Verified *uniquement* en raffinant les descriptions de tools (source : https://www.anthropic.com/engineering/writing-tools-for-agents). Le name + la description + les descriptions de paramètres **SONT** du prompt engineering : c'est le seul signal dont dispose le modèle pour choisir un tool et remplir ses arguments.

---

## 0. Les deux chemins Python (FAIT MATÉRIEL — à rappeler partout)

L'instance Dataiku a **deux code environments : Python 3.9 ET Python 3.11**. LangChain/LangGraph v1 exigent **Python ≥ 3.10**.

| Contexte | Python | Import langchain ? | Comment parler aux tools/agents |
|---|---|---|---|
| **Code Agent assigné à un code env 3.11** | ≥ 3.10 | OUI | `@tool`, `bind_tools`, `ToolRuntime`, `create_agent` (`langchain.agents`) |
| **Backend webapp OWIsMind** | 3.9.23 | **JAMAIS** | stdlib-only ; LLM Mesh / agents / tools via les **APIs natives Dataiku** directement (`SQLExecutor2`, `get_llm`, `get_agent_tool`) |

Règle dure : **ne jamais importer langchain dans un contexte 3.9.** Tout exemple `@tool`/LangChain de ce document suppose un code env 3.11 ; en 3.9, on appelle le tool comme une fonction Python ordinaire et on construit le `tool_result` à la main. Les deux chemins sont présentés quand la version compte.

---

## 1. Le protocole de tool-calling en 4 étapes (le modèle mental qui prime)

Séparer « le modèle demande » de « ton code exécute » est le modèle mental le plus important (source : https://docs.langchain.com/oss/python/langchain/models , https://www.langchain.com/blog/tool-calling-with-langchain).

1. **Création** — on emballe une fonction en tool (`@tool`, `StructuredTool`, sous-classe `BaseTool`) → produit `name`, `description`, args schema.
2. **Binding** — `model.bind_tools([...])` sérialise les schémas au format function-calling du provider. **Le binding n'exécute RIEN** (retourne un *nouveau* runnable, ne mute pas le modèle).
3. **Tool calling** — le modèle *demande* des appels : ils apparaissent dans `AIMessage.tool_calls` (liste de `ToolCall` dicts). Le modèle ne lance jamais de code.
4. **Exécution** — *ton* code invoque le tool, produit un `ToolMessage` corrélé par `tool_call_id`, l'ajoute à la liste de messages et renvoie le tout au modèle pour la réponse finale.

Anthropic cadre le même découpage par **où le code tourne** (source : https://platform.claude.com/docs/en/docs/build-with-claude/tool-use) : **client tools** (tes fonctions → `stop_reason: "tool_use"`, ton code exécute, tu renvoies `tool_result`) vs **server tools** (web_search, code_execution… exécutés par le provider). Un Code Agent Dataiku sur LLM Mesh est **quasi toujours en client-tool** : le LLM propose, **ton Python** lance le SQL/l'API et renvoie le résultat.

> **« Tool access is one of the highest-leverage primitives. »** Ajouter même des tools basiques produit des gains de capacité démesurés (LAB-Bench, SWE-bench), dépassant souvent les baselines humaines (source : https://platform.claude.com/docs/en/docs/build-with-claude/tool-use). Corollaire : la **qualité** des tools domine les résultats.

---

## 2. Créer un tool

### 2.1 `@tool` — type hints obligatoires, docstring = description

Les **type hints définissent le schéma d'entrée** (obligatoires) ; la **docstring devient la description** ; les noms en **`snake_case`** (certains providers rejettent espaces/caractères spéciaux par une erreur dure) (source : https://docs.langchain.com/oss/python/langchain/tools).

```python
from langchain.tools import tool        # v1.x ; classic : from langchain_core.tools import tool

@tool
def search_database(query: str, limit: int = 10) -> str:
    """Search the customer database for records matching the query.

    Args:
        query: Search terms to look for
        limit: Maximum number of results to return
    """
    return f"Found {limit} results for '{query}'"
```

Signature complète du décorateur (verbatim, source : https://github.com/langchain-ai/langchain/blob/master/libs/core/langchain_core/tools/convert.py) :

```python
def tool(
    name_or_callable: str | Callable[..., Any] | None = None,
    runnable: Runnable[Any, Any] | None = None,
    *args: Any,
    description: str | None = None,
    return_direct: bool = False,
    args_schema: ArgsSchema | None = None,
    infer_schema: bool = True,
    response_format: Literal["content", "content_and_artifact"] = "content",
    parse_docstring: bool = False,
    error_on_invalid_docstring: bool = True,
    extras: dict[str, Any] | None = None,
) -> BaseTool | Callable[[Callable[..., Any] | Runnable[Any, Any]], BaseTool]: ...
```

- `name_or_callable` — la fonction décorée, ou une string pour surcharger le nom (`@tool("web_search")`).
- `description` — surcharge la docstring.
- `parse_docstring=True` — parse les docstrings **Google-style** pour extraire les descriptions par argument dans le schéma.
- `error_on_invalid_docstring` — pertinent seulement avec `parse_docstring=True`. **Default différent** : `True` dans `@tool` vs `False` dans `StructuredTool.from_function`.
- `extras` — ajouté en LangChain 1.2 (2025-12-15) : paramètres/définitions de tools spécifiques au provider (source : https://docs.langchain.com/oss/python/releases/changelog).

Inspecter ce que le modèle verra : `search_database.name`, `.description`, `.args` (propriétés JSON-schema).

### 2.2 `args_schema` Pydantic — le levier #1 sur la précision des arguments

Modèle Pydantic explicite quand on a besoin de descriptions par champ, defaults, enums (`Literal`) ou validation. Chaque `Field(description=...)` est exposé au modèle et **améliore matériellement la justesse des appels** (source : https://docs.langchain.com/oss/python/langchain/tools).

```python
from pydantic import BaseModel, Field
from typing import Literal

class WeatherInput(BaseModel):
    """Input for weather queries."""
    location: str = Field(description="City name or coordinates")
    units: Literal["celsius", "fahrenheit"] = Field(
        default="celsius", description="Temperature unit preference")
    include_forecast: bool = Field(default=False, description="Include 5-day forecast")

@tool(args_schema=WeatherInput)
def get_weather(location: str, units: str = "celsius", include_forecast: bool = False) -> str:
    """Get current weather and optional forecast."""
    ...
```

`args_schema` accepte aussi un **dict JSON-schema brut** (pas de dépendance Pydantic, ou tools schema-only). En 3.9 sans Pydantic disponible, le dict JSON-schema brut est le chemin natif.

### 2.3 `StructuredTool.from_function` — création programmatique

Pour emballer une fonction qu'on ne possède pas, ou construire des tools en boucle. Accepte **`func` ET `coroutine`** (un tool sync + async) (source : https://blog.langchain.com/structured-tools/).

```python
from langchain_core.tools import StructuredTool

multiply_tool = StructuredTool.from_function(
    func=multiply_func, name="multiply",
    description="Multiply two numbers", args_schema=MultiplyInput,  # inféré si omis
)
```

Pour un contrôle total (schéma dynamique, `_run`/`_arun` custom) : sous-classer `BaseTool`.

### 2.4 Pourquoi les type hints comptent (internes de l'inférence)

Quand `infer_schema=True` sans `args_schema`, `create_schema_from_function` construit le schéma depuis hints + docstring (source : https://deepwiki.com/langchain-ai/langchain/2.3-tools-and-function-calling) : (1) modèle Pydantic de validation depuis la signature ; (2) **filtre les args internes** (`run_manager`, `callbacks`) et **injectés** (`RunnableConfig`, tout ce qui est annoté `InjectedToolArg`) — ils n'apparaissent JAMAIS dans le schéma envoyé au LLM ; (3) JSON schema propre. `tool_call_schema` = schéma vu par le modèle (args injectés strippés) ; `args` = jeu complet. La conversion provider (`convert_to_openai_tool`) strippe récursivement les `title` (tokens + conflits de validation).

### Champs clés de `BaseTool`

| Champ | Type | Default | Rôle |
|---|---|---|---|
| `name` | `str` | requis | Identifiant unique vu par le modèle |
| `description` | `str` | requis | Guidage d'usage pour le modèle |
| `args_schema` | `ArgsSchema \| None` | `None` | Pydantic `BaseModel` **ou** dict JSON-schema |
| `return_direct` | `bool` | `False` | Court-circuite la boucle d'agent (§6) |
| `handle_tool_error` | `bool \| str \| Callable` | `False` | Stratégie de récupération d'erreur (classic) |
| `response_format` | `Literal["content","content_and_artifact"]` | `"content"` | Mapping retour → `ToolMessage` (§7) |

(source : https://deepwiki.com/langchain-ai/langchain/2.3-tools-and-function-calling)

---

## 3. Naming, descriptions, doc des paramètres (le cœur de l'ACI)

Corpus et source ChatGPT **convergent** : ce n'est pas « comment faire un tool » qui compte, mais « comment écrire un tool **descriptif, minimal, gouvernable, robuste** ».

### 3.1 Names

- **Verbe-nom**, distincts : `search_database`, `calculate_price`, `fetch_user_data`. Éviter `helper`/`utility`/`do_thing`. « Clear, distinct names help agents avoid confusion » (source : https://www.anthropic.com/engineering/writing-tools-for-agents).
- **`snake_case`** pour la compatibilité cross-provider (source : https://docs.langchain.com/oss/python/langchain/tools). Contrainte Anthropic : `^[a-zA-Z0-9_-]{1,64}$`.
- **Namespacing** par préfixe service/ressource (`asana_search`, `asana_projects_search`). Préfixe vs suffixe a des « effets non-triviaux » sur les évals — **tester les deux**. Crucial avec Tool Search (§10) (source : https://www.anthropic.com/engineering/writing-tools-for-agents , https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools).

### 3.2 Descriptions — « by far the most important factor in tool performance »

Couvrir : (1) ce que fait le tool ; (2) **quand l'utiliser et quand NON** ; (3) ce que chaque paramètre signifie et son effet ; (4) format de retour (types, structure, champs) ; (5) caveats/limites, **y compris ce que le tool NE renvoie PAS**. « Aim for at least 3-4 sentences per tool description, more if complex » (source : https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools).

```text
// BON
"Retrieves the current stock price for a given ticker symbol. The ticker symbol must be a
 valid symbol for a publicly traded company on a major US exchange (NYSE/NASDAQ). Returns
 the latest trade price in USD. Use when the user asks the current/most recent price of a
 stock. Does NOT provide any other information about the stock or company."
// MAUVAIS
"Gets the stock price for a ticker."
```

Discipline éditoriale (source : https://www.anthropic.com/engineering/writing-tools-for-agents) :
- **« Each paragraph should justify its token cost. »** Default : Claude est intelligent — si retirer une phrase ne troublerait pas un lecteur compétent, la retirer.
- **Terminologie constante** : un seul terme (« always 'field', never 'field/box/element' »).
- **« Décris ton tool comme à un nouvel embauché. »** Expliciter le contexte implicite : formats de requête spécifiques, jargon, relations entre ressources.

### 3.3 Paramètres

- Noms **non ambigus** : `user_id` pas `user`.
- **Chaque propriété a une `description`** et, si fini, un **`enum`** (documente ET contraint).
- **Faire respecter par des data models stricts** : « Avoid ambiguity by clearly describing (and enforcing with strict data models) expected inputs/outputs. »
- OpenAI : limiter à **~20 fonctions** par tour ; combiner les fonctions toujours séquentielles ; **ne pas faire remplir au modèle des arguments déjà connus** ; enums pour empêcher les états invalides (source : https://developers.openai.com/api/docs/guides/function-calling).

### 3.4 Choisir QUELS tools construire (intentionnalité — le plus gros levier, le plus manqué)

- **« More tools don't always lead to better outcomes. »** Construire **« a few thoughtful tools targeting specific high-impact workflows »**, pas des wrappers fins sur chaque endpoint.
- **Consolider** comme un humain subdiviserait le travail : `list_users`+`list_events`+`create_event` → un `schedule_event` ; lookups éparpillés → un `get_customer_context`. La doc Anthropic : regrouper `create_pr`/`review_pr`/`merge_pr` en un tool avec un paramètre `action` — « fewer, more capable tools reduce selection ambiguity » (source : https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools).
- **Test de désambiguïsation** : « If a human engineer can't definitively say which tool should be used, an AI agent can't do better. » Le mode d'échec #1 = **jeux de tools gonflés / points de décision ambigus** ; viser un **overlap minimal** (source : https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents).

### 3.5 Le retour du tool (la moitié sous-estimée)

L'agent raisonne sur ce que ton tool **renvoie** ; façonne-le pour le modèle, pas pour un client de base de données (source : https://www.anthropic.com/engineering/writing-tools-for-agents) :
- **Pertinence contextuelle > flexibilité** : exclure les identifiants techniques bas-niveau (`uuid` brut, `256px_image_url`, `mime_type`) ; préférer les sémantiques (`name`, `image_url`, `file_type`). Nuance de la define-tools page : renvoyer des **identifiants sémantiques *et stables* (slugs/UUID)** plutôt que des références internes opaques — le point n'est pas « jamais d'ID » mais « des ID *signifiants et stables*, et virer le bruit » (source : https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools).
- **Enum de verbosité** (`response_format: DETAILED|CONCISE`) : impact mesuré, un retour Slack 206 → 72 tokens.
- **Token-efficient** : pagination, range, filtrage, troncature avec defaults sensés. Claude Code plafonne les retours à **25 000 tokens** ; tronquer **avec guidage** (vers une recherche plus ciblée), jamais en silence.
- **Erreurs actionnables** : « specific and actionable improvements, rather than opaque error codes » montrant le bon format (§5).

---

## 4. Binding, `tool_choice`, parallélisme

### 4.1 `bind_tools` et contrôle de `tool_choice`

`bind_tools` vit sur `BaseChatModel`, retourne un **nouveau** runnable. Accepte tools LangChain, classes Pydantic, fonctions, dicts.

```python
model_with_tools = model.bind_tools([t1], tool_choice="any")    # forcer UN tool quelconque
model_with_tools = model.bind_tools([t1], tool_choice="t1")     # forcer un tool précis
```

`"any"` = normalisation LangChain de « must call one ». Valeurs provider : `"auto"`, `"none"`, `"required"` (OpenAI) (source : https://docs.langchain.com/oss/python/langchain/models).

Sémantique côté providers :

| Anthropic | OpenAI | Effet |
|---|---|---|
| `{"type":"auto"}` | `"auto"` | Le modèle décide (default si tools fournis) |
| `{"type":"any"}` | `"required"` | Doit appeler **un** tool, le modèle choisit lequel |
| `{"type":"tool","name":"f"}` | `{"type":"function","name":"f"}` | Force **ce** tool |
| `{"type":"none"}` | `"none"` | Aucun tool (default si pas de tools) |

(source : https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools , https://developers.openai.com/api/docs/guides/function-calling)

**Comportements critiques (Anthropic)** à connaître absolument :
- Avec `any`/`tool`, l'API **préremplit** le message assistant pour forcer le tool → **pas de préambule en langage naturel** avant le `tool_use`. Pour avoir *langage naturel ET* tool précis : garder `tool_choice: auto` + l'instruire dans le user message (« Use the get_weather tool in your response. »).
- **Thinking étendu/adaptatif est incompatible avec le forced tool use** : avec thinking, seuls `auto` et `none` sont permis ; `any`/`tool` lèvent une erreur.
- **Prompt caching** : changer `tool_choice` invalide les blocs de *message* cachés (tools & system restent cachés).
- **Forced call garanti valide** : `tool_choice:{"type":"any"}` + `strict:true` ⇒ un tool *sera* appelé *et* ses inputs respectent le schéma.

### 4.2 `ToolCall` et `AIMessage.tool_calls`

```python
response.tool_calls
# [{'name':'get_weather','args':{'location':'Boston'},'id':'call_1','type':'tool_call'}, ...]
```

`ToolCall` (`TypedDict`) : `name`, `args` (dict), `id` (corrèle le futur `ToolMessage`), `type` (`"tool_call"`). Si le modèle émet du JSON malformé pour `args`, ça remonte en **`InvalidToolCall`** (args string brut + `error`), pas en `ToolCall` — une boucle robuste inspecte **les deux** `tool_calls` et `invalid_tool_calls` (source : https://deepwiki.com/langchain-ai/langchain/2.3-tools-and-function-calling).

### 4.3 La boucle d'exécution manuelle

Invoquer le tool **avec le `tool_call` dict entier** retourne un `ToolMessage` complet (id auto-corrélé) (source : https://docs.langchain.com/oss/python/langchain/models) :

```python
ai_msg = model_with_tools.invoke(messages)
messages.append(ai_msg)
for tool_call in ai_msg.tool_calls:
    tool_result = get_weather.invoke(tool_call)   # passe le dict → retourne un ToolMessage
    messages.append(tool_result)
final = model_with_tools.invoke(messages)
```

Deux modes d'invocation : `tool.invoke({"location":"Boston"})` → sortie brute (tu construis le `ToolMessage`) ; `tool.invoke(tool_call)` (dict complet `id`/`name`/`type`) → `ToolMessage` prêt avec `tool_call_id` correct. **Préférer le second dans les boucles d'agent.**

> **Gotcha (v0.3+)** : si un tool déclare un paramètre annoté `InjectedToolCallId`, `tool.invoke({...args})` en dict plat peut casser — le tool *requiert* l'invocation call-style pour peupler l'id. Passer le `ToolCall` dict complet (source : https://github.com/langchain-ai/langchain/issues/34169).

**Boucle Dataiku 3.11 (LLM Mesh + LangChain)** :

```python
llm = project.get_llm(f"openai:{CONNECTION_NAME}:gpt-4-mini").as_langchain_chat_model()
llm_with_tools = llm.bind_tools(tools)
while True:
    resp = llm_with_tools.invoke(messages)
    if len(resp.tool_calls) == 0:
        return {"text": resp.content}
    messages.append(resp)
    for tc in resp.tool_calls:
        out = execute_tool(tc["name"], tc["args"])
        messages.append(ToolMessage(tool_call_id=tc["id"], content=out))
```

(source : https://developer.dataiku.com/latest/tutorials/genai/agents-and-tools/code-agent/index.html). **En 3.9** : pas de `bind_tools` LangChain — on construit le payload tools (JSON-schema descriptors), on appelle l'agent/le LLM via l'API native, on lit les tool calls du retour et on les dispatche en Python pur (le projet OWIsMind extrait SQL/rows du retour de `get_agent_tool(id).run()`).

### 4.4 `ToolMessage`

Champs (source : https://reference.langchain.com/python/langchain-core/messages/tool/ToolMessage) : `content` (vu par le modèle), `tool_call_id` (**requis**, corrèle au `ToolCall`), `artifact` (sortie complète **NON envoyée au modèle**, §7), `status` (`"success"`/`"error"`), `name`, `id`.

### 4.5 Appels parallèles

La plupart des modèles modernes (OpenAI, Anthropic, Google) émettent **plusieurs tool calls en un tour** par défaut. Exécuter chacun, append un `ToolMessage` par call (source : https://docs.langchain.com/oss/python/langchain/models). Désactiver : `model.bind_tools([t], parallel_tool_calls=False)` (OpenAI : zéro ou un par tour). `ToolNode` (§9) exécute les calls parallèles en concurrence pour toi.

Le snippet officiel Anthropic `<use_parallel_tool_calls>` : paralléliser les calls **indépendants** (lire 3 fichiers d'un coup), **jamais** les calls dépendants, « never use placeholders or guess missing parameters » (source : https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices). **Anti-pattern latence #1** : tools synchrones lents en série — préférer async, laisser `ToolNode`/le parallélisme les lancer concurremment (source : https://medium.com/@bhagyarana80/7-langchain-tooling-anti-patterns-that-melt-agents-3588643e9644).

---

## 5. Sorties structurées & schémas stricts (deux jobs distincts)

Ne pas confondre **contraindre la réponse finale** et **contraindre les arguments d'un tool call** (source : https://platform.claude.com/docs/en/build-with-claude/structured-outputs , https://developers.openai.com/api/docs/guides/structured-outputs) :

| Job | Anthropic | OpenAI |
|---|---|---|
| Contraindre **la réponse finale** | `output_config.format` (`type: json_schema`) | `response_format:{type:"json_schema",strict:true}` |
| Contraindre **les arguments du tool** | `strict: true` sur le tool | `strict: true` sur la fonction |

« Structured Outputs is the evolution of JSON mode. Both ensure valid JSON ; only Structured Outputs ensure **schema adherence**. » Anthropic Structured Outputs est **GA** (Opus 4.5–4.8, Sonnet 4.5/4.6, Haiku 4.5, Fable 5).

**Strict-mode (OpenAI)** : `additionalProperties:false` sur chaque objet ; tous les champs en `required` ; optionnels modélisés `type:["string","null"]`. SDK acceptent Pydantic via `.parse(...)`.

**Caps Anthropic strict** : ≤ **20** tools stricts/requête ; ≤ **24** params optionnels ; ≤ **16** params union-typés ; compilation 180 s, grammaire cachée 24 h (changement de schéma → invalidation). **Required émis avant optionnels**, indépendamment de l'ordre du schéma. Refus → output possiblement hors-schéma (`stop_reason:"refusal"`). Non supportés : schémas récursifs, contraintes numériques (`minimum`/`maximum`), longueur de string, regex backreferences/lookaround.

> **Le prefill est mort.** Les réponses assistant préremplies (dernier tour) **renvoient 400 sur Claude 4.6+** (Opus 4.6/4.7/4.8, Sonnet 4.6, Fable 5). Migration : Structured Outputs / tools enum / instruction directe. (Des messages assistant *ailleurs* pour le few-shot marchent encore.) (source : gap-version-recency, https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices)

**LangChain** : `with_structured_output(PydanticModel)` pour un appel unique ; au niveau agent, `response_format=` (Pydantic / `ToolStrategy` / `ProviderStrategy`) → `result["structured_response"]`. LangChain auto-sélectionne **`ProviderStrategy`** (modèles à structured output natif : OpenAI, Grok) sinon **`ToolStrategy`**. Le strict-avec-`ProviderStrategy` est un ajout **LangChain 1.2** (source : gap-version-recency).

> ⚠️ **Issue connue #35539** : `create_agent` + `response_format` a un `tool_choice="any"` **hardcodé** dans certaines versions 1.x → **casse Anthropic thinking + structured output combinés**. Combiner exécution réelle de tools et réponse finale structurée a des soucis remontés de recursion-limit. Traiter le structured output niveau-agent comme **encore en maturation** ; pour une forme finale garantie, un appel dédié `with_structured_output` est plus robuste (source : https://github.com/langchain-ai/langchain/issues/35539).

**`gpt-5.5` est UNVERIFIED** (non-Anthropic, non vérifié contre la source). Modèles Anthropic confirmés réels : `claude-opus-4-8`, `claude-sonnet-4-6`, `claude-haiku-4-5`.

---

## 6. `return_direct` — court-circuiter la boucle (déterminisme)

`return_direct=True` retourne la sortie du tool **immédiatement**, en sautant l'appel modèle post-tool (source : https://docs.langchain.com/oss/python/langchain/tools) :

```python
@tool(return_direct=True)
def fetch_order_status(order_id: str) -> str:
    """Fetch the current status of a customer order."""
    return f"Order {order_id} is shipped and will arrive in 2 days."
```

Quand : la sortie est déjà une réponse complète prête pour l'utilisateur ; pas de raisonnement post-tool nécessaire ; **sortie déterministe non paraphrasée par le LLM**. **Caveat** : avec des appels parallèles, `return_direct` ne prend effet que si **tous** les tools appelés ont `return_direct=True`. Attention à le combiner avec l'error handling (une exception dans un return-direct tool saute la chance de récupérer).

> **Pertinence Dataiku** : `return_direct=True` est la voie framework-native pour imposer « le résultat SQL/calculé est renvoyé verbatim, le LLM ne réécrit pas les nombres » — aligné sur le pattern OWIsMind « RENDER by code, accroche LLM vérifiée chiffre par chiffre ».

---

## 7. Retourner des artifacts (`response_format="content_and_artifact"`)

Par défaut, le retour devient `ToolMessage.content` (stringifié). `response_format="content_and_artifact"` **sépare ce que le modèle voit de ce que ton code garde** : le tool retourne un **tuple `(content, artifact)`** → `content` au modèle, `artifact` **NON envoyé au modèle** (source : https://reference.langchain.com/python/langchain-core/tools/base/BaseTool/response_format).

```python
@tool(response_format="content_and_artifact")
def run_query(sql: str) -> tuple[str, dict]:
    """Run a SQL query and summarize the result."""
    rows = execute(sql)
    return f"Returned {len(rows)} rows.", {"rows": rows, "sql": sql}
```

Pour peupler l'artifact, invoquer **avec un `ToolCall` dict** (pas un args dict nu) — l'artifact atterrit sur le `ToolMessage` : `tool_msg.content` (modèle) / `tool_msg.artifact` (ton code).

> **Caveat v1** : avec `ToolNode`/`create_react_agent`, l'artifact est *stocké* sur le `ToolMessage` mais **pas auto-threadé** dans le workflow au-delà du stockage (feature requests ouvertes). Pour Dataiku, l'artifact est surtout un **side-channel** qu'on lit sur le `ToolMessage` pour rendre dans son UI (les rows SQL exactes d'un panneau d'évidence), **pas** quelque chose sur quoi l'agent raisonne. **C'est le bon pattern pour le « résultat exact capturé » d'OWIsMind** (source : https://github.com/langchain-ai/langgraph/discussions/4221).

Construire un artifact manuellement = retourner un `ToolMessage` (nécessite le call id, §8) :

```python
from langchain_core.tools import tool, InjectedToolCallId
from langchain_core.messages import ToolMessage
from typing import Annotated

@tool
def foo(x: int, tool_call_id: Annotated[str, InjectedToolCallId]) -> ToolMessage:
    """Return x."""
    return ToolMessage(str(x), artifact=x, name="foo", tool_call_id=tool_call_id)
```

---

## 8. Injection : `ToolRuntime` (v1) vs `Injected*` (classic)

Le problème : certains inputs (state, user id, handle DB, call id) doivent être **fournis par ton système, pas par le modèle**, et **absents du schéma vu par le modèle**.

### 8.1 `ToolRuntime` (v1.x, code env 3.11)

Un seul paramètre `runtime: ToolRuntime` dans la signature → **auto-injecté, caché du modèle**, sans `Annotated` (source : https://docs.langchain.com/oss/python/langchain/tools). Bundle : `state`, `context`, `config`, `store`, `stream_writer`, `tool_call_id`, `tools`, `execution_info`, `server_info`.

> **Noms de paramètres RÉSERVÉS** : interdit de nommer un arg de tool `config` ou `runtime` (réservés à `RunnableConfig` et `ToolRuntime`).

```python
from langchain.tools import tool, ToolRuntime
from dataclasses import dataclass

@dataclass
class UserContext:
    user_id: str

@tool
def get_account_info(runtime: ToolRuntime[UserContext]) -> str:
    """Get the current user's account information."""
    return lookup(runtime.context.user_id)   # user_id JAMAIS visible du LLM

agent = create_agent(model, tools=[get_account_info], context_schema=UserContext)
agent.invoke({"messages":[...]}, context=UserContext(user_id="user123"))
```

Mettre à jour l'état depuis un tool : retourner un `Command(update={...})`. `runtime.execution_info`/`server_info` nécessitent `langgraph>=1.1.5`.

### 8.2 Annotations classic (durables, ce que le code Dataiku-era utilise)

- **`InjectedToolArg`** — marqueur de base : « injecté au runtime, exclu du schéma vu par le modèle ».
- **`InjectedState`** — state du graphe LangGraph.
- **`InjectedStore`** — store persistant.
- **`InjectedToolCallId`** — id du tool call courant (pour construire un `ToolMessage`/`Command` depuis le tool).

```python
from typing_extensions import Annotated
from langchain_core.tools import tool, InjectedToolArg
from langgraph.prebuilt import InjectedState

@tool
def state_tool(x: int, state: Annotated[dict, InjectedState]) -> str:
    """Do something with state."""
    return state["foo"] + str(x)
```

`tool_call_schema` strippe tous les params annotés `InjectedToolArg` — le modèle ne voit jamais `state`, `tool_call_id`, etc.

**Carte de migration** (v1 déprécie les patterns épars au profit de `ToolRuntime`) :

| Classic | v1 |
|---|---|
| `InjectedState` | `runtime.state` |
| `InjectedStore` | `runtime.store` |
| `InjectedToolCallId` | `runtime.tool_call_id` |
| `get_runtime()` | paramètre `runtime` |
| arg `config: RunnableConfig` | `runtime.config` |

> **Takeaway Dataiku** : `InjectedToolArg`/`InjectedToolCallId` (3.11) sont la voie durable et version-safe pour passer un handle DB, une project key ou l'identité user **sans l'exposer au LLM** — exactement la posture « frontend never chooses table/connection » + « whitelist agents server-side ». **En 3.9** (backend webapp) : pas d'injection LangChain — on garde ces valeurs entièrement côté Python natif et on ne les met jamais dans le payload du tool envoyé au modèle. C'est le même invariant, implémenté à la main.

---

## 9. Gestion d'erreurs & retries (3 couches, en utiliser ≥ 2)

### 9.1 `ToolException` + `handle_tool_error` (classic, in-tool)

`ToolException` signale une erreur **récupérable** → renvoyée à l'agent comme observation, le modèle se corrige (source : https://reference.langchain.com/v0.3/python/core/tools/langchain_core.tools.base.ToolException.html).

| Valeur de `handle_tool_error` | Comportement |
|---|---|
| `False` (default) | L'exception propage (l'agent crashe) |
| `True` | Renvoie une string d'erreur générique |
| `str` | Renvoie cette string littérale |
| `Callable[[ToolException], str]` | Appelée avec l'exception, renvoie la string |

### 9.2 Wrapper try/except (le pattern portable — marche en 3.9 ET 3.11)

```python
def safe_tool_invoke(tool, args, config=None):
    try:
        return tool.invoke(args, config)
    except Exception as e:
        return f"Calling tool with args {args!r} raised: {e}"
```

Framework-agnostic, marche sur ancien LangChain Dataiku **et** en 3.9 sur des fonctions natives. Renvoyer un message lisible par le modèle pour qu'il réessaie avec des args corrigés.

### 9.3 `ToolNode.handle_tool_errors` (agents préfabriqués, 3.11)

| Valeur | Comportement |
|---|---|
| `True` | Catch tout, `ToolMessage` template d'erreur + détails |
| `False` | Désactivé, propage |
| `str` | Catch tout, `ToolMessage` custom |
| `type[Exception]` / `tuple[...]` | Catch seulement ce(s) type(s) |
| `Callable[..., str]` | Catch les exceptions matchées, renvoie la string |

> **Gotcha de récence MAJEUR** : le default a **basculé**. Depuis **langgraph-prebuilt 1.0.1 (via langgraph 1.0.2)**, l'error handling de `ToolNode` est **effectivement OFF sauf activation explicite** (source : https://github.com/langchain-ai/langgraph/issues/6486). En early `create_agent` (v1 alpha), l'error handling était cassé avec middleware (issues #33348/#33153). **Action : toujours fixer `handle_tool_errors` explicitement, jamais se fier au default.**

### 9.4 Middleware `@wrap_tool_call` (v1, recommandé)

```python
from langchain.agents.middleware import wrap_tool_call
from langchain.messages import ToolMessage

@wrap_tool_call
def handle_tool_errors(request, handler):
    """Convert tool exceptions into ToolMessages the model can handle."""
    try:
        return handler(request)
    except Exception as e:
        return ToolMessage(content=f"Tool error: check your input and retry. ({e})",
                           tool_call_id=request.tool_call["id"])

agent = create_agent(model="claude-sonnet-4-6", tools=[...], middleware=[handle_tool_errors])
```

### 9.5 Retries (distincts de error-to-observation)

- **HTTP/transport** : `max_retries=` sur le chat model (429/500/503).
- **Node-level** : `RetryPolicy` LangGraph (backoff exponentiel) ou retries state-based (compteur + edges conditionnels).
- **v1.1 (2025-12-02)** : **Model-Retry Middleware** intégré avec backoff configurable.

Distinction nette : **error-to-observation** (le modèle corrige ses *arguments*) vs **retry** (re-run le même call sur une panne *transitoire*). Pour Dataiku, les écritures SQL/effets de bord doivent être **idempotents** : un nœud LangGraph peut être **réexécuté depuis le début** après interruption/reprise (checkpoints aux frontières de super-steps).

---

## 10. Réduire les tool calls hallucinés

Une « tool hallucination » = choisir un tool inapproprié, appeler au mauvais moment, ou **inventer un nom de fonction inexistant** (source : https://arxiv.org/pdf/2412.04141). Défenses en couches :

1. **Désambiguïsation par design** — tools à overlap minimal + test de l'ingénieur humain (§3.4). Les jeux ambigus *causent* les hallucinations de sélection.
2. **Strictness du schéma** — `strict:true` / structured outputs garantissent que les inputs matchent → élimine les « hallucinations » d'arguments malformés. **Enums bornés** plutôt que texte libre partout où les valeurs sont finies (source : https://developers.openai.com/api/docs/guides/function-calling).
3. **Garde-fou de validation de nom** — vérifier le nom de fonction choisi contre le registre des tools disponibles avant exécution ; rejeter les noms inconnus (source : https://medium.com/@Nexumo_/7-guardrails-that-reduce-llm-hallucinations-78facbb0d560). **C'est l'invariant OWIsMind « whitelist agents côté serveur »** : le front envoie une clé logique, le backend résout l'`agent_id` — le modèle ne choisit jamais un id brut.
4. **Garder les schémas en contexte** — les schémas définis dans le system prompt peuvent sortir de la fenêtre → le modèle hallucine des noms qu'il ne voit plus. Mitiger par context management ou Tool Search.
5. **Chemins de pensée explicites** — exiger une raison une-ligne + l'id du tool avant l'appel, une courte observation après (CoT léger).
6. **Prompt de grounding** — `<investigate_before_answering>` : ne jamais affirmer avant d'avoir lu/investigué.
7. **Demander, pas deviner, sur params requis manquants** — Opus reconnaît mieux un param manquant et le demande ; Sonnet/Haiku peuvent inférer. Si deviner est inacceptable, forcer la demande par prompt et **ne pas** utiliser un forced tool-choice qui prérremplit une valeur devinée (source : https://platform.claude.com/docs/en/docs/build-with-claude/tool-use).

> **L'analogue under-triggering** (« I don't have that data » au lieu de router vers le tool) est la leçon OWIsMind « Expert Authority » : ne jamais laisser le modèle **nier** un fait métier ; router vers le tool ou dire honnêtement « pas d'agent pour ce domaine ». C'est un contrat d'honnêteté niveau-prompt / stop-condition, **pas un bug de tool**.

### Scaling : Tool Search (Anthropic, advanced tool use 2025-11)

Quand les définitions dominent le contexte, marquer les tools peu fréquents `defer_loading:true` : cachés jusqu'à ce que le modèle cherche une capacité, puis seuls les tools matchés se déploient en définition complète. Reporté : ~85 % de réduction de contexte ; sélection Opus 4.5 79.5 % → 88.1 %. Meilleur pour **10+ tools ou >10K tokens de définitions** (source : https://www.anthropic.com/engineering/advanced-tool-use). Coût des définitions : le tool-use system prompt caché coûte ~290 tokens (Opus 4.8, `auto`/`none`) / ~410 (`any`/`tool`), plus chaque name/description/schéma. **`gpt-5.4`+** a un mécanisme deferred-tools analogue (UNVERIFIED — non-Anthropic).

---

## 11. Déterministe vs génératif (l'anti-pattern central, leçon OWIsMind P3)

La règle d'architecture la plus importante pour un code agent.

**L'anti-pattern** : valeurs métier hardcodées dans la logique d'agent, **et** inversement laisser le LLM générer en free-form des steps/valeurs qui doivent être exactes. Anthropic : ni « brittle if-else logic » ni valeurs critiques à la discrétion du modèle — trouver la bonne altitude. « Do not hard-code values or create solutions that only work for specific test inputs » (source : https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents , https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices).

**Le pattern** : séparer **décisions LLM-bornées** et **exécution déterministe code-owned**.
- **LLM** : *compréhension* et *sélection dans un jeu de candidats contraint* (intent, quelle colonne, quelle entité) — via schémas stricts/enums, pas du texte libre. Un enum convertit « génère une valeur » en « sélectionne une valeur valide », que l'API peut *garantir*.
- **Code** : tout ce qui doit être exact — templates SQL, formatage numérique, résolution de valeur contre un index réel, rendu final. Vérifier les valeurs choisies par le modèle contre la vérité-terrain avant usage.

C'est exactement le split NL2SQL SOTA et le design OWIsMind v3 : le **Semantic Model possède le SQL** (tool, mode Agent) ; le Dataset Expert génère la *question sémantique* depuis des **templates gelés** et résout les vraies valeurs depuis un `*_value_index` ; COMPOSE templaté ; RENDER vérifié ; le moteur SQL direct est un **fallback technique**, jamais la source des valeurs métier.

**Tuning piloté par l'éval (pour que les règles viennent de preuves, pas d'un bug)** : construire des tâches d'éval multi-tool **réalistes** (pas des jouets) ; tracker accuracy, runtime, #tool-calls, tokens, erreurs de tool ; puis **laisser un agent lire les transcripts et refactorer les tools** (« Claude is an expert at analyzing transcripts and refactoring lots of tools at once »). Éviter les vérificateurs trop stricts qui rejettent des réponses correctes sur la ponctuation (source : https://www.anthropic.com/engineering/writing-tools-for-agents). C'est l'alternative disciplinée au patch d'une valeur métier pour chaque cas qui échoue (règle OWIsMind P3 : jamais de valeur métier en dur, cas inconnus → compréhension LLM contrainte ou refus honnête).

---

## 12. Discipline Dataiku : managed tools & Custom Python Tool

Taxonomie Dataiku (source ChatGPT, conceptuellement valide) : **Simple Visual Agents** (no-code), **Structured Visual Agents** (séquences de blocs + logique déterministe), **Code Agents** (logique agentique entièrement codée). Chaque agent devient un **« Virtual LLM » du LLM Mesh** — réutilisable partout, avec audit/sécurité/guardrails intégrés. L'agent n'est pas seulement du code, c'est un **objet gouverné de la plateforme**.

**Anatomie d'un Code Agent** (DSS 14+, CONFIRMÉ) : sous-classe `BaseLLM` (`from dataiku.llm.python import BaseLLM`), implémente `process(self, query, settings, trace)` (+ `aprocess`, `process_stream`, `aprocess_stream`). `query` = `SingleCompletionQuery` (dict-like ; `query["messages"]`) ; la réponse est un **dict littéral** avec clé requise `"text"` (optionnels `promptTokens`, `completionTokens`, `estimatedCost`, `toolCalls`) ; `trace` (`SpanBuilder`) log les spans (source : gap-version-recency ; https://developer.dataiku.com/latest/tutorials/genai/agents-and-tools/code-agent/index.html).

**Trois sources de tools** : fonctions embarquées, fonctions de librairie projet, **Custom Tools** plugins. Les tools sont **self-describing** (on peut récupérer un « tool descriptor » ; params = objets JSON-Schema).

**Discipline Custom Python Tool** (corpus + ChatGPT convergent) : avant de brancher un morceau de logique dans un gros agent, le développer comme un **Custom Python Tool** pour l'**isoler, le tester, le versionner** et le réutiliser. Pour une équipe : isoler les tools comme des **composants versionnés et testables**, plutôt qu'entasser toute la logique dans l'orchestrateur principal. Cela mappe la règle OWIsMind « repo = source de vérité » (tests : `python3 -m unittest discover`) et « contrats gelés : `KNOWN_TOOL_NAMES` ↔ registre, test anti-dérive ».

**Mapping des règles §1–11 sur DSS** :
- Chaque règle §3 s'applique verbatim aux **docstrings et signatures `@tool`** (en 3.11) — *ce sont* tes descriptions/schémas. En 3.9, ce sont les JSON-schema descriptors que tu construis à la main.
- `tool_choice`/`strict` dépendent du **modèle de la connexion Mesh sous-jacente** (provider-specific).
- **Whitelist server-side** (front = clé logique → backend résout l'id) = garde-fou d'hallucination (§10).
- **Déterminisme §11** = house style OWIsMind : LLM borné à compréhension/sélection ; SQL/résolution/formatage en code ; question sémantique en templates gelés ; render vérifié.
- **Artifacts §7** = le « résultat exact capturé » : le modèle voit un résumé vérifié, ton UI évidence lit `ToolMessage.artifact` (rows + SQL exacts). Le modèle ne corrompt pas les nombres.

> ⚠️ Le starter `DKUChatModel`/`create_agent` (source ChatGPT) et le `project.get_semantic_model(...)` + `get_raw()`/`save()`/`versions` (mémoire projet) sont **UNVERIFIED** contre la doc publiée — à confirmer au runtime (`dir(project)`, introspection du `dataikuapi` installé), ne pas citer comme fait documenté (source : gap-version-recency §4.2).

---

## 13. « Quand utiliser quoi » (quick guide)

| Besoin | Utiliser |
|---|---|
| Tool typé rapide depuis une fonction | `@tool` (type hints + docstring) |
| Descriptions par champ / enums / validation | `@tool(args_schema=PydanticModel)` |
| Programmatique / wrapper de fonction existante | `StructuredTool.from_function(...)` |
| Contrôle total (`_run`/`_arun`, schéma dynamique) | sous-classer `BaseTool` |
| Annoncer les tools au modèle | `model.bind_tools([...])` (+ `tool_choice`, `parallel_tool_calls`) |
| Réponse déterministe, pas de réécriture LLM | `return_direct=True` |
| Payload large/binaire, modèle veut juste un résumé | `response_format="content_and_artifact"` → `(content, artifact)` |
| Passer données système (DB, user id, call id) cachées du modèle | v1 (3.11) : `runtime: ToolRuntime` ; classic : `Annotated[..., Injected*]` ; 3.9 : Python natif, hors payload |
| Garantir des arguments de tool valides | `strict:true` sur le tool/fonction + enums |
| Forcer un tool sans préambule ni thinking | `tool_choice: tool`/`any` (+ `strict`) |
| Forcer un tool **et** garder du langage naturel | `tool_choice: auto` + instruction dans le user message |
| Erreur in-tool récupérable → auto-correction | `ToolException` + `handle_tool_error` (classic) ; `@wrap_tool_call` (v1) ; `ToolNode(handle_tool_errors=...)` explicite |
| Panne transitoire provider/réseau | `max_retries` (modèle) + `RetryPolicy` / Model-Retry Middleware |
| Beaucoup de tools / définitions dominent le contexte | Tool Search (`defer_loading`) + namespacing |
| Valeurs métier exactes | code déterministe (templates, value index) ; LLM sélectionne dans des candidats contraints |
| Boucle ReAct standard (3.11) | `create_agent` (`langchain.agents`) |
| Topologie custom, fan-out parallèle, supervisor | `StateGraph` manuel + `ToolNode` + `tools_condition` (voir `references/langgraph-v1.md`) |
| Agent Python dans Dataiku | `BaseLLM.process` + LLM Mesh + (3.11) `@tool` + boucle `bind_tools` / (3.9) API native |

---

## 14. Pièges & anti-patterns (mémo)

1. **Trop de tools / tools qui se chevauchent** → points de décision ambigus, mauvais tool choisi. Consolider ; test de l'ingénieur humain.
2. **Descriptions une-ligne** → « le facteur #1 de perf », viser 3-4+ phrases dont quand *ne pas* utiliser et ce qui n'est *pas* renvoyé.
3. **Renvoyer des rows DB brutes / IDs opaques / gros blobs** → champs sémantiques, stables, high-signal ; paginer/tronquer.
4. **Texte libre où un enum convient** → enums + strict pour rendre la valeur sélectionnable et garantie.
5. **Confondre « bind » et « execute »** → `bind_tools` n'annonce que des schémas, rien ne tourne avant que toi (ou `ToolNode`) n'invoque.
6. **Oublier la corrélation `tool_call_id`** → un `ToolMessage` orphelin casse l'appariement ; invoquer avec le `ToolCall` dict complet.
7. **Attendre que l'artifact atteigne le modèle** → l'artifact est délibérément non envoyé, non auto-threadé ; side-channel code/UI.
8. **Se fier au default d'error handling** → flippé OFF après langgraph 1.0.2 ; fixer `handle_tool_errors` explicitement.
9. **`InjectedToolCallId` + invoke en dict plat** → force l'invocation call-style.
10. **Noms d'arg réservés** `config`/`runtime`.
11. **Forcer un tool en attendant un préambule** → `any`/`tool` suppriment le texte naturel et cassent avec thinking.
12. **Encore du prefill** pour forcer JSON sur 4.6+ → 400, utiliser Structured Outputs.
13. **Prompts « CRITICAL/MUST » agressifs sur nouveaux modèles** → over-triggering (Opus 4.5/4.6 plus réactifs au system prompt) ; langage normal.
14. **Hardcoder des valeurs métier / patcher une règle par cas d'échec** → séparer déterministe vs génératif ; tuner depuis des évals réalistes.
15. **Imports faux après v1** → `langchain.tools`/`messages`/`agents` ; chains/retrievers/hub en `langchain-classic` (maintenu jusqu'à déc. 2026). `create_react_agent` est **déprécié** → `create_agent` (voir `references/anti-patterns-deprecations-versions.md`).
16. **Importer langchain en 3.9** → JAMAIS ; APIs natives Dataiku uniquement.

---

## Sources principales

- LangChain Tools : https://docs.langchain.com/oss/python/langchain/tools
- LangChain Models (bind_tools, ToolCall, parallèle, boucle) : https://docs.langchain.com/oss/python/langchain/models
- `@tool` / `StructuredTool` (source) : https://github.com/langchain-ai/langchain/blob/master/libs/core/langchain_core/tools/convert.py · https://github.com/langchain-ai/langchain/blob/master/libs/core/langchain_core/tools/structured.py
- `ToolNode` / `handle_tool_errors` : https://github.com/langchain-ai/langgraph/blob/main/libs/prebuilt/langgraph/prebuilt/tool_node.py · default flip : https://github.com/langchain-ai/langgraph/issues/6486
- `ToolMessage` / `response_format` / `ToolRuntime` : https://reference.langchain.com/python/langchain-core/messages/tool/ToolMessage · https://reference.langchain.com/python/langchain-core/tools/base/BaseTool/response_format · https://reference.langchain.com/python/langgraph.prebuilt/tool_node/ToolRuntime
- Injection classic : https://reference.langchain.com/v0.3/python/core/tools/langchain_core.tools.base.InjectedToolCallId.html · https://reference.langchain.com/v0.3/python/core/tools/langchain_core.tools.base.ToolException.html
- Architecture / inférence de schéma : https://deepwiki.com/langchain-ai/langchain/2.3-tools-and-function-calling
- structured output + tool_choice issue : https://github.com/langchain-ai/langchain/issues/35539
- Anthropic — Writing effective tools : https://www.anthropic.com/engineering/writing-tools-for-agents
- Anthropic — Effective context engineering : https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- Anthropic — Advanced tool use (Tool Search, input_examples) : https://www.anthropic.com/engineering/advanced-tool-use
- Anthropic — Define tools / Tool use / Structured outputs / Prompting best practices : https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools · https://platform.claude.com/docs/en/docs/build-with-claude/tool-use · https://platform.claude.com/docs/en/build-with-claude/structured-outputs · https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices
- OpenAI — Function calling / Structured outputs : https://developers.openai.com/api/docs/guides/function-calling · https://developers.openai.com/api/docs/guides/structured-outputs
- Dataiku — Code Agent / Tools LLM Mesh : https://developer.dataiku.com/latest/tutorials/genai/agents-and-tools/code-agent/index.html · https://developer.dataiku.com/latest/tutorials/genai/agents-and-tools/llm-agentic/tools/index.html
- Tool hallucination (arXiv) : https://arxiv.org/pdf/2412.04141 · guardrails : https://medium.com/@Nexumo_/7-guardrails-that-reduce-llm-hallucinations-78facbb0d560
- Anti-patterns tooling : https://medium.com/@bhagyarana80/7-langchain-tooling-anti-patterns-that-melt-agents-3588643e9644
- Recency/versions (autoritaire) : `docs/agentic-research/gap-version-recency-recheck-2026.md`
