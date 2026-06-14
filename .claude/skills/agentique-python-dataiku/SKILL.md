---
name: agentique-python-dataiku
description: >-
  Use when designing, building, orchestrating, prompting, reviewing, or debugging
  code-based AI agents in Python — single agents, orchestrators, or specialized
  sub-agents — with LangChain, LangGraph, or Dataiku DSS. Triggers: créer/auditer
  un agent ou orchestrateur, multi-agents, sous-agents spécialisés, tool calling,
  LLM Mesh, Code Agent Dataiku, mémoire/persistance, RAG, structured output,
  tracing/guardrails/évaluation, ou choix du niveau d'abstraction
  (create_agent vs LangGraph vs visual/code agent) et du runtime Python (3.9 vs 3.11).
---

# Agentique Python — LangChain, LangGraph & Dataiku DSS

> **À jour : juin 2026** — LangChain 1.x, LangGraph 1.x, Dataiku DSS 14.x.
> Prose en français, code en anglais. Skill de référence : ce `SKILL.md` est l'aiguillage,
> le détail vit dans `references/` (lecture à la demande).

## Principe central

Un bon agent n'est pas un « gros prompt malin », c'est une **architecture** : on choisit le **bon niveau d'abstraction**, on **découpe les responsabilités**, on **contrôle le contexte**, et on met le tout **sous gouvernance**. La fiabilité est un problème de génie logiciel (déterminisme, idempotence, tests, observabilité), pas de magie de prompt. Le LLM n'intervient **que là où le raisonnement probabiliste apporte vraiment** ; partout où la séquence/branche/boucle est connue d'avance, un **workflow déterministe** bat l'autonomie.

## ⚠️ Deux faits non négociables (lire avant de coder)

### 1. Double chemin Python sur Dataiku — 3.9 ET 3.11

L'instance Dataiku a **deux** code environments : **Python 3.9** et **Python 3.11**.

| Contexte | Python | LangChain / LangGraph v1 (exigent ≥ 3.10) | Comment appeler le LLM/agent/tool |
|---|---|---|---|
| **Code Agent / recette sur code env 3.11** | 3.11 | ✅ **utilisables** (`import langchain` OK) | `create_agent`, `StateGraph`, un LLM Mesh enveloppé en chat model LangChain\*, ou APIs Mesh |
| **Backend webapp OWIsMind** (et tout contexte 3.9) | 3.9.23 | ❌ **interdits** | **stdlib-only**, APIs Dataiku natives (LLM Mesh / agent tools) **directement**, **aucun** `import langchain` |

> \* L'import exact `DKUChatModel` (`dataiku.langchain.dku_llm`) est **non confirmé** contre la doc publiée — préférer `llm.as_langchain_chat_model()` ; cf. `references/dataiku-code-agents.md`.

**Ne JAMAIS importer `langchain`/`langgraph` dans un contexte 3.9.** Si du code agentique doit tourner côté backend 3.9, on appelle le LLM Mesh / les agents / les tools **via les APIs Dataiku** (cf. `references/dataiku-code-agents.md` et le pattern `get_agent_tool().run()` dans `references/code-patterns-dataiku.md`).

### 2. Vérité des versions (les vieux tutos mentent)

`references/anti-patterns-deprecations-versions.md` fait foi. Corrections les plus piégeuses :

- `create_react_agent` est **déprécié** (LangGraph v1) → utiliser `langchain.agents.create_agent`. `AgentExecutor`/`initialize_agent` sont passés dans `langchain-classic`.
- `recursion_limit` par défaut = **25** (pas 1000) → augmenter via `config={"recursion_limit": N}`.
- `astream_events` version par défaut = **v2** (v3 = opt-in, ≥ 1.3).
- `durability` par défaut = **`'async'`** (le passer explicitement dans les exemples).
- `add_conditional_edges` **n'a pas** de paramètre `then=`.
- `claude-opus-4-8 / claude-sonnet-4-6 / claude-haiku-4-5` sont réels. `gpt-5.5`, `gemini-3.5-flash` = **non vérifiés** ici.

## Procédure (suivre dans l'ordre)

