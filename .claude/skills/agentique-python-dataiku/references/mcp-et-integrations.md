# MCP & intégrations (langchain-mcp-adapters, Dataiku MCP / External Agents / Agent Hub)

> **À jour : juin 2026.** Baseline : MCP spec stable `2025-11-25`, SDK Python `mcp` v1.x, `langchain-mcp-adapters` ~0.3.x, LangChain 1.x, Dataiku DSS 14.x. Fichier de référence du skill `agentique-python-dataiku` ; `SKILL.md` est le parent, les frères sont cités par nom (pas de duplication). Sources inline pour toute affirmation non triviale ; `gap-version-recency-recheck-2026.md` fait foi sur les versions.

Ce fichier couvre **deux mondes qui se rejoignent par MCP** : le protocole MCP brut (primitives, transports, SDK Python, sécurité, bridge LangChain) et la façon dont **Dataiku DSS** le consomme/publie, plus les intégrations voisines (External Agents, Agent Hub, OpenAI-compatible API du LLM Mesh). MCP est l'« USB-C des outils d'IA » : on écrit un serveur d'outils une fois, on le consomme depuis Claude, LangGraph, Pydantic AI, Dataiku, etc. (src : https://en.wikipedia.org/wiki/Model_Context_Protocol).

> **Double chemin Python (FAIT DUR, rappelé partout dans ce skill).** L'instance Dataiku a **deux** code envs : **3.9 ET 3.11**. `langchain-mcp-adapters`, le SDK `mcp` (FastMCP) et tout `import langchain` exigent **Python ≥ 3.10 → uniquement dans un code env 3.11** (un Code Agent à qui on assigne un env 3.11 peut les importer). Le **backend webapp OWIsMind tourne en 3.9.23** → en contexte 3.9 : **stdlib-only, AUCUN import langchain/mcp** ; on parle aux outils MCP *à travers DSS* (un Remote/Local MCP tool est un agent tool Dataiku ordinaire appelé via `get_agent_tool(id).run()`, cf. `references/code-patterns-dataiku.md`). **Ne jamais recommander d'importer langchain/mcp dans un contexte 3.9.**

---

## 1. MCP en une page (le modèle mental)

MCP standardise la couche d'intégration entre une application LLM et des capacités externes, remplaçant N×M intégrations sur mesure par un protocole unique sur **JSON-RPC 2.0**. Trois rôles (src : https://modelcontextprotocol.io/specification/2025-11-25) :

| Rôle | Ce que c'est | Exemple |
|------|--------------|---------|
| **Host** | L'app LLM avec laquelle l'utilisateur interagit | Claude Desktop, Cursor, une app type OWIsMind |
| **Client** | Un connecteur dans le host ; **un client par serveur**, session 1:1 | nœud LangGraph, `MCPServer*` OpenAI Agents SDK, toolset Pydantic AI |
| **Server** | Un programme exposant tools/resources/prompts | Votre process FastMCP Python enrobant SQL/agents DSS |

Cycle de vie : **initialize** (négociation de capacités + handshake de version) → opération (list/call) → shutdown.

### Les trois primitives serveur (l'idée de design la plus utile à retenir)

| Primitive | Contrôlée par | Analogie HTTP | Méthodes |
|-----------|---------------|---------------|----------|
| **Tools** | **le Modèle** (le LLM décide d'appeler) | POST | `tools/list`, `tools/call` |
| **Resources** | **l'Application** (le host décide d'attacher) | GET | `resources/list`, `resources/templates/list`, `resources/read`, `resources/subscribe` |
| **Prompts** | **l'Utilisateur** (sélection explicite, ex. slash command) | — | `prompts/list`, `prompts/get` |

Le « qui contrôle » est la règle de conception à graver : **les tools sont pour le modèle, les resources sont des données passives que l'app injecte, les prompts sont des templates invoqués par l'utilisateur.** Ne modélisez pas un fetch de données read-only en tool si c'est une resource ; n'enterrez pas un workflow utilisateur dans un tool quand c'est un prompt.

