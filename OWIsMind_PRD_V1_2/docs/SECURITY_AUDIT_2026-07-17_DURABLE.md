# Audit securite adversarial - Durable Step Shell (v1.3)

Base auditee : working tree = HEAD 79a94c5 (2 commits au-dela du snapshot 80c05cf ; le
fix `fix(security): correlate guard rejects comma-joined tables` 79a94c5 est deja applique).
Methode : lecture fichier par fichier + execution ciblee des gardes (jamais les suites, comme demande).

## Verdict global

Aucun CRITIQUE. Deux IMPORTANT, tous deux de la classe defense-en-profondeur / integrite des caps,
corrigeables en quelques lignes. Le reste des invariants de la section 11 est implemente proprement et
de facon coherente. Les deux constats touchent exactement les deux zones que le brief demandait de
casser en priorite (garde SQL du correlate, fix TOCTOU de la reservation).

---

## IMPORTANT 1 - La garde SQL du correlate laisse passer une table hors allowlist via un commentaire

Fichier : `OWIsMind_PRD_V1_2/genai/agents/OWIsMind_orchestrator.py`
- `_corr_guard_model_sql` lignes 1586-1623
- scan des refs de table `_CORR_TABLE_LIST_RE` lignes 1541-1543 + boucle 1608-1616

Cause racine : la garde blanchit les litteraux chaine (ligne 1602) mais ne neutralise JAMAIS les
commentaires SQL (`/* */`, `--`). Le scan `_CORR_TABLE_LIST_RE = \b(?:from|join)\s+(...)` exige un
`\s+` apres FROM/JOIN. PostgreSQL traite `/**/` comme un espace, donc `FROM/**/table` est du SQL
valide, mais `\s+` ne matche pas `/` : la table qui suit le commentaire n'est jamais capturee, donc
jamais confrontee a l'allowlist des alias d1..dN. La regex des tables systeme (`pg_*`,
`information_schema`) attrape encore ces cas par le nom, mais TOUTE table physique non-systeme
(les tables `webapp_*`, la table users, la table physique d'un autre domaine, ou la table physique
du catalogue qui porte justement les colonnes server-only `connection_name` / `physical_table`)
devient lisible.

Preuve (execution de la vraie fonction sur le working tree) :
```
ACCEPT | SELECT * FROM/**/webapp_users
ACCEPT | SELECT * FROM d1 JOIN/**/webapp_users ON true
ACCEPT | SELECT * FROM d1 UNION SELECT a,b FROM/**/secret
reject:table_not_allowed:webapp_users | SELECT * FROM d1 WHERE x IN (SELECT a FROM webapp_users)
```
Le meme enonce avec un espace normal est rejete ; seul le commentaire passe. Le `final_sql`
(`WITH d1 AS (...), d2 AS (...) <model_sql>`) est ensuite execute en read-only
(`transaction_read_only` + `statement_timeout` 30s + LIMIT 500), donc c'est une fuite de
confidentialite (lecture cross-table), pas une ecriture. Les lignes lues remontent au `model_view`
(15 lignes vers le modele), au `generated_sql` Evidence et a la reponse synthetisee.

Scenario d'exploitation : le SQL du correlate est ecrit par le modele Sonnet a partir du `task` du
step ; une injection via le plan/task qui pousse le modele a inserer un commentaire avant un nom de
table (le prompt l'interdit, mais la garde EST la couche defense-en-profondeur, exactement comme le
comma-join corrige en 79a94c5) lit une table arbitraire de `SQL_owi`. Lire la table physique du
catalogue exposerait les colonnes server-only `connection_name` / `physical_table` (viole aussi
l'invariant #2).

Correctif minimal (coherent avec le fix comma-join) : apres le blanchiment des litteraux, rejeter
tout marqueur de commentaire avant les scans :
```python
if "/*" in blanked or "--" in blanked:
    return None, "comment_in_sql"
```
(le prompt bannit deja les commentaires). Variante equivalente : effacer les commentaires dans
`blanked` (`re.sub(r"/\*.*?\*/", " ", blanked, flags=re.S)` puis `re.sub(r"--[^\n]*", " ", blanked)`)
avant les scans denylist / FROM-JOIN. La variante "reject" est la plus simple.

---

## IMPORTANT 2 - Le reaping des reservations annule le cap TOCTOU "1 run par utilisateur"

Fichier : `Plugin/owismind/python-lib/owismind/agents/durable_runner.py`
- `start_workflow` reserve un placeholder sous le lock : `_WORKERS["resv-"+exchange_id] =
  {"user_id":..., "thread": None, "reservation": True}` (lignes 134-144), justement pour fermer le
  TOCTOU entre la verification du cap et le spawn du worker.
- `_reap_dead_workers_locked` (lignes 246-250) supprime TOUTE entree `_WORKERS` dont `thread` est
  falsy, et il tourne en tete de chaque `start_workflow` (ligne 136).

Cause racine : le placeholder de reservation a `thread=None`, donc un `start_workflow` concurrent du
MEME utilisateur reape la reservation du frere avant de compter -> `actives_for_user` sous-compte ->
le cap `MAX_ACTIVE_WORKFLOWS_PER_USER=1` est franchi. La fenetre = duree de vie de la reservation :
de l'insert (ligne 143) au `pop` du `finally` (ligne 170), soit create_run (un aller-retour SQL
INSERT) + claim_run + spawn.