1. **Faut-il vraiment un agent ?** Un seul appel LLM ? un **workflow** déterministe (chaining/routing/parallel/orchestrator-workers/evaluator-optimizer) ? ou une vraie **autonomie** (le modèle choisit ses étapes/outils) ? → `references/panorama-et-decision.md`.
2. **Choisir le niveau d'abstraction** : `create_agent` (boucle modèle+outils+middleware) → LangGraph (graphe d'état explicite, parallélisme, interruptions, reprise) → Dataiku Visual/Code Agent (enveloppe entreprise). Puis **choisir le runtime Python** (encart ci-dessus). → `references/panorama-et-decision.md`, `references/dataiku-code-agents.md` ; **starters prêts à coller (3.9 ET 3.11)** → `references/code-patterns-dataiku.md`.
3. **Concevoir les outils en premier** (l'ACI : nom/description/schéma/erreurs = surface la plus rentable). → `references/tools-et-tool-design.md`.
4. **Architecturer le contexte et le prompt** (pas un prompt monolithique : context engineering, templates déterministes vs LLM, anti « règles par bug »). → `references/prompting-et-determinisme.md`.
5. **Décider mémoire/état** (checkpointer court terme, Store long terme, idempotence sous retries). → `references/memoire-persistance-hitl.md`.
6. **Orchestrer** si multi-domaines (superviseur / sous-agents-comme-outils / handoffs ; pare-feu d'honnêteté : router, ne jamais inventer un fait métier). → `references/orchestration-multi-agents.md`.
7. **Forcer des sorties structurées** dès qu'une sortie est consommée par du code (texte libre = exception). → `references/langchain-v1.md`.
8. **Exposer / streamer l'agent vers l'UI** : en DSS, SSE est bufferisé par le proxy nginx → **polling-via-thread** (start/poll/stop) sur runtime sync 3.9. → `references/async-concurrence-streaming.md`.
9. **Mettre sous gouvernance** : tracing, évaluation (réponse **et** trajectoire), guardrails, approvals, RBAC, sécurité (OWASP LLM Top 10), et **borner coût/latence par run** (quota). Écrire des **tests déterministes** des tools/nœuds + un **test anti-dérive** du registre/manifeste. → `references/eval-tracing-securite-production.md`.

## Quand utiliser ce skill / quand ne pas

- **Utiliser** : concevoir/auditer/implémenter un agent ou orchestrateur Python ; multi-agents ; tool design ; mémoire ; RAG ; MCP ; routing de modèles ; streaming d'agent ; tracing/éval/guardrails ; tout code agent Dataiku.
- **Ne pas surdimensionner** : un seul appel LLM sans outils ni état → pas besoin de framework agentique. Une tâche dont le flux est entièrement connu → workflow déterministe, pas un agent autonome.

## Aiguillage des références

| Besoin | Fichier |
|---|---|
| Workflow vs agent, choix de framework, arbre de décision | `references/panorama-et-decision.md` |
| LangChain v1, `create_agent`, middleware, structured output | `references/langchain-v1.md` |
| Design d'outils (l'ACI), `ToolRuntime`, erreurs, `tool_choice` | `references/tools-et-tool-design.md` |
| LangGraph : `StateGraph`, reducers, `Command`, `Send`, subgraphs | `references/langgraph-v1.md` |
| Mémoire, persistance, human-in-the-loop, exécution durable, idempotence | `references/memoire-persistance-hitl.md` |
| Orchestrateur + sous-agents, handoffs, pare-feu d'honnêteté | `references/orchestration-multi-agents.md` |
| Prompting, context engineering, déterminisme (templates vs LLM) | `references/prompting-et-determinisme.md` |
| RAG, retrieval, Dataiku Knowledge Banks, RAG guardrails | `references/rag-et-knowledge-banks.md` |
| MCP, `langchain-mcp-adapters`, Dataiku MCP / External Agents / Agent Hub | `references/mcp-et-integrations.md` |
| Sélection de modèles, routing, fallbacks, prompt caching | `references/modeles-routing-caching.md` |
| Async, concurrence, `Send` fan-out, streaming vers frontend (dont 3.9) | `references/async-concurrence-streaming.md` |
| Dataiku : LLM Mesh, agents visuels/code, tools managés, **double chemin Python** | `references/dataiku-code-agents.md` |
| Éval, tracing, observabilité, sécurité, gouvernance, checklist prod | `references/eval-tracing-securite-production.md` |
| Anti-patterns, dépréciations, vérité des versions (2026) | `references/anti-patterns-deprecations-versions.md` |
| Patterns de code prêts à l'emploi (3.9 ET 3.11) | `references/code-patterns-dataiku.md` |

## Red flags — STOP si tu te surprends à…

- …`import langchain` dans un contexte **Python 3.9** → utiliser les APIs Dataiku natives.
- …recommander `create_react_agent`, `AgentExecutor` ou `initialize_agent` comme la voie moderne → `create_agent`.
- …laisser le LLM **générer du SQL** libre ou inventer une valeur métier → templates déterministes / valeurs résolues (anti « règles par bug »).
- …faire dire à un routeur « cette donnée n'existe pas » → un routeur **route**, il n'émet pas de fait métier (pare-feu d'honnêteté).
- …confier le control-flow à une boucle de framework cachée que tu ne maîtrises pas → descends en `StateGraph` quand la topologie l'exige (12-factor : own your control flow).
- …écrire un nœud/outil à effet de bord **non idempotent** → un nœud peut être réexécuté après reprise (checkpoints aux frontières de super-step).
- …rendre du texte libre là où du code va le parser → structured output.
- …lancer une boucle d'agent **sans borne de coût/latence par run** ni quota → budgéter et plafonner (`references/eval-tracing-securite-production.md`).
- …brancher des tools/nœuds **sans tests déterministes** ni **test anti-dérive** du registre/manifeste (discipline P0 du projet) → écrire les tests d'abord.

## Sources

Synthèse réconciliée d'un corpus de recherche multi-agents (docs officielles LangChain/LangGraph/Dataiku/Anthropic, juin 2026) + une recherche ChatGPT, ancrée dans les patterns OWIsMind validés en DSS. Chaque fichier `references/` porte ses URLs de source inline ; les claims non confirmés sont marqués `UNVERIFIED`.
