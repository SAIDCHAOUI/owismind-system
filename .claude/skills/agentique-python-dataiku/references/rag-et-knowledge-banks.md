# RAG & retrieval (LangChain/LangGraph + Dataiku Knowledge Banks)

> À jour : juin 2026. Baseline : LangChain 1.x (`langchain-core` 1.4.7), LangGraph 1.x, Dataiku DSS 14.x. Référence consultable à la demande ; le parent est `SKILL.md`. Voir aussi `references/langgraph-v1.md` (graphes/cycles), `references/dataiku-code-agents.md` (Code Agent, tools, `run()`), `references/eval-tracing-securite-production.md` (RAG guardrails, Agent Review).

---

## 0. Décider d'abord : RAG vs fine-tuning vs long contexte

Avant tout code retrieval, trancher le besoin. Corpus et source ChatGPT convergent : « rends `texte libre uniquement` l'exception » et garde la connaissance métier hors du code.

| Approche | Choisir quand | Éviter quand |
|---|---|---|
| **RAG / retrieval** | connaissance volumineuse, qui change souvent, à citer/tracer, gouvernée ; besoin de fraîcheur et d'attribution de sources | un fait unique stable ; latence ultra-critique sans corpus |
| **Long contexte** (stuff brut dans le prompt) | corpus petit/stable qui tient dans la fenêtre (Opus 4.8 / Sonnet 4.6 = **1M tokens, sans surcharge long-contexte**) ; pas de besoin d'index réutilisable | corpus large/dynamique (coût par requête + dilution de l'attention) |
| **Fine-tuning** | apprendre un **style/format/comportement**, pas des faits ; réduire des prompts longs répétés | injecter des faits qui changent (le modèle les fige et hallucine sur le périmé) |

Règle : *fine-tune le comportement, RAG les faits, long-contexte ce qui tient et ne bouge pas.* Les trois se combinent (un modèle fine-tuné sur le style + RAG pour les faits + un peu de contexte direct).

## 0bis. Deux architectures de retrieval (à trancher en second)

Distinctes — ne pas confondre :

