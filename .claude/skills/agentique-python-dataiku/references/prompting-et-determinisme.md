# Prompting, context engineering & déterminisme (templates vs LLM)

> À jour : juin 2026 (LangChain 1.x, LangGraph 1.x, Dataiku DSS 14.x). Référence du skill `agentique-python-dataiku` — voir `SKILL.md` (parent). Réfs croisées : `references/langchain-v1.md`, `references/langgraph-v1.md`, `references/dataiku-code-agents.md`, `references/orchestration-multi-agents.md`, `references/eval-tracing-securite-production.md`.

La thèse de ce fichier : en 2026, **le prompting n'est plus la rédaction d'un gros prompt système, c'est de l'architecture de contexte**, et la fiabilité vient de la **séparation explicite entre ce que le LLM a le droit de générer (langage, sélection contrainte) et ce que le code possède (valeurs exactes, SQL, formatage)**. Le corpus framework-agnostique (Anthropic / LangChain) et le retour de terrain OWIsMind (DSS-validé) convergent sur ce point ; là où ils divergent, le code-owned OWIsMind l'emporte sur les APIs/versions, la doc officielle l'emporte sur les signatures.

---

## 0. Contexte Python (à rappeler partout où la version compte)

L'instance Dataiku a **DEUX** code envs : **Python 3.9 ET Python 3.11**. Tous les patterns ci-dessous existent en deux variantes.

| Contexte | Règle | Conséquence prompting/déterminisme |
|---|---|---|
| **Code env 3.11** (≥ 3.10) | LangChain/LangGraph v1 importables. Un Code Agent affecté à un env 3.11 peut `import langchain`. | System prompt / structured output / middleware via les APIs LangChain. |
| **Contexte 3.9** (backend webapp OWIsMind, 3.9.23) | **stdlib + `dataiku` uniquement, AUCUN import langchain.** Appel LLM Mesh / agents / tools via les APIs Dataiku natives. | System prompt assemblé à la main ; JSON mode via `with_json_output` ; pas de `create_agent`. |

**Ne jamais recommander d'importer langchain en contexte 3.9.** Les agents OWIsMind validés (`dataset_expert_agent.py`, `orchestrator_agent.py`) sont des fichiers standalone stdlib-only, collés dans DSS — c'est le modèle de référence pour le 3.9.

---

## 1. Le system prompt d'agent : rôle, contraintes, conditions d'arrêt, contrat de sortie

### 1.1 La « bonne altitude »

Viser entre deux échecs : la **logique if/else figée et fragile** d'un côté, le **guidage vague qui présume un contexte partagé** de l'autre. Le prompt optimal est « specific enough to guide behavior effectively, yet flexible enough to provide the model with strong heuristics ». Méthode : **partir d'un prompt minimal sur le modèle le plus fort, puis ajouter des instructions au fur et à mesure des modes d'échec observés** — « the minimal set of information that fully outlines your expected behavior ». (source : https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)

### 1.2 System prompt vs tour utilisateur

> « Your system prompt should contain only the rules, role, and constraints that apply to every single response in the session. Anything task-specific belongs in the user message, not the system prompt. Keeping your system prompt lean means it stays in active context longer. » (source : https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)

Pour un workflow multi-étapes : **injecter un bloc de contexte au début de chaque nœud de tâche** pour ré-ancrer le modèle sur l'objectif courant — une ou deux phrases (rôle, but, format de sortie) suffisent. (source : idem)

Côté OWIsMind, c'est exactement le `pass_context` (opt-in) de l'orchestrateur : le préfixe utilisateur est reconstruit à **chaque** `/chat/start` et collé au message COURANT seulement, l'historique étant rejoué brut. La continuité conversationnelle est portée par ce bloc, pas par un system prompt qui grossit.

### 1.3 Les quatre sections d'un system prompt d'agent

| Section | Contenu | Snippet / règle |
|---|---|---|
| **Role** | une phrase oriente déjà ton/comportement | `system="You are a helpful coding assistant specializing in Python."` |
| **Constraints / guardrails** | ce qu'il peut / ne peut pas faire | voir §1.5 (conditions d'arrêt, confirmation) |
| **Stop conditions** | quand cesser d'appeler des outils et répondre ; quand demander à l'utilisateur ; quand confirmer avant une action destructive | voir §1.5 |
| **Output contract** | forme exacte de la réponse finale | dire **quoi faire** plutôt que **quoi ne pas faire** |

