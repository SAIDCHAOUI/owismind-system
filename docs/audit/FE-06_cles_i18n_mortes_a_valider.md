# FE-06 : cles i18n mortes, liste A VALIDER avant toute suppression (audit 2026-08-05)

> Methode : extraction des cles plates de messages.json (327 cles/locale) et extra.js (688 cles/locale),
> recherche litterale dans tous les .vue/.js hors src/i18n, apres exclusion des prefixes construits
> dynamiquement (ev.exp., mode., art.tab., fb.reason., fb.cat., bench.band., bench.verdict., bench.evo., bench.form., admin.quotas.src., admin.agents.badge., ag.badge., src.calc., src.an.bucket., tl.kind.).
> Gotcha F6 (messages.json pristine) : la suppression demande une DECISION EXPLICITE de l'utilisateur.
> Rien n'a ete supprime : ce fichier est le livrable de relecture, bloc par bloc.

## messages.json : 209 cles jamais lues

### bloc `ag.*` (1)
- `ag.new_conv_with` : "Nouvelle conversation avec {0}"

### bloc `default.*` (5)
- `default.answer_html` : "Le revenu Q1 2026 est de <span class=\"kpi-inline\">25,1 M€</span> contre <span
- `default.resp_demo` : "Réponse de démonstration pour : <em>« {0} »</em>."
- `default.resp_hint` : "Essayez « Prépare-moi un brief 1&1 » pour la démo complète multi-agent."
- `default.user_q` : "Quelle est la variation du revenu Q1 2026 vs Q1 2025 ?"
- `default.yday_label` : "Hier · 11:08"

### bloc `ev.*` (79)
- `ev.calls_n` : "{0} appels LLM · {1}"
- `ev.chart.bar` : "Barres"
- `ev.chart.kpi` : "KPI"
- `ev.chart.legend.actuals` : "Actuals"
- `ev.chart.legend.budget` : "Budget"
- `ev.chart.legend.forecast` : "Forecast"
- `ev.chart.line` : "Courbe"
- `ev.chart.stacked` : "Empilé"
- `ev.chip.duration` : "Durée"
- `ev.chip.tool` : "Tool"
- `ev.col.month` : "Mois"
- `ev.col.phase` : "Phase"
- `ev.col.revenue` : "Revenu (€)"
- `ev.col.solution` : "Solution"
- `ev.col.yoy` : "YoY"
- `ev.hub.add_filter` : "+ Filtre"
- `ev.hub.ai.applied` : "Appliqué par OWIsMind"
- `ev.hub.ai.placeholder` : "Demander à OWIsMind de modifier le dataset…"
- `ev.hub.ai.s1` : "Garder seulement 2025"
- `ev.hub.ai.s2` : "Trier par revenu décroissant"
- `ev.hub.ai.s3` : "Cacher la phase FORECAST"
- `ev.hub.ai.s4` : "Ne garder que Roaming Sponsor"
- `ev.hub.ai.send` : "Envoyer"
- `ev.hub.ai.suggest` : "Suggestions"
- `ev.hub.delete_selected` : "Supprimer"
- `ev.hub.duplicate_selected` : "Dupliquer"
- `ev.hub.empty_sub` : "Ajustez ou réinitialisez les filtres."
- `ev.hub.empty_title` : "Aucune ligne ne correspond"
- `ev.hub.filter.all` : "Toutes"
- `ev.hub.filter.phase` : "Phase"
- `ev.hub.filter.solution` : "Solution"
- `ev.hub.filter.year` : "Année"
- `ev.hub.filters` : "Filtres"
- `ev.hub.filters_active` : "filtre actif"
- `ev.hub.filters_active_p` : "filtres actifs"
- `ev.hub.kpi.phases` : "Phases incluses"
- `ev.hub.kpi.revenue` : "Revenu total (filtré)"
- `ev.hub.kpi.rows` : "Lignes affichées"
- `ev.hub.kpi.yoy` : "YoY moyen"
- `ev.hub.reset` : "Tout réinitialiser"
- `ev.hub.row_selected` : "ligne sélectionnée"
- `ev.hub.rows_selected` : "lignes sélectionnées"
- `ev.hub.scope_sources` : "Scope & sources"
- `ev.hub.scope_sources_sub` : "Comment ces données ont été récupérées"
- `ev.hub.search_ph` : "Rechercher dans les lignes…"
- `ev.hub.showing` : "Affichage de {0} sur {1} lignes"
- `ev.hub.subtitle` : "Filtrez, triez, modifiez. L'IA peut aussi opérer sur ce jeu pour vous."
- `ev.hub.title` : "Hub de travail"
- `ev.hub.tool.add_col` : "Ajouter colonne"
- `ev.hub.tool.add_row` : "Ajouter ligne"
- `ev.hub.tool.cols` : "Colonnes"
- `ev.hub.tool.edit` : "Mode édition"
- `ev.hub.tool.edit_on` : "Édition active"
- `ev.hub.tool.export` : "Exporter CSV"
- `ev.row.agents` : "Agents"
- `ev.row.client` : "Client"
- `ev.row.currency` : "Devise"
- `ev.row.period` : "Période"
- `ev.row.phases` : "Phases"
- `ev.row.row_count` : "Lignes retournées"
- `ev.row.scope` : "Scope"
- `ev.sample_lbl` : "Échantillon"
- `ev.sample_note` : "12 lignes affichées sur 24 retournées · le calcul porte sur le jeu complet"
- `ev.section.breakdown` : "Répartition par agent"
- `ev.section.scope` : "Scope & paramètres"
- `ev.section.sources` : "Sources"
- `ev.section.summary` : "Résultat synthétique"
- `ev.src.ops_desc` : "Tickets OWI · incidents/changes · sévérité · SLA · refresh 15 min"
- `ev.src.sem_desc` : "Modèle sémantique consolidé · revenus actuals/budget/forecast · refresh quotidi
- `ev.subtitle_brief` : "Brief 1&1 · Multi-agent · 2 145 tokens · $0.0142"
- `ev.tab.chart` : "Chart"
- `ev.tab.cost` : "Cost"
- `ev.tab.data` : "Données & Preuves"
- `ev.tab.dataset` : "Dataset"
- `ev.tab.evidence` : "Evidence"
- `ev.tab.trace` : "Trace"
- `ev.tokens` : "Tokens"
- `ev.tokens_split` : "{0} prompt · {1} completion"
- `ev.total_cost` : "Coût total"

