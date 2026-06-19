# PLAN WEBAPP - Scaling OWIsMind (Mission 1)

> Plan d'amélioration step-by-step / feature-by-feature de la **webapp** et de ses capacités.
> Produit en session multi-agents (6 lecteurs du code reel + 5 recherches etat de l'art + 4 personas + 5 architectes + 5 critiques adversariales). **Aucune implementation, aucun commit.**
> Pendant : `docs/scaling/.workdir/` (provenance brute, scratch supprimable).
> Plan jumeau : `PLAN_AGENTS.md` (factory de sous-agents). Quelques chantiers transverses (journal d'audit, reconciliation, semaphore de concurrence) vivent cote agents et sont references ici.

---

## 0. Thèse et regle de lecture

La webapp tient deja le plus dur (orchestration, grounding semantique, Evidence, artefacts chart/table/KPI, budget mensuel, charte). Ce qui fait la difference pour les 4 personas (account manager, product owner, directeur marketing, dirigeant), c'est **sortir la reponse de l'app** (telecharger, partager, mettre dans un deck, envoyer) et **garder la conversation en mouvement** (relances, comparaisons, decomposition). Une grande partie se livre **sans aucune installation** en reutilisant le resultat deja capture (`generated_sql[].result`) et l'instance Chart.js deja en memoire. Les morceaux lourds (PDF, email, voix) viennent plus tard, derriere installation explicite et derriere confirmation humaine (HITL).

**Chaque feature est decrite par 6 champs** : (a) ce que c'est, (b) valeur par persona, (c) approche technique avec les fichiers/seams reels, (d) effort (S/M/L) et installation eventuelle, (e) risque / surete instance / securite / charte, (f) dependances et phase.

**Deux statuts** sur chaque element technique :
- **VERIFIED** : prouve dans le code de cette session.
- **NEEDS-DSS-VALIDATION** : plausible mais a confirmer sur l'instance avant de parier l'archi dessus. On ne sequence jamais un "VERIFIED" sur une hypothese non prouvee.

---

## 1. Cinq verites transverses a graver (corrections de la revue adversariale)

Ces points priment sur toute carte de feature ci-dessous. Ils sont issus de la critique adversariale et corrigent des erreurs reelles dans les propositions initiales.

1. **Un export = l'EXTRAIT DE PREUVE plafonne (200 lignes), pas "les donnees brutes".**
   Le resultat capture est borne a `MAX_RESULT_ROWS=200`, `MAX_RESULT_COLS=50`, `MAX_RESULT_JSON_CHARS=100k` (`evidence/capture.py`), documente comme "a PROOF EXCERPT, not a data export". Donc tout PNG/CSV/XLSX construit dessus est un extrait. Regles : (i) **etiqueter visiblement** l'export comme "lignes vues par l'agent (extrait plafonne)", (ii) **ne JAMAIS re-executer le SQL de l'agent** pour "completer" l'export (viole le non-negociable #3 et charge l'instance), (iii) abandonner la promesse "donne au client la liste brute". Un vrai export complet est une feature distincte, gouvernee, paginee, off-peak (parquee en Phase 3+).

2. **Le panneau Evidence est une propriete de la SESSION webapp, pas du tool.**
   `show_chart`/`show_table`/`show_kpi` sont des fonctions in-process de NOTRE code agent qui emettent un evenement `ARTIFACT` sur le stream LangGraph, capte par NOTRE backend, joint au resultat capture cote serveur. Quadruple couplage (etat memoire `state["latest"]`, stream writer LangGraph, interpreteur de stream backend via `/chat/poll`, jointure de donnees). **Un agent visuel/etranger ne peut pas aujourd'hui peupler le panneau** : il n'a ni cet etat, ni stream, ni `exchange_id` dans notre schema. Cf. section 5.

3. **Ajouter un "kind" d'evenement ou d'artefact = bump de contrat GELE coordonne, pas un append.**
   L'allowlist des types de chart est verrouillee en **trois endroits** (`chart_payload.CHART_TYPES`, `streaming._ARTIFACT_CHART_TYPES` qui jette l'evenement avant stockage, et le `_validate` de l'orchestrateur + les chaines de prompt agent). Un nouveau kind impose une modif en lock-step de `streaming.py` + `storage/artifacts.py` (`_ARTIFACT_KINDS` + `_sanitize`) + le test anti-derive `KNOWN_*` cote agent + **recoll des 2 Code Agents (env 3.11)**. A budgeter comme un changement multi-fichiers, jamais "un item de plus".

4. **Le rendu cote serveur (PDF/XLSX/matplotlib) epuise un worker dans un backend mono-process.**
   Le backend est mono-process avec un petit pool ; le throttle `evidence/throttle` existant ne couvre PAS les nouvelles routes. Regles pour `/export` et `/report` : (i) **throttle dedie plus strict**, (ii) **semaphore global de rendu** (max ~2 en vol, 429 au-dela), (iii) caps durs `MAX_PDF_CHARTS`, lignes embarquees, taille, (iv) **mesurer le temps de rendu sur l'instance** avant d'affirmer "< 1s" (l'import matplotlib a froid coute deja ~1s).

5. **Installs par environnement, et tout est a valider.**
   Backend = Python 3.9.23. Code Agents = env 3.11 separe. Un plugin agent tool = un 3e env, version non confirmee. `reportlab`, `matplotlib`, `openpyxl` = **demandes d'installation explicites a l'utilisateur** (non-negociable #1), par env, statut NEEDS-DSS-VALIDATION ("probablement present" n'est pas un fait). **Jamais WeasyPrint** (libs systeme pango/cairo). On prefere le PNG client `toBase64Image()` (deja charte) au rendu matplotlib serveur.

---

## 2. A SPIKER sur l'instance AVANT de parier l'archi (un apres-midi)

Ces tests debloquent ou tuent des branches entieres. A faire en premier, indépendamment des phases.

- **S1. Selection par un agent VISUEL d'un plugin tool.** Packager `attribute_lookup` en `python-agent-tools/` (cf. `dataiku-agents/tools/attribute_lookup_tool.py` qui implemente deja `BaseAgentTool`), l'installer, et confirmer qu'un **agent visuel** peut le selectionner dans le catalogue GenAI. Ce seul test valide toute la prémisse "exposer les tools" (Track A, section 5).
- **S2. Version Python de l'env d'un plugin tool.** Determine si `reportlab`/`openpyxl`/`matplotlib` y sont installables et compatibles.
- **S3. Handoff `exchange_id` + binding proprietaire.** Depuis une session webapp, passer `exchange_id` en entree d'un tool et confirmer que `invoke()` peut ecrire une ligne owner-scopee que `/evidence/meta` relit. **Critique securite** : valider que l'ecriture est liee au proprietaire par la **session authentifiee** (jamais par un `exchange_id`/`user_id` venant de l'input du tool) ; sinon c'est une ecriture cross-tenant (cf. section 6, B1). Si ce spike echoue, `render_chart` pour agents etrangers est mort : on se rabat sur "le tool renvoie du JSON, pas de panneau".
- **S4. Identite d'execution d'un tool appele depuis Flask.** `get_agent_tool(id).run()` depuis le backend tourne-t-il sous l'identite service ou sous l'utilisateur appelant ? Determine si la gouvernance d'acces par dataset est respectee.
- **S5. Presence reelle de `openpyxl`/`matplotlib`/`reportlab`** dans l'env backend 3.9 (`pip list` dans un notebook). Conditionne XLSX et PDF.

---

## 3. Feuille de route par phases

Ordre = valeur/effort, du gratuit-immediat au lourd-gated. Resume en fin de section.

### PHASE 0 - Quick wins, ZERO install (a livrer en premier)

**W0.1 - Telechargement PNG d'un chart (client-side)** [VERIFIED]
- (a) Un bouton de telechargement sur chaque chart, exporte exactement ce que l'utilisateur voit.
- (b) Account manager colle la courbe de revenus dans un deck QBR ; directeur marketing dans une revue de campagne ; dirigeant pour un slide board. C'est l'action "sortir ca de l'app" la plus demandee.
- (c) L'instance Chart.js existe deja dans `ArtifactChart.vue` mais `toBase64Image()` n'est jamais appele. Cabler l'icone `download` deja presente (`ui/icons.js`) : `const url = chartRef.toBase64Image('image/png', 1); const a = document.createElement('a'); a.download = name; a.href = url; a.click()`. Zero backend. Ajouter cle i18n `ev.chart.download` dans `extra.js` (fr+en).
- (d) **S, aucune install.**
- (e) Aucune charge instance (GPU navigateur). Charte : bouton `Button` carre, icone seule, pas d'orange, **aria-label fr+en** obligatoire (icone seule = AA sinon en echec). **Nom de fichier serveur-genere et sanitise** `owismind_<exchange_id>.png` ou whitelist `[A-Za-z0-9_-]` + longueur bornee (jamais interpoler titre/label modele dans l'entete, cf. section 6 H3). Le PNG est deja charte (couleurs resolues des tokens) : c'est aussi la source recommandee pour le chart embarque dans un PDF (section Phase 2), plutot qu'un re-rendu matplotlib off-charte.
- (f) Aucune. A livrer en premier (meilleur ratio valeur/effort de la mission).

**W0.2 - Export CSV de l'extrait capture (stdlib)** [VERIFIED, avec caveat #1]
- (a) "Export CSV" sur un resultat, sert l'extrait `generated_sql[].result` que l'agent a vu, **etiquete comme extrait plafonne**.
- (b) Account manager recupere les lignes par compte dans Excel ; product owner alimente son pivot. Supprime l'email "tu peux m'envoyer les chiffres bruts ?" - tant que la limite est claire.
- (c) Preferer le **chemin serveur** pour la fidelite (le store front ne contient que les lignes source paginees, pas le resultat). Nouvelle route sur la blueprint `api` : `GET /owismind-api/evidence/export?exchange_id=X&format=csv`. Reutiliser le **garde partage `_evidence_guard()`** (`routes.py`), charger le resultat capture comme `/evidence/meta`, serialiser avec `csv.writer` + `io.StringIO`, repondre `Response(text, mimetype='text/csv', headers=Content-Disposition)`. **WHERE explicite `exchange_id AND user_id`** (owner-scope, comme `read_artifacts`). `format` valide contre un **enum serveur** `{csv,xlsx,pdf}`. Cap `MAX_EXPORT_ROWS` (miroir des caps existants). La route ne prend QUE `exchange_id` + `format` (jamais table/colonne/connexion, non-negociable #3).
- (d) **S, aucune install.**
- (e) Lecture de JSON deja stocke, pas de SQL execute. **Bandeau de troncature visible** dans l'UI et premiere ligne du fichier ("extrait plafonne a N lignes"). Nom de fichier sanitise serveur. Throttle dedie (section 4). **Auditer chaque export** (section 6).
- (f) Depend du garde Evidence partage. Sous un menu "Export" carre (`ui/Menu`) commun avec W0.1.

**W0.3 - Bandeau soft-quota a 80%** [VERIFIED]
- (a) Un bandeau d'avertissement non bloquant AVANT le 402 dur a 100%.
- (b) Tous : evite l'arret brutal en plein milieu d'une analyse, donne de la marge.
- (c) `storage/budget.py` calcule deja depense/limite ; `/usage` le renvoie. Ajouter un champ `pct_used`, afficher un bandeau a >=80% (reutiliser le pattern du bandeau "epuise" existant). Probablement front-only.
- (d) **S, aucune install.**
- (e) Lecture seule. **Charte (correction critique)** : pas de bandeau orange plein (depenser l'accent rare orange sur une non-action entraine a ignorer l'orange). Texte noir + **un filet 1px orange a gauche** sur fond blanc plat, dismissible. Le 100% (402) garde le traitement fort existant.
- (f) Aucune. Phase 0.

**W0.4 - Socle d'export (route + throttle + semaphore + audit)** [VERIFIED]
- (a) L'epine dorsale partagee de tous les exports : une route parametree par `format`, un throttle dedie, un semaphore de rendu, l'audit.
- (b) Indirect (rend toutes les features d'export sures et sequencables).
- (c) Une route `/evidence/export` ou `format` est un parametre (csv maintenant ; xlsx/pdf = une branche, pas un nouvel endpoint). Throttle dedie (le `evidence_throttle` actuel ne couvre que `_evidence_guard`). Semaphore process-wide `max ~2` rendus en vol. Journal d'audit des exports (voir `PLAN_AGENTS.md` Phase 0, table `webapp_audit_v1`).
- (d) **S-M, aucune install.**
- (e) Toutes les regles #1 et #4 de la section 1 s'appliquent ici.
- (f) Socle de W0.2 puis Phase 1-2 (XLSX, PDF).

### PHASE 1 - Différenciateurs (zero/peu install)

**W1.1 - Reconciliation claim-vs-result en mode SHADOW (log-only d'abord)** [VERIFIED moteur, correction adversariale majeure]
- (a) Chaque nombre du recit est verifie comme present dans le resultat SQL capture ; le flag est d'abord **ecrit au journal, pas affiche**.
- (b) Le garde anti-hallucination #1 du produit : un seul faux chiffre revenu envoye a un dirigeant et l'adoption s'effondre. C'est l'ossature de confiance de tout le reste.
- (c) Passe Python 3.9 pure dans un nouveau `evidence/reconcile.py` (modeler sur `sql_explain.py` : pur, ne leve jamais), appele cote serveur a la finalisation de la reponse, la ou `generated_sql[].result` est deja joint (`evidence/service.py`). **Correction critique** : un `==` naif echoue (`1,2 M€` vs `1199847.3`). Il faut un extracteur numerique robuste + tolerance de format (reutiliser la logique de `format_number` mais en matcher bidirectionnel). **Donc : livrer en mode shadow** (ecrire `reconcile_flag` dans `webapp_audit_v1`), **mesurer le taux de faux positifs**, et n'exposer un badge utilisateur qu'une fois la fiabilite prouvee.
- (d) **M, aucune install.** Redemarrage backend.
- (e) Charge nulle (regex/string). **Renommer la sortie "verifie/non verifie vs source", pas "confidence"** : la reconciliation prouve la **tracabilite**, pas la justesse de l'analyse.
- (f) Prerequis a tout le reste cote confiance. Tres haut ROI. Le detecteur vit cote evidence/agents (cf. `PLAN_AGENTS.md` Phase 0).

**W1.2 - Chips de relance (deterministes depuis AGENT_RESULT)** [VERIFIED]
- (a) 2-3 questions de suivi cliquables sous chaque reponse.
- (b) Le plus gros levier d'engagement. Le directeur marketing qui ne connait pas le modele de donnees recoit la bonne question suivante ("vs trimestre dernier ?", "top 5 comptes ?"). Transforme un one-shot en conversation ; les dirigeants explorent sans apprendre la syntaxe.
- (c) Generer **deterministiquement** depuis `AGENT_RESULT {intent, resolvedFilters}` + les axes `Profile.groupable`, **sans appel LLM** (cout + latence + zero surface d'hallucination). Nouveau kind d'evenement `SUGGESTIONS` ajoute au contrat gele (cf. verite #3 : bump coordonne `streaming.py` + recoll agents). Rendu en chips charte par `MessageAgent.vue`, clic = `chat.send()`. **Correction** : contraindre les suggestions aux dimensions que le profil ET les filtres juste resolus confirment peuplees (eviter "top 5 comptes ?" qui presuppose 5 comptes). La variante LLM reste un flag **off par defaut**.
- (d) **M, aucune install.** Recoll agents.
- (e) Les suggestions sont des QUESTIONS, jamais des faits : pas d'hallucination. Charte : chips carrees, orange au survol seulement (pas d'etat plein orange par defaut).
- (f) Reutilise la plomberie d'evenements. Phase 1.

**W1.3 - "Explain this number" (decomposition)** [VERIFIED, backend deja la]
- (a) Cliquer un nombre du recit -> ouvre l'Evidence scope sur les lignes qui le produisent.
- (b) Confiance. Le product owner / dirigeant qui n'agira pas sur un chiffre qu'il ne peut pas defendre. Rempart contre "l'IA a invente".
- (c) Deja majoritairement construit : `evidence/sql_explain.py` + `capture.py` + `EvidenceCalc.vue`/`EvidenceResult.vue` + drill `/evidence/rows`. Le travail neuf = l'**interaction** : detecter les nombres dans le markdown de `MessageAgent.vue`, les lier au drill (ouvrir le panneau scope sur la ligne). Aucun SQL neuf (redérive du `generated_sql` stocke). **Correction** : commencer par les **valeurs KPI** uniquement (detecter tout nombre en prose est plus delicat - encore les formats), elargir ensuite.
- (d) **M, aucune install.**
- (e) Drill deja re-valide serveur (refuse > 8 cles). Pas de surface neuve.
- (f) Phase 1.

**W1.4 - Onglets Evidence : Trace + Cost (Dataset gate PII)** [VERIFIED]
- (a) Ajouter des onglets au panneau Evidence : trace de l'agent (timeline lisible), cout de cette reponse. (Le Dataset complet attend la gouvernance PII.)
- (b) Product owner (trace/debug), dirigeant (transparence cout), AM (donnees source).
- (c) `EvidencePanel.vue` utilise deja `ui/Tabs.vue`. Les donnees existent : trace depuis les evenements deja streames, cout depuis les colonnes usage de `webapp_chat_v5`. Composition de donnees existantes en onglets - faible risque. Onglets carres.
- (d) **M, aucune install.**
- (e) **L'onglet Dataset (lignes source) doit attendre la gouvernance PII** (section 6 H5) : c'est une copie durable potentiellement PII. Trace/Cost d'abord (pas de PII).
- (f) Phase 1.

**W1.5 - Export XLSX (extrait)** [NEEDS-DSS-VALIDATION install]
- (a) Branche `format=xlsx` de la route d'export : extrait capture -> classeur formate.
- (b) AM/finance : feuille formatee, typee, prete a pivoter (vs CSV brut).
- (c) Meme branche de route ; `openpyxl.Workbook()`, ecrire colonnes+lignes depuis l'extrait capture, un style d'entete, repondre en `application/vnd.openxmlformats...`. **Demander a l'utilisateur d'installer `openpyxl`** dans l'env backend 3.9 si absent (S5) - pur Python, pas de lib systeme.
- (d) **S, peut requerir une install (`openpyxl`).**
- (e) Meme cap `MAX_EXPORT_ROWS` (borne aussi la RAM). Meme etiquette "extrait". Throttle dedie.
- (f) Depend du socle Phase 0. Si install refusee : rester sur CSV, dropper XLSX.

### PHASE 2 - Livrables (install gated, HITL)

**W2.1 - Rapport PDF par template-fill (ReportLab)** [VERIFIED design, install requis]
- (a) PDF brande en un clic (recit + PNG du chart + tableau), **structure figee, le modele ne remplit que des slots texte/nombre**.
- (b) Account manager envoie au client un one-pager soigne sans toucher PowerPoint ; dirigeant : one-pager board-ready ; marketing : brief d'impact de campagne. Feature phare de la mission "plus de types de sortie".
- (c) **Discipline template-fill = la propriete de surete.** Templates versionnes **dans le plugin** (`python-lib/owismind/deliverables/templates/*.py`), jamais generes par le modele. Chaque module exporte `VERSION`, `SLOT_SCHEMA` (slots nommes + types + longueurs bornees), `render(slots, result, chart_pngs) -> bytes`. Le modele remplit les slots via `with_json_output` (chemin fiable, P0). **Decision : ReportLab** (pur Python, pip seul, AUCUNE lib systeme), pas WeasyPrint (pango/cairo). Chart embarque = le **PNG client `toBase64Image()`** poste au backend (deja charte), pas matplotlib (couleurs/geometrie off-charte par defaut). Nouvelle branche `format=pdf&template=client_one_pager` ; **reconciliation en GATE** (un nombre non verifie BLOQUE le PDF, abstention > hallucination, une fois le detecteur fiable). HITL preview avant generation.
  - Slots `client_one_pager` : `{client_name<=80, period_label<=40, headline<=200, kpis[<=4]{label<=40,value<=40}, narrative<=1200, chart_refs[<=2], footnote<=160}` (les `value` sont **echos du resultat capture**).
  - Slots `exec_summary` : `{title, period_label, tldr<=300, kpis<=6, risks[<=3]<=120, recommendation<=400, chart_refs<=3}`.
- (d) **L, install requise : `reportlab`** (et `matplotlib` SEULEMENT si un re-rendu serveur s'avere necessaire - a eviter).
- (e) **Surete instance (correction #4)** : rendu derriere throttle dedie + semaphore (max ~2), caps `MAX_PDF_CHARTS=3` + lignes, **mesurer le temps reel** avant "synchrone OK". **Charte (correction critique)** : le template embarque la **vraie image `orange-logo.png`**, jamais une marque redessinee en ReportLab (violation L092) ; **passe obligatoire de suppression des tirets longs** sur chaque slot rempli par le LLM (#9) ; filet carre, accent `#FF7900` sur la title-bar uniquement, Helvetica. **PII** : un PDF est une copie durable et transferable - appliquer la politique PII (section 6 H5) au point de serialisation + auditer l'export.
- (f) Depend de W0.1 (PNG), du kind `deliverable` (bump de contrat, verite #3), des modules template. Phase 2.

**W2.2 - Nouveaux types de chart charte-safe (combo / waterfall)** [VERIFIED, correction charte]
- (a) Etendre le vocabulaire au-dela de bar/line (waterfall = pont actuals->budget, combo = volume+taux).
- (b) Waterfall = pont budget (or pour les dirigeants) ; combo (marketing/PO).
- (c) `chart_payload.build_chart_payload` construit le payload Chart.js cote serveur - etendre avec de nouvelles branches `type`. **Correction verite #3** : l'allowlist de types est verrouillee en 3 endroits (`CHART_TYPES`, `_ARTIFACT_CHART_TYPES`, `_validate` orchestrateur + prompts) -> bump coordonne + recoll des 2 agents. Waterfall = astuce de barres empilees (pas de plugin Chart.js = pas d'install).
- (d) **M, aucune install** (Chart.js coeur seulement ; un plugin waterfall SERAIT une install -> a eviter).
- (e) **Charte (correction)** : pas de paire rouge/vert (off-charte + echec AA + daltonisme). Encoder la direction du delta par **position/label + un aplat sombre vs une barre "fantome" contour 1px** ; reserver `#FF7900` a la seule barre de total. Couleurs resolues des tokens.
- (f) Active W2.3. Phase 2.

**W2.3 - Intent "comparaison / vs periode precedente"** [VERIFIED, cote agent]
- (a) "vs trimestre dernier / vs budget / YoY" comme intent first-class -> reponse en delta + chart combo/waterfall.
- (b) La question que dirigeants et AM posent vraiment. Coeur de toute revue d'activite.
- (c) Ajouter `comparison` au set d'intents du sous-agent (UNDERSTAND genere du Profile). Le tool semantique comprend deja ACTUALS/BUDGET. RENDER emet un `show_chart` combo/waterfall (W2.2). Contrat gele : etendre `KNOWN_*` via le test anti-derive, jamais renommer. Recoll des 2 agents.
- (d) **M, aucune install.** Recoll agents.
- (e) Le "ne jamais sommer entre phases" est la calibration humaine intrinseque : reutiliser la semantique de scenario existante, ne pas la re-deriver. Reconciliation (W1.1) garde les deltas.
- (f) Avec W2.2 et W1.1. Phase 2.

**W2.4 - Brouillon d'email (HITL, aucun envoi serveur en v1)** [VERIFIED design]
- (a) Le modele remplit un template d'email -> une carte brouillon que l'utilisateur relit et envoie lui-meme.
- (b) AM : "envoie ce resume revenus au client" -> brouillon pret, edite puis envoye. Dirigeant : transferer un exec summary.
- (c) Sous-kind `email` du `deliverable`. Slots `{to_hint, subject<=160, body_text, attachment_refs}` - **structure FIGEE par le template, le modele remplit des slots TEXTE seulement**. **Correction securite/charte** : pas de `body_html` rempli par le modele (vecteur XSS) : le template possede tout le markup, le modele ne fournit que du texte ; la preview rend du texte, pas du HTML modele. La carte rend sujet+corps pour **revue** ; flag `requires_confirmation` cote serveur.
- (d) **M pour brouillon+preview, aucune install.**
- (e) **Aucun envoi depuis le serveur en v1.** Preview + "copier" + `mailto:` (texte seul) uniquement : zero install, zero surface d'envoi. Un envoi SMTP serveur est une decision SEPAREE et ULTERIEURE : creds SMTP en config admin (comme `sql_config`), allowlist de destinataires serveur (jamais un `to` choisi par le modele - anti-exfiltration), `requires_confirmation` par message gate serveur (#4), rate-limit + audit. **NE PAS** construire l'envoi serveur tant que l'utilisateur ne le demande pas explicitement (YAGNI + blast radius).
- (f) Depend du kind `deliverable`. Phase 2.

**W2.5 - Declenchement natif par l'agent (`build_report` / `draft_email`)** [VERIFIED pour notre orchestrateur ; NEEDS-DSS-VALIDATION pour agents etrangers]
- (a) Tools de l'orchestrateur pour qu'une reponse se termine par "j'ai prepare un PDF / un brouillon d'email".
- (b) Tous : le livrable arrive DANS la reponse, le produit devient agentique.
- (c) Ajouter `build_report`/`draft_email` aux specs in-process de l'orchestrateur **exactement comme `show_chart`/`show_table`** (fonctions in-process, pas des tools DSS). Le tool emet un `deliverable` ARTIFACT avec `template_id` + slots remplis ; il NE rend PAS les bytes (rendu serveur-trusted au telechargement). **Correction adversariale forte** : pour un agent ETRANGER/visuel, ceci ne marche PAS (pas d'`exchange_id`, pas de stream, pas d'`state["latest"]`) -> hors scope ici, statut NEEDS-DSS-VALIDATION (cf. section 5). Ne concevoir que pour NOTRE orchestrateur.
- (d) **M, aucune install.** Recoll agents (env 3.11).
- (e) Le tool n'ecrit qu'un spec borne ; le cap `MAX_ARTIFACTS_ACCUM` protege d'un agent emballe. **Toute route export pouvant declencher un appel LLM doit re-appliquer `budget.has_budget()`** (cf. section 6 M7) ; les routes purement deterministes (CSV/PNG/PDF-template sur resultat deja capture) sont legitimement hors quota - les DISTINGUER.
- (f) Dernier : depend que W2.1/W2.4 existent pour rendre le spec.

### PHASE 3 - Différé / pilote par les metriques

**W3.1 - Cache semantique** [demote a metrics-gated]
- (a) Cacher `(question + filtres resolus + agent_key) -> (resultat + recit)`, TTL 24h.
- (b) Indirect (cout + latence).
- (c) **Correction majeure** : la cascade route deja 85-90% en petit modele ; un 360 = 3 petits appels = deja peu cher en absolu. Le cache ne paie que si les questions se REPETENT dans 24h (non prouve). Risques : memoire non bornee (LRU + max entries), **peremption sur refresh des donnees** (pas de hook aujourd'hui -> cle incluant un timestamp de refresh + divulgation "depuis le cache"), **fuite cross-user** (cle owner/entitlement-aware ou stocker seulement des agregats non-row-level). Cle POST-resolution -> dans `_run_subagents`, pas a `/chat/start`. **Decision data-driven** : construire le journal d'audit d'abord, n'activer le cache que si le taux de repetition mesure > ~25%.
- (d) **M, aucune install.**
- (f) Apres journal d'audit (cf. `PLAN_AGENTS.md`). Pas un prerequis du 360.

**W3.2 - Digest KPI programme (brouillon vers boite interne, batch)** [HITL, correction securite]
- (a) Un resume programme ("vos comptes cette semaine").
- (b) AM/dirigeant qui n'ouvre pas l'app : le produit vient a eux.
- (c) **Correction securite forte** : un envoi automatise non gate d'un chiffre potentiellement non reconcilie a un CLIENT est exactement la ligne rouge, automatisee. Donc : tourne en **scenario DSS programme off-peak** (jamais un cron webapp), produit un **brouillon vers une boite INTERNE** ou une notification in-app, **pas un envoi client auto**. **Batch unique** (un scenario, pas N runs par utilisateur), cap sur le nombre total de runs, reutiliser des agregats precalcules plutot qu'un appel agent live par couple user-KPI (sinon bombe de fan-out sur timer).
- (d) **L**, smtplib stdlib mais config SMTP + sign-off admin.
- (e) Email = territoire HITL `requires_confirmation`. Off-peak programme.
- (f) Tres tard. Depend de la discipline template W2.1.

**W3.3 - `render_chart`/`render_table` pour agents etrangers** [NEEDS-DSS-VALIDATION, gold-plating, defere]
- Seulement si le spike S3 passe (handoff `exchange_id` + binding proprietaire serveur). Implique une nouvelle table `webapp_artifacts_v2` (colonne `data` inline) ou `webapp_tool_artifacts_v1` (no-ALTER, #6). **Defere jusqu'a ce qu'un utilisateur reel veuille un agent visuel dans notre panneau.** Cf. section 5.

---

## 4. Récapitulatif de séquencement (webapp)

| Phase | Features | Install | Statut |
|---|---|---|---|
| **0 (cette semaine)** | PNG client (W0.1), CSV extrait (W0.2), bandeau 80% (W0.3), socle export+throttle+semaphore+audit (W0.4) | **zero** | VERIFIED |
| **1** | Reconciliation shadow (W1.1), chips deterministes (W1.2), explain-this-number (W1.3), onglets Trace/Cost (W1.4), XLSX (W1.5) | zero sauf XLSX (`openpyxl`) | VERIFIED + 1 install |
| **2** | PDF template-fill (W2.1), charts charte-safe (W2.2), comparison intent (W2.3), email brouillon (W2.4), tools natifs (W2.5) | `reportlab` (PDF) | VERIFIED design |
| **3 (metrics-gated)** | cache semantique (W3.1), digest interne batch (W3.2), render_chart etranger (W3.3 si spike S3) | zero / SMTP | metrics/NEEDS-VALIDATION |

**MVP honnete de la mission "plus de types de sortie"** : **PNG (client) + CSV extrait** - zero install, livrable tout de suite, ~80% de la valeur "sortir ca de l'app". Ne jamais laisser le PDF (phare mais install + gated) retarder ces deux gains gratuits.

---

## 5. Exposer les tools de la webapp aux agents (la question difficile de l'utilisateur)

> "Je ne suis pas sur qu'un agent visuel puisse exposer/utiliser les tools de la webapp ; aujourd'hui on dirait que seul un code agent peut. Peut-on les exposer comme tools normaux, peut-etre via le plugin ?"

**Diagnostic honnete.** Les verbes de rendu (`show_chart`/`show_table`) ne sont pas des tools portables : ce sont des fonctions in-process couplees a 4 couches de NOTRE stack (etat memoire, stream LangGraph, interpreteur backend, jointure de donnees). **Un agent visuel/etranger ne peut pas peupler le panneau Evidence aujourd'hui.** Ce n'est pas un trou de permission, c'est un trou de plomberie : le panneau lateral est une propriete de la session webapp, pas du tool. Conclusion : **chart/table-dans-le-panneau est le plus dur a externaliser ; PDF/email/CSV sont les plus faciles.**

**Track B - Le backend appelle les tools (VERIFIED, levier le moins cher, a faire d'abord).**
Le backend Flask 3.9 peut appeler **n'importe quel managed tool** via `dataiku.api_client().get_default_project().get_agent_tool(id).run(payload)` - l'orchestrateur le fait deja pour `attribute_lookup` et `v4oqA6R` (prouve in-process). Un petit module `agents/tool_caller.py` (timeout + contexte proprietaire). Cela debloque des features deterministes SANS agent : un bouton "Telecharger PDF" qui appelle un tool directement, sans LLM, sans brulage de quota, sans risque d'hallucination. **80% des livrables (PDF/CSV/PNG) n'ont besoin d'aucun agent.** A faire en premier.

**Track A - Plugin agent tools (l'instinct de l'utilisateur, correct).**
Dataiku supporte un chemin de premiere classe : **plugin custom agent tools** (`python-agent-tools/<tool>/tool.json` + `tool.py` qui etend `BaseAgentTool` : `set_config`/`get_descriptor`/`invoke`). `attribute_lookup_tool.py` implemente DEJA ce contrat (mais en objet projet, pas package plugin). Une fois package + installe, le tool apparait dans le catalogue GenAI, **selectionnable par agents VISUELS ET code** (doc developpeur ; a confirmer par le spike S1). Decouper les tools en 2 classes :
- **Classe 1 - tools autonomes (VERIFIED-feasible, a construire) :** l'input porte tout, l'output EST le livrable. Pas d'`exchange_id`, pas d'etat, pas de panneau.
  - `build_pdf` : remplit un template fige (slots JSON modele) -> rend un PDF dans un managed folder, renvoie `{"output": json.dumps({url})}`. ReportLab (install plugin-env, S2). Le modele remplit des slots, jamais la structure.
  - `draft_email` : remplit un template fixe -> `{subject, body_text}`, **n'envoie jamais**. HITL preview cote webapp. Aucun install (smtplib + template stdlib).
  - `query_<domain>` : wrapper mince exposant un semantic query d'un domaine comme tool selectionnable, pour qu'un agent etranger reponde "revenus de X" sans notre orchestrateur. `invoke()` fait `get_agent_tool("v4oqA6R").run()`. **NEEDS-DSS-VALIDATION** : identite d'execution (S4) ; **budget gate** si LLM derriere (section 6 M7).
- **Classe 2 - `render_chart`/`render_table` (NEEDS-DSS-VALIDATION, le dur).** Prend des lignes serialisees + un spec et veut les poser dans le panneau, meme pour un agent etranger. Probleme de couplage : (i) l'input doit porter la data (l'agent etranger n'a pas `state["latest"]`), (ii) il faut un endroit pour atterrir (`exchange_id` + ecriture). **Ne marche que si l'agent est invoque depuis NOTRE session webapp** (seul contexte ou un `exchange_id` existe). Pour un agent vraiment externe : degrader gracieusement en "renvoie le tableau en JSON, pas de panneau". **Correction securite (section 6 B1)** : l'ecriture doit etre liee au proprietaire par la session authentifiee, jamais par un `exchange_id`/`user_id` venant de l'input du tool. Spike S3 d'abord.

**Track C - Serveur MCP (futur, ne pas construire).** Exposer les tools OWIsMind en MCP pour reutilisation cross-produit. Necessite **DSS 14.0+ et Python 3.10+** ; notre backend est 3.9.23 -> hors host sans service 3.11 separe. YAGNI maintenant. Parquer.

**Recommandation.** Spiker S1+S2+S3+S4 (un apres-midi). Construire dans l'ordre : Phase 0 PNG/CSV (Track B implicite) -> `tool_caller.py` + `build_pdf`/`draft_email` autonomes (Track A Classe 1) -> `render_chart` etranger SEULEMENT si S3 passe, avec degradation JSON sinon. **Discipline de migration** : les built-ins `show_chart`/`show_table` restent INTACTS ; les plugin tools sont ADDITIFS ; jamais de big-bang sur le flux chart/table qui marche. La phrase honnete a l'utilisateur : **PDF/email/PNG/CSV s'externalisent proprement aujourd'hui via Track B ; chart-dans-le-panneau pour un agent etranger est conditionne au spike `exchange_id` - le valider avant de parier dessus.**

---

## 6. Gouvernance, sécurité et charte des nouvelles surfaces

**Securite (corrections adversariales) :**
- **B1 - Chemin d'ECRITURE des artefacts exploitable (a corriger AVANT tout "tool ecrit Evidence").** `save_artifacts` fait un UPSERT keye sur `exchange_id` SEUL et reassigne `user_id` depuis l'input (`artifacts.py`). Un `exchange_id` force = ecriture cross-tenant + reprise de propriete. Controle requis : (a) ne jamais accepter `user_id`/`exchange_id` depuis l'input du tool ; le backend forge le binding depuis la session authentifiee ; (b) UPSERT garde `WHERE existing.user_id = :session_user` (rejeter, pas reassigner). C'est une vraie vulnerabilite, pas un risque futur.
- **H2/H3 - Routes d'export :** `_evidence_guard` + WHERE `exchange_id AND user_id` explicite + `format` enum serveur + `MAX_EXPORT_ROWS` + **nom de fichier serveur-genere/sanitise** (jamais titre/label modele dans `Content-Disposition` : injection CRLF). Jamais table/colonne/connexion depuis la query (#3).
- **H4 - Email :** aucun envoi serveur en v1. Si un jour : HITL par message gate serveur, allowlist de destinataires serveur (jamais un `to` modele), creds SMTP admin, rate-limit + audit. Le digest auto (W3.2) est reclasse brouillon-interne.
- **H5 - PII des exports = un DESIGN manquant, pas un one-liner.** Un export (CSV/XLSX/PDF) est une copie durable, transferable, de PII (noms clients, carrier codes, account managers) quittant l'app gouvernee. Definir : QUI peut exporter de la PII (masquage pilote par tag de colonne OU entitlement admin "export-with-PII"), QUOI est masque, applique au point de serialisation, + **audit de chaque export**.
- **M7 - Bypass de quota :** toute route pouvant declencher un appel LLM (`query_<domain>`, build avec appel semantique) doit re-appliquer `budget.has_budget(user_id)` comme `/chat/start`. Distinguer les routes purement deterministes (hors quota legitimement).
- **L12 - Whitelist agents :** `validate_agent_meta` (champs editoriaux admin) ne doit JAMAIS pouvoir atteindre `agent_id`/`semantic_model_id`/`lookup_dataset` meme via un body JSON force.

**Gouvernance :**
- **Journal d'audit `webapp_audit_v1`** (append-only, miroir de `storage/usage.py` : parametrise + COMMIT + statement_timeout). Couvre **runs + exports + brouillons/envois + invocations de tools** (pas seulement le chat). Note de retention/rotation. Detail dans `PLAN_AGENTS.md` Phase 0 - **prerequis transverse**.
- **Reconciliation = detecteur ET gate.** Pour les livrables/email : un nombre non verifie BLOQUE l'export/brouillon (abstention > hallucination), une fois le detecteur fiable (apres le mode shadow W1.1).

**Charte (corrections, non-negociable #10) - chaque nouvelle surface :**
- Confidence/trust = vocabulaire **plein/pointille/gris existant** (`EvidenceTrust.vue`), **JAMAIS feu tricolore, jamais vert**. Renommer "verifie/non verifie vs source", pas "score de confiance".
- Bandeau 80% = filet 1px orange a gauche sur blanc plat, **pas d'aplat orange** (ne pas depenser l'accent rare orange sur une non-action).
- Waterfall/deltas = position + aplat sombre / barre fantome 1px, **jamais rouge/vert** (echec AA + daltonisme) ; `#FF7900` reserve a la barre de total.
- PDF/email = **vraie image `orange-logo.png`** embarquee, jamais une marque redessinee (L092) ; **passe de suppression des tirets longs** (`—`/`–`, #9) sur chaque slot rempli par le LLM.
- Boutons icone-seule (download) = **aria-label fr+en** ; `prefers-reduced-motion` sur les nouvelles cartes ; AA partout ; double i18n fr+en obligatoire (`extra.js`).

---

## 7. Ce qu'on DROP (YAGNI)

La meilleure discipline de cout du set : ne PAS construire ces items sans demande reelle.
- **Evidence multi-agent (un panneau par agent)** : pas de reponses multi-agents en pratique aujourd'hui. **Exception** : le 360 (cf. `PLAN_AGENTS.md`) en a besoin pour la provenance par domaine - le re-ouvrir SEULEMENT pour ce cas, ou inliner des citations taggees par domaine.
- **Pin-to-dashboard / vues sauvegardees** : un 2e modele de persistance pour une demande non prouvee. L'historique EST la vue sauvegardee.
- **Voix (STT)** : trou noir install + precision + privacy pour un outil B2B. Le micro reste un label "bientot".
- **Edit profile (PUT /me)** : trivial mais sans besoin demontre.
- **Budget dashboard admin complet** : l'onglet Quotas + le bandeau 80% (W0.3) couvrent. Garder les alertes, dropper le dashboard.
- **Titre de conversation par IA** : appel LLM par conversation + redeploy pour un label de sidebar ; le regex existant suffit. **Coupe de la Phase 1.** Si jamais : deterministe (premiers tokens de l'intent resolu), fire-and-forget apres persistance, skip pres du budget temps, fail-open au regex.

---

## 8. Registre des installations (par environnement, a valider)

| Lib | Env cible | Pour | Statut |
|---|---|---|---|
| `openpyxl` | backend 3.9 | XLSX (W1.5) | NEEDS-DSS-VALIDATION (verifier presence S5, sinon ASK user) |
| `reportlab` | backend 3.9 (et/ou env plugin-tool S2) | PDF (W2.1, build_pdf) | ASK user (pur Python) |
| `matplotlib` | backend 3.9 | charts serveur pour PDF (eviter, preferer PNG client) | NEEDS-DSS-VALIDATION |
| WeasyPrint | - | - | **INTERDIT** (libs systeme pango/cairo, #1) |
| SMTP serveur | - | envoi email | **HORS v1** (blast radius, decision utilisateur explicite) |

L'agent n'installe rien (#1). Chaque ligne "ASK user" = un aller-retour d'approbation, potentiellement decline.

---

## 9. Checklist non-négociables (a verifier pour chaque feature)

- [ ] **#1 NO INSTALL par l'agent** : toute dependance = ASK explicite (tableau section 8).
- [ ] **#2 Surete instance** : throttle dedie + semaphore sur rendu/export ; recipes off-peak (cf. agents) ; caps partout ; mesurer avant d'affirmer "rapide".
- [ ] **#3 SQL direct** : route export = `exchange_id`+`format` seulement, jamais table/connexion/query ; pas de re-execution du SQL agent ; owner-scope WHERE explicite ; parametrise + COMMIT/read-only.
- [ ] **#4 Whitelist agents** : front envoie une cle opaque ; `agent_id` jamais du front ; `validate_agent_meta` ne touche pas les ids techniques.
- [ ] **#5 frontend/node_modules jamais dans le zip.**
- [ ] **#6 Ne pas editer** `resource/owismind-app/` ni `ready-for-dataiku/` (generes) ; nouvelle table = `_vN`, jamais d'ALTER.
- [ ] **#7 Code + commentaires en anglais** (cette prose reste fr).
- [ ] **#8 Backend Python 3.9.23** : ne rien asserter en 3.11/FastAPI ; chaque install par env.
- [ ] **#9 Aucun tiret cadratin/demi-cadratin** : passe de suppression sur tout slot rempli par LLM, et dans l'UI/code/commentaires.
- [ ] **#10 Charte Orange** : carre/plat, orange rare, vraie image logo, pas de color-mix/blur/degrade/glow/emoji/feu-tricolore ; tokens semantiques ; aria fr+en.
- [ ] **Audit** de toute action externe (export/email/tool) ; **budget gate** sur toute route LLM ; **reconciliation gate** sur les livrables.