Organiser avec **balises XML ou en-têtes Markdown** (`<background_information>`, `<instructions>`, `## Tool guidance`, `## Output description`). Pour le contrat de sortie, préférer le positif : au lieu de « Do not use markdown », écrire « Your response should be composed of smoothly flowing prose paragraphs » (ou envelopper dans des balises XML qu'on dépouille en post-traitement). (source : https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices)

### 1.4 Être clair et direct ; motiver les règles

Règle d'or : « Show your prompt to a colleague with minimal context … If they'd be confused, Claude will be too. » Expliquer **pourquoi** une règle existe généralise mieux qu'un ordre nu : au lieu de `NEVER use ellipses`, écrire « Your response will be read aloud by a text-to-speech engine, so never use ellipses since the TTS engine will not know how to pronounce them. » (source : https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices)

### 1.5 Conditions d'arrêt, autonomie, confirmation

Sans guidage, les modèles récents « may take actions that are difficult to reverse ». Anthropic fournit un snippet de confirmation qui classe les actions **destructives** (`rm -rf`, `drop table`), **difficilement réversibles** (`git push --force`, `git reset --hard`) et **visibles de l'extérieur** (push, commentaire, message) comme nécessitant confirmation, avec la consigne « do not use destructive actions as a shortcut … don't bypass safety checks (e.g. `--no-verify`). » (source : https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices)

Cela mappe directement sur la règle OWIsMind « Safety instance Dataiku » et la posture SQL read-only : `SET LOCAL statement_timeout TO '30000'` + `SET LOCAL transaction_read_only TO on`, exécutés en `pre_queries` de `SQLExecutor2.query_to_iter` (`dataset_expert_agent.py:113-114`). La condition d'arrêt principale d'un agent OWIsMind n'est pas dans le prompt : **le LLM ne décide rien pendant l'exécution** (§5).

### 1.6 Sur-déclenchement sur les modèles récents

Opus 4.5/4.6/4.8 sont **plus** réactifs au system prompt. Les prompts écrits pour combattre le *sous*-déclenchement des anciens modèles **sur**-déclenchent maintenant. Dialer en arrière : remplacer « CRITICAL: You MUST use this tool when… » par « Use this tool when… ». Quand le thinking est **off**, Opus est « particularly sensitive to the word 'think' » — préférer « consider », « evaluate », « reason through ». (source : https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices)

### 1.7 Contrôle du sur-engineering

Tendance à over-engineer (fichiers en trop, abstractions inutiles, flexibilité spéculative). Contrer par des limites de portée explicites : « Only make changes that are directly requested or clearly necessary … Don't add error handling, fallbacks, or validation for scenarios that can't happen … The right amount of complexity is the minimum needed for the current task. » (source : idem)

---

## 2. Le context engineering comme levier dominant

### 2.1 Pourquoi le contexte est fini : context rot

Le modèle a un **« attention budget »** fini : « Every new token introduced depletes this budget. » Le **context rot** est la dégradation mesurable du rappel à mesure que la fenêtre se remplit — cause racine : l'attention transformer forme **n² relations par paire pour n tokens**, étirées à mesure que le contexte croît (les données d'entraînement penchent vers des séquences courtes). Maxime directrice : **« find the smallest set of high-signal tokens that maximize the likelihood of your desired outcome. »** (source : https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)

### 2.2 Les trois niveaux de contexte (cadrage LangChain, validé par la doc officielle)