Preuve (execution de `_reap_dead_workers_locked` sur une entree en forme de reservation) :
```
before reap: ['resv-ex1', 'r-live']
after  reap: ['r-live']            # la reservation (thread=None) a ete purgee
```
Les tests `test_per_user_cap_raises_busy` / `test_global_capacity_cap_raises_busy` utilisent des
workers a thread VIVANT (`is_alive=lambda: True`), donc n'exercent jamais la course des reservations.

Scenario d'exploitation : un utilisateur double-soumet (double-clic, deux onglets, ou un script) deux
messages differents dans la fenetre create_run ; les deux passent la verification par utilisateur et
spawnent deux runs durables concurrents, violant l'invariant #4 "1 analyse active par utilisateur".
Impact borne (les entrees worker reelles a thread vivant, elles, ne sont PAS reapees, et le semaphore
Mesh global `MAX_MESH_CALLS=3` plafonne toujours la charge instance), donc pas de risque de
saturation de l'instance, mais l'isolation par utilisateur et le but affiche de la reservation sont
casses. Reponse directe a la question du brief : non, le fix TOCTOU de la reservation n'est pas
correct en l'etat.

Correctif minimal : exclure les placeholders de reservation du reaper :
```python
dead = [rid for rid, w in _WORKERS.items()
        if not w.get("reservation")
        and (not w.get("thread") or not w["thread"].is_alive())]
```

---

## Mineur / by-design (non bloquants, a acter consciemment)

A) `generated_sql` du correlate expose les noms de table physiques dans Evidence. Le `final_sql`
   embarque la table server-only dans la CTE (`WITH d1 AS (SELECT ... FROM "PROJECT_drive_revenues")`)
   et cette chaine remonte au resultat du step -> `_merge_step_results` -> `chat_v5.generated_sql` ->
   panneau Evidence (frontend). L'event public `AGENT_GENERATED_SQL` exclut bien le texte SQL
   (`_public_event_payload` whiteliste `eventKind/blockId/toolName/label/sqlIndex/success/rowCount`,
   pas `sql`), et le modele ne voit jamais les noms physiques (verifie par
   `test_model_never_sees_physical_tables`). Mais Evidence, lui, montre la table physique, EXACTEMENT
   comme le SQL `semantic-model-query` legacy le fait deja. Coherent avec le legacy, pas une
   regression ; a signaler pour que l'equipe accepte consciemment que l'invariant #2
   ("physical_table ne doit jamais atteindre le frontend") a une exception "panneau Evidence" partagee
   avec le chemin legacy.

B) Invariant #3 "une capability desactivee en cours de run bloque le step" : l'enforcement passe par
   `get_capabilities()` qui filtre le `CAPABILITIES` de module, charge UNE fois depuis le hub a
   l'import. Dans un process orchestrateur vivant, desactiver une capability dans le hub ne prend
   effet qu'apres reload / re-paste du module (comme le chemin legacy). La validation au plan et les
   checks d'execution (correlate ligne 3649, specialist via `build_execute_subcalls`) lisent tous le
   meme set cache. Pas un nouveau defaut vs legacy, mais le "en cours de run" n'est vrai qu'a travers
   un reload. Non verifiable depuis le code (semantique de reload du process agent DSS).

