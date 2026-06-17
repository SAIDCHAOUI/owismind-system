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

    // Settings - honest empty states (no mock budget/usage figures)
    'set.profile.groups': 'Groupes',
    'set.budget.empty': 'Le suivi du budget mensuel sera bientôt disponible.',
    'set.usage.empty': "L'historique d'usage sera bientôt disponible.",

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
    'admin.quotas.empty': 'La gestion des quotas et budgets sera bientôt disponible.',
    'admin.activity.empty': "Le journal d'activité sera bientôt disponible.",

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
    'mode.label': 'Mode du modèle',
    'mode.eco': 'Éco',
    'mode.medium': 'Medium',
    'mode.high': 'High',
    'mode.eco_hint': 'Éco : rapide, économique et recommandé par défaut. Cliquez pour changer de mode.',
    'mode.medium_hint': 'Medium : équilibré, qualité supérieure. Cliquez pour changer de mode.',
    'mode.high_hint': 'High : qualité maximale, plus coûteux. Cliquez pour changer de mode.',
    // Mode-explanation popup
    'mode.modal_title': 'Mode de réponse',
    'mode.modal_intro':
      'Choisissez la puissance du modèle selon votre question. Plus de puissance affine l\'analyse, pour un coût plus élevé.',
    'mode.recommended': 'Recommandé',
    'mode.cancel': 'Annuler',
    'mode.validate': 'Valider',
    'mode.reco_line': 'Notre recommandation : rapide, économique et de très bonne qualité pour la grande majorité des questions.',
    'mode.cost_label': 'Coût',
    'mode.speed_label': 'Vitesse',
    'mode.eco_desc':
      'Le meilleur équilibre performances / qualité, et le plus économique. Idéal pour les recherches et les questions du quotidien.',
    'mode.medium_desc':
      'Un cran au-dessus pour les analyses qui demandent un peu plus de finesse.',
    'mode.high_desc':
      'Raisonnement et analyse approfondis, pour les questions complexes.',
    'mode.eco_cost': 'Faible',
    'mode.medium_cost': 'Modéré',
    'mode.high_cost': 'Élevé',
    'mode.eco_speed': 'Très rapide',
    'mode.medium_speed': 'Rapide',
    'mode.high_speed': 'Plus posé',
    'mode.envelope_note':
      'Les modes plus puissants consomment plus vite votre enveloppe de 50 €/mois. Réservez High aux questions qui le justifient vraiment.',

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

    // Settings - honest empty states (no mock budget/usage figures)
    'set.profile.groups': 'Groups',
    'set.budget.empty': 'Monthly budget tracking will be available soon.',
    'set.usage.empty': 'Usage history will be available soon.',

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
    'admin.quotas.empty': 'Quotas and budget management will be available soon.',
    'admin.activity.empty': 'The activity log will be available soon.',

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
    'mode.label': 'Model mode',
    'mode.eco': 'Eco',
    'mode.medium': 'Medium',
    'mode.high': 'High',
    'mode.eco_hint': 'Eco: fast, economical and recommended by default. Click to change mode.',
    'mode.medium_hint': 'Medium: balanced, higher quality. Click to change mode.',
    'mode.high_hint': 'High: maximum quality, more expensive. Click to change mode.',
    // Mode-explanation popup
    'mode.modal_title': 'Response mode',
    'mode.modal_intro':
      'Choose the model power to match your question. More power sharpens the analysis, for a higher cost.',
    'mode.recommended': 'Recommended',
    'mode.cancel': 'Cancel',
    'mode.validate': 'Apply',
    'mode.reco_line': 'Our recommendation: fast, economical and very good quality for the vast majority of questions.',
    'mode.cost_label': 'Cost',
    'mode.speed_label': 'Speed',
    'mode.eco_desc':
      'The best performance / quality balance, and the most economical. Ideal for lookups and everyday questions.',
    'mode.medium_desc':
      'A step up for analyses that need a bit more finesse.',
    'mode.high_desc':
      'Deeper reasoning and analysis, for complex questions.',
    'mode.eco_cost': 'Low',
    'mode.medium_cost': 'Moderate',
    'mode.high_cost': 'High',
    'mode.eco_speed': 'Very fast',
    'mode.medium_speed': 'Fast',
    'mode.high_speed': 'More deliberate',
    'mode.envelope_note':
      'More powerful modes use up your €50/month envelope faster. Reserve High for questions that genuinely warrant it.',

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
  },
}
