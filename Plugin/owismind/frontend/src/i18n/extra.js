// Phase-3 domain catalog - UI strings that did NOT exist in the maquette
// extraction (messages.json), added modularly and MERGED into vue-i18n (see
// i18n/index.js) so messages.json stays a pristine 1:1 port of window.OWI_I18N.
//
// These are mostly HONEST empty-state / "coming soon" strings: every secondary
// feature without a backend (budget, usage, feedback submit, projects) shows a
// clearly labeled state here - never fake numbers (memory: "zéro faux chiffre").
//
// Keys use `x.*` for generic reusable strings, or a domain prefix (set./fb./
// faq./ag./pj.) for page-specific ones. Flat dotted keys, same shape as the
// timeline catalog. Extensibility: add a string = add one line in both locales.
export const extraMessages = {
  fr: {
    // Generic reusable
    'x.soon': 'Bientôt',
    'x.coming_soon': 'Bientôt disponible',
    'x.close': 'Fermer',

    // Chat - prompt guidance: better input → better answer. Overrides the maquette's
    // neutral placeholder (messages.json) and adds an empty-screen tip.
    'prompt.placeholder': 'Décrivez votre demande le plus précisément possible…',
    'empty.tip':
      'Conseil : plus votre demande est précise et bien formulée - les termes employés, la période, le périmètre - meilleure sera la réponse.',

    // Settings - profile groups label
    'set.profile.groups': 'Groupes',

    // Settings - monthly budget card (real /usage data)
    'set.budget.loading': 'Chargement de votre consommation…',
    'set.budget.resets': 'Réinitialisé le {0}',
    'set.budget.blocked':
      'Budget mensuel atteint. De nouvelles requêtes seront possibles le {0} (réinitialisation mensuelle).',
    'set.budget.off': 'Suivi de consommation actif. Aucune limite mensuelle appliquée actuellement.',
    'set.budget.src_default': 'Limite mensuelle : {0} (par défaut).',
    'set.budget.src_global_temp': 'Limite mensuelle : {0} (augmentation temporaire jusqu\'au {1}).',
    'set.budget.src_user': 'Limite mensuelle : {0} (allouée par un administrateur).',
    'set.budget.src_user_temp': 'Limite mensuelle : {0} (boost temporaire jusqu\'au {1}).',

    // Settings - usage detail (this month + lifetime)
    'set.usage.tokens': 'tokens',
    'set.usage.tokens_month': 'Tokens ce mois',
    'set.usage.spend_month': 'Dépense ce mois',
    'set.usage.lifetime_cost': 'Dépense totale',
    'set.usage.last': 'Dernière activité',

    // Settings - agent-context window (repurposed from the old "conversations shown").
    'set.context': 'Contexte',
    'set.context.max': "Messages d'historique envoyés à l'agent",
    'set.context.max_desc':
      "Nombre des derniers messages de la conversation inclus comme contexte (entre 10 et 50).",

    // Sidebar - conversation list states
    'sb.conv_loading': 'Chargement des conversations…',
    'sb.conv_empty': 'Aucune conversation pour le moment.',
    'sb.conv_error': "Échec du chargement de l'historique.",
    'sb.loadingMore': 'Chargement…',

    // Thread lazy load (on click)
    'chat.loadingThread': 'Chargement de la conversation…',
    'chat.loadThreadError': 'Impossible de charger cette conversation.',

    // Chat - stop generation (the ■ button + interrupted-answer markers)
    'prompt.stop': 'Arrêter la génération',
    'chat.stopped': 'Génération arrêtée',
    'chat.stopping': 'Arrêt en cours…',
    'chat.interrupted_empty': 'Réponse interrompue',

    // Chat - monthly budget banner (sends paused once the credit is reached)
    'chat.quota_banner':
      'Budget mensuel épuisé : {0} utilisés sur {1}. De nouvelles requêtes seront possibles le {2}.',
    'chat.quota_short': 'Budget mensuel épuisé. Réessayez après la réinitialisation du 1er du mois.',

    // Chat - the collapsed activity block (agent steps header line)
    'tl.steps': "Étapes de l'agent",
    'tl.steps_count': '{0} étape(s)',
    'tl.seconds': '{0} s',

    // Feedback - the "other" reason (the rest live in messages.json's maquette port).
    'fb.reason.other': 'Autre',
    'msg.feedback_failed': "Échec de l'envoi du feedback.",

    // Feedback - adaptive modal (positive variant) + the ⋯ detailed-feedback entry.
    'msg.feedback_title_positive': "Qu'avez-vous aimé ?",
    'msg.feedback_suggestion_label_positive': 'Dites-nous ce qui vous a plu',
    'msg.more_options': "Plus d'options",
    'msg.give_feedback': 'Donner un retour détaillé',

    // Per-message token/cost usage line (shown under each agent answer).
    'msg.usage_tokens': 'tokens',
    'msg.usage_in': "Tokens d'entrée (question + contexte)",
    'msg.usage_out': 'Tokens de sortie (réponse générée)',
    'msg.usage_cost': 'Coût estimé de cet échange',

    // Feedback - no submit endpoint yet
    'fb.soon_note': "L'envoi de feedback sera bientôt disponible. L'équipe OWI prépare ce service.",
    'fb.empty': "Vous n'avez pas encore de demande.",

    // FAQ - client-side search (the maquette never wired it)
    'faq.no_results': 'Aucun résultat pour « {0} ».',

    // Agents - fallbacks for agents not described in the local registry
    'ag.generic_tagline': 'Agent IA OWI',
    'ag.generic_desc':
      "Cet agent est activé pour votre compte. Sa fiche détaillée n'est pas encore renseignée.",
    'ag.no_agents': "Aucun agent n'est activé pour votre compte. Contactez un administrateur.",
    'ag.tools_section_empty': 'Aucun outil renseigné.',

    // Project - no project API yet
    'pj.coming':
      'La gestion de projets sera bientôt disponible : regrouper des conversations, instructions personnalisées et suivi par projet.',

    // Admin - the maquette kept all admin strings inline (al(fr,en)); ported here.
    'admin.eyebrow': "Console d'administration",
    'admin.title': 'Administration',
    'admin.desc': 'Gérez le stockage, les agents exposés et les administrateurs.',
    'admin.loading': "Chargement de l'espace admin…",
    'admin.load_error': "Échec du chargement de l'espace admin.",
    'admin.tab.overview': "Vue d'ensemble",
    'admin.tab.agents': 'Agents',
    'admin.tab.users': 'Utilisateurs',
    'admin.tab.quotas': 'Quotas & budgets',
    'admin.tab.activity': "Journal d'activité",
    'admin.kpi.users': 'Utilisateurs',
    'admin.kpi.agents': 'Agents exposés',
    'admin.kpi.connection': 'Connexion SQL',
    'admin.storage.title': 'Stockage',
    'admin.storage.connection': 'Connexion SQL',
    'admin.storage.project_key': 'Project key',
    'admin.storage.prefix': 'Préfixe',
    'admin.storage.namespace': 'Namespace',
    'admin.storage.tables': 'Tables (project key + namespace toujours conservés)',
    'admin.storage.none': '(aucun)',
    'admin.storage.traces': 'Dataset de traces',
    'admin.storage.traces_off': '(aucun - stockage des traces désactivé)',
    'admin.storage.prefix_ignored':
      'Préfixe « {0} » ignoré : trop long ou invalide (max 16 caractères : lettres, chiffres, _ et -).',
    'admin.storage.note':
      'Pour changer la connexion ou le préfixe : onglet Settings de la webapp (dropdown « SQL connection »), puis redémarrer le backend.',
    'admin.agents.title': 'Agents exposés',
    'admin.agents.desc':
      'Choisissez un projet, cochez les agents à mettre à disposition, puis enregistrez. Les utilisateurs ne verront que les agents activés ici.',
    'admin.agents.project': 'Projet',
    'admin.agents.project_choose': '- Sélectionner un projet -',
    'admin.agents.loading': 'Chargement des agents…',
    'admin.agents.none_in_project': 'Aucun agent dans ce projet.',
    'admin.agents.enabled_title': 'Activés (toutes sources)',
    'admin.agents.save': 'Enregistrer la sélection',
    'admin.agents.saving': 'Enregistrement…',
    'admin.agents.saved': '{0} agent(s) enregistré(s).',
    'admin.agents.remove': 'Retirer',
    'admin.users.title': 'Utilisateurs',
    'admin.users.desc': 'Promouvez en admin une personne ayant déjà ouvert la webapp.',
    'admin.users.col_user': 'Utilisateur',
    'admin.users.col_groups': 'Groupes',
    'admin.users.col_admin': 'Admin',
    'admin.users.you': '(vous)',
    'admin.users.make_admin': 'Rendre admin',
    'admin.users.revoke_admin': 'Retirer admin',
    'admin.users.last_admin_error': 'Impossible : il doit rester au moins un admin.',
    // Admin - monthly budgets / quotas (real)
    'admin.quotas.title': 'Budgets mensuels',
    'admin.quotas.desc':
      'Chaque utilisateur dispose d\'un crédit mensuel (par défaut {0}) qui se réinitialise le 1er du mois. Ajustez la limite globale ou attribuez des limites par utilisateur.',
    'admin.quotas.loading': 'Chargement des budgets…',
    'admin.quotas.error': "Échec de l'opération.",
    'admin.quotas.global_title': 'Configuration globale',
    'admin.quotas.default_limit': 'Limite mensuelle par défaut ($)',
    'admin.quotas.enabled': 'Appliquer la limite (bloquer au dépassement)',
    'admin.quotas.enabled_hint':
      'Si désactivé, la consommation reste suivie et affichée, mais aucune requête n\'est bloquée.',
    'admin.quotas.temp_title': 'Augmentation temporaire (tous les utilisateurs)',
    'admin.quotas.temp_amount': 'Limite temporaire ($)',
    'admin.quotas.temp_days': 'Durée (jours)',
    'admin.quotas.temp_active': 'Boost global actif : {0} jusqu\'au {1}.',
    'admin.quotas.temp_clear': 'Retirer le boost global',
    'admin.quotas.temp_apply': 'Appliquer le boost',
    'admin.quotas.save': 'Enregistrer la configuration',
    'admin.quotas.saving': 'Enregistrement…',
    'admin.quotas.saved': 'Configuration enregistrée.',
    'admin.quotas.users_title': 'Limites par utilisateur',
    'admin.quotas.users_desc':
      'Cochez un ou plusieurs utilisateurs, puis attribuez une limite (permanente ou temporaire) ou réinitialisez au défaut.',
    'admin.quotas.col_user': 'Utilisateur',
    'admin.quotas.col_usage': 'Ce mois',
    'admin.quotas.col_limit': 'Limite',
    'admin.quotas.col_remaining': 'Restant',
    'admin.quotas.col_source': 'Origine',
    'admin.quotas.src.default': 'Défaut',
    'admin.quotas.src.global_temp': 'Boost global',
    'admin.quotas.src.user_permanent': 'Personnalisée',
    'admin.quotas.src.user_temp': 'Temporaire',
    'admin.quotas.blocked_tag': 'Bloqué',
    'admin.quotas.expires_on': 'jusqu\'au {0}',
    'admin.quotas.select_all': 'Tout',
    'admin.quotas.selected': '{0} sélectionné(s)',
    'admin.quotas.none_selected': 'Sélectionnez au moins un utilisateur.',
    'admin.quotas.apply_title': 'Appliquer aux {0} utilisateur(s) sélectionné(s)',
    'admin.quotas.limit_amount': 'Nouvelle limite ($)',
    'admin.quotas.duration': 'Durée',
    'admin.quotas.permanent': 'Permanente',
    'admin.quotas.temp_days_opt': 'Temporaire ({0} j)',
    'admin.quotas.note': 'Note (facultatif)',
    'admin.quotas.apply': 'Appliquer la limite',
    'admin.quotas.applying': 'Application…',
    'admin.quotas.clear': 'Réinitialiser au défaut',
    'admin.quotas.applied': '{0} utilisateur(s) mis à jour.',
    'admin.activity.empty': "Le journal d'activité sera bientôt disponible.",

    // === Charte redesign additions =========================================
    // Account (the page formerly "Settings" -> "My account").
    'set.eyebrow': 'Mon compte',
    'set.title': 'Mon compte',
    'sb.settings': 'Mon compte',
    'sb.account': 'Compte',

    // Sidebar - collapsed icon rail (tooltips).
    'sb.expand': 'Déplier le menu',
    'sb.collapse': 'Replier le menu',
    'rail.new': 'Nouvelle conversation',
    'rail.chat': 'Conversations',
    'rail.agents': 'Agents',
    'rail.help': 'Aide et support',
    'rail.account': 'Mon compte',

    // Agents library - list + detail.
    'ag.eyebrow': 'Bibliothèque',
    'ag.title': 'Agents disponibles',
    'ag.desc':
      "Les agents OWI déployés sur Dataiku DSS. Ouvrez une fiche pour voir ce qu'un agent sait faire, puis démarrez une conversation.",
    'ag.search': 'Rechercher un agent…',
    'ag.no_match': "Aucun agent ne correspond à « {0} ».",
    'ag.count': '{0} agent(s)',
    'ag.back': 'Tous les agents',
    'ag.capabilities': 'Ce que fait cet agent',
    'ag.tools': 'Outils exposés',
    'ag.tools_count': '{0} outil(s)',
    'ag.new_conv_with': 'Démarrer une conversation',
    'ag.start': 'Démarrer une conversation',
    'ag.open': 'Voir la fiche',
    'ag.badge.default': 'Par défaut',
    'ag.badge.new': 'Nouveau',
    'ag.badge.beta': 'Bêta',
    'ag.meta_missing':
      "La fiche de cet agent n'a pas encore été renseignée par un administrateur.",

    // Admin - agent profile editor (admin-authored, stored with the whitelist).
    'admin.agents.pick_project': 'Projet source',
    'admin.agents.in_project': 'Agents du projet',
    'admin.agents.add': 'Ajouter',
    'admin.agents.added': 'Ajouté',
    'admin.agents.enabled_count': 'Agents exposés ({0})',
    'admin.agents.enabled_empty':
      'Aucun agent exposé pour le moment. Choisissez un projet, puis ajoutez les agents à mettre à disposition.',
    'admin.agents.configure': 'Modifier la fiche',
    'admin.agents.no_profile': 'Fiche à compléter',
    'admin.agents.has_profile': 'Fiche renseignée',
    'admin.agents.editor_title': "Fiche de l'agent",
    'admin.agents.editor_desc':
      "Cette fiche est ce que vos utilisateurs voient dans la bibliothèque. Renseignez-la pour qu'ils comprennent ce que l'agent sait faire.",
    'admin.agents.f_label': 'Agent (Dataiku)',
    'admin.agents.f_icon': 'Icône',
    'admin.agents.f_badge': 'Badge',
    'admin.agents.f_tagline': 'Accroche',
    'admin.agents.f_tagline_ph': 'Ex. : Revenus, budget et forecast',
    'admin.agents.f_desc': 'Description',
    'admin.agents.f_desc_ph':
      "Décrivez en quelques phrases ce que l'agent sait faire, ses sources de données et quand l'utiliser.",
    'admin.agents.f_caps': 'Capacités',
    'admin.agents.f_caps_ph': 'Une capacité par ligne',
    'admin.agents.f_caps_hint': 'Une capacité par ligne (8 maximum).',
    'admin.agents.f_tools': 'Outils exposés',
    'admin.agents.f_tools_ph': 'Un outil par ligne',
    'admin.agents.f_tools_hint': 'Noms affichés aux utilisateurs (un par ligne, 16 maximum).',
    'admin.agents.f_modes': 'Modes de réponse',
    'admin.agents.f_modes_opt': 'Cet agent gère les modes de réponse (Smart / Pro / Claude)',
    'admin.agents.f_modes_hint':
      "À cocher uniquement pour un agent de code OWI qui sait interpréter les modes (ex. l'orchestrateur OWIsMind). Pour un agent visuel standard, laissez décoché : le sélecteur de mode reste alors masqué dans le chat.",
    'admin.agents.badge.none': 'Aucun',
    'admin.agents.badge.default': 'Par défaut',
    'admin.agents.badge.new': 'Nouveau',
    'admin.agents.badge.beta': 'Bêta',
    'admin.agents.preview': 'Aperçu',
    'admin.agents.editor_done': 'Terminé',
    'admin.agents.unsaved': 'Fiches modifiées - cliquez sur « {0} » pour appliquer.',
    'admin.agents.char_count': '{0}/{1}',

    // Evidence Studio (v1) - the proof panel
    'ev.title': 'Evidence Studio',
    'ev.open': 'Preuves',
    'ev.close': 'Fermer les preuves',
    'ev.filters': "Filtres appliqués par l'agent",
    'ev.filters.add': 'Ajouter un filtre',
    'ev.filters.reset': 'Version agent',
    'ev.filters.advanced': 'Condition avancée',
    'ev.filters.remove': 'Retirer ce filtre',
    'ev.modified': 'Filtres modifiés',
    'ev.table.empty': 'Aucune ligne ne correspond aux filtres.',
    'ev.table.page': 'Page {0}',
    'ev.table.prev': 'Page précédente',
    'ev.table.next': 'Page suivante',
    'ev.table.source': 'Table source',
    'ev.table.loaded': '{0} ligne(s) chargée(s)',
    'ev.table.more': 'Faites défiler pour charger plus',
    'ev.table.loadingMore': 'Chargement…',
    'ev.sql.title': 'Détails techniques (SQL)',
    'ev.sql.copy': 'Copier le SQL',
    'ev.sql.copied': 'SQL copié',
    'ev.degraded': "Vue interactive indisponible - voici la requête exacte exécutée par l'agent.",
    'ev.degraded.no_dataset': "La table interrogée par l'agent ne correspond à aucun dataset SQL de ce projet - la vue interactive est indisponible. Voici la requête exacte exécutée par l'agent.",
    'ev.degraded.no_sql': "Cette réponse n'a pas produit de requête SQL exploitable - rien à visualiser.",
    'ev.error': 'Impossible de charger les preuves.',
    'ev.retry': 'Réessayer',
    'ev.loading': 'Chargement des preuves…',
    'ev.picker.empty': 'Aucune valeur disponible.',
    'ev.picker.truncated': 'Premières {0} valeurs distinctes',
    'ev.picker.max': 'Maximum {0} valeurs par filtre',
    'ev.picker.apply': 'Appliquer',
    'ev.column': 'Colonne…',

    // - Evidence trust layer (v2) - proof levels, sources, calc steps, result, drill.
    // Badge wording is deliberately CAUTIOUS (honesty rules, spec §9): "certifié"
    // only for deterministically verified levels, "déclaré" for raw agent claims.
    'ev.proof.level.result': 'Résultat certifié',
    'ev.proof.level.source': 'Source certifiée',
    'ev.proof.level.partial': 'Preuve partielle',
    'ev.proof.level.declared': "Déclaré par l'agent",
    'ev.proof.level.partial_note': '{0} élément(s) non reproduit(s)',
    'ev.proof.level.desc.result':
      "Le calcul est décomposé étape par étape et le résultat exact utilisé par l'agent a été conservé.",
    'ev.proof.level.desc.source':
      'La source et le périmètre exacts de la requête sont identifiés - les lignes affichées sont relues maintenant, pas au moment de la réponse.',
    'ev.proof.level.desc.partial':
      'Une partie seulement du périmètre a pu être reproduite - les éléments non reproduits sont listés, jamais masqués.',
    'ev.proof.level.desc.declared':
      "Affirmation de l'agent : cette requête n'a pas pu être vérifiée automatiquement.",
    'ev.proof.sources': 'Source des données',
    'ev.proof.sources.more': '+{0} autre(s) requête(s) exécutée(s)',
    'ev.proof.sources.open': 'Ouvrir le jeu de données dans Dataiku',
    'ev.proof.calc': 'Comment ce résultat est calculé',
    'ev.proof.result': "Résultat utilisé par l'agent",
    'ev.proof.result.rows': '{0} ligne(s)',
    'ev.proof.result.missing':
      "Le résultat exact utilisé par l'agent n'a pas été conservé pour cette réponse.",
    'ev.proof.result.truncated': 'Résultat tronqué - premières lignes seulement.',
    'ev.proof.result.drill': 'Voir les lignes sources de ce résultat',
    'ev.proof.drill.banner': 'Lignes sources : {0}',
    'ev.proof.drill.exit': 'Revenir au résultat',
    'ev.proof.explore': 'Explorer les données sources',

    // Evidence Studio - artifact tabs (KPI / chart / table)
    'art.tab.evidence': 'Preuves',
    'art.tab.chart': 'Graphique',
    'art.tab.table': 'Tableau',
    'art.tab.kpi': 'Indicateur',
    'art.chart.empty': 'Impossible de tracer le graphique pour ces données.',
    'art.chart.truncated': 'Données tronquées - premières valeurs seulement.',
    'art.chart.title_fallback': 'Graphique',
    'art.table.empty': "Le résultat exact utilisé par l'agent n'a pas été conservé.",
    'art.table.truncated': 'Résultat tronqué - premières lignes seulement.',
    'art.kpi.empty': "Impossible d'afficher l'indicateur pour ces données.",

    // Chat - model mode picker (cost/quality dial sent with each turn)
    'mode.label': 'Mode de réponse',
    'mode.smart': 'Smart',
    'mode.pro': 'Pro',
    'mode.claude': 'Claude',
    'mode.smart_hint': 'Smart : rapide, économique et recommandé pour presque toutes vos questions. Cliquez pour changer de mode.',
    'mode.pro_hint': 'Pro : plus puissant, pour les analyses qui demandent davantage de finesse (plus coûteux). Cliquez pour changer de mode.',
    'mode.claude_hint': 'Claude : le plus puissant et de loin le plus coûteux. À réserver aux questions très complexes. Cliquez pour changer de mode.',
    // Mode-explanation popup
    'mode.modal_title': 'Mode de réponse',
    'mode.modal_intro':
      'Choisissez la puissance du modèle selon votre question. Pour la très grande majorité des cas, Smart suffit largement : les modes supérieurs sont plus puissants, mais nettement plus coûteux.',
    'mode.recommended': 'Recommandé',
    'mode.cancel': 'Annuler',
    'mode.validate': 'Valider',
    'mode.reco_line': 'Commencez toujours par Smart : rapide, économique et déjà de très bonne qualité pour la grande majorité de vos questions.',
    'mode.cost_label': 'Coût',
    'mode.speed_label': 'Vitesse',
    'mode.smart_desc':
      'Le mode à utiliser par défaut. Rapide, économique et de très bonne qualité : il couvre la quasi-totalité des recherches et des questions du quotidien. Dans le doute, restez sur Smart.',
    'mode.pro_desc':
      'Un cran au-dessus de Smart : plus puissant pour les analyses qui demandent un peu plus de finesse. Sensiblement plus coûteux que Smart, à réserver aux cas où Smart ne suffit pas.',
    'mode.claude_desc':
      'Le modèle le plus puissant (Claude), pour le raisonnement et les analyses en profondeur. À réserver aux questions vraiment complexes : soignez votre demande et expliquez précisément ce que vous attendez.',
    'mode.claude_warning':
      'Beaucoup plus cher : Claude épuise bien plus vite votre enveloppe mensuelle de 50 $. À n\'utiliser que pour des analyses complexes, avec une demande bien construite.',
    'mode.smart_cost': 'Faible',
    'mode.pro_cost': 'Modéré',
    'mode.claude_cost': 'Élevé',
    'mode.smart_speed': 'Très rapide',
    'mode.pro_speed': 'Rapide',
    'mode.claude_speed': 'Plus posé',
    'mode.envelope_note':
      'Les modes Pro et surtout Claude consomment beaucoup plus vite votre enveloppe mensuelle de 50 $. Gardez Claude pour les questions qui le justifient vraiment ; Smart suffit pour le reste.',

    // Calculation steps - frozen `kind` enum (spec §2). Params are display
    // strings ({0}/{1}/{2}, list interpolation); column names stay verbatim.
    'ev.exp.source': 'Source : {0}',
    'ev.exp.join': 'Croiser les données avec {1} ({0})',
    'ev.exp.filter_eq': 'Filtrer : {0} = {1}',
    'ev.exp.filter_neq': 'Filtrer : {0} ≠ {1}',
    'ev.exp.filter_gt': 'Filtrer : {0} > {1}',
    'ev.exp.filter_gte': 'Filtrer : {0} ≥ {1}',
    'ev.exp.filter_lt': 'Filtrer : {0} < {1}',
    'ev.exp.filter_lte': 'Filtrer : {0} ≤ {1}',
    'ev.exp.filter_in': 'Filtrer : {0} parmi {2} ({1} valeur(s))',
    'ev.exp.filter_notin': 'Filtrer : {0} hors de {2} ({1} valeur(s))',
    'ev.exp.filter_between': 'Filtrer : {0} entre {1} et {2}',
    'ev.exp.filter_null': 'Filtrer : {0} non renseigné',
    'ev.exp.filter_notnull': 'Filtrer : {0} renseigné',
    'ev.exp.filter_like': 'Filtrer : {0} correspond au motif {1}',
    'ev.exp.filter_advanced': 'Condition avancée : {0}',
    'ev.exp.filter_unmapped': 'Condition non reproduite : {0}',
    'ev.exp.group': 'Regrouper par {0}',
    'ev.exp.distinct': 'Dédupliquer les lignes',
    'ev.exp.agg_sum': 'Additionner {0}',
    'ev.exp.agg_avg': 'Moyenner {0} (valeurs renseignées)',
    'ev.exp.agg_min': 'Prendre le minimum de {0}',
    'ev.exp.agg_max': 'Prendre le maximum de {0}',
    'ev.exp.agg_count_star': 'Compter les lignes',
    'ev.exp.agg_count': 'Compter les valeurs renseignées de {0}',
    'ev.exp.agg_count_distinct': 'Compter les valeurs distinctes de {0}',
    'ev.exp.agg_filtered': 'Calculer {0} sur {1} uniquement quand {2}',
    'ev.exp.calc_ratio': 'Calculer le ratio {0} / {1}',
    'ev.exp.calc_percent': 'Calculer le pourcentage : {0}',
    'ev.exp.calc_diff': "Calculer l'écart entre {0} et {1}",
    'ev.exp.calc_share': 'Part de {0} dans le total',
    'ev.exp.window_rank': 'Classer les lignes ({0})',
    'ev.exp.window_row_number': 'Numéroter les lignes ({0})',
    'ev.exp.window_running': 'Cumul de {0} ({1})',
    'ev.exp.window_lag': 'Comparer {0} à la ligne précédente',
    'ev.exp.having': 'Ne garder que les groupes où {0}',
    'ev.exp.sort': 'Trier par {0} ({1})',
    'ev.exp.topn': 'Garder les {0} premiers (tri : {1})',
    'ev.exp.limit_arbitrary': 'Limiter à {0} lignes (sans ordre garanti)',
    'ev.exp.cte_step': 'Étape intermédiaire {0} : {1}',
    'ev.exp.union': 'Empiler avec {0} autre(s) ensemble(s) - non détaillés',
    'ev.exp.opaque': 'Opération non interprétée : {0}',

    // === Auth gate (not authenticated to DSS) - full-screen sign-in-required screen ===
    'authgate.eyebrow': 'Accès',
    'authgate.title': 'Connexion à Dataiku requise',
    'authgate.body':
      "Nous n'avons pas pu vous identifier. Connectez-vous à Dataiku DSS dans ce navigateur, puis rechargez cette page (F5). Vous pouvez aussi ouvrir OWIsMind directement depuis l'espace OWIsMind dans Dataiku DSS.",
    'authgate.reload': 'Recharger (F5)',
    'authgate.lang': 'Langue',
    'authgate.theme_dark': 'Passer au thème sombre',
    'authgate.theme_light': 'Passer au thème clair',

    // === Admin impersonation ("view as user", READ-ONLY) - isolated, removable feature ===
    'impersonate.open': 'Consulter les conversations',
    'impersonate.picker_title': 'Consulter en tant qu\'un utilisateur',
    'impersonate.search': 'Rechercher un utilisateur…',
    'impersonate.empty': 'Aucun utilisateur à afficher.',
    'impersonate.loading': 'Chargement des utilisateurs…',
    'impersonate.error': 'Chargement impossible. Réessayez.',
    'impersonate.banner': 'Consultation en tant que {0} (revue admin) - lecture seule',
    'impersonate.exit': 'Quitter la consultation',
    'impersonate.readonly_note':
      'Lecture seule : vous consultez le compte de {0}, l\'envoi est désactivé.',

    // === Benchmark suggestions (collaborative golden-set intake, ALL users) ===
    'sb.benchmark': 'Benchmark',
    'rail.benchmark': 'Suggérer pour le benchmark',
    'msg.suggest_benchmark': 'Suggérer pour le benchmark',
    'bench.eyebrow': 'Benchmark',
    'bench.title': 'Suggérer une question de test',
    'bench.desc':
      "Aidez-nous à évaluer les agents : proposez une question avec la bonne réponse que vous connaissez. Vos suggestions alimentent les prochains benchmarks qui mesurent la justesse des agents.",
    // From-chat suggestion (pre-filled from an answer)
    'bench.modal.title': 'Suggérer cette question pour le benchmark',
    'bench.modal.intro':
      "Vérifiez la question et la réponse de l'agent, puis indiquez si la réponse est correcte. Si elle ne l'est pas, donnez la bonne réponse : votre retour servira à tester l'agent.",
    'bench.modal.question_label': 'Question posée',
    'bench.modal.answer_label': "Réponse de l'agent",
    'bench.modal.verdict_label': "La réponse de l'agent est-elle correcte ?",
    'bench.modal.verdict_yes': 'Oui, elle est correcte',
    'bench.modal.verdict_no': 'Non, elle est incorrecte ou incomplète',
    'bench.modal.reference_label': 'Réponse correcte attendue',
    'bench.modal.reference_ph': 'Indiquez la bonne réponse (chiffres, périmètre, etc.)',
    'bench.modal.missing_label': 'Ce qui manque ou ce qui cloche (facultatif)',
    'bench.modal.missing_ph': "Ex. : il a oublié le filtre sur l'année",
    'bench.modal.category_label': 'Catégorie (facultatif)',
    'bench.modal.category_ph': 'Ex. : revenus, tickets',
    'bench.modal.submit': 'Envoyer la suggestion',
    'bench.modal.cancel': 'Annuler',
    // Manual suggestion (from scratch)
    'bench.form.title': 'Nouvelle question de test',
    'bench.form.question_label': 'Question',
    'bench.form.question_ph': "La question à poser à l'agent",
    'bench.form.reference_label': 'Réponse correcte attendue',
    'bench.form.reference_ph': 'La bonne réponse, que vous savez exacte',
    'bench.form.expected_label': 'Valeur clé à vérifier (facultatif)',
    'bench.form.expected_ph': 'Ex. : 12345, 2026-03-31',
    'bench.form.expected_type_label': 'Type',
    'bench.form.type.none': '- aucun -',
    'bench.form.type.numeric': 'Nombre',
    'bench.form.type.currency': 'Montant',
    'bench.form.type.date': 'Date',
    'bench.form.type.string': 'Texte',
    'bench.form.type.list': 'Liste',
    'bench.form.expected_help':
      "Si une seule valeur précise répond à la question (un nombre, un montant, une date), indiquez-la : elle servira d'ancre de vérification automatique.",
    'bench.form.category_label': 'Catégorie (facultatif)',
    'bench.form.category_ph': 'Ex. : revenus, tickets',
    'bench.form.submit': 'Envoyer la suggestion',
    'bench.form.submitting': 'Envoi…',
    // My suggestions list
    'bench.mine.title': 'Mes suggestions',
    'bench.mine.loading': 'Chargement…',
    'bench.mine.empty': "Vous n'avez pas encore proposé de question.",
    'bench.mine.col_question': 'Question',
    'bench.mine.col_source': 'Origine',
    'bench.mine.col_status': 'Statut',
    'bench.mine.col_date': 'Date',
    'bench.status.pending': 'En attente',
    'bench.status.accepted': 'Acceptée',
    'bench.status.rejected': 'Écartée',
    'bench.source.chat': 'Conversation',
    'bench.source.manual': 'Manuelle',
    'bench.sent': 'Merci ! Votre suggestion a bien été envoyée.',
    'bench.send_failed': "Échec de l'envoi de la suggestion. Réessayez.",

    // === Benchmark tab - broader page header ===
    'bench.page_title': 'Benchmark des agents',
    'bench.page_desc':
      "Consultez la justesse des agents mesurée par le benchmark, puis aidez à l'améliorer en proposant des questions de test.",

    // Consultation (results)
    'bench.consult.title': 'Résultats du benchmark',
    'bench.consult.desc':
      "Choisissez un agent pour voir sa dernière évaluation : justesse globale, détail par mode et par sujet, question par question.",
    'bench.consult.agent_label': 'Agent',
    'bench.consult.no_agents_title': 'Aucun benchmark disponible',
    'bench.consult.no_agents':
      "Aucun agent ne dispose encore d'un benchmark. Un administrateur peut en activer un depuis la fiche d'un agent.",
    'bench.consult.loading': 'Chargement des résultats…',
    'bench.consult.not_configured': "Aucun benchmark n'est configuré pour cet agent.",
    'bench.consult.read_error':
      'Les résultats ont été lus en mode dégradé : certaines informations peuvent manquer.',
    'bench.consult.load_error': 'Impossible de charger les résultats du benchmark.',
    'bench.consult.no_results': "Aucun résultat de benchmark pour cet agent pour l'instant.",
    'bench.consult.run_label': 'Exécution',
    'bench.consult.hero': '{0} réponses correctes sur {1}',

    // KPI tiles
    'bench.kpi.accuracy': 'Justesse',
    'bench.kpi.questions': 'Questions',
    'bench.kpi.configs': 'Configurations',
    'bench.kpi.cost': 'Coût total',
    'bench.kpi.needs_review': 'À revoir',

    // Confidence band (donut)
    'bench.band.high': 'Confiance élevée',
    'bench.band.medium': 'Confiance moyenne',
    'bench.band.low': 'Confiance faible',
    'bench.band.unknown': 'Confiance',

    // Per agent x mode table
    'bench.cfg.title': 'Résultats par agent et par mode',
    'bench.cfg.col_config': 'Agent / mode',
    'bench.cfg.col_questions': 'Questions',
    'bench.cfg.col_ok': 'OK',
    'bench.cfg.col_error': 'Erreurs',
    'bench.cfg.col_accuracy': 'Justesse',
    'bench.cfg.col_score': 'Score',
    'bench.cfg.col_latency': 'Latence moy.',
    'bench.cfg.col_cost': 'Coût moy.',
    'bench.cfg.col_review': 'À revoir',

    // Per category bars
    'bench.cat.title': 'Justesse par sujet',
    'bench.cat.count': '{0} question(s)',
    'bench.cat.uncategorized': 'Sans catégorie',

    // Per question table
    'bench.detail.title': 'Question par question',
    'bench.detail.col_question': 'Question',
    'bench.detail.col_category': 'Catégorie',
    'bench.detail.col_agent': 'Agent / mode',
    'bench.detail.col_judge': 'Juge',
    'bench.detail.col_verdict': 'Verdict',
    'bench.detail.reference': 'Réponse attendue',
    'bench.detail.expected': 'Valeur clé',
    'bench.detail.answer': "Réponse de l'agent",
    'bench.detail.judge_comment': 'Commentaire du juge',
    'bench.detail.notes': 'Notes',
    'bench.detail.objective': 'Ancre objective',
    'bench.detail.objective_yes': 'Concordance exacte',
    'bench.detail.objective_no': 'Pas de concordance exacte',
    'bench.detail.reviewed': 'Revu par',

    // On-demand full evidence (complete answer + generated SQL + result table)
    'bench.ev.title': "Ce que l'agent a réellement fait",
    'bench.ev.answer': "Réponse complète de l'agent",
    'bench.ev.sql': "SQL généré par l'agent",
    'bench.ev.query': 'Requête {0}',
    'bench.ev.rows': '{0} ligne(s)',
    'bench.ev.ok': 'succès',
    'bench.ev.failed': 'échec',
    'bench.ev.data': 'Données utilisées pour répondre',
    'bench.ev.no_sql': "L'agent n'a généré aucun SQL pour cette réponse.",
    'bench.ev.no_data': 'Aucune ligne de résultat capturée pour cette requête.',
    'bench.ev.truncated': "Résultat tronqué pour l'affichage.",
    'bench.ev.loading': 'Chargement du détail complet...',
    'bench.ev.error': 'Impossible de charger le détail complet.',
    'bench.ev.empty': 'Aucun détail capturé pour cette tentative.',

    // Verdict badges
    'bench.verdict.correct': 'Correct',
    'bench.verdict.incorrect': 'Incorrect',
    'bench.verdict.review': 'À revoir',
    'bench.verdict.unknown': 'Indéterminé',
    'bench.verdict.overridden': 'Ajusté',

    // Consultation hero + reference (LAB results parity)
    'bench.consult.correct_label': 'Bonnes réponses',
    'bench.consult.hero_note': "À quelle fréquence l'IA donne la bonne réponse.",
    'bench.consult.hero_meta': '{0} question(s) de référence, {1} configuration(s) testée(s)',
    'bench.cfg.questions_n': '{0} question(s)',
    'bench.detail.col_result': 'Résultat',
    'bench.detail.col_score': 'Score',
    'bench.detail.show': 'Voir les détails',
    'bench.detail.hide': 'Masquer les détails',
    'bench.ref.measure_h': "Comment c'est mesuré",
    'bench.ref.measure_p':
      "Chaque agent répond à une liste de questions de référence validées par un humain. La justesse est la part de réponses correctes.",
    'bench.ref.score_h': 'Score et verdict',
    'bench.ref.judge_t': 'Juge IA',
    'bench.ref.judge_d':
      'Un modèle note chaque réponse en tenant compte de la note humaine de sévérité.',
    'bench.ref.dc_t': 'À revoir',
    'bench.ref.dc_d': 'Réponses où le contrôle automatique et le juge IA sont en désaccord.',
    'bench.ref.modes_h': 'Modes',
    'bench.ref.modes_p': 'Un agent peut tourner en plusieurs modes ; chacun est une configuration.',
    'bench.ref.modes_std': 'Standard : agent sans sélecteur de mode.',

    // Admin review + override
    'bench.review.title': 'Revue administrateur',
    'bench.review.mark_correct': 'Marquer correct',
    'bench.review.mark_incorrect': 'Marquer incorrect',
    'bench.review.clear': "Retirer l'ajustement",
    'bench.review.comment_ph': 'Commentaire (facultatif)',
    'bench.review.saved': 'Verdict mis à jour.',
    'bench.review.failed': "Échec de la mise à jour du verdict.",
    'bench.review.reset_note':
      'Relancer la MÊME exécution réinitialise les ajustements ; les ajustements des exécutions passées sont conservés.',
    'bench.review.reviewed_by': '{0} le {1}',

    // Benchmark v2: selector, per-question evolution, reference vs produced
    'bench.consult.benchmark_label': 'Benchmark',
    'bench.consult.benchmark_caption': 'Benchmark : {0}',
    'bench.evo.improved': 'En progrès',
    'bench.evo.regressed': 'En recul',
    'bench.evo.same': 'Stable',
    'bench.evo.first': 'Première tentative',
    'bench.evo.attempts_n': '{0} tentatives',
    'bench.evo.attempt_n': 'Tentative {0}',
    'bench.evo.history_title': 'Évolution des tentatives',
    'bench.refprod.title': 'Référence et production',
    'bench.refprod.reference_sql': 'SQL de référence',
    'bench.refprod.suggested_tool': 'Outil suggéré',
    'bench.refprod.tools_used': 'Outils utilisés',
    'bench.refprod.none': '- aucun -',

    // Suggest sub-section (accordion)
    'bench.section.suggest_title': 'Suggérer une question de test',
    'bench.section.suggest_desc':
      'Proposez une question avec la bonne réponse que vous connaissez : elle alimente les prochains benchmarks.',

    // Admin agent-profile benchmark section
    'bench.profile.section': 'Benchmark',
    'bench.profile.enabled': 'Cet agent dispose d\'un benchmark',
    'bench.profile.enabled_hint':
      "Quand c'est activé, les utilisateurs peuvent consulter les résultats de cet agent dans l'onglet Benchmark.",
    'bench.profile.connection': 'Connexion SQL',
    'bench.profile.table': 'Table des résultats',
    'bench.profile.table_ph': 'Choisir ou saisir une table',
    'bench.profile.tables_loading': 'Chargement des tables…',
    'bench.profile.tables_error': 'Impossible de lister les tables de cette connexion.',
    'bench.profile.refresh_tables': 'Rafraîchir les tables',
    'bench.profile.agent_key': "Clé d'agent (filtre, facultatif)",
    'bench.profile.agent_key_ph': 'Ex. : agent:038G7mlF',
    'bench.profile.agent_key_hint':
      "Si la table contient plusieurs agents, indiquez la clé d'agent à filtrer.",
    'bench.profile.validate': 'Vérifier le schéma',
    'bench.profile.validating': 'Vérification…',
    'bench.profile.ok': 'Schéma compatible.',
    'bench.profile.missing': 'Schéma incompatible : colonnes manquantes : {0}',
    'bench.profile.error': 'Impossible de vérifier le schéma.',

    // === Source Data Explorer (browse an agent's configured datasets) ===
    'ev.tab.sources': 'Données sources',
    'src.cta.title': 'Explorer les données sources',
    'src.cta.hint': "Parcourez les jeux de données de l'agent : recherchez, filtrez et triez sans écrire de requête.",
    'src.panel.title': 'Données sources',
    'src.dataset_label': 'Jeu de données',
    'src.search.placeholder': 'Rechercher dans le jeu de données…',
    'src.search.min': 'Saisissez au moins 2 caractères pour lancer la recherche.',
    'src.filters.title': 'Filtres',
    'src.filters.add': 'Ajouter un filtre',
    'src.filters.clear': 'Tout effacer',
    'src.filters.remove': 'Retirer ce filtre',
    'src.column': 'Colonne…',
    'src.picker.empty': 'Aucune valeur disponible.',
    'src.picker.truncated': 'Premières {0} valeurs distinctes',
    'src.picker.max': 'Maximum {0} valeurs par filtre',
    'src.picker.apply': 'Appliquer',
    'src.loading': 'Chargement…',
    'src.error': 'Impossible de charger les données.',
    'src.retry': 'Réessayer',
    'src.empty': 'Aucune ligne ne correspond.',
    'src.loaded': '{0} ligne(s) chargée(s)',
    'src.more': 'Faites défiler pour charger plus',
    'src.loadingMore': 'Chargement…',
    // Admin: attach source datasets to an agent's profile (agent-profile modal).
    'src.admin.section': 'Jeux de données sources',
    'src.admin.hint': "Jeux de données bruts que l'agent expose : les utilisateurs peuvent les parcourir (recherche, filtres, tri) sans écrire de requête. 8 au maximum.",
    'src.admin.dataset_ph': 'Nom du jeu de données',
    'src.admin.label_ph': 'Nom affiché (optionnel)',
    'src.admin.add': 'Ajouter un jeu de données',
    'src.admin.remove': 'Retirer',
    'src.admin.load_error': 'Impossible de charger la liste des jeux de données.',
    'src.admin.refresh': 'Actualiser la liste',
  },
  en: {
    // Generic reusable
    'x.soon': 'Soon',
    'x.coming_soon': 'Coming soon',
    'x.close': 'Close',

    // Chat - prompt guidance: better input → better answer. Overrides the maquette's
    // neutral placeholder (messages.json) and adds an empty-screen tip.
    'prompt.placeholder': 'Describe your request as precisely as possible…',
    'empty.tip':
      'Tip: the more precise and well-phrased your request - the terms you use, the period, the scope - the better the answer.',

    // Settings - profile groups label
    'set.profile.groups': 'Groups',

    // Settings - monthly budget card (real /usage data)
    'set.budget.loading': 'Loading your usage…',
    'set.budget.resets': 'Resets on {0}',
    'set.budget.blocked':
      'Monthly budget reached. New requests resume on {0} (monthly reset).',
    'set.budget.off': 'Usage tracking is on. No monthly limit is currently enforced.',
    'set.budget.src_default': 'Monthly limit: {0} (default).',
    'set.budget.src_global_temp': 'Monthly limit: {0} (temporary boost until {1}).',
    'set.budget.src_user': 'Monthly limit: {0} (granted by an administrator).',
    'set.budget.src_user_temp': 'Monthly limit: {0} (temporary boost until {1}).',

    // Settings - usage detail (this month + lifetime)
    'set.usage.tokens': 'tokens',
    'set.usage.tokens_month': 'Tokens this month',
    'set.usage.spend_month': 'Spend this month',
    'set.usage.lifetime_cost': 'Lifetime spend',
    'set.usage.last': 'Last activity',

    // Settings - agent-context window (repurposed from the old "conversations shown").
    'set.context': 'Context',
    'set.context.max': 'History messages sent to the agent',
    'set.context.max_desc':
      'Number of recent conversation messages included as context (between 10 and 50).',

    // Sidebar - conversation list states
    'sb.conv_loading': 'Loading conversations…',
    'sb.conv_empty': 'No conversation yet.',
    'sb.conv_error': 'Failed to load history.',
    'sb.loadingMore': 'Loading…',

    // Thread lazy load (on click)
    'chat.loadingThread': 'Loading conversation…',
    'chat.loadThreadError': 'Could not load this conversation.',

    // Chat - stop generation (the ■ button + interrupted-answer markers)
    'prompt.stop': 'Stop generating',
    'chat.stopped': 'Generation stopped',
    'chat.stopping': 'Stopping…',
    'chat.interrupted_empty': 'Response interrupted',

    // Chat - monthly budget banner (sends paused once the credit is reached)
    'chat.quota_banner':
      'Monthly budget reached: {0} used of {1}. New requests resume on {2}.',
    'chat.quota_short': 'Monthly budget reached. Try again after the 1st-of-month reset.',

    // Chat - the collapsed activity block (agent steps header line)
    'tl.steps': 'Agent steps',
    'tl.steps_count': '{0} step(s)',
    'tl.seconds': '{0}s',

    // Feedback - the "other" reason (the rest live in messages.json's maquette port).
    'fb.reason.other': 'Other',
    'msg.feedback_failed': 'Could not send feedback.',

    // Feedback - adaptive modal (positive variant) + the ⋯ detailed-feedback entry.
    'msg.feedback_title_positive': 'What did you like?',
    'msg.feedback_suggestion_label_positive': 'Tell us what you liked',
    'msg.more_options': 'More options',
    'msg.give_feedback': 'Give detailed feedback',

    // Per-message token/cost usage line (shown under each agent answer).
    'msg.usage_tokens': 'tokens',
    'msg.usage_in': 'Input tokens (question + context)',
    'msg.usage_out': 'Output tokens (generated answer)',
    'msg.usage_cost': 'Estimated cost of this exchange',

    // Feedback - no submit endpoint yet
    'fb.soon_note': 'Feedback submission will be available soon. The OWI team is preparing this service.',
    'fb.empty': "You don't have any request yet.",

    // FAQ - client-side search (the maquette never wired it)
    'faq.no_results': 'No result for "{0}".',

    // Agents - fallbacks for agents not described in the local registry
    'ag.generic_tagline': 'OWI AI agent',
    'ag.generic_desc':
      'This agent is enabled for your account. Its detailed profile is not documented yet.',
    'ag.no_agents': 'No agent is enabled for your account. Please contact an administrator.',
    'ag.tools_section_empty': 'No tools documented.',

    // Project - no project API yet
    'pj.coming':
      'Project management will be available soon: grouping conversations, custom instructions and per-project tracking.',

    // Admin - the maquette kept all admin strings inline (al(fr,en)); ported here.
    'admin.eyebrow': 'Admin console',
    'admin.title': 'Administration',
    'admin.desc': 'Manage storage, exposed agents and administrators.',
    'admin.loading': 'Loading admin space…',
    'admin.load_error': 'Failed to load the admin space.',
    'admin.tab.overview': 'Overview',
    'admin.tab.agents': 'Agents',
    'admin.tab.users': 'Users',
    'admin.tab.quotas': 'Quotas & budgets',
    'admin.tab.activity': 'Activity log',
    'admin.kpi.users': 'Users',
    'admin.kpi.agents': 'Exposed agents',
    'admin.kpi.connection': 'SQL connection',
    'admin.storage.title': 'Storage',
    'admin.storage.connection': 'SQL connection',
    'admin.storage.project_key': 'Project key',
    'admin.storage.prefix': 'Prefix',
    'admin.storage.namespace': 'Namespace',
    'admin.storage.tables': 'Tables (project key + namespace always kept)',
    'admin.storage.none': '(none)',
    'admin.storage.traces': 'Trace dataset',
    'admin.storage.traces_off': '(none - trace storage disabled)',
    'admin.storage.prefix_ignored':
      'Prefix “{0}” ignored: too long or invalid (max 16 chars: letters, digits, _ and -).',
    'admin.storage.note':
      'To change the connection or prefix: the webapp\'s Settings tab (the "SQL connection" dropdown), then restart the backend.',
    'admin.agents.title': 'Exposed agents',
    'admin.agents.desc':
      'Pick a project, tick the agents to expose, then save. Users only see the agents enabled here.',
    'admin.agents.project': 'Project',
    'admin.agents.project_choose': '- Select a project -',
    'admin.agents.loading': 'Loading agents…',
    'admin.agents.none_in_project': 'No agent in this project.',
    'admin.agents.enabled_title': 'Enabled (all sources)',
    'admin.agents.save': 'Save selection',
    'admin.agents.saving': 'Saving…',
    'admin.agents.saved': '{0} agent(s) saved.',
    'admin.agents.remove': 'Remove',
    'admin.users.title': 'Users',
    'admin.users.desc': 'Promote to admin someone who has already opened the webapp.',
    'admin.users.col_user': 'User',
    'admin.users.col_groups': 'Groups',
    'admin.users.col_admin': 'Admin',
    'admin.users.you': '(you)',
    'admin.users.make_admin': 'Make admin',
    'admin.users.revoke_admin': 'Revoke admin',
    'admin.users.last_admin_error': 'Not allowed: at least one admin must remain.',
    // Admin - monthly budgets / quotas (real)
    'admin.quotas.title': 'Monthly budgets',
    'admin.quotas.desc':
      'Every user gets a monthly credit (default {0}) that resets on the 1st. Adjust the global limit or grant per-user limits.',
    'admin.quotas.loading': 'Loading budgets…',
    'admin.quotas.error': 'The operation failed.',
    'admin.quotas.global_title': 'Global settings',
    'admin.quotas.default_limit': 'Default monthly limit ($)',
    'admin.quotas.enabled': 'Enforce the limit (block when exceeded)',
    'admin.quotas.enabled_hint':
      'When off, usage is still tracked and shown, but no request is ever blocked.',
    'admin.quotas.temp_title': 'Temporary boost (all users)',
    'admin.quotas.temp_amount': 'Temporary limit ($)',
    'admin.quotas.temp_days': 'Duration (days)',
    'admin.quotas.temp_active': 'Global boost active: {0} until {1}.',
    'admin.quotas.temp_clear': 'Remove the global boost',
    'admin.quotas.temp_apply': 'Apply boost',
    'admin.quotas.save': 'Save configuration',
    'admin.quotas.saving': 'Saving…',
    'admin.quotas.saved': 'Configuration saved.',
    'admin.quotas.users_title': 'Per-user limits',
    'admin.quotas.users_desc':
      'Tick one or more users, then grant a limit (permanent or temporary) or reset them to the default.',
    'admin.quotas.col_user': 'User',
    'admin.quotas.col_usage': 'This month',
    'admin.quotas.col_limit': 'Limit',
    'admin.quotas.col_remaining': 'Remaining',
    'admin.quotas.col_source': 'Source',
    'admin.quotas.src.default': 'Default',
    'admin.quotas.src.global_temp': 'Global boost',
    'admin.quotas.src.user_permanent': 'Custom',
    'admin.quotas.src.user_temp': 'Temporary',
    'admin.quotas.blocked_tag': 'Blocked',
    'admin.quotas.expires_on': 'until {0}',
    'admin.quotas.select_all': 'All',
    'admin.quotas.selected': '{0} selected',
    'admin.quotas.none_selected': 'Select at least one user.',
    'admin.quotas.apply_title': 'Apply to the {0} selected user(s)',
    'admin.quotas.limit_amount': 'New limit ($)',
    'admin.quotas.duration': 'Duration',
    'admin.quotas.permanent': 'Permanent',
    'admin.quotas.temp_days_opt': 'Temporary ({0}d)',
    'admin.quotas.note': 'Note (optional)',
    'admin.quotas.apply': 'Apply limit',
    'admin.quotas.applying': 'Applying…',
    'admin.quotas.clear': 'Reset to default',
    'admin.quotas.applied': '{0} user(s) updated.',
    'admin.activity.empty': 'The activity log will be available soon.',

    // === Charte redesign additions =========================================
    // Account (the page formerly "Settings" -> "My account").
    'set.eyebrow': 'My account',
    'set.title': 'My account',
    'sb.settings': 'My account',
    'sb.account': 'Account',

    // Sidebar - collapsed icon rail (tooltips).
    'sb.expand': 'Expand menu',
    'sb.collapse': 'Collapse menu',
    'rail.new': 'New conversation',
    'rail.chat': 'Conversations',
    'rail.agents': 'Agents',
    'rail.help': 'Help and support',
    'rail.account': 'My account',

    // Agents library - list + detail.
    'ag.eyebrow': 'Library',
    'ag.title': 'Available agents',
    'ag.desc':
      'The OWI agents deployed on Dataiku DSS. Open an agent to see what it can do, then start a conversation.',
    'ag.search': 'Search agents…',
    'ag.no_match': 'No agent matches "{0}".',
    'ag.count': '{0} agent(s)',
    'ag.back': 'All agents',
    'ag.capabilities': 'What this agent does',
    'ag.tools': 'Exposed tools',
    'ag.tools_count': '{0} tool(s)',
    'ag.new_conv_with': 'Start a conversation',
    'ag.start': 'Start a conversation',
    'ag.open': 'View profile',
    'ag.badge.default': 'Default',
    'ag.badge.new': 'New',
    'ag.badge.beta': 'Beta',
    'ag.meta_missing': "This agent's profile has not been filled in by an administrator yet.",

    // Admin - agent profile editor (admin-authored, stored with the whitelist).
    'admin.agents.pick_project': 'Source project',
    'admin.agents.in_project': 'Agents in the project',
    'admin.agents.add': 'Add',
    'admin.agents.added': 'Added',
    'admin.agents.enabled_count': 'Exposed agents ({0})',
    'admin.agents.enabled_empty':
      'No agent exposed yet. Pick a project, then add the agents you want to make available.',
    'admin.agents.configure': 'Edit profile',
    'admin.agents.no_profile': 'Profile to complete',
    'admin.agents.has_profile': 'Profile filled in',
    'admin.agents.editor_title': 'Agent profile',
    'admin.agents.editor_desc':
      "This profile is what your users see in the library. Fill it in so they understand what the agent can do.",
    'admin.agents.f_label': 'Agent (Dataiku)',
    'admin.agents.f_icon': 'Icon',
    'admin.agents.f_badge': 'Badge',
    'admin.agents.f_tagline': 'Tagline',
    'admin.agents.f_tagline_ph': 'e.g. Revenue, budget and forecast',
    'admin.agents.f_desc': 'Description',
    'admin.agents.f_desc_ph':
      'Describe in a few sentences what the agent can do, its data sources and when to use it.',
    'admin.agents.f_caps': 'Capabilities',
    'admin.agents.f_caps_ph': 'One capability per line',
    'admin.agents.f_caps_hint': 'One capability per line (8 max).',
    'admin.agents.f_tools': 'Exposed tools',
    'admin.agents.f_tools_ph': 'One tool per line',
    'admin.agents.f_tools_hint': 'Names shown to users (one per line, 16 max).',
    'admin.agents.f_modes': 'Response modes',
    'admin.agents.f_modes_opt': 'This agent supports the response modes (Smart / Pro / Claude)',
    'admin.agents.f_modes_hint':
      'Tick this only for an OWI code agent that can interpret the modes (e.g. the OWIsMind orchestrator). For a plain visual agent, leave it off: the mode picker then stays hidden in chat.',
    'admin.agents.badge.none': 'None',
    'admin.agents.badge.default': 'Default',
    'admin.agents.badge.new': 'New',
    'admin.agents.badge.beta': 'Beta',
    'admin.agents.preview': 'Preview',
    'admin.agents.editor_done': 'Done',
    'admin.agents.unsaved': 'Profiles edited - click "{0}" to apply.',
    'admin.agents.char_count': '{0}/{1}',

    // Evidence Studio (v1) - the proof panel
    'ev.title': 'Evidence Studio',
    'ev.open': 'Evidence',
    'ev.close': 'Close evidence',
    'ev.filters': 'Filters applied by the agent',
    'ev.filters.add': 'Add a filter',
    'ev.filters.reset': 'Agent version',
    'ev.filters.advanced': 'Advanced condition',
    'ev.filters.remove': 'Remove this filter',
    'ev.modified': 'Filters modified',
    'ev.table.empty': 'No row matches the filters.',
    'ev.table.page': 'Page {0}',
    'ev.table.prev': 'Previous page',
    'ev.table.next': 'Next page',
    'ev.table.source': 'Source table',
    'ev.table.loaded': '{0} row(s) loaded',
    'ev.table.more': 'Scroll to load more',
    'ev.table.loadingMore': 'Loading…',
    'ev.sql.title': 'Technical details (SQL)',
    'ev.sql.copy': 'Copy SQL',
    'ev.sql.copied': 'SQL copied',
    'ev.degraded': 'Interactive view unavailable - here is the exact query the agent ran.',
    'ev.degraded.no_dataset': 'The table the agent queried maps to no SQL dataset in this project - the interactive view is unavailable. Here is the exact query the agent ran.',
    'ev.degraded.no_sql': 'This answer produced no usable SQL query - nothing to visualize.',
    'ev.error': 'Could not load the evidence.',
    'ev.retry': 'Retry',
    'ev.loading': 'Loading evidence…',
    'ev.picker.empty': 'No value available.',
    'ev.picker.truncated': 'First {0} distinct values',
    'ev.picker.max': 'Up to {0} values per filter',
    'ev.picker.apply': 'Apply',
    'ev.column': 'Column…',

    // - Evidence trust layer (v2) - proof levels, sources, calc steps, result, drill.
    // Badge wording is deliberately CAUTIOUS (honesty rules, spec §9): "certified"
    // only for deterministically verified levels, "claim" for raw agent claims.
    'ev.proof.level.result': 'Certified result',
    'ev.proof.level.source': 'Certified source',
    'ev.proof.level.partial': 'Partial proof',
    'ev.proof.level.declared': 'Agent claim',
    'ev.proof.level.partial_note': '{0} element(s) not reproduced',
    'ev.proof.level.desc.result':
      'The computation is decomposed step by step and the exact result the agent used was kept.',
    'ev.proof.level.desc.source':
      'The exact source and scope of the query are identified - the rows shown are re-read now, not at answer time.',
    'ev.proof.level.desc.partial':
      'Only part of the scope could be reproduced - anything not reproduced is listed, never hidden.',
    'ev.proof.level.desc.declared':
      'Agent claim: this query could not be verified automatically.',
    'ev.proof.sources': 'Data source',
    'ev.proof.sources.more': '+{0} more quer(y/ies) run',
    'ev.proof.sources.open': 'Open the dataset in Dataiku',
    'ev.proof.calc': 'How this result is computed',
    'ev.proof.result': 'Result used by the agent',
    'ev.proof.result.rows': '{0} row(s)',
    'ev.proof.result.missing': 'The exact result the agent used was not kept for this answer.',
    'ev.proof.result.truncated': 'Result truncated - first rows only.',
    'ev.proof.result.drill': 'See the source rows behind this result',
    'ev.proof.drill.banner': 'Source rows: {0}',
    'ev.proof.drill.exit': 'Back to the result',
    'ev.proof.explore': 'Explore the source data',

    // Evidence Studio - artifact tabs (KPI / chart / table)
    'art.tab.evidence': 'Evidence',
    'art.tab.chart': 'Chart',
    'art.tab.table': 'Table',
    'art.tab.kpi': 'KPI',
    'art.chart.empty': 'Cannot render the chart for this data.',
    'art.chart.truncated': 'Data truncated - first values only.',
    'art.chart.title_fallback': 'Chart',
    'art.table.empty': 'The exact result the agent used was not kept for this answer.',
    'art.table.truncated': 'Result truncated - first rows only.',
    'art.kpi.empty': 'Cannot display the KPI for this data.',

    // Chat - model mode picker (cost/quality dial sent with each turn)
    'mode.label': 'Response mode',
    'mode.smart': 'Smart',
    'mode.pro': 'Pro',
    'mode.claude': 'Claude',
    'mode.smart_hint': 'Smart: fast, economical and recommended for almost every question. Click to change mode.',
    'mode.pro_hint': 'Pro: more powerful, for analyses that need extra finesse (more expensive). Click to change mode.',
    'mode.claude_hint': 'Claude: the most powerful and by far the most expensive. Reserve it for very complex questions. Click to change mode.',
    // Mode-explanation popup
    'mode.modal_title': 'Response mode',
    'mode.modal_intro':
      'Choose the model power to match your question. For the vast majority of cases, Smart is more than enough: the higher modes are more powerful but noticeably more expensive.',
    'mode.recommended': 'Recommended',
    'mode.cancel': 'Cancel',
    'mode.validate': 'Apply',
    'mode.reco_line': 'Always start with Smart: fast, economical and already very good quality for the vast majority of your questions.',
    'mode.cost_label': 'Cost',
    'mode.speed_label': 'Speed',
    'mode.smart_desc':
      'The mode to use by default. Fast, economical and very good quality: it covers almost all lookups and everyday questions. When in doubt, stay on Smart.',
    'mode.pro_desc':
      'A step up from Smart: more powerful for analyses that need a bit more finesse. Noticeably more expensive than Smart, for when Smart is not enough.',
    'mode.claude_desc':
      'The most powerful model (Claude), for deep reasoning and analysis. Reserve it for genuinely complex questions: craft your request and explain precisely what you expect.',
    'mode.claude_warning':
      'Much more expensive: Claude burns through your $50/month envelope far faster. Use it only for complex analyses, with a well-crafted request.',
    'mode.smart_cost': 'Low',
    'mode.pro_cost': 'Moderate',
    'mode.claude_cost': 'High',
    'mode.smart_speed': 'Very fast',
    'mode.pro_speed': 'Fast',
    'mode.claude_speed': 'More deliberate',
    'mode.envelope_note':
      'The Pro and especially Claude modes use up your $50/month envelope much faster. Keep Claude for questions that genuinely warrant it; Smart is enough for the rest.',

    // Calculation steps - frozen `kind` enum (spec §2). Params are display
    // strings ({0}/{1}/{2}, list interpolation); column names stay verbatim.
    'ev.exp.source': 'Source: {0}',
    'ev.exp.join': 'Combine the data with {1} ({0})',
    'ev.exp.filter_eq': 'Filter: {0} = {1}',
    'ev.exp.filter_neq': 'Filter: {0} ≠ {1}',
    'ev.exp.filter_gt': 'Filter: {0} > {1}',
    'ev.exp.filter_gte': 'Filter: {0} ≥ {1}',
    'ev.exp.filter_lt': 'Filter: {0} < {1}',
    'ev.exp.filter_lte': 'Filter: {0} ≤ {1}',
    'ev.exp.filter_in': 'Filter: {0} among {2} ({1} value(s))',
    'ev.exp.filter_notin': 'Filter: {0} excluding {2} ({1} value(s))',
    'ev.exp.filter_between': 'Filter: {0} between {1} and {2}',
    'ev.exp.filter_null': 'Filter: {0} is empty',
    'ev.exp.filter_notnull': 'Filter: {0} is filled in',
    'ev.exp.filter_like': 'Filter: {0} matches the pattern {1}',
    'ev.exp.filter_advanced': 'Advanced condition: {0}',
    'ev.exp.filter_unmapped': 'Condition not reproduced: {0}',
    'ev.exp.group': 'Group by {0}',
    'ev.exp.distinct': 'Remove duplicate rows',
    'ev.exp.agg_sum': 'Sum {0}',
    'ev.exp.agg_avg': 'Average {0} (filled-in values)',
    'ev.exp.agg_min': 'Take the minimum of {0}',
    'ev.exp.agg_max': 'Take the maximum of {0}',
    'ev.exp.agg_count_star': 'Count the rows',
    'ev.exp.agg_count': 'Count the filled-in values of {0}',
    'ev.exp.agg_count_distinct': 'Count the distinct values of {0}',
    'ev.exp.agg_filtered': 'Compute {0} on {1} only when {2}',
    'ev.exp.calc_ratio': 'Compute the ratio {0} / {1}',
    'ev.exp.calc_percent': 'Compute the percentage: {0}',
    'ev.exp.calc_diff': 'Compute the difference between {0} and {1}',
    'ev.exp.calc_share': 'Share of {0} in the total',
    'ev.exp.window_rank': 'Rank the rows ({0})',
    'ev.exp.window_row_number': 'Number the rows ({0})',
    'ev.exp.window_running': 'Running total of {0} ({1})',
    'ev.exp.window_lag': 'Compare {0} with the previous row',
    'ev.exp.having': 'Keep only groups where {0}',
    'ev.exp.sort': 'Sort by {0} ({1})',
    'ev.exp.topn': 'Keep the top {0} (sort: {1})',
    'ev.exp.limit_arbitrary': 'Limit to {0} rows (no guaranteed order)',
    'ev.exp.cte_step': 'Intermediate step {0}: {1}',
    'ev.exp.union': 'Stack with {0} other set(s) - not detailed',
    'ev.exp.opaque': 'Operation not interpreted: {0}',

    // === Auth gate (not authenticated to DSS) - full-screen sign-in-required screen ===
    'authgate.eyebrow': 'Access',
    'authgate.title': 'Sign in to Dataiku required',
    'authgate.body':
      'We could not identify you. Please sign in to Dataiku DSS in this browser, then reload this page (F5). You can also open OWIsMind directly from the OWIsMind workspace in Dataiku DSS.',
    'authgate.reload': 'Reload (F5)',
    'authgate.lang': 'Language',
    'authgate.theme_dark': 'Switch to dark theme',
    'authgate.theme_light': 'Switch to light theme',

    // === Admin impersonation ("view as user", READ-ONLY) - isolated, removable feature ===
    'impersonate.open': 'Review conversations',
    'impersonate.picker_title': 'View as a user',
    'impersonate.search': 'Search a user…',
    'impersonate.empty': 'No user to show.',
    'impersonate.loading': 'Loading users…',
    'impersonate.error': 'Could not load. Try again.',
    'impersonate.banner': 'Viewing as {0} (admin review) - read-only',
    'impersonate.exit': 'Exit impersonation',
    'impersonate.readonly_note':
      "Read-only: you are viewing {0}'s account, sending is disabled.",

    // === Benchmark suggestions (collaborative golden-set intake, ALL users) ===
    'sb.benchmark': 'Benchmark',
    'rail.benchmark': 'Suggest for the benchmark',
    'msg.suggest_benchmark': 'Suggest for the benchmark',
    'bench.eyebrow': 'Benchmark',
    'bench.title': 'Suggest a test question',
    'bench.desc':
      'Help us evaluate the agents: propose a question with the correct answer you know. Your suggestions feed the next benchmarks that measure how accurate the agents are.',
    // From-chat suggestion (pre-filled from an answer)
    'bench.modal.title': 'Suggest this question for the benchmark',
    'bench.modal.intro':
      "Check the question and the agent's answer, then tell us whether the answer is correct. If it is not, give the correct answer: your feedback is used to test the agent.",
    'bench.modal.question_label': 'Question asked',
    'bench.modal.answer_label': "Agent's answer",
    'bench.modal.verdict_label': "Is the agent's answer correct?",
    'bench.modal.verdict_yes': 'Yes, it is correct',
    'bench.modal.verdict_no': 'No, it is incorrect or incomplete',
    'bench.modal.reference_label': 'Expected correct answer',
    'bench.modal.reference_ph': 'Give the correct answer (figures, scope, etc.)',
    'bench.modal.missing_label': 'What is wrong or missing (optional)',
    'bench.modal.missing_ph': 'e.g. it forgot the year filter',
    'bench.modal.category_label': 'Category (optional)',
    'bench.modal.category_ph': 'e.g. revenue, tickets',
    'bench.modal.submit': 'Send suggestion',
    'bench.modal.cancel': 'Cancel',
    // Manual suggestion (from scratch)
    'bench.form.title': 'New test question',
    'bench.form.question_label': 'Question',
    'bench.form.question_ph': 'The question to ask the agent',
    'bench.form.reference_label': 'Expected correct answer',
    'bench.form.reference_ph': 'The correct answer, which you know to be exact',
    'bench.form.expected_label': 'Key value to verify (optional)',
    'bench.form.expected_ph': 'e.g. 12345, 2026-03-31',
    'bench.form.expected_type_label': 'Type',
    'bench.form.type.none': '- none -',
    'bench.form.type.numeric': 'Number',
    'bench.form.type.currency': 'Amount',
    'bench.form.type.date': 'Date',
    'bench.form.type.string': 'Text',
    'bench.form.type.list': 'List',
    'bench.form.expected_help':
      'If a single precise value answers the question (a number, an amount, a date), enter it: it becomes the automatic verification anchor.',
    'bench.form.category_label': 'Category (optional)',
    'bench.form.category_ph': 'e.g. revenue, tickets',
    'bench.form.submit': 'Send suggestion',
    'bench.form.submitting': 'Sending…',
    // My suggestions list
    'bench.mine.title': 'My suggestions',
    'bench.mine.loading': 'Loading…',
    'bench.mine.empty': 'You have not proposed a question yet.',
    'bench.mine.col_question': 'Question',
    'bench.mine.col_source': 'Source',
    'bench.mine.col_status': 'Status',
    'bench.mine.col_date': 'Date',
    'bench.status.pending': 'Pending',
    'bench.status.accepted': 'Accepted',
    'bench.status.rejected': 'Declined',
    'bench.source.chat': 'Conversation',
    'bench.source.manual': 'Manual',
    'bench.sent': 'Thank you! Your suggestion has been sent.',
    'bench.send_failed': 'Could not send the suggestion. Please try again.',

    // === Benchmark tab - broader page header ===
    'bench.page_title': 'Agent benchmark',
    'bench.page_desc':
      'Check how accurate the agents are as measured by the benchmark, then help improve it by proposing test questions.',

    // Consultation (results)
    'bench.consult.title': 'Benchmark results',
    'bench.consult.desc':
      'Pick an agent to see its latest evaluation: overall accuracy, a breakdown by mode and by topic, question by question.',
    'bench.consult.agent_label': 'Agent',
    'bench.consult.no_agents_title': 'No benchmark available',
    'bench.consult.no_agents':
      'No agent has a benchmark yet. An administrator can enable one from an agent profile.',
    'bench.consult.loading': 'Loading results…',
    'bench.consult.not_configured': 'No benchmark is configured for this agent.',
    'bench.consult.read_error':
      'Results were read in a degraded mode: some information may be missing.',
    'bench.consult.load_error': 'Could not load the benchmark results.',
    'bench.consult.no_results': 'No benchmark results for this agent yet.',
    'bench.consult.run_label': 'Run',
    'bench.consult.hero': '{0} of {1} answered correctly',

    // KPI tiles
    'bench.kpi.accuracy': 'Accuracy',
    'bench.kpi.questions': 'Questions',
    'bench.kpi.configs': 'Configurations',
    'bench.kpi.cost': 'Total cost',
    'bench.kpi.needs_review': 'Needs review',

    // Confidence band (donut)
    'bench.band.high': 'High confidence',
    'bench.band.medium': 'Medium confidence',
    'bench.band.low': 'Low confidence',
    'bench.band.unknown': 'Confidence',

    // Per agent x mode table
    'bench.cfg.title': 'Results by agent and mode',
    'bench.cfg.col_config': 'Agent / mode',
    'bench.cfg.col_questions': 'Questions',
    'bench.cfg.col_ok': 'OK',
    'bench.cfg.col_error': 'Errors',
    'bench.cfg.col_accuracy': 'Accuracy',
    'bench.cfg.col_score': 'Score',
    'bench.cfg.col_latency': 'Avg latency',
    'bench.cfg.col_cost': 'Avg cost',
    'bench.cfg.col_review': 'Needs review',

    // Per category bars
    'bench.cat.title': 'Accuracy by topic',
    'bench.cat.count': '{0} question(s)',
    'bench.cat.uncategorized': 'Uncategorized',

    // Per question table
    'bench.detail.title': 'Question by question',
    'bench.detail.col_question': 'Question',
    'bench.detail.col_category': 'Category',
    'bench.detail.col_agent': 'Agent / mode',
    'bench.detail.col_judge': 'Judge',
    'bench.detail.col_verdict': 'Verdict',
    'bench.detail.reference': 'Expected answer',
    'bench.detail.expected': 'Key value',
    'bench.detail.answer': "Agent's answer",
    'bench.detail.judge_comment': 'Judge comment',
    'bench.detail.notes': 'Notes',
    'bench.detail.objective': 'Objective anchor',
    'bench.detail.objective_yes': 'Exact match',
    'bench.detail.objective_no': 'No exact match',
    'bench.detail.reviewed': 'Reviewed by',

    // On-demand full evidence (complete answer + generated SQL + result table)
    'bench.ev.title': 'What the agent actually did',
    'bench.ev.answer': 'Full agent answer',
    'bench.ev.sql': 'SQL generated by the agent',
    'bench.ev.query': 'Query {0}',
    'bench.ev.rows': '{0} row(s)',
    'bench.ev.ok': 'success',
    'bench.ev.failed': 'failed',
    'bench.ev.data': 'Data used to answer',
    'bench.ev.no_sql': 'The agent generated no SQL for this answer.',
    'bench.ev.no_data': 'No result rows were captured for this query.',
    'bench.ev.truncated': 'Result truncated for display.',
    'bench.ev.loading': 'Loading the full detail...',
    'bench.ev.error': 'Could not load the full detail.',
    'bench.ev.empty': 'No captured detail for this attempt.',

    // Verdict badges
    'bench.verdict.correct': 'Correct',
    'bench.verdict.incorrect': 'Incorrect',
    'bench.verdict.review': 'Needs review',
    'bench.verdict.unknown': 'Undetermined',
    'bench.verdict.overridden': 'Overridden',

    // Consultation hero + reference (LAB results parity)
    'bench.consult.correct_label': 'Correct answers',
    'bench.consult.hero_note': 'How often the AI gives the right answer.',
    'bench.consult.hero_meta': '{0} reference question(s), {1} configuration(s) tested',
    'bench.cfg.questions_n': '{0} question(s)',
    'bench.detail.col_result': 'Result',
    'bench.detail.col_score': 'Score',
    'bench.detail.show': 'Show details',
    'bench.detail.hide': 'Hide details',
    'bench.ref.measure_h': 'How this is measured',
    'bench.ref.measure_p':
      'Each agent answers a list of human-validated reference questions. Accuracy is the share of correct answers.',
    'bench.ref.score_h': 'Score and verdict',
    'bench.ref.judge_t': 'AI judge',
    'bench.ref.judge_d':
      'A model scores each answer, taking the human strictness note into account.',
    'bench.ref.dc_t': 'To double-check',
    'bench.ref.dc_d': 'Answers where the automatic check and the AI judge disagreed.',
    'bench.ref.modes_h': 'Modes',
    'bench.ref.modes_p': 'An agent can run in several modes; each one is a configuration.',
    'bench.ref.modes_std': 'Standard: an agent with no mode selector.',

    // Admin review + override
    'bench.review.title': 'Admin review',
    'bench.review.mark_correct': 'Mark correct',
    'bench.review.mark_incorrect': 'Mark incorrect',
    'bench.review.clear': 'Clear override',
    'bench.review.comment_ph': 'Comment (optional)',
    'bench.review.saved': 'Verdict updated.',
    'bench.review.failed': 'Could not update the verdict.',
    'bench.review.reset_note':
      'Re-running the SAME run resets overrides; overrides on past runs are kept.',
    'bench.review.reviewed_by': '{0} on {1}',

    // Benchmark v2: selector, per-question evolution, reference vs produced
    'bench.consult.benchmark_label': 'Benchmark',
    'bench.consult.benchmark_caption': 'Benchmark: {0}',
    'bench.evo.improved': 'Improved',
    'bench.evo.regressed': 'Regressed',
    'bench.evo.same': 'Unchanged',
    'bench.evo.first': 'First attempt',
    'bench.evo.attempts_n': '{0} attempts',
    'bench.evo.attempt_n': 'Attempt {0}',
    'bench.evo.history_title': 'Attempt history',
    'bench.refprod.title': 'Reference and produced',
    'bench.refprod.reference_sql': 'Reference SQL',
    'bench.refprod.suggested_tool': 'Suggested tool',
    'bench.refprod.tools_used': 'Tools used',
    'bench.refprod.none': '- none -',

    // Suggest sub-section (accordion)
    'bench.section.suggest_title': 'Suggest a test question',
    'bench.section.suggest_desc':
      'Propose a question with the correct answer you know: it feeds the next benchmarks.',

    // Admin agent-profile benchmark section
    'bench.profile.section': 'Benchmark',
    'bench.profile.enabled': 'This agent has a benchmark',
    'bench.profile.enabled_hint':
      'When on, users can consult this agent\'s results in the Benchmark tab.',
    'bench.profile.connection': 'SQL connection',
    'bench.profile.table': 'Results table',
    'bench.profile.table_ph': 'Pick or type a table',
    'bench.profile.tables_loading': 'Loading tables…',
    'bench.profile.tables_error': 'Could not list the tables of this connection.',
    'bench.profile.refresh_tables': 'Refresh tables',
    'bench.profile.agent_key': 'Agent key (filter, optional)',
    'bench.profile.agent_key_ph': 'e.g. agent:038G7mlF',
    'bench.profile.agent_key_hint':
      'If the table holds several agents, give the agent key to filter on.',
    'bench.profile.validate': 'Validate schema',
    'bench.profile.validating': 'Validating…',
    'bench.profile.ok': 'Schema compatible.',
    'bench.profile.missing': 'Schema incompatible: missing columns: {0}',
    'bench.profile.error': 'Could not validate the schema.',

    // === Source Data Explorer (browse an agent's configured datasets) ===
    'ev.tab.sources': 'Source data',
    'src.cta.title': 'Explore the source data',
    'src.cta.hint': "Browse the agent's datasets: search, filter and sort without writing a query.",
    'src.panel.title': 'Source data',
    'src.dataset_label': 'Dataset',
    'src.search.placeholder': 'Search this dataset…',
    'src.search.min': 'Type at least 2 characters to search.',
    'src.filters.title': 'Filters',
    'src.filters.add': 'Add a filter',
    'src.filters.clear': 'Clear all',
    'src.filters.remove': 'Remove this filter',
    'src.column': 'Column…',
    'src.picker.empty': 'No value available.',
    'src.picker.truncated': 'First {0} distinct values',
    'src.picker.max': 'At most {0} values per filter',
    'src.picker.apply': 'Apply',
    'src.loading': 'Loading…',
    'src.error': 'Could not load the data.',
    'src.retry': 'Retry',
    'src.empty': 'No row matches.',
    'src.loaded': '{0} row(s) loaded',
    'src.more': 'Scroll to load more',
    'src.loadingMore': 'Loading…',
    // Admin: attach source datasets to an agent's profile (agent-profile modal).
    'src.admin.section': 'Source datasets',
    'src.admin.hint': "Raw datasets this agent exposes: users can browse them (search, filter, sort) without writing a query. Up to 8.",
    'src.admin.dataset_ph': 'Dataset name',
    'src.admin.label_ph': 'Display name (optional)',
    'src.admin.add': 'Add dataset',
    'src.admin.remove': 'Remove',
    'src.admin.load_error': 'Could not load the dataset list.',
    'src.admin.refresh': 'Refresh list',
  },
}