LangChain découpe la discipline en trois — utile pour savoir *où* agir. (source : https://docs.langchain.com/oss/python/langchain/agents ; cadrage conceptuel ChatGPT, réconcilié avec la doc)

| Niveau | Contenu | Levier |
|---|---|---|
| **Model context** | prompt système, historique, outils, response format | altitude du prompt, trim/résumé, schémas d'outils discriminants |
| **Tool context** | ce que les outils lisent/écrivent dans `state` / `store` | `ToolRuntime` (caché du schéma), réponses d'outils high-signal |
| **Life-cycle context** | résumés, guardrails, logging | middleware : `before_model`, `wrap_model_call`, summarization |

Les agents « échouent plus souvent parce que le bon contexte n'a pas été passé au bon moment que parce que le modèle serait insuffisant ». Le prompting est donc une discipline d'**architecture du contexte**, pas la rédaction d'un prompt monolithique.

### 2.3 Récupération juste-à-temps (just-in-time)

Garder des **identifiants légers** (chemins, requêtes stockées, liens) et charger la donnée **à l'exécution via des outils**, comme la cognition humaine (on utilise des index, pas un corpus mémorisé). Hybride accepté : « retrieving some data up front for speed, and pursuing further autonomous exploration at its discretion. » (source : https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)

OWIsMind incarne ce principe : le **value index** (`{column_name, value, value_norm, occurrences}`) est interrogé par SQL à l'exécution pour mapper « algerie telecom » / « ipl » à la cellule exacte et sa colonne — **on ne charge jamais le corpus** (`build_value_index_recipe.py`, `_resolve_terms` `dataset_expert_agent.py:1850-1961`).

### 2.4 Trim / résumé / horizon long

| Technique | Mécanisme | Réglage |
|---|---|---|
| **Compaction** | résumer une fenêtre quasi pleine et réinitialiser | « maximize recall first, then iterate to improve precision » ; forme la plus légère = **tool-result clearing** |
| **Structured note-taking** | persister des notes hors fenêtre (mémoire agentique) | « persistent memory with minimal overhead » |
| **Sous-agents** | une fenêtre propre qui ne remonte qu'un **résumé condensé (~1 000–2 000 tokens)** | isole le contexte lourd du lead agent |

(source : https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)

Primitives Anthropic récentes (post-cutoff Jan 2026, à signaler) : **context editing** (élagage à base de règles dans le scaffold), **context awareness** (capacité restante après chaque tool call ; sur Claude 4.5/4.6 le modèle suit son budget restant — prévenir le modèle si le harness compacte, sinon il conclut trop tôt), **memory tools**, **programmatic tool calling** (le modèle orchestre des outils en **exécutant du code** : ~37 % de réduction de tokens sur tâches complexes, les résultats intermédiaires restent **hors contexte**). (source : https://www.anthropic.com/engineering/advanced-tool-use)

En DSS, ces leviers s'expriment via LangChain (env 3.11) — `SummarizationMiddleware`, sous-agents — ou à la main (env 3.9) : caps de résultat mirroirés localement (50×50 lignes×cols, 256 car./cellule, budget JSON 64k dans `dataset_expert_agent.py:116-121`), tool-result clearing manuel, résumé de synthèse en fan-out parallèle.

### 2.5 Coût en tokens des définitions d'outils

Les définitions d'outils **coûtent des tokens en continu**. Le prompt système caché de tool-use vaut p.ex. **290 tokens pour Opus 4.8** en `auto`/`none` et **410** en `any`/`tool` (les anciens modèles coûtent plus). S'ajoutent name/description/schema de chaque outil + chaque `tool_use` + chaque `tool_result`. Quand les définitions dominent le contexte (10+ outils ou > 10K tokens), marquer les outils rares `defer_loading: true` (Tool Search) : ~85 % de réduction de contexte, précision de sélection Opus 4.5 79,5 % → 88,1 %. (source : https://platform.claude.com/docs/en/docs/build-with-claude/tool-use ; https://www.anthropic.com/engineering/advanced-tool-use) — détail sélection/schémas d'outils : voir `references/dataiku-code-agents.md`.

---

## 3. Templates déterministes vs étapes générées par le LLM (l'anti-pattern central)

### 3.1 La règle architecturale

Évidence SOTA NL2SQL citée par le repo (L051) : **couche sémantique + templates déterministes ≫ SQL LLM libre (98-100 % vs 84-90 %)**. La conception robuste sépare le pipeline en **décisions bornées par le LLM** et **exécution déterministe possédée par le code** :

- **LLM** : *compréhension* et *sélection dans un ensemble de candidats contraint* (intent, quelle colonne, quelle entité) — via schémas stricts / enums, **jamais en texte libre**.
- **Code** : tout ce qui doit être exact — templates SQL, formatage numérique, résolution de valeurs contre un index réel, rendu final. Vérifier les valeurs choisies par le modèle contre la vérité terrain **avant** usage.

(source : https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents ; https://github.com/humanlayer/12-factor-agents factors 1/4/8)

### 3.2 Quand INTERDIRE au LLM de générer le SQL / les étapes

Le pipeline OWIsMind UNDERSTAND → RESOLVE → COMPOSE → QUERY → RENDER est la mise en œuvre de référence (`dataset_expert_agent.py`, `salesdrive_agent.py`). **La division du travail est le point :**

| Étape | Ce que fait le LLM | Ce que fait le CODE (déterministe) |
|---|---|---|
| **UNDERSTAND** | 1 appel JSON strict : scope, langue, intent, scénarios, période(s), axe group-by, top-N, **termes** bruts à résoudre | valider/dégrader le JSON contre le profil ; jamais faire confiance à une valeur inventée |
| **RESOLVE** | rien | ancrer chaque terme contre le value index par SQL (exact → fuzzy) ; politique d'ambiguïté ; clarification |
| **COMPOSE** | rien | construire le SQL ou la question sémantique depuis des **templates gelés** |
| **QUERY** | rien (ou, en `direct`/`custom` seulement, écrit du SQL gardé) | exécuter le SQL / appeler le tool sémantique ; capturer SQL + lignes |
| **RENDER** | une **phrase d'accroche**, chaque chiffre vérifié | formater table et montants par code ; fallback déterministe |

**Le LLM écrit du texte libre en exactement quatre endroits, tous bornés** (`dataset_expert_agent.py`) :
1. UNDERSTAND — JSON strict, enums **ancrées sur le profil** (`build_understand_schema:522-548`) : le modèle ne peut pas émettre un scénario qui n'existe pas.
2. La phrase d'accroche — vérifiée chiffre par chiffre (§3.4).
3. Le SQL d'intent `custom` uniquement (la longue traîne, ~10-20 %) — sous **SQL guard** dur.
4. La synthèse/capabilities de l'orchestrateur — contrainte aux résultats fournis / faits du registre.

**Tout le reste est en templates gelés** : 9 intents structurés → builders SQL déterministes (`build_sql:909-1038` : pivots scénario/période via `SUM(CASE WHEN … THEN … ELSE 0 END)`, `share_of_total` via `SUM() OVER ()`) ; la question sémantique composée de templates par intent (`build_semantic_question`).

### 3.3 Le moteur hybride semantic-tool (décision DSS-validée, L052)

Après A/B en DSS : **laisser le Semantic Model Query tool POSSÉDER le SQL**, et faire que toutes nos couches (profil, grounding, désambiguïsation) lui fournissent le meilleur contexte. `SQL_ENGINE = "semantic_tool"` est le défaut ; le moteur direct code-owned devient un **fallback technique** (`FALLBACK_TO_DIRECT`, `dataset_expert_agent.py:85-97`). Un résultat vide légitime n'est **pas** un échec (reste honnête `no_data`) — seul un échec *technique* déclenche le fallback (`:2170-2180`).

Composition gagnante (`build_semantic_question:1178-1298`) : **« la QUESTION USER MÈNE »** (verbatim en tête) → intent hint déterministe → **valeurs exactes groupées par colonne → sémantique `IN` par colonne, jamais `Product = A AND Product = B`** (le bug AND-impossible, `:1257-1276`) → règle d'énumération (lister plusieurs valeurs → OR + une ligne par item) → scénario/période explicites → note de destination (« retourne une table propre avec alias de colonnes, jamais de prose »). Extraction en mode Agent : **priorité de clés puis DERNIÈRE occurrence** (le texte final, pas le préambule « I'll start by exploring the schema… ») (`extract_semantic_payload:1364-1414`).

### 3.4 Pourquoi pas tout laisser au LLM

La génération libre de valeurs exactes réintroduit l'hallucination (§4) et rend la sortie invérifiable. **Les enums / schémas stricts convertissent « générer une valeur » en « sélectionner une valeur valide », ce que l'API peut *garantir*.** (source : https://developers.openai.com/api/docs/guides/function-calling) Pour la forme de la réponse finale, les structured outputs garantissent le contrat (voir `references/langchain-v1.md` et la doc Anthropic/OpenAI). Le seul endroit où le LLM *doit* générer est ce qu'un humain ferait aussi par jugement (phrasé, planification, désambiguïsation) — et même là, préférer des **templates gelés** pour tout ce qui est user-facing et load-bearing, le LLM ne remplissant que des slots.

**Trust boundary OWIsMind (RENDER) :** table et chiffres formatés **par code** (`build_table`, `format_number`), exacts par construction. Le LLM écrit seulement l'accroche, puis **chaque chiffre cité doit exister dans l'allowed-number set du résultat, sinon toute l'accroche est rejetée** et un fallback déterministe est utilisé (`verify_headline:1641-1650`, `allowed_number_set:1611-1638`). Le modèle n'introduit jamais un chiffre invérifiable.

---

## 4. Réduire les appels d'outils hallucinés

Une « tool hallucination » = choisir un outil inapproprié, appeler au mauvais moment, ou **inventer un nom de fonction inexistant**. (source : https://arxiv.org/pdf/2412.04141) Défenses, en couches :

1. **Désambiguïsation par conception** — outils à recouvrement minimal + le test de l'ingénieur humain (« If a human engineer can't definitively say which tool should be used, an AI agent can't be expected to do better »). Les ensembles d'outils ambigus *causent* les hallucinations de sélection. (source : https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
2. **Schémas stricts** — `strict: true` / structured outputs garantissent que les inputs matchent le schéma, éliminant les « hallucinations » d'arguments malformés. **Enums bornés** plutôt que texte libre partout où les valeurs sont finies. (source : https://developers.openai.com/api/docs/guides/function-calling)
3. **Garde-fou de validation de nom** — vérifier le nom de fonction choisi contre le registre des outils disponibles **avant** exécution ; rejeter les noms inconnus. (source : https://medium.com/@Nexumo_/7-guardrails-that-reduce-llm-hallucinations-78facbb0d560)
4. **Garder les schémas en contexte** — des schémas poussés hors fenêtre font halluciner des noms d'outils qu'on ne voit plus ; mitiger par gestion du contexte (§2) ou Tool Search.
5. **Chemins de pensée explicites** — exiger une raison d'une ligne + l'id de l'outil avant l'appel, et une courte observation après. (source : https://dev.to/monuminu/llm-agent-guardrails-the-engineering-playbook-for-taking-an-8b-local-model-from-53-to-99-on-18c)
6. **Prompt de grounding** — `<investigate_before_answering>` : « Never speculate about code you have not opened … Never make any claims about code before investigating … give grounded and hallucination-free answers. » (source : https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices)
7. **Demander, ne pas deviner, sur paramètre requis manquant** — Opus reconnaît mieux un paramètre manquant et le demande ; Sonnet/Haiku peuvent l'inférer. Si deviner est inacceptable, forcer la demande par prompt et **ne jamais utiliser un forced tool-choice qui préremplit une supposition**. (source : https://platform.claude.com/docs/en/docs/build-with-claude/tool-use)
8. **Règles néro-symboliques dures** — règles déterministes que le LLM ne peut pas outrepasser pour les actions à plus fort enjeu. (source : https://dev.to/monuminu/llm-agent-guardrails-the-engineering-playbook-for-taking-an-8b-local-model-from-53-to-99-on-18c)

### 4.1 L'analogue « sous-déclenchement » : le pare-feu d'honnêteté Expert Authority (L050)

Le symétrique du nom-d'outil halluciné est le LLM qui **nie/invente un fait métier au lieu de router** (« budget 2026 » → « I don't have budget data » sans appeler l'agent). Bug central confirmé sur 817 questions réelles. Fix architectural (pas seulement prompt), `orchestrator_agent.py:55-63, 665-674` :

- L'orchestrateur **N'AUTHORE JAMAIS un fait métier.** Le seul « non » permis est **« I have no agent for this DOMAIN »** (`CAPABILITY_GAP`) — *jamais* « the data does not exist » (ça, c'est l'appel de l'expert via `out_of_scope`/`no_data`). Dans le doute → **router**.
- `CAPABILITY_GAP` / `OUT_OF_SCOPE` = **templates déterministes sourcés du registre** (`render_non_business_text`, `build_capability_gap_answer`) — pas de surface de fait métier, par construction. C'est précisément parce que le texte libre laissait fuiter des faits hallucinés.
- `BUSINESS_DOMAINS` (carte noms-seulement) distingue un domaine *réel mais non staffé* (→ CAPABILITY_GAP honnête) d'une question *non-OWI* (→ OUT_OF_SCOPE). Un domaine devient « staffé » dès qu'un agent enabled le déclare — ajouter un agent ferme le gap **sans changement de prompt**.
- **Test anti-dérive** : importe le `KNOWN_PHASES` du sous-agent et échoue si la description planner re-rétrécit la portée (`test_manifest_antidrift.py`). L'invariant métier vit dans un **test**, pas dans la logique de l'agent (P3).

---

## 5. Thinking / reasoning + outils

- **Adaptive thinking** (`thinking: {type: "adaptive"}` + `output_config.effort` ∈ `low|medium|high|xhigh|max`) remplace l'extended thinking manuel. `budget_tokens` est **supprimé (400) sur Opus 4.7/4.8 et Fable 5**, deprecated sur Opus 4.6 / Sonnet 4.6. Migration : `thinking={"type":"adaptive"}, output_config={"effort":"high"}`. (`xhigh` ajouté en 4.7 ; `max` = tier Opus + Sonnet 4.6, pas Haiku.) (source : gap-version-recency-recheck-2026.md §5.2 ; https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices)
- **Réfléchir après les résultats d'outils** : « After receiving tool results, carefully reflect on their quality and determine optimal next steps before proceeding. »
- **Préférer le thinking général** (« think thoroughly ») aux listes d'étapes écrites à la main — « Claude's reasoning frequently exceeds what a human would prescribe ».
- **Contrôle du sur-thinking** (haute effort = beaucoup d'exploration) : « choose an approach and commit to it … avoid revisiting decisions unless new information contradicts your reasoning », ou baisser `effort`.
- **Incompatibilité dure** : le **forced tool use (`any`/`tool`) n'est PAS autorisé avec le thinking** — seuls `auto`/`none` sont permis ; `any`/`tool` lèvent une erreur. (source : https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools)
- **Le thinking interleavé est aussi un outil d'éval** : l'activer pour sonder *pourquoi* l'agent appelle (ou non) un outil et trouver les faiblesses de description. (source : https://www.anthropic.com/engineering/writing-tools-for-agents)
- ⚠️ **LangChain caveat** : `create_agent` + `response_format` a un `tool_choice="any"` codé en dur pour l'outil de structured output dans certaines versions 1.x, ce qui **casse la combinaison Anthropic thinking + structured output** (issue #35539). Pour une forme finale garantie, un dernier appel dédié `with_structured_output` est plus robuste. (source : https://github.com/langchain-ai/langchain/issues/35539) — détail : `references/langchain-v1.md`.

---

## 6. Few-shot pour l'usage d'outils

### 6.1 Exemples in-prompt

- Envelopper dans `<example>` / `<examples>`. **3–5 exemples**, **Pertinents, Divers (couvrir les cas limites), Structurés** : « A few well-crafted examples … can dramatically improve accuracy and consistency. »
- Pour les agents : **curer des exemples canoniques, ne pas énumérer chaque cas limite** — « examples are the 'pictures' worth a thousand words … curate a set of diverse, canonical examples ». (source : https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- Few-shot compose avec le thinking : mettre des blocs `<thinking>` dans les exemples pour montrer le motif de raisonnement.
- **Placement long-contexte** : pour 20k+ tokens, mettre les longs documents EN HAUT, la requête/instructions/exemples EN BAS — « Queries at the end can improve response quality by up to 30% ». (source : https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices)

### 6.2 `input_examples` sur l'outil lui-même (Anthropic, advanced tool use, 2025-11)

Exemples d'inputs schema-validés attachés à la définition de l'outil. Gros gain sur les params complexes/imbriqués/sensibles au format : **« Tool use examples improved accuracy from 72% to 90% on complex parameter handling. »** Chaque exemple doit valider contre `input_schema` (sinon 400) ; **non supporté pour les server tools** ; coût ~20–50 tokens (simple) à ~100–200 (imbriqué). (source : https://www.anthropic.com/engineering/advanced-tool-use ; https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools)

```json
"input_examples": [
  {"location": "San Francisco, CA", "unit": "fahrenheit"},
  {"location": "Tokyo, Japan", "unit": "celsius"},
  {"location": "New York, NY"}
]
```

En DSS (LLM Mesh), la disponibilité de `strict` / `input_examples` / `tool_choice` dépend du **modèle de la connexion Mesh sous-jacente** (provider-specific) — tester, ne pas présumer.

---

## 7. L'anti « rules-by-bug » (P3, L048) — non négociable

**Ne jamais coder en dur une valeur métier dans la logique d'un agent.** Cas inconnu → compréhension LLM contrainte à une liste de candidats, ou refus honnête — **jamais un patch par valeur**. Mandat utilisateur explicite. (source repo : `memory/LESSONS.md` L048 ; cohérent avec l'anti-hardcoding snippet Anthropic : « Do not hard-code values … implement the actual logic that solves the problem generally », https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices)

Comment c'est tenu concrètement (`dataset_expert_agent.py`, `orchestrator_agent.py`) :

| Au lieu de… | …faire |
|---|---|
| une liste « ne pas extraire X » codée en dur | stopwords **dérivés du profil** (labels/synonymes de métriques, scénarios, noms de colonnes) + petite liste d'opérateurs générique (`_term_stopwords:492-515`) |
| coder « gap vs budget » = ACTUALS-vs-BUDGET | scénario par défaut **lu dans le profil** (`:441-450`) — généralise sans hardcoding |
| patcher une valeur par cas de boucle de clarification | **mémoire conversationnelle** : `pass_context` (message assistant précédent + réponse user brute) + politiques génériques (préférence valeur-exacte, auto-pick par priorité de colonne) + round-trip **parseable** `VALUE (Column)` qui casse la boucle infinie (L048) |
| affirmer un invariant métier dans le code | l'asserter dans un **test anti-dérive** important `KNOWN_PHASES` (L050) |

> Généralisation v3 (L051) : l'expertise vient des **artefacts du Flow** — recette profiler (stats déterministes + 1 passe d'enrichissement LLM, **overrides humains appliqués en dernier et jamais écrasés**, `apply_overrides`) et recette value-index. **Aucune valeur métier ne vit dans le repo** ; le code de l'agent est 100 % paramétré par les ids dataset/tool/LLM.

### 7.1 Tuning piloté par l'éval (pour que les règles viennent de preuves, pas d'un bug)

Construire des **tâches d'éval multi-outils réalistes** (« Customer ID 9182 reported being charged three times … find all relevant log entries and determine if other customers were affected »), pas des jouets ; tracker **accuracy, runtime, #tool-calls, token consumption, tool errors** ; puis **laisser un agent lire les transcripts et refactorer les outils en masse**. Éviter les **vérificateurs trop stricts** qui rejettent une bonne réponse sur la ponctuation. (source : https://www.anthropic.com/engineering/writing-tools-for-agents) C'est l'alternative disciplinée au patch d'une valeur métier par cas en échec. En DSS, l'équivalent gouverné = **Evaluate Agent recipe** (réponse + trajectoire) et **Agent Review** (cas de test + LLM-as-judge + feedback humain) — voir `references/eval-tracing-securite-production.md`.

---

## 8. Réconciliation corpus ↔ ChatGPT (accords / conflits)

| Point | Corpus (Anthropic/LangChain + OWIsMind) | ChatGPT | Verdict |
|---|---|---|---|
| Prompting = architecture de contexte | thèse centrale, sourcée Anthropic | même cadrage (3 niveaux model/tool/life-cycle) | **accord** — adopter la taxonomie 3-niveaux de ChatGPT |
| Templates déterministes ≫ LLM libre | L051 (98-100 % vs 84-90 %), 12-factor 1/4/8 | « rendre le texte libre l'exception, pas la norme » | **accord** |
| Structured outputs par défaut | doc Anthropic/OpenAI, garanties de schéma | « JSON/Pydantic pour éviter le parsing fragile » | **accord** |
| `create_react_agent` | **déprécié** en LangGraph v1 → `langchain.agents.create_agent` | idem (filtrer les patterns obsolètes) | **accord** — section deprecated obligatoire |
| Mémoire court/long terme | checkpointer (thread) / store (durable) | idem + Additional Request Context Dataiku | **accord** ; le contexte additionnel DSS ≠ fenêtre LLM (ne pas confondre) |
| Versions/signatures | autoritatif (gap-recency) | jetons `citeturn` = faux, ignorer comme URLs | **corpus/recency gagne** sur APIs/versions |

Apports propres de ChatGPT retenus : taxonomie Dataiku (Simple/Structured Visual Agents, Code Agents, agent = « Virtual LLM » du LLM Mesh) et la notion de **context quarantine** des sous-agents (= sous-agents §2.4). Détail orchestration : `references/orchestration-multi-agents.md`.

---

## 9. « Quand utiliser quoi » (table de décision)

| Objectif | Utiliser |
|---|---|
| Contraindre la **forme de la réponse finale** | Anthropic `output_config.format` / OpenAI `response_format` json_schema (strict) |
| Garantir des **arguments d'outil valides** | `strict: true` sur l'outil/fonction + enums bornés |
| Forcer un outil, sans préambule, sans thinking | `tool_choice: tool`/`any` (+ `strict`) — **incompatible thinking** |
| Forcer un outil **et** garder du langage naturel | `tool_choice: auto` + instruction dans le message user |
| Beaucoup d'outils / définitions dominant le contexte | Tool Search (`defer_loading`) + namespacing |
| Params complexes/imbriqués qui perdent le modèle | `input_examples` sur l'outil ; few-shot |
| Boucle d'agent long-horizon | adaptive thinking + `effort` ; compaction ; note-taking ; sous-agents |
| **Valeurs métier exactes** | **code déterministe** (templates, value index) ; LLM ne sélectionne que dans des candidats contraints |
| Empêcher un refus inventé (router au lieu de nier) | pare-feu d'honnêteté : LLM n'authore jamais un fait ; refus = templates déterministes (§4.1) |
| Éviter le patch par valeur | mémoire conversationnelle + LLM contraint + test anti-dérive (§7) |
| Agent Python en DSS 3.11 | `create_agent` + middleware + bridge LangChain `llm.as_langchain_chat_model()` (import `DKUChatModel` **NON VÉRIFIÉ** — préférer `as_langchain_chat_model()`, voir `references/dataiku-code-agents.md` §3.10) |
| Agent Python en DSS 3.9 | standalone stdlib-only, `with_json_output`, templates, appels LLM Mesh natifs |

---

## 10. Anti-patterns (référence rapide)

1. **Bruit task-specific dans le system prompt.** Le garder aux rôle/règles/contraintes session-wide ; le détail de tâche va dans le tour user / bloc de nœud.
2. **Prompts « CRITICAL/MUST » agressifs sur modèles récents** → sur-déclenchement. Langage normal.
3. **Forcer un outil en attendant un préambule** — `any`/`tool` suppriment le langage naturel et cassent avec le thinking.
4. **Texte libre là où un enum convient** — convertir « générer » en « sélectionner » (garantissable).
5. **Laisser le LLM générer des valeurs exactes / du SQL load-bearing** — invérifiable + hallucinations. Templates + value index + vérification.
6. **Coder en dur une valeur métier / patcher une règle par cas** — mémoire conversationnelle + LLM contraint + test, jamais de patch par valeur (P3).
7. **Tout charger en amont** — context rot. Just-in-time + compaction/note-taking/sous-agents.
8. **Le LLM comme source de vérité des faits** — il traduit l'intention et compose ; le code/data déterministe est la vérité (Expert Authority).
9. **Faire confiance aveuglément au structured output agent-level en LangChain** — `tool_choice="any"` codé en dur ↔ thinking (issue #35539) ; préférer un `with_structured_output` final dédié.
10. **Relayer le préambule d'un tool en mode Agent** comme réponse — extraire par **priorité de clés + DERNIÈRE occurrence** (L052).
11. **Importer langchain en contexte 3.9** — interdit ; stdlib-only + APIs Dataiku natives.

---

## 11. Sources principales

- Anthropic — Effective context engineering for AI agents : https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- Anthropic — Writing effective tools for agents : https://www.anthropic.com/engineering/writing-tools-for-agents
- Anthropic — Advanced tool use (beta) : https://www.anthropic.com/engineering/advanced-tool-use
- Anthropic — Building effective agents : https://www.anthropic.com/research/building-effective-agents
- Anthropic — Prompting best practices : https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices
- Anthropic — Tool use / Define tools : https://platform.claude.com/docs/en/docs/build-with-claude/tool-use · https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools
- OpenAI — Function calling / Structured outputs : https://developers.openai.com/api/docs/guides/function-calling · https://developers.openai.com/api/docs/guides/structured-outputs
- LangChain — Agents / Tools (v1) : https://docs.langchain.com/oss/python/langchain/agents · https://docs.langchain.com/oss/python/langchain/tools
- LangChain — structured output + tool_choice issue #35539 : https://github.com/langchain-ai/langchain/issues/35539
- HumanLayer — 12-Factor Agents : https://github.com/humanlayer/12-factor-agents
- Reducing Tool Hallucination (arXiv 2412.04141) : https://arxiv.org/pdf/2412.04141
- 7 Guardrails that reduce LLM hallucinations : https://medium.com/@Nexumo_/7-guardrails-that-reduce-llm-hallucinations-78facbb0d560 · LLM Agent Guardrails playbook : https://dev.to/monuminu/llm-agent-guardrails-the-engineering-playbook-for-taking-an-8b-local-model-from-53-to-99-on-18c
- Dataiku — Code Agent / tools LLM Mesh : https://developer.dataiku.com/latest/tutorials/genai/agents-and-tools/code-agent/index.html
- Repo OWIsMind (vérité terrain DSS-validée) : `dataiku-agents/agents/dataset_expert_agent.py`, `dataiku-agents/agents/orchestrator_agent.py`, `salesdrive/salesdrive_agent.py`, `memory/LESSONS.md` (L047, L048, L050, L051, L052)
- Recency/versions : `agentic-research/gap-version-recency-recheck-2026.md` (autoritatif)

> **Note de fiabilité.** Ids Anthropic `claude-opus-4-8` / `claude-sonnet-4-6` / `claude-haiku-4-5` = réels/courants. `gpt-5.5` / `gemini-3.5-flash` = **NON VÉRIFIÉS** (non-Anthropic). `astream_events` défaut = **`v2`** (`v3` opt-in, ≥ LangChain 1.3). `docs.anthropic.com` redirige (301) vers `platform.claude.com/docs`.