### bloc `fb.*` (5)
- `fb.desc` : "Signalez un bug, une mauvaise réponse, ou demandez une nouvelle fonctionnalité.
- `fb.eyebrow` : "Aide & feedback"
- `fb.status.need_info` : "Infos manquantes"
- `fb.status.reviewed` : "Revue"
- `fb.title` : "Aide & feedback"

### bloc `locale.*` (1)
- `locale.tag` : "fr-FR"

### bloc `modal.*` (15)
- `modal.cancel` : "Annuler"
- `modal.del_conv.body` : "La conversation « {0} » sera définitivement supprimée. Cette action est irréver
- `modal.del_conv.title` : "Supprimer la conversation"
- `modal.del_proj.body` : "Le projet « {0} » sera supprimé. Les conversations associées seront conservées 
- `modal.del_proj.title` : "Supprimer le projet"
- `modal.delete` : "Supprimer"
- `modal.new_proj.label` : "Nom du projet"
- `modal.new_proj.placeholder` : "ex. Préparation comité Q3"
- `modal.new_proj.title` : "Nouveau projet"
- `modal.ok` : "Valider"
- `modal.rename_conv.label` : "Nom de la conversation"
- `modal.rename_conv.title` : "Renommer la conversation"
- `modal.rename_proj.label` : "Nom du projet"
- `modal.rename_proj.title` : "Renommer le projet"
- `modal.save` : "Enregistrer"

### bloc `msg.*` (6)
- `msg.branch_nav` : "Navigation entre les versions"
- `msg.copy_manual_hint` : "Le presse-papier n'est pas accessible ici. Le texte est sélectionné, appuyez su
- `msg.copy_manual_title` : "Copiez le texte manuellement"
- `msg.edit_hint` : "Entrée pour un saut de ligne · Échap pour annuler"
- `msg.feedback` : "Feedback"
- `msg.view_evidence` : "Voir les preuves"