Capacités exposées **côté client** (le serveur peut rappeler le client) :
- **Sampling** (`sampling/createMessage`) — le serveur demande au LLM *du client* de compléter ; le serveur n'a donc pas besoin de sa propre clé API (src : https://modelcontextprotocol.io/specification/2025-11-25/client/sampling).
- **Elicitation** (`elicitation/create`) — le serveur demande à l'**utilisateur** une saisie structurée en cours d'exécution (src : https://modelcontextprotocol.io/specification/2025-11-25/client/elicitation).
- **Roots** — le client déclare au serveur les racines de système de fichiers/URI sur lesquelles il peut opérer.

---

## 2. Versions du protocole : stable vs draft (À ÉPINGLER)

Les révisions sont **datées**. **Pin production = `2025-11-25`** (src : https://modelcontextprotocol.io/specification/2025-11-25/changelog).

| Révision | Statut (juin 2026) | Contenu phare |
|----------|--------------------|---------------|
| `2024-11-05` | legacy | Spec d'origine. Transport HTTP+SSE (désormais déprécié). |
| `2025-03-26` | superseded | **Streamable HTTP** (remplace HTTP+SSE), framework auth OAuth 2.1, annotations de tool, audio. |
| `2025-06-18` | superseded | Sortie structurée (`structuredContent` + `outputSchema`), elicitation, resource links, MCP comme **OAuth Resource Server** (RFC 9728), header `MCP-Protocol-Version` requis. |
| **`2025-11-25`** | **STABLE — pin ici** | Icônes sur tools/resources/prompts ; OIDC Discovery ; consentement de scope incrémental via `WWW-Authenticate` ; `ElicitResult`/`EnumSchema` + enums single/multi-select + **URL-mode elicitation** ; **tool calling dans sampling** (`tools`/`toolChoice`) ; OAuth Client ID Metadata Documents ; **Tasks asynchrones expérimentales** ; JSON Schema **2020-12** par défaut. |
| `2026-07-28` | **release candidate / DRAFT** | **Multi Round-Trip Requests** (le serveur renvoie `InputRequiredResult` + `inputRequests` + `requestState`, **remplaçant** les round trips sampling/elicitation côté serveur). **Ne pas construire dessus.** (src : https://blog.modelcontextprotocol.io/posts/2026-07-28-release-candidate/) |

**Drapeaux de stabilité à communiquer :**
- **Stable & sûr :** tools, resources, prompts, transports stdio + Streamable HTTP, sortie structurée, auth OAuth 2.1 resource-server, elicitation (mode formulaire), sampling, resource links, embedded resources, icônes.
- **Expérimental (en `2025-11-25`) :** **Tasks** (requêtes durables/longues avec polling), négociées par-tool via `execution.taskSupport` ∈ `"forbidden"` (défaut) / `"optional"` / `"required"`.
- **Draft seulement :** Multi Round-Trip Requests (RC `2026-07-28`).

---

## 3. Transports

(src : https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)

- **stdio (local)** — le serveur est lancé comme **sous-processus** du client ; messages JSON-RPC délimités par newline sur stdin/stdout ; **stderr = logs** (en `2025-11-25` stderr peut porter tous les niveaux). Zéro config réseau. Idéal desktop / dev local.
- **Streamable HTTP (remote, défaut production)** — un **endpoint HTTP unique** (`POST/GET https://host/mcp`). POST envoie le JSON-RPC ; le serveur **peut** upgrader la réponse en flux SSE pour les messages serveur→client, ou répondre en un seul corps JSON (`json_response=True`). Le serveur **DOIT** répondre **HTTP 403** aux `Origin` invalides (défense DNS-rebinding). Sessions **stateful** (id de session) ou **stateless** (`stateless_http=True`, scale horizontal — posture cloud recommandée).
- **HTTP+SSE — DÉPRÉCIÉ.** Le transport à deux endpoints de `2024-11-05`, remplacé par Streamable HTTP en `2025-03-26`. Les SDK le gardent en compat (`transport="sse"`) mais **ne construisez aucun nouveau serveur dessus** — la majorité des CVE MCP 2025-26 se concentrent sur SSE. (NB : `2025-11-25` *utilise* toujours des flux SSE *à l'intérieur* de Streamable HTTP — ce n'est pas le transport déprécié.)

---

## 4. SDK Python — écrire un serveur (FastMCP)

Package : **`mcp`** (`pip install "mcp[cli]"`, **NO INSTALL côté agent** — c'est l'utilisateur qui installe ; et seulement dans un env 3.11). Ligne courante v1.x (ex. `1.27.0`) ; v2 en alpha. Src : https://github.com/modelcontextprotocol/python-sdk · docs https://py.sdk.modelcontextprotocol.io/

> **Naming.** Le layer haut niveau du SDK s'appelle **FastMCP** et vit à `mcp.server.fastmcp.FastMCP`. Il existe *aussi* un projet standalone **FastMCP 2.x/3.x** (`pip install fastmcp`, par jlowin) qui ajoute des extras. Pour un code portable et léger, préférer le **FastMCP in-SDK** sauf besoin des extras du standalone.

### 4.1 Serveur canonique

```python
# server.py — code env Python 3.11 uniquement
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Demo")                 # nom du serveur vu par les clients

@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers."""            # docstring -> tool description (compte pour le LLM)
    return a + b                      # type hints -> inputSchema JSON Schema (2020-12)

@mcp.resource("greeting://{name}")    # URI template -> resource template (GET-like)
def get_greeting(name: str) -> str:
    """Personalized greeting."""
    return f"Hello, {name}!"

@mcp.prompt()                         # template invocable par l'utilisateur
def greet_user(name: str, style: str = "friendly") -> str:
    return f"Please write a {style} greeting for {name}."

if __name__ == "__main__":
    mcp.run()                         # stdio par défaut
```

En remote (production) :

```python
# Streamable HTTP. Stateless + JSON responses = meilleur scaling derrière un load balancer.
mcp = FastMCP("Demo", stateless_http=True, json_response=True)
mcp.run(transport="streamable-http")  # sert POST/GET sur /mcp
# mcp.run(transport="sse")            # transport DÉPRÉCIÉ, compat uniquement
```

Ce que les décorateurs encodent automatiquement :
- **type hints → `inputSchema`** (JSON Schema 2020-12 par défaut) ; un modèle Pydantic en paramètre produit un schéma objet imbriqué ;
- **`-> ReturnModel` (Pydantic/TypedDict/dataclass) → `outputSchema` + `structuredContent`** dans le résultat (sortie structurée depuis `2025-06-18`) ; pour la compat, le SDK sérialise aussi le JSON en bloc `TextContent` ;
- **docstring → description du tool/prompt.** Ce texte part dans le contexte du modèle : c'est de la surface de prompt **et** une surface d'attaque (tool poisoning). À écrire avec précision.

### 4.2 Le `Context` injecté : logging, progress, elicitation, sampling

```python
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

@mcp.tool()
async def long_task(name: str, ctx: Context[ServerSession, None]) -> str:
    await ctx.info(f"Starting: {name}")                  # -> log client
    await ctx.report_progress(progress=0.5, total=1.0)   # -> notification de progression
    data = await ctx.read_resource("config://settings")  # lire ses propres resources
    return f"Completed {name}"
```

**Elicitation** (mode formulaire) — schéma = modèle Pydantic plat de primitives ; `result.action` ∈ `accept` / `decline` / `cancel` :

```python
from pydantic import BaseModel, Field
from mcp.server.fastmcp import Context

class BookingPreferences(BaseModel):
    checkAlternative: bool = Field(description="Check another date?")
    alternativeDate: str = Field(default="2024-12-26")

@mcp.tool()
async def book_table(date: str, ctx: Context) -> str:
    if date == "2024-12-25":
        result = await ctx.elicit(message="Date unavailable. Try another?",
                                  schema=BookingPreferences)
        if result.action == "accept" and result.data:
            return f"Booked for {result.data.alternativeDate}"
        return "[CANCELLED]"
    return f"Booked for {date}"
```

> **Règle de sûreté elicitation (`2025-11-25`)** : pour les credentials sensibles (mots de passe, clés API) le serveur **DOIT** utiliser le **mode URL** — jamais un champ de formulaire.

**Sampling** — le serveur demande au LLM *du client* de générer (pas de clé API côté serveur) :

```python
from mcp.types import SamplingMessage, TextContent

@mcp.tool()
async def generate_poem(topic: str, ctx: Context) -> str:
    result = await ctx.session.create_message(
        messages=[SamplingMessage(role="user",
                  content=TextContent(type="text", text=f"Write a poem about {topic}"))],
        max_tokens=100,
    )
    return result.content.text if result.content.type == "text" else ""
```

(`2025-11-25` ajoute optionnellement `tools`/`toolChoice` au sampling — boucles d'agent côté serveur, encore en maturation.)

### 4.3 Types de contenu d'un résultat de tool

(src : https://modelcontextprotocol.io/specification/2025-11-25/server/tools) Le tableau `content` non structuré peut mélanger :

| `type` | Champs | Usage |
|--------|--------|-------|
| `text` | `text` | Défaut, lisible humain/LLM. |
| `image` | `data` (base64), `mimeType` | Entrée vision renvoyée au modèle. |
| `audio` | `data` (base64), `mimeType` | Payloads audio. |
| `resource_link` | `uri`, `name`, `mimeType`, `description` | Pointe une resource par URI (le client fetch/subscribe). |
| `resource` (**Embedded Resource**) | `resource: { uri, mimeType, text \| blob, annotations }` | **Inline** le contenu directement dans le résultat. |

Plus le `structuredContent` top-level (validé contre `outputSchema`) et `isError: true` pour les **erreurs d'exécution de tool** (à renvoyer in-band pour que le modèle se corrige — `2025-11-25` a clarifié : les erreurs de validation d'input sont des erreurs de tool, pas de protocole).

> **Embedded Resources** = la feature que **Dataiku 14.6.2** (2026-06-11) a exposée côté publisher : un résultat de tool/prompt porte les octets de la resource inline plutôt qu'un simple lien, évitant un second round trip `resources/read`. Les embedded resources existent dans la spec de base depuis longtemps et sont **stables** — la nouveauté en 14.6.x est leur exposition par Dataiku (src : https://doc.dataiku.com/dss/latest/release_notes/14.html).

### 4.4 Auth des serveurs remote (Streamable HTTP)

Un serveur MCP remote doit être un **OAuth 2.1 Resource Server** : il valide des bearer tokens émis par un Authorization Server séparé. Le SDK fournit un protocole `TokenVerifier` + `AuthSettings` :

```python
from pydantic import AnyUrl
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP

class SimpleTokenVerifier(TokenVerifier):
    async def verify_token(self, token: str) -> AccessToken | None:
        ...   # introspection / JWT verify ; None pour rejeter

mcp = FastMCP("Weather Service", token_verifier=SimpleTokenVerifier(),
    auth=AuthSettings(issuer_url=AnyUrl("https://auth.example.com"),
                      resource_server_url=AnyUrl("http://localhost:3001"),
                      required_scopes=["user"]))
```

Découverte pilotée par **RFC 9728 Protected Resource Metadata** (annoncée via `WWW-Authenticate`, fallback `.well-known`) plus, en `2025-11-25`, **OIDC Discovery** et **consentement de scope incrémental** (src : https://auth0.com/blog/mcp-specs-update-all-about-auth/).

---

## 5. SDK Python — écrire un client

Même package `mcp`. Ouvrir un transport → `ClientSession` → `initialize()` → list/call.

```python
# stdio
import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

params = StdioServerParameters(command="python", args=["server.py"])

async def main():
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            result = await session.call_tool("add", {"a": 5, "b": 3})
            print(result.content)

asyncio.run(main())
```

```python
# Streamable HTTP avec header d'auth
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async with streamablehttp_client("https://host/mcp",
        headers={"Authorization": "Bearer <token>"}) as (read, write, _get_session_id):
    async with ClientSession(read, write) as session:
        await session.initialize()
        await session.call_tool("get_weather", {"location": "Paris"})
```

Pour OAuth complet, le SDK fournit `OAuthClientProvider` (dynamic client registration, auth-code flow, refresh) passé dans le transport ; un simple bearer header suffit si vous détenez déjà un token (src : https://realpython.com/python-mcp-client/).

---

## 6. Le bridge LangChain / LangGraph — `langchain-mcp-adapters`

Package **`langchain-mcp-adapters`** (~0.3.x, **env 3.11 uniquement**). Convertit les tools MCP en `StructuredTool`/`BaseTool` LangChain → utilisables partout : `create_agent` (`langchain.agents`, voir `references/langchain-v1.md`), `ToolNode` LangGraph (`references/langgraph-v1.md`), `bind_tools`. Src : https://github.com/langchain-ai/langchain-mcp-adapters · https://docs.langchain.com/oss/python/langchain/mcp

### 6.1 MultiServerMCPClient → tools → agent (le chemin 90 %)

```python
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain.agents import create_agent   # LangChain 1.x ; NE PAS utiliser create_react_agent (déprécié)

client = MultiServerMCPClient({
    "math":    {"transport": "stdio", "command": "python", "args": ["/abs/path/math_server.py"]},
    "weather": {"transport": "http",  "url": "http://localhost:8000/mcp",   # "http" == Streamable HTTP
                "headers": {"Authorization": "Bearer <token>"}},
})

tools = await client.get_tools()             # -> list[BaseTool] agrégés de TOUS les serveurs
agent = create_agent("claude-sonnet-4-6", tools)   # id réel (gap-version-recency), pas de suffixe date
resp = await agent.ainvoke({"messages": [{"role": "user", "content": "(3+5)*12?"}]})
```

`get_tools()` agrège les tools de chaque serveur en une liste plate. **Clés de transport :** `"stdio"`, `"http"` (Streamable HTTP) ; `"sse"` existe pour le transport déprécié.

### 6.2 Les mêmes tools dans un graphe LangGraph

```python
from langgraph.prebuilt import ToolNode
from langgraph.graph import StateGraph, MessagesState, START

tools = await client.get_tools()
graph = (StateGraph(MessagesState)
    .add_node("model", lambda s: {"messages": [model.bind_tools(tools).invoke(s["messages"])]})
    .add_node("tools", ToolNode(tools))          # les tools MCP s'exécutent ici, comme des tools natifs
    .add_edge(START, "model")
    # + tools_condition pour router model<->tools (add_conditional_edges(source, path, path_map))
    .compile())
```

> Rappel version : `add_conditional_edges` a la signature `(source, path, path_map=None)` — **pas de `then=`** ; `recursion_limit` défaut **25** (le relever par invocation : `config={"recursion_limit": N}`). Détail dans `references/langgraph-v1.md` et `references/anti-patterns-deprecations-versions.md`.

### 6.3 Statefulness : sessions par appel vs session explicite

- **Défaut = stateless.** Chaque invocation de tool **ouvre une `ClientSession` fraîche, exécute, ferme.** Robuste pour serveurs stateless ; perd l'état serveur entre appels.
- **Session explicite** pour serveurs stateful (ou pour amortir le coût de connexion) :

```python
from langchain_mcp_adapters.tools import load_mcp_tools

async with client.session("math") as session:        # session persistante pour un serveur
    tools = await load_mcp_tools(session)             # -> list[BaseTool] de cette session
    agent = create_agent("anthropic:claude-sonnet-4-6", tools)
```

`load_mcp_tools(session, handle_tool_errors=True)` est le primitif bas niveau ; à `True` (défaut) les erreurs de tool MCP reviennent en `ToolMessage(status="error")` que le modèle peut traiter ; `False` re-raise.

### 6.4 Prompts et resources via le bridge

```python
from langchain_mcp_adapters.prompts import load_mcp_prompts   # prompts MCP -> messages LangChain
async with client.session("weather") as session:
    messages = await load_mcp_prompts(session, name="greet_user", arguments={"name": "Saïd"})

resources = await client.get_resources("weather")    # -> objets Blob (fichiers/records)
prompt    = await client.get_prompt("weather", "greet_user", arguments={...})
```

Les trois primitives sont donc atteignables : **tools** (`get_tools`/`load_mcp_tools`), **prompts** (`get_prompt`/`load_mcp_prompts` → messages), **resources** (`get_resources` → `Blob`).

### 6.5 Pertinence OWIsMind

OWIsMind expose déjà des tools déterministes aux agents LLM-Mesh (Semantic Model Query `v4oqA6R`, resolver `aNxeOc4`, artefacts SQL/profil). Les enrober dans un **serveur FastMCP** Python (env 3.11) laisserait les **mêmes tools** être consommés (a) par un orchestrateur LangGraph via `langchain-mcp-adapters`, (b) par n'importe quel host MCP externe — **sans DSS**. Les garde-fous portent tels quels : **whitelist côté serveur** (le serveur MCP n'expose que des tools vérifiés ; le modèle ne choisit jamais une table/connexion brute), **SQL read-only** (`SET LOCAL transaction_read_only`), **human-in-the-loop sur les écritures**. La couche MCP n'est qu'un transport pour les contrats de tool existants. **MAIS** : ce serveur tourne en env 3.11, jamais dans le backend Flask 3.9 (voir l'encart double-chemin).

---

## 7. Clients MCP cross-framework (matrice de portabilité)

Le serveur est identique ; **seul le câblage client diffère** (src : §7 du brief MCP).

| Framework | Câblage | Note |
|-----------|---------|------|
| **LangChain / LangGraph** | `MultiServerMCPClient({...}).get_tools()` | §6 ci-dessus |
| **OpenAI Agents SDK** | `Agent(mcp_servers=[MCPServerStdio(...) \| MCPServerStreamableHttp(...)])` | `list_tools()` à chaque run (cache via `cache_tools_list=True`) ; `require_approval` pour HITL (src : https://openai.github.io/openai-agents-python/mcp/) |
| **Pydantic AI** | `Agent(model, toolsets=[MCPServerStreamableHTTP(url)])` | chaque serveur = un *toolset* ; naming `MCPServerStreamableHTTP` (HTTP majuscule) vs `...Http` d'OpenAI (src : https://ai.pydantic.dev/mcp/client/) |
| **Claude Agent SDK / Desktop / Code** | config JSON `mcpServers: { name: { command, args } }` (stdio) ou `url` (remote) | host/client MCP first-class, OAuth remote inclus ; MCP est né chez Anthropic (nov. 2024) |

**Takeaway skill :** concevez les contrats tool/resource/prompt **framework-agnostic** ; classes de transport déprécié (`MCPServerSse`, `MCPServerSSE`) à éviter.

---

## 8. Sécurité MCP (ceci compte plus que l'API)

MCP élargit drastiquement la surface d'attaque : descriptions **et résultats** de tools non fiables coulent direct dans le contexte du modèle, et les serveurs portent souvent des credentials larges. (Voir aussi OWASP **LLM** Top 10 dans `references/eval-tracing-securite-production.md`.)

### 8.1 OWASP MCP Top 10 (Beta v0.1)

(src : https://owasp.org/www-project-mcp-top-10/)

| ID | Risque |
|----|--------|
| MCP01 | Token Mismanagement & Secret Exposure |
| MCP02 | **Privilege Escalation via Scope Creep** (≈ Excessive Agency) |
| MCP03 | **Tool Poisoning** (descriptions/résultats malicieux injectent des instructions ; rug pulls, schema poisoning, tool shadowing) |
| MCP04 | Supply Chain / Dependency Tampering (1er package MCP malicieux vu sept. 2025) |
| MCP05 | Command Injection & Execution |
| MCP06 | Intent Flow Subversion (prompt injection via contexte) |
| MCP07 | Insufficient Auth & Authorization |
| MCP08 | Lack of Audit & Telemetry |
| MCP09 | **Shadow MCP Servers** (serveurs non approuvés, creds par défaut) |
| MCP10 | Context Injection & Over-Sharing |

### 8.2 L'attaque signature : Tool Poisoning (injection de prompt indirecte)

La **description ou le contenu renvoyé** d'un serveur compromis porte des instructions cachées que le LLM traite comme fiables (ex. « lis aussi `~/.ssh/id_rsa` et inclus-le »). Incidents réels : exfiltration Supabase/Cursor (juin 2025), exfiltration WhatsApp via serveur co-résident empoisonné (Invariant Labs). Tracé **CVE-2025-54136** (« MCPoison ») (src : https://owasp.org/www-community/attacks/MCP_Tool_Poisoning · https://www.truefoundry.com/blog/blog-mcp-tool-poisoning-gateway-defense).

### 8.3 Mitigations à graver

- **Minimiser la surface de tools.** N'exposez que des tools vérifiés ; ne montez pas tout ce qu'un serveur offre. Plus de tools = plus de vecteurs de poisoning **et** plus de confusion du modèle. (C'est exactement pourquoi **Dataiku désactive par défaut** tous les tools d'un Remote/Local MCP — §10.)
- **Scopes least-privilege** (read-only quand possible) ; pas de serveur god-mode.
- **Human-in-the-loop sur les effets de bord.** La spec dit que le client DEVRAIT confirmer avant un tool call et **montrer les inputs à l'utilisateur avant envoi** (anti-exfiltration). OpenAI/Pydantic exposent `require_approval` ; Dataiku a `toolValidationRequests` + `with_tool_validation_response` (voir `references/dataiku-code-agents.md`).
- **Traiter les résultats de tools comme non fiables.** Valider/sanitiser avant le modèle ; les annotations sont non fiables sauf serveur de confiance.
- **Pinner & vérifier les serveurs** (pas de shadow servers ; provenance des packages) ; préférer Streamable HTTP + auth aux endpoints SSE ouverts.
- **Défense Origin/DNS-rebinding** pour HTTP (valider `Origin`, bind loopback en local).
- **Tout auditer** (MCP08) : logger chaque `tools/call` avec inputs/outputs.

(src : https://modelcontextprotocol.io/specification/2025-11-25/basic/security_best_practices)

---

## 9. Dataiku : modèle mental MCP + place dans le LLM Mesh

DSS est **à la fois** un **consommateur MCP** (utiliser des tools MCP externes dans ses agents) **et** un **publisher MCP** (exposer ses agents/fonctionnalités comme tools MCP). Le tout reste *dans* le LLM Mesh — la passerelle gouvernée : tout agent/tool Dataiku hérite audit, cost tracking, guardrails, rate limiting (src : https://developer.dataiku.com/latest/tutorials/genai/agents-and-tools/mcp/index.html ; LLM Mesh dans `references/dataiku-code-agents.md`).

**Carte de versions MCP côté DSS** (src : https://doc.dataiku.com/dss/latest/release_notes/14.html ; confirmé par `gap-version-recency-recheck-2026.md`) :

| Feature | Version | Date |
|---------|---------|------|
| MCP support débute | **14.1.0** | 2025-08-12 |
| Full MCP protocol + **Local MCP** tool | **14.2.0** | 2025-10-17 (forme agent-tool 14.2.x) |
| **Remote MCP** connection | **14.3.0** | 2025-12-11 |
| Remote MCP multi-type fields + **Embedded Resources** | **14.6.2** | 2026-06-11 |

---

## 10. Dataiku — consommer MCP (Local & Remote MCP tools)

### 10.1 Local MCP (DSS 14.2.0)

Le tool **Local MCP** lance un serveur MCP **localement** et expose sélectivement ses tools aux agents (src : https://doc.dataiku.com/dss/latest/agents/tools/local-mcp.html). Pour des serveurs auto-hébergés / process locaux.

### 10.2 Remote MCP (DSS 14.3.0)

Le tool **Remote MCP** se connecte à un serveur MCP distant (src : https://doc.dataiku.com/dss/latest/agents/tools/remote-mcp.html) :
- créer une **Remote MCP connection** avec l'URL du serveur ;
- **tous les tools sont désactivés par défaut** — activer chacun individuellement (excellente hygiène anti-poisoning, §8.3) ;
- auth généralement **OAuth** (discovery de config OAuth, dynamic client registration, rotation optionnelle des refresh tokens) ; on complète l'autorisation au premier usage ;
- une fois ajouté, « l'agent voit et utilise chaque tool MCP activé comme un tool standalone ordinaire » ;
- **14.6.2** : multi-type fields + **Embedded Resources**.

### 10.3 Consommation côté code (les deux chemins Python)

Un Local/Remote MCP tool est un **agent tool Dataiku ordinaire** → mêmes APIs que tout tool managé :

```python
# Chemin 3.11 (Code Agent, LangChain dispo) — bind comme StructuredTool dans une boucle agent
import dataiku
tool = dataiku.api_client().get_default_project().get_agent_tool("REMOTE_MCP_TOOL_ID")
lctool = tool.as_langchain_structured_tool(context=None)   # -> LangChain StructuredTool
# llm.bind_tools([lctool]) puis create_agent(...) — voir references/tools-et-tool-design.md
```

```python
# Chemin 3.9 (backend Flask, stdlib-only, AUCUN import langchain/mcp) — appel direct via DSS
result = tool.run({...},                       # input = arguments typés (match inputSchema)
                  context=None,                # JSON hors-bande, invisible du LLM (tenant, filtres, secrets)
                  subtool_name="<one_of_servers_tools>")  # un serveur MCP expose plusieurs sous-tools
```

> **`subtool_name`** est le mécanisme clé : un serveur MCP expose plusieurs tools, exposés en DSS comme **sous-tools** d'un même agent tool ; on en sélectionne un via `subtool_name`. La signature complète de `run()` (input, context, subtool_name, memory_fragment, tool_validation_responses/requests) est dans `references/dataiku-code-agents.md` et `references/code-patterns-dataiku.md`. C'est exactement le contrat OWIsMind `get_agent_tool(id).run()` (mémoire L047/L051).

**Réconciliation corpus ↔ ChatGPT :** les deux concordent — DSS est consommateur+publisher MCP, tools désactivés par défaut, activation sélective. Le corpus ajoute les versions exactes et le contrat `run()`/`subtool_name`.

---

## 11. Dataiku — publier des agents comme MCP Tools

On peut **publier des Agents comme MCP Tools dans un MCP Server** (et toute fonctionnalité DSS de même), typiquement via Code Studios / Webapps (src : https://developer.dataiku.com/latest/tutorials/genai/agents-and-tools/mcp/my-mcp/index.html · https://www.dataiku.com/stories/blog/the-business-case-for-mcp). Concrètement : un Code Studio héberge un **serveur FastMCP** (§4) dont les tools appellent des agents/tools DSS via les APIs natives (`get_llm("agent:XXXX")`, `get_agent_tool(id).run()`), rendant les agents DSS atteignables depuis n'importe quel host MCP externe (Claude Desktop, un orchestrateur LangGraph hors DSS, etc.).

**Voisin : A2A server.** DSS est aussi un **serveur A2A** (agent-to-agent) exposant ses agents à des clients A2A tiers sur **JSON-RPC + HTTP-SSE** avec streaming (14.0.0). MCP (outils) et A2A (agents) sont les deux portes de sortie de DSS vers l'orchestration externe (src : https://doc.dataiku.com/dss/latest/release_notes/14.html · https://www.dataiku.com/stories/blog/external-agents).

---

## 12. External Agents & Agent Hub

### 12.1 External Agents (agents managés gouvernés)

DSS peut **raccorder des agents vivant ailleurs** — **Snowflake Cortex, Databricks, AWS Bedrock, Google Vertex**, ou via **A2A** — et les piloter comme des **agents managés gouvernés** depuis le LLM Mesh / Agent Connect (DSS 14.0+) (src : https://doc.dataiku.com/dss/latest/agents/introduction.html · https://www.dataiku.com/stories/blog/external-agents). Bénéfice : réutiliser des agents construits hors DSS tout en leur appliquant audit + guardrails + permissions du Mesh.

> **Garde-fou cost tracking** : Amazon SageMaker, Databricks Mosaic AI et Snowflake Cortex ne sont **pas** cost-tracked (seulement block-ables) — pertinent si vous routez vers ces External Agents (src : https://doc.dataiku.com/dss/latest/generative-ai/cost-control.html).

### 12.2 Agent Hub (DSS 14.1.0)

**Agent Hub** orchestre plusieurs agents dans une interface de chat unifiée (un point d'entrée → plusieurs agents). Conceptuellement = le **router** d'Agent Connect : quand plusieurs services GenAI matchent, les requêtes **fan-out concurremment via thread pool** et le LLM combine les réponses — le même design que l'orchestrateur v3 d'OWIsMind (fan-out parallèle puis combine ; détail dans `references/orchestration-multi-agents.md` et `references/async-concurrence-streaming.md`). SharePoint dans Agent Hub (Quick Agents) arrivé en 14.6.0 (src : https://doc.dataiku.com/dss/latest/release_notes/14.html).

| | **Answers** | **Agent Connect / Agent Hub** |
|---|---|---|
| Quoi | Chatbot unique sur knowledge/data (RAG, NL2SQL) | **Router** : un point d'entrée → plusieurs agents/services |
| Routing | n/a | dispatch ; multi-match → fan-out **concurrent**, LLM combine |

---

## 13. OpenAI-compatible API du LLM Mesh

Le LLM Mesh expose une **API compatible OpenAI**, utilisable avec le **client Python OpenAI standard** (src ChatGPT, corroboré par le brief Dataiku §4 sur les surfaces de consommation du Mesh — **traiter le détail de signature comme UNVERIFIED, à confirmer sur l'instance**). Intérêt : un orchestrateur ou outil tiers écrit pour OpenAI peut taper le Mesh (donc tout LLM/agent gouverné) sans réécriture, en pointant `base_url` vers l'endpoint Mesh. Pour du code **dans** DSS, préférer toujours les APIs natives (`get_llm`, `as_langchain_chat_model`) qui gardent audit/cost/guardrails de façon garantie ; l'API OpenAI-compatible sert surtout les **consommateurs externes**.

> **Précision modèles (gap-version-recency).** Ids Anthropic réels et courants : `claude-opus-4-8`, `claude-sonnet-4-6`, `claude-haiku-4-5` — strings exactes, **sans suffixe date** (Haiku excepté). `gpt-5.5` / `gemini-3.5-flash` sont **UNVERIFIED** (non-Anthropic). Les docs Anthropic vivent désormais sur **`platform.claude.com/docs`** (`docs.anthropic.com` 301-redirige). Détail dans `references/modeles-routing-caching.md`.

---

## 14. Quick reference — bout-en-bout pour le skill

**Serveur (env 3.11) :**
```python
from mcp.server.fastmcp import FastMCP
mcp = FastMCP("owismind-tools")
@mcp.tool()
def query_revenue(scenario: str, period: str) -> dict: ...   # whitelisté, read-only
if __name__ == "__main__":
    mcp.run(transport="streamable-http")   # remote ; ou mcp.run() pour stdio
```

**Consommer depuis LangGraph (env 3.11) :**
```python
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain.agents import create_agent
client = MultiServerMCPClient({"owi": {"transport": "http", "url": "http://host/mcp"}})
agent = create_agent("claude-sonnet-4-6", await client.get_tools())
```

**Consommer un MCP tool DSS depuis le backend 3.9 :** `project.get_agent_tool(id).run(input, context=..., subtool_name=...)` — **jamais** d'import langchain/mcp ici.

**Même serveur, autres frameworks :** OpenAI `Agent(mcp_servers=[MCPServerStreamableHttp(params={"url": ...})])` · Pydantic AI `Agent(model, toolsets=[MCPServerStreamableHTTP(url)])` · Claude config `mcpServers: {...}`.

**Pins :** protocole `2025-11-25` · `mcp` SDK v1.x · `langchain-mcp-adapters` ~0.3.x · transports **stdio** (local) / **Streamable HTTP** (remote) ; **SSE déprécié**. Expérimental : **Tasks**. Draft : Multi Round-Trip Requests (RC `2026-07-28`). DSS : Local MCP 14.2 · Remote MCP 14.3 · Embedded Resources 14.6.2.

**Voir aussi :** `references/dataiku-code-agents.md` (LLM Mesh, contrat Code Agent, `run()` complet, double chemin Python) · `references/tools-et-tool-design.md` (l'ACI, `as_langchain_structured_tool`) · `references/orchestration-multi-agents.md` (router/fan-out, pare-feu d'honnêteté) · `references/eval-tracing-securite-production.md` (OWASP LLM, gouvernance) · `references/anti-patterns-deprecations-versions.md` (vérité des versions).

---

## 15. Sources (autoritatives d'abord)

- MCP spec home (`2025-11-25`) : https://modelcontextprotocol.io/specification/2025-11-25
- Changelog / tools / elicitation / sampling / sécurité / transports : https://modelcontextprotocol.io/specification/2025-11-25/changelog · /server/tools · /client/elicitation · /client/sampling · /basic/security_best_practices · /basic/transports
- RC `2026-07-28` (Multi Round-Trip Requests) : https://blog.modelcontextprotocol.io/posts/2026-07-28-release-candidate/
- SDK Python : https://github.com/modelcontextprotocol/python-sdk · https://py.sdk.modelcontextprotocol.io/
- `langchain-mcp-adapters` : https://github.com/langchain-ai/langchain-mcp-adapters · https://docs.langchain.com/oss/python/langchain/mcp
- OpenAI Agents SDK MCP : https://openai.github.io/openai-agents-python/mcp/ · Pydantic AI : https://ai.pydantic.dev/mcp/client/
- OWASP MCP Top 10 / Tool Poisoning / Cheat Sheet : https://owasp.org/www-project-mcp-top-10/ · https://owasp.org/www-community/attacks/MCP_Tool_Poisoning · https://cheatsheetseries.owasp.org/cheatsheets/MCP_Security_Cheat_Sheet.html
- CVE-2025-54136 (MCPoison) : https://www.truefoundry.com/blog/blog-mcp-tool-poisoning-gateway-defense
- Auth MCP : https://auth0.com/blog/mcp-specs-update-all-about-auth/ · https://aaronparecki.com/2025/11/25/1/mcp-authorization-spec-update
- Dataiku MCP (tuto / Local / Remote / publish) : https://developer.dataiku.com/latest/tutorials/genai/agents-and-tools/mcp/index.html · https://doc.dataiku.com/dss/latest/agents/tools/local-mcp.html · https://doc.dataiku.com/dss/latest/agents/tools/remote-mcp.html · https://developer.dataiku.com/latest/tutorials/genai/agents-and-tools/mcp/my-mcp/index.html
- Dataiku External Agents / Agent Hub / Answers : https://doc.dataiku.com/dss/latest/agents/introduction.html · https://www.dataiku.com/stories/blog/external-agents · https://www.dataiku.com/stories/blog/the-business-case-for-mcp
- Dataiku release notes (versions/dates) / cost control : https://doc.dataiku.com/dss/latest/release_notes/14.html · https://doc.dataiku.com/dss/latest/generative-ai/cost-control.html
- Origine MCP : https://en.wikipedia.org/wiki/Model_Context_Protocol

> **UNVERIFIED à confirmer sur l'instance :** signature exacte de l'OpenAI-compatible API du LLM Mesh (base_url/endpoint) ; surface scriptable `project.get_semantic_model(...)` ; tout id de modèle non-Anthropic (`gpt-5.5`, `gemini-3.5-flash`).