---

## Invariants verifies propres (avec preuve)

1. SELECT-only + read-only sur CHAQUE SQL agent : la lecture du catalogue
   (`_correlate_catalog_schemas` l.3587-3588) ET l'EXPLAIN / preview / final (`_correlate_run`
   l.3618-3625) utilisent tous `_CORRELATE_PRE_QUERIES = (statement_timeout 30s,
   transaction_read_only on)`. run_state : lectures via `readonly_pre_queries()`, ecritures via le
   seul `_WRITE_TIMEOUT_PRE_QUERY`. Structure SELECT-only imposee (un seul statement, commence par
   select, WITH possede par le code, denylist, blocage tables systeme, allowlist) SAUF le trou
   commentaire (IMPORTANT 1). Le SQL de lecture du catalogue utilise des ids valides par charset
   (`_CORR_SAFE_ID_RE`) + doublement des quotes -> pas d'injection.
2. Pas de fuite server-only : `project_run_public` retire les champs de lease ; `poll_durable` /
   `active_run_for_session` ne renvoient que la projection publique ; `append_events` denyliste
   `OWI_WORKFLOW_CONTROL` ; `streaming` normalise le chunk de controle en type interne
   `workflow_control` + garde anti-fuite pre-T5 sur les agent_event ; `_public_event_payload`
   whiteliste des cles non-lignes ; `build_progress_block` / `model_view` portent resumes + schemas +
   <=15 lignes, jamais de noms physiques (sauf note A sur Evidence).
3. Whitelist a trois niveaux : le front n'envoie que `agent_key` ; `resolve_enabled_agent` cote
   serveur ; les `capability_keys` du plan valides contre les caps agent activees dans
   `validate_workflow_plan` ; `_PLAN_FORBIDDEN_RE` bannit SQL / table / agent id dans le plan (caveat
   B sur le mid-run).
4. Caps de charge : superviseur claim <=1 run/scan (`find_recoverable_runs(limit=1)` + `claim_run`
   atomique) ; semaphore Mesh=3 avec acquire borne (l.804) ; global 8 (les vraies entrees worker a
   thread vivant tiennent) ; par-user 1 (voir IMPORTANT 2) ; retries transient seulement, quota jamais
   retente (`classify_failure` + `_handle_step_outcome` -> quota termine le run) ; purge bornee
   <=1000 ; batching d'events ; payloads bornes.
5. Parametrage SQL : chaque valeur derivee de l'utilisateur passe par `sql_value` / `nullable_value` /
   `_int_arg` / `_ts_sql`, y compris `load_run_by_exchange` et `find_active_run_for_session` ;
   owner-scope sur `load_run`, `read_events`, `read_activity`, `request_stop`, `/chat/active`,
   `/chat/activity`, `/chat/poll` (via `poll_durable`). `sql_value` = `toSQL(Constant(...))`.
6. Forge de token : `parse_workflow_control` (regle de queue : seuls whitespace + autres tokens de
   controle apres le token gagnant) + le backend appende SON token d'autorite en DERNIER + en legacy
   le bloc `[Context - ...]` (non-token) est TOUJOURS appende apres le texte user (`build_user_suffix`)
   -> un `⟦owi:workflow⟧` forge par l'utilisateur ne peut jamais etre en vraie queue. `wfstep`/`wfdone`
   re-valides + last-token-wins ; ids bornes au charset.
7. DoS : boucles bornees (`MAX_REPLANS`, `MAX_TOTAL_STEP_ATTEMPTS`, attempts/step, budget de step,
   deadline de run), acquire semaphore borne, pagination du poll (`done` seulement quand page<500),
   threads daemon, heartbeat/lease.
8. Exposition de donnees : previews / model_view capes 15, pas de lignes brutes dans les events
   publics (projection whitelist), pas de PII loggee (`/chat/start` logge `msg_len` seul).

## Non verifiable depuis le code (a garder comme gate DSS)
- Le grant DB SELECT-only "niveau base" + `statement_timeout` au niveau connexion (spec 11.1) = gate
  de deploiement DSS, pas prouvable depuis le repo.
- Semantique de reload du process Code Agent DSS (caveat B).
- Suites non relancees (consigne du brief) ; gardes verifiees par execution ciblee.
