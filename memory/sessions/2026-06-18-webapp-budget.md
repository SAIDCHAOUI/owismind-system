# Session 2026-06-18 (soir) - WEBAPP : suivi coûts/tokens + budget mensuel par utilisateur

> Session **webapp** (Plugin/owismind/). En parallele : une session **agents** (dataiku-agents/) et une
> session **doc** (project-documentation/, lecture seule). Aucun fichier hors `Plugin/owismind/` + ce
> fichier de notes n'a ete touche par cette session. **AUCUN commit / push** (interdit cette session,
> l'user committera demain matin).

## Objectif (demande user)
Terminer de brancher toute la partie **profil** + suivi de consommation : chaque utilisateur voit sa
conso en tokens et en argent, son suivi, sa limite et ce qu'il lui reste pour le mois. Credits de **50 $**
par mois glissant (calendrier), **reset le 1er du mois**. Etre transparent. Admin peut **augmenter le quota
d'un, plusieurs ou tous les utilisateurs**, de maniere **permanente ou temporaire**. Regle tables : **JAMAIS
d'ALTER**, nouvelle table versionnee si besoin (l'user gere la migration des anciennes donnees).

## Etat : CODE + TESTS + BUILD + ZIP PRETS. NON deploye en DSS (a faire au reveil).
- **422 tests backend** verts (`python3 -m unittest discover -s Plugin/owismind/tests`), dont **37 nouveaux**
  (`tests/test_budget.py`).
- **124 tests frontend** verts (`cd Plugin/owismind/frontend && node --test test/*.test.js`), dont **8 nouveaux**
  (`test/budgetModel.test.js`).
- Build Vite OK, zip **`Plugin/ready-for-dataiku/owismind-upload.zip`** = **79 entrees, `index-DeS8HQfW.js`**,
  propre (verifie), body.html recable.
- Revue adversariale (workflow 12 agents, 5 dimensions, chaque finding verifie) : **0 critical / 0 high**.
  2 defauts confirmes -> **corriges** (voir plus bas). Verdict final : production-ready.

## A FAIRE AU REVEIL (deploiement DSS - l'user seul)
1. **Upload le zip** `owismind-upload.zip` (79 entrees) dans le plugin DSS `owismind`.
2. **REDEMARRER le backend** de la webapp (python-lib a change : nouvelle table + routes budget).
3. **PAS de recoll d'agents** : les Code Agents (orchestrateur / sous-agent) n'ont PAS ete touches.
4. Smoke-tests :
   - Profil (Settings) : carte Budget (jauge depense/limite, restant, date de reset, ligne d'origine de la
     limite) + carte Usage (tokens du mois, depense, lifetime). Doit afficher des chiffres reels.
   - Poser quelques questions -> la depense du mois augmente, le restant diminue, le compteur de requetes monte.
   - Quand la depense atteint 50 $ : l'envoi est **bloque** (bouton + banniere transparente "budget epuise,
     reprise le <1er du mois prochain>").
   - Admin -> onglet **Quotas & budgets** : voir la table par utilisateur (depense du mois, limite effective,
     restant, origine), changer la **limite par defaut**, armer un **boost global temporaire** (montant + jours),
     selectionner des utilisateurs et leur appliquer une limite **permanente ou temporaire (7/30/90 j)** ou
     les **reinitialiser au defaut**.

## Architecture livree
### Backend (`Plugin/owismind/python-lib/owismind/`)
- **NOUVELLE table `webapp_user_quota_v1`** (`migrations.py`, `USER_QUOTA_V1_LOGICAL`, `ensure_user_quota_table`) :
  override par utilisateur `{user_id PK, limit_usd, expires_at (NULL=permanent), note, updated_at, updated_by}`.
  Creee lazy au 1er usage (CREATE IF NOT EXISTS). **Aucun ALTER** : le defaut global vit dans
  `webapp_settings_v1` (cle `monthly_budget`), le bucket mensuel `webapp_usage_monthly_v1` (deja la, Run 4)
  et les compteurs lifetime de `webapp_users_v1` (deja la) sont **inchanges**.
