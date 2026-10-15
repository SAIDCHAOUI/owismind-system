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