### bloc `page.*` (1)
- `page.back` : "Retour"

### bloc `pj.*` (28)
- `pj.conv_count` : "{0} conversation"
- `pj.conv_count_n` : "{0} conversations"
- `pj.convs` : "Conversations du projet"
- `pj.empty` : "Aucune conversation pour le moment. Démarrez-en une avec le bouton ci-dessus."
- `pj.instructions` : "Instructions personnalisées"
- `pj.instructions_desc` : "Donnez du contexte à OWIsMind pour ce projet (ex : ton, format, sources préféré
- `pj.instructions_placeholder` : "Ex : « Réponds en français, concentre-toi sur les comptes DACH, privilégie les 
- `pj.new_conv` : "Nouvelle conversation dans ce projet"
- `pj.set.archive` : "Archiver le projet"
- `pj.set.color` : "Couleur"
- `pj.set.danger` : "Zone de danger"
- `pj.set.delete` : "Supprimer le projet"
- `pj.set.description` : "Description"
- `pj.set.description_ph` : "Décrivez l'objectif du projet en une ou deux phrases"
- `pj.set.id` : "Identifiant projet"
- `pj.set.id_help` : "Identifiant interne · non modifiable."
- `pj.set.instructions` : "Instructions OWIsMind"
- `pj.set.instructions_ph` : "Donnez du contexte à OWIsMind pour ce projet (ton, sources préférées, périmètre
- `pj.set.name` : "Nom du projet"
- `pj.set.name_ph` : "ex. Comptes clés DACH Q2"
- `pj.set.stats` : "Aperçu"
- `pj.set.stats.convs` : "Conversations"
- `pj.set.stats.cost` : "Coût total"
- `pj.set.stats.created` : "Créé le"
- `pj.set.stats.tokens` : "Tokens"
- `pj.set.sub` : "Modifiez le nom, la description, la couleur et les instructions du projet."
- `pj.set.title` : "Paramètres du projet"
- `pj.settings` : "Paramètres du projet"

### bloc `prompt.*` (9)
- `prompt.all_agents` : "Voir tous les agents"
- `prompt.audio_source` : "Source audio"
- `prompt.choose_agent_header` : "Choisir un agent"
- `prompt.demo_source` : "Démo"
- `prompt.demo_transcript` : "Prépare-moi un brief complet pour ma réunion avec 1&1 demain matin"
- `prompt.foot_recording` : "L'enregistrement s'arrête automatiquement après 10s d'inactivité. Cliquez sur l
- `prompt.mic_source` : "Micro"
- `prompt.recording` : "Enregistrement"
- `prompt.stop_recording` : "Terminer l'enregistrement"

### bloc `sb.*` (18)
- `sb.confirm.delete_conv` : "Supprimer cette conversation « {0} » ?"
- `sb.confirm.delete_proj` : "Supprimer le projet « {0} » ? Les conversations seront conservées mais détachée
- `sb.menu.add_to_project` : "Ajouter à un projet"
- `sb.menu.change_color` : "Changer la couleur"
- `sb.menu.change_project` : "Changer de projet"
- `sb.menu.choose_project` : "Choisir un projet"
- `sb.menu.delete` : "Supprimer"
- `sb.menu.no_project` : "Pas de projet"
- `sb.menu.remove_from_project` : "Retirer du projet"
- `sb.menu.rename` : "Renommer"
- `sb.new_project` : "Nouveau projet"
- `sb.new_project_prompt` : "Nom du nouveau projet ?"
- `sb.no_results` : "Aucune conversation pour « {0} »"
- `sb.prompt.rename_conv` : "Nouveau nom de la conversation :"
- `sb.prompt.rename_proj` : "Nouveau nom du projet :"
- `sb.search` : "Rechercher"
- `sb.search_placeholder` : "Rechercher dans les conversations…"
- `sb.signout` : "Se déconnecter"