1. **Retrieve-then-generate (une chaîne).** Toujours retrieve → stuff → generate une fois. Cheap, prévisible, latence minimale. Quand *toute* requête a besoin du corpus et la question est bien formée. C'est le RAG classique.
2. **Retrieve-as-a-tool (dans la boucle d'agent).** Le retriever est un **tool** ; le LLM *décide* s'il le faut, peut l'appeler N fois, reformuler, ou le sauter (chit-chat, hors-sujet). Plus d'appels LLM, mais gère le multi-hop, les follow-ups et le « faut-il vraiment retrieve ? ». C'est le **RAG agentique**.

Règle : FAQ figée → chaîne ; assistant général qui a *parfois* besoin du corpus → retriever-as-tool. L'orchestrateur OWIsMind fait déjà (2) : le pattern « Expert Authority » (router, ne pas nier) **est** la décision agentique d'appeler ou non le tool de retrieval. Le pipeline NL2SQL d'OWIsMind (UNDERSTAND → RESOLVE → COMPOSE → QUERY) est conceptuellement un retriever-as-tool : le Semantic Model + value-index jouent le rôle de corpus exact.

---

## 1. Le pipeline : chunk → embed → store → retrieve

⚠️ **Contexte Python (fait dur, l'instance a DEUX code envs).** LangChain/LangGraph v1 exigent **Python ≥ 3.10** → import possible **uniquement dans un code env 3.11** (un Code Agent à qui l'on assigne le 3.11 peut importer `langchain`/`langgraph`). Le **backend webapp OWIsMind tourne en Python 3.9.23** : en contexte 3.9, **stdlib-only, AUCUN import langchain** — appeler LLM Mesh / agents / tools via les APIs Dataiku natives (`get_llm`, `tool.run()`, `new_embeddings()`). Ne **jamais** recommander d'importer langchain en 3.9. Les §1–8 ci-dessous = chemin 3.11 ; le §9 donne les équivalents natifs Dataiku.

Pipeline canonique (source : [docs.langchain.com/oss/python/langchain/knowledge-base](https://docs.langchain.com/oss/python/langchain/knowledge-base)) :

```python
# Chemin 3.11 (code env LangChain), PAS le backend 3.9
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.vectorstores import InMemoryVectorStore
from langchain.embeddings import init_embeddings

splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000, chunk_overlap=200, add_start_index=True
)
all_splits = splitter.split_documents(docs)            # docs: list[Document]

embeddings = init_embeddings("openai:text-embedding-3-large")  # factory provider-agnostique
vector_store = InMemoryVectorStore(embeddings)                  # in-process : tests / petits corpus
vector_store.add_documents(all_splits)

hits = vector_store.similarity_search("How many distribution centers...", k=4)
hits_scored = vector_store.similarity_search_with_score("Nike 2023 revenue", k=4)  # [(doc, score)]
```

- Un `Document` = `page_content: str` + `metadata: dict`. La metadata est **porteuse** : elle pilote le filtrage (§6) et la citation de sources.
- `init_embeddings` = miroir v1 de `init_chat_model` (factory provider-agnostique : `"cohere:..."`, `"huggingface:BAAI/bge-small-en-v1.5"`, `"ollama:nomic-embed-text"`, …). Chemin d'import à confirmer contre docs.langchain.com ([référence langchain embeddings init](https://reference.langchain.com/python/langchain/embeddings/init_embeddings)) — `init_chat_model` est vérifié (langchain/chat_models), `init_embeddings` est le pendant embeddings de la même factory v1. **Le modèle d'embedding qui indexe DOIT être celui qui interroge** — stocke-le à côté de l'index.

---

## 2. Stratégies de chunking (où se gagne/perd la qualité RAG)

Source : [text-splitters API](https://python.langchain.com/api_reference/text_splitters/markdown/langchain_text_splitters.markdown.MarkdownTextSplitter.html).

| Splitter | Quand |
|---|---|
| `RecursiveCharacterTextSplitter` | **Défaut recommandé.** Coupe sur une liste de priorité (`\n\n`, `\n`, ` `, `""`) → garde paragraphes/phrases entiers jusqu'à devoir trancher. `chunk_size`/`chunk_overlap` en caractères. |
| `RecursiveCharacterTextSplitter.from_language(Language.PYTHON, ...)` | **Code.** 24 langages avec séparateurs conscients du langage (fonctions/classes intactes). Idéal pour indexer une codebase. |
| `MarkdownHeaderTextSplitter` | **Markdown.** Coupe par hiérarchie de titres et **attache le chemin de titre en metadata** (un chunk sait qu'il vit sous `# H1 > ## H2`). Souvent suivi d'un re-split récursif. |
| `SemanticChunker` (`langchain_experimental.text_splitter`) | **Conscient du sens.** Détecte les ruptures de sujet par embeddings. Plus coûteux (embed pendant le split) ; pour la prose hétérogène. |
| `TokenTextSplitter` | Quand il faut respecter exactement un budget de tokens. |

```python
from langchain_text_splitters import RecursiveCharacterTextSplitter, Language
py_splitter = RecursiveCharacterTextSplitter.from_language(
    language=Language.PYTHON, chunk_size=800, chunk_overlap=80
)
```

Défauts pratiques : prose ~500–1500 chars, ~10–20 % overlap (empêche qu'une réponse soit coupée à la frontière) ; ajuster en **inspectant les chunks retournés**. `add_start_index=True` enregistre l'offset en metadata (highlighting/drill-down — même rôle que le value-index OWIsMind qui pointe vers les lignes source).

---

## 3. Store → retriever : `as_retriever()`

Un **Retriever** est un `Runnable` (`.invoke`, `.batch`, async). `as_retriever()` choisit la stratégie et ses réglages :

```python
# similarité simple (défaut)
retriever = vector_store.as_retriever(search_type="similarity", search_kwargs={"k": 4})

# MMR — Maximal Marginal Relevance : fetch_k candidats, retourne k pertinents ET diversifiés
retriever = vector_store.as_retriever(
    search_type="mmr", search_kwargs={"k": 5, "fetch_k": 20, "lambda_mult": 0.5}
)

# seuil de score : ne retourne que les hits assez proches (moins d'hallucinations)
retriever = vector_store.as_retriever(
    search_type="similarity_score_threshold",
    search_kwargs={"k": 5, "score_threshold": 0.4},
)
docs = retriever.invoke("query string")
```

- **`mmr`** corrige « 5 chunks quasi-dupliqués ». `lambda_mult` : 1.0 = pure pertinence, 0.0 = pure diversité.
- **`similarity_score_threshold`** peut légitimement retourner **zéro** doc → le code aval doit gérer « rien de pertinent ». C'est le signal de **refus honnête** (cf. OWIsMind P3, « router pas inventer »).

---

## 4. Exposer le retriever comme tool

### 4a. `create_retriever_tool` (cas standard)
Source : [create_retriever_tool](https://reference.langchain.com/python/langchain-core/tools/retriever/create_retriever_tool).

```python
from langchain_core.tools.retriever import create_retriever_tool

retriever_tool = create_retriever_tool(
    retriever,
    name="search_revenue_docs",
    description=(
        "Search the revenue knowledge base. Use for questions about revenue "
        "definitions, phases (actuals/budget/forecast), and metric methodology."
    ),
    document_separator="\n\n",   # join des docs dans la sortie string du tool
)
```

La **description EST le signal de routage** — le LLM décide d'appeler le tool dessus. Sois précis sur *ce qu'il y a dans le corpus* et *à quoi il sert* (analogue du registre-manifeste OWIsMind `{id,label,description,domain}` sur lequel l'orchestrateur route).

### 4b. Custom `@tool` (contrôle de la string retournée)
Le tutoriel officiel agentic-RAG utilise cette forme pour formatter/tronquer/attacher des citations :

```python
from langchain.tools import tool

@tool
def retrieve_revenue_docs(query: str) -> str:
    """Search and return revenue methodology docs."""  # docstring = description vue par le LLM
    docs = retriever.invoke(query)
    return "\n\n".join(d.page_content for d in docs)
```

`create_retriever_tool` pour le standard rapide ; `@tool` quand tu dois citer, plafonner la longueur, ou renvoyer de la metadata structurée.

---

## 5. Mieux retrouver : multi-query, parent-document, hybrid, rerank

> Beaucoup d'utilitaires retriever ont migré dans le namespace **`langchain_classic`** en v1 (l'ancien code utilisait `langchain.retrievers.*`). `langchain-classic` est en **maintenance jusqu'à décembre 2026**.

### 5a. MultiQueryRetriever — booster le recall
Le LLM réécrit la requête en N variantes, retrieve pour chacune, retourne **l'union** (dédup). Corrige « la formulation a raté le bon chunk ». Source : [MultiQueryRetriever](https://reference.langchain.com/python/langchain-classic/retrievers/multi_query/MultiQueryRetriever).

```python
from langchain_classic.retrievers.multi_query import MultiQueryRetriever
mqr = MultiQueryRetriever.from_llm(retriever=base_retriever, llm=llm, include_original=True)
docs = mqr.invoke("How does the system handle concurrent writes?")
```

Coût : +1 appel LLM par requête. Même intention que l'étape UNDERSTAND d'OWIsMind (question user → candidats résolvables).

### 5b. ParentDocumentRetriever — « petit pour chercher, grand pour lire »
Embed les **petits** chunks enfants (matching précis), retourne le **parent** plus large (contexte complet). Le vector store tient les enfants ; un docstore tient les parents. Source : [ParentDocumentRetriever](https://reference.langchain.com/python/langchain-classic/retrievers/parent_document_retriever/ParentDocumentRetriever).

```python
from langchain_classic.retrievers import ParentDocumentRetriever
from langchain.storage import InMemoryStore
from langchain_text_splitters import RecursiveCharacterTextSplitter

retriever = ParentDocumentRetriever(
    vectorstore=vector_store,                                    # indexe les enfants
    docstore=InMemoryStore(),                                    # tient les parents
    child_splitter=RecursiveCharacterTextSplitter(chunk_size=400),
    parent_splitter=RecursiveCharacterTextSplitter(chunk_size=2000),  # omis → parents = docs bruts
)
retriever.add_documents(docs)                                   # split + indexe les 2 niveaux
```

### 5c. EnsembleRetriever — hybrid (BM25 keyword + dense vector)
Combine un retriever **sparse/keyword** (BM25 — exact pour termes, codes, IDs, acronymes) avec un **dense/sémantique**, fusionnés par **Reciprocal Rank Fusion pondéré (RRF)**. Source : [EnsembleRetriever](https://reference.langchain.com/python/langchain-classic/retrievers/ensemble/EnsembleRetriever).

```python
from langchain_community.retrievers import BM25Retriever
from langchain_classic.retrievers import EnsembleRetriever

bm25 = BM25Retriever.from_documents(all_splits); bm25.k = 5
dense = vector_store.as_retriever(search_kwargs={"k": 5})
hybrid = EnsembleRetriever(retrievers=[bm25, dense], weights=[0.4, 0.6])  # weights = pondération RRF par retriever ; la constante RRF c≈60 est interne à EnsembleRetriever (pas réglée ici)
docs = hybrid.invoke("error code E1042 in the billing module")
```

L'hybrid est le **plus gros gain pratique** pour les corpus à jargon/IDs/codes — le pur sémantique perd les tokens exacts. C'est exactement pourquoi OWIsMind garde un **value-index exact** à côté du semantic model : le match exact pour les littéraux que l'embedding lisserait.

### 5d. ContextualCompressionRetriever + reranker — booster la précision
Over-fetch cheap (k≈20), puis un **cross-encoder reranker** réordonne par pertinence vraie et garde le top-n. Two-stage : recall rapide, puis précision exacte. Source : [Cohere reranker](https://docs.langchain.com/oss/python/integrations/retrievers/cohere-reranker).

```python
# Reranker hébergé (Cohere)
from langchain_cohere import CohereRerank
from langchain_classic.retrievers.contextual_compression import ContextualCompressionRetriever

compressor = CohereRerank(model="rerank-english-v3.0", top_n=3)
reranked = ContextualCompressionRetriever(
    base_compressor=compressor,
    base_retriever=vector_store.as_retriever(search_kwargs={"k": 20}),
)

# Cross-encoder local (sans API, modèle HF)
from langchain_classic.retrievers.document_compressors import CrossEncoderReranker
from langchain_community.cross_encoders import HuggingFaceCrossEncoder
compressor = CrossEncoderReranker(model=HuggingFaceCrossEncoder(model_name="BAAI/bge-reranker-base"), top_n=3)
```

Un bi-encoder (embeddings) score query et doc **séparément** ; un cross-encoder score la **paire conjointement** → bien plus exact, mais trop lent sur tout le corpus, d'où « retrieve large, rerank étroit ». `top_n` = ce qui survit dans le prompt.

**Empilement qui marche :** `EnsembleRetriever(BM25 + dense, k=20)` → `ContextualCompressionRetriever(reranker, top_n=4)` → `create_retriever_tool`. Hybrid pour le recall, rerank pour la précision, tool pour le contrôle agentique.

---

## 6. Filtrage par metadata (précision cheap, avant les vecteurs)

Restreindre l'espace de recherche par metadata structurée **avant** le ranking de similarité — plus rapide et plus correct qu'espérer que l'embedding capte une catégorie. Syntaxe spécifique au store ; PGVector utilise des opérateurs Mongo-style. Source : [PGVector](https://docs.langchain.com/oss/python/integrations/vectorstores/pgvector).

```python
results = vector_store.similarity_search(
    "billing changes", k=10,
    filter={"$and": [{"year": {"$gte": 2024}}, {"dept": {"$in": ["finance", "ops"]}}]},
)
retriever = vector_store.as_retriever(search_kwargs={"k": 5, "filter": {"dept": {"$eq": "finance"}}})
```

Pour des filtres **dérivés par le LLM** (« les docs finance de l'an dernier » → filtre structuré) : `SelfQueryRetriever` (le LLM émet query string + filtre metadata).

---

## 7. Vector stores de production

| Store | Import | Quand |
|---|---|---|
| `InMemoryVectorStore` | `langchain_core.vectorstores` | tests, petits corpus éphémères |
| `FAISS` | `langchain_community.vectorstores` | local, rapide, mono-process ; `save_local`/`load_local` |
| **`PGVector`** | `langchain_postgres` | **tu fais déjà tourner Postgres** (cas OWIsMind) |
| `Chroma` | `langchain_chroma` | dev local persistant |
| `Pinecone`/`Milvus`/`Qdrant`/Elasticsearch | pkgs `langchain_*` | managé / scale |

PGVector requiert **psycopg3** (driver `postgresql+psycopg://`, pas psycopg2) :

```python
from langchain_postgres import PGVector
vector_store = PGVector(
    embeddings=init_embeddings("openai:text-embedding-3-large"),
    collection_name="my_docs",
    connection="postgresql+psycopg://user:pw@localhost:6024/db",
    use_jsonb=True,
)
vector_store.add_documents(docs, ids=[d.metadata["id"] for d in docs])
```

Pour OWIsMind : une collection `PGVector` peut vivre dans le même Postgres que les tables SQL — **mais** respecter les règles maison : SQL-direct, pas de Flow au runtime, requêtes paramétrées, accès read-only, **pas de route SQL générique exposée**. (Et : ce code PGVector est un chemin **3.11** ; le backend 3.9 ne l'importe pas.)

---

## 8. RAG agentique en graphe LangGraph (la boucle corrective)

Pattern officiel « custom RAG agent » : le LLM décide de retrieve, les docs sont **gradés**, l'échec déclenche une **réécriture** + retry, le succès part en génération. Il faut des **cycles** → `StateGraph`. Source : [docs.langchain.com/oss/python/langgraph/agentic-rag](https://docs.langchain.com/oss/python/langgraph/agentic-rag). Voir `references/langgraph-v1.md` pour les primitives.

**Nœuds & flux**
- `generate_query_or_respond` — LLM avec `bind_tools([retriever_tool])` : émet un tool-call (retrieve) ou répond direct (pas de corpus).
- `retrieve` — un `ToolNode([retriever_tool])` préfab qui exécute le tool-call.
- `grade_documents` — LLM en **structured output** score la pertinence yes/no → route.
- `rewrite_question` — LLM reformule, reboucle.
- `generate_answer` — LLM répond depuis le contexte retrouvé.

```python
from typing import Literal
from pydantic import BaseModel, Field
from langgraph.graph import START, END, StateGraph, MessagesState
from langgraph.prebuilt import ToolNode
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage

response_model = init_chat_model("anthropic:claude-sonnet-4-6", temperature=0)
grader_model   = init_chat_model("anthropic:claude-haiku-4-5", temperature=0)

def generate_query_or_respond(state: MessagesState):
    return {"messages": [response_model.bind_tools([retriever_tool]).invoke(state["messages"])]}

class GradeDocuments(BaseModel):
    binary_score: str = Field(description="'yes' if relevant, else 'no'")

def grade_documents(state: MessagesState) -> Literal["generate_answer", "rewrite_question"]:
    question, context = state["messages"][0].content, state["messages"][-1].content  # [-1] = sortie du tool
    prompt = f"Question: {question}\n\nRetrieved:\n{context}\n\nRelevant? yes/no."
    score = grader_model.with_structured_output(GradeDocuments).invoke(
        [{"role": "user", "content": prompt}]).binary_score
    return "generate_answer" if score == "yes" else "rewrite_question"

def rewrite_question(state: MessagesState):
    q = state["messages"][0].content
    new_q = response_model.invoke([{"role": "user", "content": f"Rewrite for retrieval:\n{q}"}]).content
    return {"messages": [HumanMessage(content=new_q)]}

def generate_answer(state: MessagesState):
    q, ctx = state["messages"][0].content, state["messages"][-1].content
    prompt = f"Answer using only this context.\nQ: {q}\nContext:\n{ctx}"
    return {"messages": [response_model.invoke([{"role": "user", "content": prompt}])]}

def route_after_query(state: MessagesState):
    return "retrieve" if getattr(state["messages"][-1], "tool_calls", None) else END

wf = StateGraph(MessagesState)
wf.add_node(generate_query_or_respond)
wf.add_node("retrieve", ToolNode([retriever_tool]))
wf.add_node(rewrite_question)
wf.add_node(generate_answer)
wf.add_edge(START, "generate_query_or_respond")
# add_conditional_edges(source, path, path_map=None) — PAS de paramètre then=
wf.add_conditional_edges("generate_query_or_respond", route_after_query,
                         {"retrieve": "retrieve", END: END})
wf.add_conditional_edges("retrieve", grade_documents)              # -> generate_answer | rewrite_question
wf.add_edge("generate_answer", END)
wf.add_edge("rewrite_question", "generate_query_or_respond")       # le cycle correctif

graph = wf.compile(durability="async")   # défaut = "async" ; le passer explicitement
```

- `ToolNode` auto-exécute le tool appelé ; `with_structured_output(GradeDocuments)` force un yes/no parsable.
- L'arête `rewrite_question → generate_query_or_respond` est **la boucle** qui rend le système « agentique » (une chaîne ne peut pas).
- **Borne anti-boucle infinie** : le `recursion_limit` défaut est **25** (PAS 1000). Le relever **par invocation**, pas en touchant un défaut :
  ```python
  graph.invoke(inputs, config={"recursion_limit": 50})
  ```
- `astream_events` pour streamer le graphe : défaut **`version="v2"`** (`v3` est opt-in/expérimental, nécessite LangChain ≥ 1.3) — voir `references/langgraph-v1.md`.

### Variantes (même squelette, politique différente)
- **Corrective RAG (CRAG)** — à l'échec du grade, fallback **web search** au lieu de (ou avant) la réécriture ; re-grade et merge. ([blog LangChain](https://blog.langchain.com/agentic-rag-with-langgraph/), [DataCamp CRAG](https://www.datacamp.com/tutorial/corrective-rag-crag))
- **Self-RAG** — checks **post-génération** : la réponse est-elle *groundée* (pas d'hallucination) ? *adresse*-t-elle la question ? Sinon, régénère/re-retrieve. Ajoute des nœuds de réflexion après `generate_answer`. ([DataCamp Self-RAG](https://www.datacamp.com/tutorial/self-rag))
- **Adaptive RAG** — un nœud **router** classe d'abord la complexité et choisit la stratégie : no-retrieval / single-shot / itératif-correctif. ([Adaptive RAG](https://langchain-ai.github.io/langgraph/tutorials/rag/langgraph_adaptive_rag/))

Mapping OWIsMind v3 : grade-documents ≈ RENDER « vérifier la réponse contre les lignes capturées » ; rewrite-query ≈ COMPOSE re-templating ; la branche refus-honnête ≈ « score_threshold ne renvoie rien → router, ne pas inventer » (Expert Authority).

---

## 9. Angle Dataiku : Knowledge Bank ≈ retriever LangChain

Le **Knowledge Bank (KB)** Dataiku *est* un vector store + retriever managé. Source : [DSS vector stores](https://doc.dataiku.com/dss/latest/generative-ai/knowledge/vector-stores.html), [DSS 14 release notes](https://doc.dataiku.com/dss/latest/release_notes/14.html).

**Backends :**
- *Out-of-box :* Chroma (défaut), FAISS, Milvus (local), Qdrant.
- *Connection-backed (vector stores externes/non-managés) :* **pgvector**, Pinecone, Milvus (remote), Azure AI Search, Elasticsearch (≥7.14), OpenSearch (incl. AWS serverless), Vertex Vector Search. (External Vector Store support = **14.5.0** ; pgvector & Snowflake Cortex Search = **14.6.0**, 2026-05-25.)

**Search settings (équivalents des knobs `as_retriever`)** — source : [KB search settings](https://doc.dataiku.com/dss/latest/generative-ai/knowledge/kb-search-settings.html) :

| KB setting | Équivalent LangChain |
|---|---|
| Search type : similarity (cosine/euclidean/dot) | `search_type="similarity"` |
| Search type : MMR | `search_type="mmr"` |
| Hybrid (similarity + keyword ; Azure AI Search / Elasticsearch / Milvus) | `EnsembleRetriever(BM25 + dense)` |
| Reranking : natifs (Azure Semantic Ranker ; Elasticsearch/Milvus RRF) + model-based (HF Hub BGE-Reranker ; Cohere via Bedrock / MS AI Foundry) | `ContextualCompressionRetriever` + `CohereRerank`/`CrossEncoderReranker` |
| Metadata filtering | `filter={...}` (pgvector restreint les noms de colonnes metadata à alphanumérique + underscore) |

Reranking (introduit **14.0.0**, élargi en 14.4) s'applique **au RAG (Augmented LLMs)** *et* au **Knowledge Bank Search Tool** pour agents — i.e. le cas retriever-as-tool du §4. C'est le **gain de précision cheap** : l'activer dans les KB search settings.

**Accès programmatique** — récupérer un KB comme vector store LangChain + LLM Mesh comme chat model → bâtir le graphe du §8 par-dessus Dataiku. Source : [Programmatic RAG with LLM Mesh + LangChain](https://developer.dataiku.com/latest/tutorials/genai/nlp/llm-mesh-rag/index.html).

```python
# CHEMIN 3.11 (code env LangChain) — un Code Agent en 3.11 peut faire ça
# ⚠️ UNVERIFIED : tout le pont LangChain Dataiku ci-dessous (chemin d'import DKUChatModel,
# dataiku.KnowledgeBank(...), kb.as_langchain_vectorstore(), DKUChatModel(...)) est à confirmer
# au runtime / introspecter dans DSS — non confirmé contre la référence Python publiée (cf. §11).
import dataiku
from dataiku.langchain.dku_llm import DKUChatModel  # UNVERIFIED import path — introspecter dataiku.langchain en DSS

kb = dataiku.KnowledgeBank(id=KB_ID, project_key=project_key)   # UNVERIFIED — introspecter en DSS
vector_store = kb.as_langchain_vectorstore()                    # UNVERIFIED — LangChain VectorStore (à confirmer en DSS)
retriever    = vector_store.as_retriever(search_kwargs={"k": 4})  # tout §3–8 s'applique ensuite

llm = DKUChatModel(llm_id=GPT_LLM_ID, temperature=0)           # UNVERIFIED — modèle LLM Mesh, LangChain-compatible (à confirmer)
```

Un KB Dataiku tombe donc direct dans `create_retriever_tool(retriever, ...)` et dans le graphe agentic-RAG — les compétences LangChain transfèrent 1:1. DSS offre aussi un **Knowledge Bank Search Tool** no-code (= `create_retriever_tool`, hérite des mêmes search/rerank settings).

### Chemin Python 3.9 (backend webapp) — natif, sans langchain
En contexte 3.9, **ne pas importer langchain**. Le KB Search Tool reste un tool managé → l'appeler via l'API native :

```python
# CHEMIN 3.9 (backend Flask) — stdlib + APIs Dataiku, AUCUN langchain
import dataiku
project = dataiku.api_client().get_default_project()
tool = project.get_agent_tool(KB_SEARCH_TOOL_ID)
result = tool.run({"query": "actual revenue definition"})       # contexte hors-LLM via context=
chunks = result["output"]                                        # passages + sources

# embeddings natifs (sans langchain) :
emb = project.get_llm(EMBEDDING_MODEL_ID).new_embeddings()
emb.add_text("text to embed"); vectors = emb.execute().get_embeddings()
```

Détail du contrat `tool.run(input, context=…)`, `get_descriptor`, `as_langchain_structured_tool` → `references/dataiku-code-agents.md`. La whitelist côté serveur OWIsMind s'applique : le front envoie une clé logique, le backend résout l'id du tool/KB.

---

## 10. RAG guardrails (relevance, faithfulness)

Le LLM Mesh fournit des **RAG guardrails** qui évaluent une réponse vis-à-vis des extraits récupérés (source ChatGPT corroborée par les guardrails Mesh, voir `references/eval-tracing-securite-production.md`) :

- **Relevance** — les passages récupérés sont-ils pertinents pour la question ? (= le `grade_documents` du §8, mais côté plateforme).
- **Faithfulness / groundedness** — la réponse est-elle ancrée dans les extraits, sans invention ? (= la branche Self-RAG).

Les **Custom Guardrails** peuvent rejeter, modifier ou réécrire requête/réponse ; comme ils vivent dans le Mesh, ils s'appliquent **aux agents et tools**, pas seulement aux appels modèle bruts. Discipline d'ingénierie indépendante du framework : (1) seuil de score → autoriser un refus honnête (« rien trouvé »), (2) grader la pertinence avant de générer, (3) vérifier la groundedness après. C'est le pendant RAG de la règle OWIsMind P3 (« router pas nier ; jamais de fait métier inventé »).

---

## 11. Réconciliation corpus ↔ source ChatGPT

| Point | Verdict |
|---|---|
| KB = brique native RAG du LLM Mesh + intégration LangChain | **Accord** corpus ↔ ChatGPT. |
| Sorties structurées (Pydantic/JSON) plutôt que parsing fragile | **Accord** — appliqué au `grade_documents` (`with_structured_output`). |
| RAG guardrails relevance/faithfulness | **ChatGPT ajoute** le wording « relevance/faithfulness » ; cohérent avec les guardrails Mesh du corpus. Conservé. |
| `create_react_agent` (anciens tutos ReAct) | **Déprécié** en LangGraph v1 → `langchain.agents.create_agent` ; `AgentExecutor`/`initialize_agent` vivent dans `langchain-classic` (maintenance jusqu'à déc. 2026). Ne pas recopier les vieux squelettes ReAct. |
| Jetons `citeturn…` de la source ChatGPT | **Ignorés** (marqueurs internes, pas des URLs). URLs réelles = celles du corpus ci-dessus. |

**Non vérifié / à confirmer au runtime :** `project.get_semantic_model(...)` + `get_raw()`/`save()`/`versions` (project-internal, absent de la référence Python publiée — introspecter en DSS avant de s'y fier). **Pont LangChain Dataiku du §9** : `from dataiku.langchain.dku_llm import DKUChatModel`, `DKUChatModel(llm_id=..., temperature=0)`, `dataiku.KnowledgeBank(id=..., project_key=...)`, `kb.as_langchain_vectorstore()` — chemin d'import et signatures non confirmés contre la référence Python publiée ; introspecter `dataiku.langchain` en DSS avant de s'y fier (le tutoriel Dataiku RAG programmatique reste la source la plus proche, mais l'API exacte peut différer par version). `gpt-5.5` / `gemini-3.5-flash` (non-Anthropic, non vérifiés). Liens `docs.anthropic.com` → 301 vers `platform.claude.com/docs`.

---

## 12. Checklist builder

1. **Trancher RAG vs fine-tune vs long contexte** (§0) avant tout code.
2. **Chunker délibérément** — `RecursiveCharacterTextSplitter` par défaut ; `.from_language` pour le code ; markdown header splitter pour les docs ; metadata riche.
3. **Embedder une fois, interroger avec le même modèle** (`init_embeddings`).
4. **Store** : `InMemoryVectorStore`/`FAISS` en dev, `PGVector` (psycopg3) pour prod-sur-Postgres.
5. **Retrieve** : `similarity` k≈4 ; +MMR si redondant ; +`score_threshold` pour autoriser le « rien trouvé » honnête.
6. **Recall** → `MultiQueryRetriever` et/ou **hybrid** `EnsembleRetriever(BM25 + dense)` (vital pour IDs/jargon). **Précision/contexte perdu** → `ContextualCompressionRetriever` + reranker, et/ou `ParentDocumentRetriever`.
7. **Filtrer par metadata** avant la similarité dès que la requête a une structure.
8. **Exposer en tool** (`create_retriever_tool` ou `@tool`) — **la description est le routeur**.
9. **Décisions/boucles/multi-hop** → LangGraph `StateGraph` : grade → rewrite → retry, `recursion_limit` (défaut 25, relever par invocation), `durability="async"`. +web-fallback (CRAG), +grounding (Self-RAG), +router de complexité (Adaptive) au besoin.
10. **Dataiku 3.11** : KB → `as_langchain_vectorstore()` → pipeline identique ; activer le **reranking** dans les KB search settings (DSS 14) pour le gain de précision cheap.
11. **Dataiku 3.9 (backend)** : **jamais d'import langchain** ; KB/embeddings via `tool.run()` / `new_embeddings()` natifs ; whitelist côté serveur.
12. **Guardrails RAG** : seuil → refus honnête ; grade relevance avant génération ; vérifie faithfulness après.

---

## Sources (autoritatives d'abord)
- Semantic search / vector stores / splitters / `as_retriever` : https://docs.langchain.com/oss/python/langchain/knowledge-base
- RAG agent custom en LangGraph (grade/rewrite/ToolNode) : https://docs.langchain.com/oss/python/langgraph/agentic-rag
- `create_retriever_tool` : https://reference.langchain.com/python/langchain-core/tools/retriever/create_retriever_tool
- MultiQueryRetriever : https://reference.langchain.com/python/langchain-classic/retrievers/multi_query/MultiQueryRetriever
- ParentDocumentRetriever : https://reference.langchain.com/python/langchain-classic/retrievers/parent_document_retriever/ParentDocumentRetriever
- EnsembleRetriever (RRF pondéré) : https://reference.langchain.com/python/langchain-classic/retrievers/ensemble/EnsembleRetriever
- ContextualCompressionRetriever + CohereRerank : https://docs.langchain.com/oss/python/integrations/retrievers/cohere-reranker
- PGVector (langchain-postgres) : https://docs.langchain.com/oss/python/integrations/vectorstores/pgvector
- Text splitters : https://python.langchain.com/api_reference/text_splitters/markdown/langchain_text_splitters.markdown.MarkdownTextSplitter.html
- Adaptive RAG : https://langchain-ai.github.io/langgraph/tutorials/rag/langgraph_adaptive_rag/
- CRAG / Self-RAG : https://blog.langchain.com/agentic-rag-with-langgraph/ · https://www.datacamp.com/tutorial/corrective-rag-crag · https://www.datacamp.com/tutorial/self-rag
- Dataiku DSS vector stores : https://doc.dataiku.com/dss/latest/generative-ai/knowledge/vector-stores.html
- Dataiku KB search settings (reranking/hybrid/MMR) : https://doc.dataiku.com/dss/latest/generative-ai/knowledge/kb-search-settings.html
- Dataiku DSS 14 release notes : https://doc.dataiku.com/dss/latest/release_notes/14.html
- Dataiku RAG programmatique (LLM Mesh + LangChain) : https://developer.dataiku.com/latest/tutorials/genai/nlp/llm-mesh-rag/index.html
- `add_conditional_edges` (signature) : https://reference.langchain.com/python/langgraph/graph/state/StateGraph/add_conditional_edges
- `recursion_limit` (défaut 25) : https://docs.langchain.com/oss/python/langgraph/errors/GRAPH_RECURSION_LIMIT
- `astream_events` (défaut v2) : https://reference.langchain.com/python/langchain-core/runnables/base/Runnable/astream_events
