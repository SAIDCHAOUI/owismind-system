# OWIsMind dev harness (simulateur local, hors plugin)

Un environnement de validation VISUELLE du frontend Vue, sans instance DSS : le
frontend du plugin est servi tel quel par un Vite dedie, et un backend MOCK
repond a toutes les routes `/owismind-api/*` avec les MEMES formats que le vrai
backend Flask (`python-lib/owismind`). Objectif : que Claude (ou un humain) ait
des yeux sur l'UI (Playwright, captures d'ecran) et puisse simuler un run
d'agent complet : timeline live, SQL genere, artefacts (chart / table / KPI),
Evidence Studio, Source Data Explorer, budget.

## Regle d'or

**Le code du plugin n'est JAMAIS modifie ni adapte au simulateur.** C'est le
simulateur qui se plie aux contrats du plugin (events normalises de
`agents/streaming.py`, transport polling de `agents/stream_manager.py`,
payloads de `evidence/service.py` + `evidence/chart_payload.py`, routes de
`api/routes.py`). Si un ecart apparait, on corrige LE MOCK, pas le plugin.
Le shim DSS (`window.getWebAppBackendUrl`) est injecte au moment du serve,
le `index.html` du frontend sur disque reste intact.

## Lancer

```bash
# depuis la racine du repo (node_modules du frontend requis, aucun install)
OWIsMind_PRD_V2_0/plugin/owismind/frontend/node_modules/.bin/vite \
  --config OWIsMind_PRD_V2_0/dev-harness/vite.config.mjs
# -> http://127.0.0.1:5199
```

## Ce que le mock simule

- `/me`, `/agents` (1 orchestrateur avec modes + 2 sources), `/usage` (budget),
  `/conversations` + `/conversation` (1 conversation seedee, prete pour Evidence).
- `/chat/start` + `/chat/poll` : run scripte et CADENCE dans le temps (narration,
  etapes timeline avec labels orchestrateur, `generated_sql`, artefact, deltas de
  reponse markdown avec tableau, `usage_summary`, `final_answer`, `run_done`).
  `/chat/stop` : arret cooperatif (reponse partielle + event `stopped`).
- Scenarios : question par defaut -> expert revenus (bar chart actuals vs budget
  par solution) ; message contenant `kpi` ou `total` -> artefact KPI.
- `/evidence/meta|rows|aggregate|distinct` : descripteur complet (chips editables,
  verification `calc_decomposed`, explication, result capture, artefacts avec
  payload Chart.js calcule cote serveur, drill-down) + re-requete du dataset.
- `/source/meta|rows|aggregate|distinct` : 2 datasets synthetiques (revenus ~640
  lignes, tickets ~130 lignes), filtres structures, recherche pliee aux accents,
  agregats (sum/avg/median/min/max/count/count_distinct, buckets temporels).

Les chiffres du chat, du chart, de la capture SQL et des re-requetes Evidence
sont calcules DEPUIS le meme dataset synthetique : tout est coherent.

## Donnees

100 % synthetiques et deterministes (PRNG seede, `mock/data.mjs`) : aucun compte,
revenu ou ticket reel. Rejouable a l'identique d'un run a l'autre.

## Fichiers

- `vite.config.mjs` : root = frontend du plugin, shim DSS injecte, middleware mock.
- `mock/api.mjs` : le routeur des routes `/owismind-api/*` (formats du vrai backend).
- `mock/scenario.mjs` : les runs scriptes + port JS fidele de `chart_payload.py`.
- `mock/data.mjs` : datasets + moteur de requetes en memoire (filtres, recherche,
  agregation, distinct) qui imite les formes SQL du backend.
- `.vite-cache/` : cache Vite du harness (git-ignore, jamais sous le plugin).

## V2 : espace de travail

Toute question métier joue le scénario multi-facettes `buildWorkspaceScenario` (plan 4 étapes,
2 experts, 3 SQL `s1q1/s1q2/s2q1`, 5 widgets, 4 notes, provenances) avec des events `workspace`
au format du backend (le poll retire les lignes capturées, comme le worker). `/workspace` et
`has_workspace` sont simulés ; la conversation seedée `sess-seed-ws-1` permet de tester la
restauration. Les runs V1.3 demandent le préfixe explicite « v1 » (« v1 total », « v1 détail »,
« v1 ... ») ; une salutation seule (« bonjour ») reste une réponse sans données.

Écran d'arrivée : aucun panneau imposé, seulement la zone d'appel (teaser) à droite ; un clic
ouvre les données de l'agent. Pendant un run, l'espace de travail s'ouvre de lui-même ; fermé,
le teaser le signale (accent orange). Sous 900 px de large, le panneau devient une feuille du bas.

## V2 : continuité du Studio (continuer ou nouveau)

Miroir du vrai backend (`mock/studio.mjs`) : `/chat/start` lit `screen_context.studio_exchange_id`
(simple pointeur, motif `^[A-Za-z0-9_-]{1,128}$`) ou, à défaut, le dernier échange de la
conversation qui a un Studio ; la base n'est retenue que si elle est dans la MÊME session, n'est
pas l'échange courant, n'est pas en cours et a des widgets. L'orchestrateur reçoit alors le bloc
`[CURRENT STUDIO ...]` (titres et types seulement, 1800 caractères max) et le jeton
`⟦owi:studio={"ids":[...]}⟧` ; l'id de la base ne passe jamais par l'agent.