### bloc `set.*` (27)
- `set.appearance_desc` : "Choisissez le thème de l'application."
- `set.budget.avg_cost` : "Coût moyen"
- `set.budget_desc` : "Mai 2026 · renouvelé le 1er du mois. Alertes à 50 %, 80 %. Blocage à 100 %."
- `set.desc` : "Profil, préférences d'affichage, langue, budget mensuel et historique de consom
- `set.hist.agent` : "Agent"
- `set.hist.conv` : "Conversation"
- `set.hist.cost` : "Coût"
- `set.hist.date` : "Date"
- `set.hist.tokens` : "Tokens"
- `set.language_desc` : "La langue de l'interface OWIsMind."
- `set.profile.dataiku_help` : "Non modifiable · synchronisé avec votre compte Dataiku."
- `set.profile.dataiku_id` : "Identifiant Dataiku"
- `set.profile.edit_sub` : "Mettez à jour les informations affichées sur votre compte OWIsMind."
- `set.profile.edit_title` : "Personnaliser le profil"
- `set.profile.email` : "Adresse e-mail"
- `set.profile.email_help` : "Par défaut : {0}"
- `set.profile.full_name` : "Nom complet"
- `set.profile.full_name_ph` : "Prénom Nom"
- `set.profile.role_field` : "Rôle"
- `set.profile.role_ph` : "ex. Senior Data Scientist"
- `set.profile.team_field` : "Équipe"
- `set.profile.team_ph` : "ex. OWI Data & AI"
- `set.profile.title_field` : "Poste / mission"
- `set.profile.title_ph` : "Décrivez votre poste en une phrase"
- `set.usage.by_agent` : "Par agent"
- `set.usage.spend30` : "Dépense sur 30 jours"
- `set.usage_desc` : "30 derniers jours · 274 requêtes · $19,07"

### bloc `support.*` (3)
- `support.desc` : "Posez vos questions à l'équipe OWIsMind sur Microsoft Teams. Réponse sous 24 h 
- `support.eyebrow` : "Aide & support"
- `support.title` : "Support Teams"

### bloc `tl.*` (8)
- `tl.default.1.sub` : "intent classification"
- `tl.default.1.title` : "OWIsMind analyse la demande"
- `tl.default.2.sub` : "fallback générique"
- `tl.default.2.title` : "Sélection de l'agent"
- `tl.default.3.sub` : "génération"
- `tl.default.3.title` : "Composition de la réponse"
- `tl.default.4.sub` : "$0.0048"
- `tl.default.4.title` : "Réponse prête"

### bloc `top.*` (3)
- `top.brief_pill` : "Brief 1&1 - réunion 21 mai"
- `top.open_evidence` : "Ouvrir Evidence Studio"
- `top.orchestrator_tagline` : "OWIsMind orchestrator"

## extra.js : 35 cles jamais lues

### bloc `admin.*` (7)
- `admin.agents.enabled_title`
- `admin.agents.in_project`
- `admin.agents.project`
- `admin.quotas.expires_on`
- `admin.quotas.global_title`
- `admin.quotas.loading`
- `admin.quotas.selected`

### bloc `ar.*` (1)
- `ar.manual_tables_label`

### bloc `bench.*` (23)
- `bench.cfg.col_config`
- `bench.cfg.col_error`
- `bench.cfg.col_ok`
- `bench.cfg.col_questions`
- `bench.consult.hero_meta`
- `bench.detail.answers_title`
- `bench.detail.col_agent`
- `bench.detail.col_judge`
- `bench.detail.col_result`
- `bench.detail.col_score`
- `bench.detail.col_verdict`
- `bench.detail.hide`
- `bench.detail.judge_comment`
- `bench.detail.meta_title`
- `bench.detail.objective`
- `bench.detail.objective_no`
- `bench.detail.objective_yes`
- `bench.detail.show`
- `bench.detail.uncategorized`
- `bench.ev.answer`
- `bench.ev.sql`
- `bench.ev.title`
- `bench.refprod.title`

### bloc `ev.*` (4)
- `ev.proof.level.desc.declared`
- `ev.proof.level.desc.partial`
- `ev.proof.level.desc.result`
- `ev.proof.level.desc.source`