- **`storage/budget.py` (NOUVEAU)** : source unique de la resolution de limite.
  - Config globale `{limit_usd=50, enabled=true, temp_limit_usd, temp_expires_at}`.
  - Resolution : override utilisateur ACTIF > boost global temporaire ACTIF > defaut. "Actif" = `expires_at>now()`
    (NULL=permanent). Override teste cote SQL (horloge DB), boost global teste cote Python (horloge app) - documente.
  - `usage_status(user_id)` (1 lecture owner-scopee, LEFT JOIN bucket+quota+users), `has_budget` (gate, blocke
    quand `spent>=limit` et `enabled`), `admin_overview` (1 requete bornee tous users), `set_budget_config`
    (arm/clear/**preserve** le boost), `set_user_quotas`/`clear_user_quotas` (1 transaction).
  - **$50 + reset 1er** = `date_trunc('month', now())` (bucket par mois, nouveau mois = nouvelle ligne, pas de job
    de reset) ; `next_reset` = 1er du mois suivant.
- **`sql_builders.py`** : 4 builders purs (status, admin overview, quota upsert, quota clear). Valeurs escapees
  via `sql_value`, montants = litteraux numeriques serveur, jours int-coerces (anti-injection).
- **`security/validation.py`** : `validate_budget_amount` / `validate_expires_days` / `validate_user_id_list` /
  `validate_quota_note` (bornes, codes stables).
- **`api/routes.py`** :
  - Enforcement dans **`/chat/start`** : avant toute ecriture, **402 `monthly_quota_exceeded`** (payload budget) ;
    **fail-OPEN** sur erreur de lecture (la reponse prime, la depense est quand meme enregistree).
  - **`GET /usage`** : statut du mois pour l'appelant (owner-scope).
  - **`POST /admin/budget`** (config globale, **preserve** le boost si non touche) + **`GET`** (overview) +
    **`POST /admin/budget/users`** (set/clear override pour un/plusieurs/tous). Tout derriere `_admin_guard`.
- `sql_config.storage_status` liste la nouvelle table (visible cote admin Storage).

### Frontend (`Plugin/owismind/frontend/src/`)
- **`composables/budgetModel.js` (NOUVEAU, pur, teste)** : format $ / tokens / date, `usagePct`, `gaugePct`,
  `usageLevel` (off/over/warn/ok).
- **`stores/session.js`** : `usage` ref + `loadUsage()` (best-effort, dans init) + `budgetBlocked` computed.
- **`stores/chat.js`** : `canSend` bloque si `budgetBlocked` ; `loadUsage()` rafraichi apres chaque run ;
  sur la course 402, l'echange optimiste est retire (pas de bulle d'erreur vide), la banniere prend le relais.
- **`views/SettingsView.vue`** : vraies cartes Budget (jauge + restant + reset + ligne de transparence sur
  l'origine de la limite) et Usage (mois + lifetime). Plus de faux chiffres / etats "bientot".
- **`views/AdminView.vue`** : onglet **Quotas** reel (config globale + boost temporaire global + table par
  utilisateur + selection multiple + appliquer permanent/temporaire + reset). Selection = `reactive(new Set())`.
- **`views/ChatView.vue`** : banniere budget transparente + mapping d'erreur.
- **`services/backend.js`** : `fetchUsage`, `fetchAdminBudget`, `saveAdminBudget`, `saveAdminUserQuota`.
- **`i18n/extra.js`** : ~50 cles FR+EN (parite exacte), zero tiret cadratin/demi-cadratin (regle #9 verifiee).

## Corrections issues de la revue adversariale
1. **[MEDIUM corrige]** Admin ne pouvait pas sauver la limite par defaut quand un boost global temporaire etait
   actif (le form renvoyait montant+jours incoherents -> HTTP 400). **Fix** : decouplage. `POST /admin/budget`
   sans champ temp = **preserve** le boost actif ; bouton "Appliquer le boost" dedie (montant+jours) ; "Retirer"
   envoie `clear_temp`. Backend `set_budget_config(preserve_temp/clear_temp)`. + 4 tests.
2. **[LOW corrige]** Devise : `mode.envelope_note` disait "50 EUR/mois" alors que toute la feature est en $.
   Aligne sur "50 $" (FR+EN).
3. **[LOW corrige]** Import mort `formatTokens`/`tokensFmt` dans AdminView -> retire.

## Decisions / points a confirmer avec l'user (pas des blocages)
- **Devise = $** (le cout LLM Mesh `estimatedCost` est en USD ; l'user a dit "50 dollars"). Si facturation reelle
  en EUR souhaitee, c'est une conversion future (la donnee Mesh reste en $).
- **Les admins sont soumis au budget** comme tout le monde (ils peuvent se sur-allouer eux-memes). Choix uniforme ;
  a revoir si l'user veut exempter les admins.
- **Au 1er deploiement**, sans action admin, tout le monde a automatiquement **50 $/mois applique** (defaut). L'admin
  peut desactiver l'application (switch "enabled") pour suivre sans bloquer.
- Pas de page d'historique mensuel detaille (graphe par jour) : on montre mois courant + lifetime. Extension possible.

## Analyse de securite (workflow dedie 13 agents, 5 angles, findings verifies pour exploitabilite)
**Verdict : aucune faille exploitable Medium+.** Invariants OK : pas d'injection SQL (tout escape via
`sql_value`/litteraux numeriques serveur ; jours int-coerces avant `interval`), pas d'IDOR/escalade
(`/usage` + payload 402 = user des headers uniquement ; `_admin_guard` 1ere instruction des routes admin ;
aucun chemin pour qu'un user fixe son propre quota), pas de contournement d'enforcement (toutes les variantes
regenerate/edit/stop passent par le gate `/chat/start` ; fail-open non forcable car la lecture ne prend que
le user_id escape), pas de fuite d'info (codes d'erreur stables, note/contenu jamais loggue), frontend = pas
de `v-html` sur les donnees budget (tout en `{{ }}`/i18n).
6 findings LOW/INFO. **3 corriges cette session :**
- **#2 (LOW, DoS)** `/usage` n'avait pas de throttle -> ajout d'un **bucket token dedie**
  (`throttle.usage_can_accept`, 12 burst / 5/s, separe du bucket evidence) -> 429 `rate_limited`.
- **#3 (LOW, robustesse)** `validate_budget_amount` levait un `OverflowError` non capture sur un enorme entier
  JSON (`10**400`) -> 500 opaque ; **catch elargi** a `OverflowError` -> 400 `invalid_amount` propre. + tests.
- **#4 (INFO, defense en profondeur)** lectures/ecritures budget sans `statement_timeout` -> ajout de
  `SET LOCAL statement_timeout 30s` (+ `transaction_read_only` sur les lectures), calque sur `artifacts.py`/
  `evidence`. (NB : `set_user_quotas` retourne desormais `len(user_ids)`, pas `len(pre)`.)
**3 acceptes / documentes (pas corriges) :**
- **#1 (LOW, by-design)** TOCTOU concurrent sur `/chat/start` : depassement **borne** (~1 run au-dela de la
  limite, auto-convergent ; le spacing 1s/user le limite deja). Contrat fail-open/disponibilite assume.
- **#5 (INFO, ops)** echec **persistant** de `record_usage` (best-effort, swallowed) -> enforcement silencieusement
  off. Non declenchable par un attaquant (faute serveur) ; `chat_v5` reste la source de verite reconstructible.
  Suggestion future : log ERROR dedie / reconciliation periodique.
- **#6 (INFO, admin-only)** `set_user_quotas` peut inliner jusqu'a 1000 upserts (~0.9 Mo de SQL) en 1 transaction.
  Borne (`MAX_QUOTA_USERS=1000`), admin de confiance. Suggestion future : `VALUES ... ON CONFLICT` multi-lignes.

## Analyse RENFORCEE surete instance DSS / connexion SQL (workflow 18 agents, 5 angles, verifie)
**Verdict : AUCUN danger pour l'instance DSS ni la connexion `SQL_owi`. 0 finding dangereux.** Tout l'ajout
DB est en **O(1) sur PK**, borne par throttle + `statement_timeout` 30s, sur un executor frais emprunte/rendu
(pas de fuite de connexion, pas d'idle-in-transaction, identique au pattern valide `artifacts.py`/`evidence`).
Empreinte par action : `/chat/start` = +1 lecture budget (3 LEFT JOIN sur PK, anchor 1 ligne) **deja gatee par
`can_accept`** (1 s/user + cap 8) ; `/usage` = 1 lecture **gatee** par bucket dedie (12 burst / 5/s) ; admin =
lectures bornees `LIMIT 1000`, ecritures admin-only bornees (`MAX_QUOTA_USERS=1000`). Pas de boucle/retry/
recursion/resultat non borne ; pas de contention de verrous avec le chat (le chat ne fait que LIRE la table
quota ; les ecritures admin ne prennent que des `RowExclusiveLock` sur les lignes touchees). DDL = 1x/process.
**Durcissements appliques (non requis pour la surete, mais demandes "le plus safe possible") :**
- **Cache config en process (TTL 30s + invalidation a l'ecriture)** : supprime le **2e aller-retour DB** sur
  chaque envoi de chat et chaque `/usage` (le hot-path budget fait desormais **1 lecture**, plus 2). +3 tests.
- **`settings.get_setting` / `set_setting` durcis** au meme idiome (`statement_timeout` + `transaction_read_only`
  en lecture, `statement_timeout` en ecriture) : borne aussi la **resolution de whitelist d'agents** (deja sur le
  hot-path `/chat/start`, jusque-la non bornee). Module partage, changement purement additif (SELECT/UPSERT).
- **PAS de multi-row VALUES** pour `set_user_quotas` : creerait une requete unique ~0,9 Mo = exactement le risque
  de longueur de ligne CRU interdit par L013. Garde 1000 petites instructions (chacune ~900 o, log borne par ligne).
Items restants = info/cosmetique (sort borne ~50 lignes en work_mem ; logs DSS du bulk-save admin rare). 430 tests OK.

## Verifs reproductibles
- Backend : `cd Plugin/owismind && python3 -m unittest discover -s tests` (**430 OK** apres durcissements secu + instance).
- Frontend : `cd Plugin/owismind/frontend && node --test test/*.test.js` (124 OK).
- Build local sans toucher resource/ : `./node_modules/.bin/vite build --outDir /tmp/owi_bc --emptyOutDir` puis `rm -rf /tmp/owi_bc`.
- Tirets bannis : `LC_ALL=C grep -rlP '\xe2\x80\x9[34]' <fichiers>` -> doit etre vide.
- Zip : `Plugin/ready-for-dataiku/owismind-upload.zip` (79 entrees, `index-DeS8HQfW.js`), reconstruit apres les correctifs secu.