- Scripté : avec une base valide, un message qui raffine l'écran (« garde », « ajoute »,
  « en dessous », « remplace », « ce graphique »...) joue le run CONTINUE : `studio.carry` (seq 1,
  déjà développé comme le relaie le worker), puis un texte de section et une courbe large liés au
  `s1q1` de CE run (même id que le `s1q1` de la base, exprès : les widgets portés se résolvent
  contre leur `origin`).
- Live / stub : outil `edit_studio(mode=continue|new, remove?)` exposé seulement avec une base,
  refus unique d'un `publish_widget` avant décision, ids alloués après les widgets portés,
  `replaces` sur `publish_widget`, `widget.remove` pour un retrait après coup. Le worker du mock
  remplace le `studio.continue` par le `studio.carry` (même seq). En `OWI_HARNESS_MODE=stub`, un
  2e tour « garde ce graphique et ajoute en dessous le même sur 2025 uniquement » rejoue le flux
  complet hors ligne.
- `GET /workspace` sert `origins: {exchange_origine: {resolved, provenance}}` et les
  `widgets_data` des widgets portés ; une origine absente = `orphan`.

## Mode live (Anthropic API)

Le simulateur peut faire tourner de VRAIS agents (Claude Haiku 5.5, `claude-haiku-5-5`) sur
des données synthétiques locales, pour tester le frontend de bout en bout sans Dataiku.

- **Clé** : créer `OWIsMind_PRD_V2_0/dev-harness/.env` (git-ignoré) avec
  `ANTHROPIC_API_KEY=sk-ant-...` (la variable d'environnement du même nom marche aussi).
  Clé présente -> mode `live` ; absente -> mode `scripted` (inchangé). `OWI_HARNESS_MODE=scripted`
  force le scripté, `OWI_HARNESS_MODE=stub` joue le chemin live avec un faux modèle (zéro réseau,
  zéro coût). Le mode actif s'affiche au démarrage (`[owi-harness] mode: ...`), la clé jamais.
- **Lancer** : même commande que ci-dessus, puis http://127.0.0.1:5199.
- **Ce qui est réel** : un orchestrateur (outils `set_plan`, `update_plan_step`,
  `call_revenue_expert`, `call_tickets_expert`, `publish_widget`, `add_note`, `final_answer`) et
  deux sous-agents (revenus sur `DRIVE_Revenues` + `Opportunities_Won`, tickets sur
  `TroubleTickets_year`) qui écrivent et exécutent leur SQL (`run_sql`). Les events (timeline,
  narration, `generated_sql` avec `sql_id`, `plan.set` / `plan.step` / `prov.set` / `widget.add`,
  deltas de réponse, `usage_summary` avec les vrais tokens) arrivent AU FIL de l'eau, au même
  format que le mode scripté (builders partagés `mock/events.mjs`).
- **Ce qui est simulé** : les données (3 tables `node:sqlite` en mémoire, seedées, déterministes :
  `public."OWISMIND_DEV_drive_revenues"` ~3000 lignes, `..._troubletickets_year` 1500,
  `..._opportunities_won` 500), le SQL (dialecte SQLite et non PostgreSQL, pas de modèle
  sémantique), la réponse streamée (le texte final est découpé en deltas). Evidence et Source Data
  re-requêtent ces tables (dataset trouvé par le `FROM`, chips depuis le `WHERE` quand il est
  simple, sinon condition avancée listée et niveau de vérification abaissé, honnêtement).
- **Garde-fous** : Haiku uniquement, `max_tokens` bornés, 12 tours max pour l'orchestrateur,
  6 par appel d'expert, plafond de tokens par run, délai max 4 min, détecteur de boucle,
  2 retries max (429 / 5xx), SQL en lecture seule (un seul SELECT, ni PRAGMA ni ATTACH,
  connexion `query_only`, worker avec timeout 5 s, 500 lignes max). `/chat/stop` arrête
  proprement. Tout dépassement finit par un event d'erreur honnête.
- **Coût** : Haiku 5.5 = 0,10 $ / M tokens en entrée, 0,50 $ / M en sortie. Une analyse complète
  coûte typiquement de l'ordre du centime ; le coût estimé de chaque run est loggé dans le
  terminal Vite et remonté dans `usage_summary`.

## Langue de réponse (mode live)

La langue de réponse est celle du DERNIER message utilisateur, pas celle de l'interface.
`mock/live/lang.mjs` est le portage fidèle de `agents/context.py` (même liste de mots, même
score, même bloc `[Context - ...] ⟦owi:lang=..⟧` + consigne `IMPORTANT - reply in ...`) :
`liveApi.mjs` calcule `promptLang` (langue de l'interface en arbitrage d'un message neutre comme
"42") et `userSuffix`, et les passe à `LiveTurn`. Test de parité Python / JS (aucun install) :
`node --test OWIsMind_PRD_V2_0/dev-harness/mock/live/lang.test.mjs`.
