# OWIsMind Webapp v3 - Cahier des charges fonctionnel

> **Type :** cahier des charges fonctionnel (produit, pas du how-to technique).
> **Statut :** cadrage. **Beaucoup de ce document est désormais LIVRÉ et VALIDÉ EN DSS** - l'état réel
> et les décisions actées vivent dans `memory/PROJECT_STATE.md` (§9-13) + `memory/CONTEXT.md`, qui **priment**.
> Ce document garde surtout l'**intention produit utile pour les fonctions à venir** (au premier chef
> **Evidence Studio**, différé par décision user).

---

## 1. Vision produit

Portail **agentique métier** pour les utilisateurs OWI : dialoguer en langage naturel avec des agents IA
Dataiku DSS, mais pas un simple chatbot - une interface de **confiance** qui expose les preuves d'une réponse.

Trois objectifs : **Productivité** (analyses métier rapides) · **Confiance** (données, étapes, SQL, traces,
coûts visibles) · **Extensibilité** (ajouter agents / artefacts / graphiques sans refonte).

Le trio différenciant : **Conversation + Live Execution Timeline + Evidence Studio**.

Positionnement : portail pro de confiance, orienté données/preuves/traçabilité - pas une démo IA, pas un
chatbot grand public, pas un outil opaque.

---

## 2. Principes structurants

- **Transparence par défaut** : l'utilisateur peut toujours savoir quel agent agit, quelle étape/outil est en
  cours, quelle donnée et quel SQL ont servi, et le coût. Les détails techniques vivent dans des **panneaux
  dédiés**, jamais dans la réponse principale.
- **Confiance par les preuves** : distinguer **Evidence** (ce qui a réellement produit la réponse : résultat
  exact, SQL, row count, filtres, scope, source) de **Dataset Explorer** (exploration, possiblement sur sample).
- **Agent-agnostic** : la webapp ne contient pas la logique métier des agents. Ajouter un agent = acte de
  **configuration**, pas de refonte. Agents prévus : Orchestrateur OWIsMind (défaut), Revenues, Tickets, CX,
  Opportunities, Product/Customer Base, Delivery.
- **Modularité** : conversation, streaming, timeline, Evidence Studio, dataset explorer, charts, SQL/trace/cost
  viewers, feedback, FAQ, settings, i18n, exports - chaque brique évolue indépendamment.
- **Desktop-first responsive** (12" → ultra-wide) ; **mobile hors priorité V1**.
- **Multilingue extensible** : FR + EN en V1, tout label UI traduisible.

---

## 3. Pages & navigation

Entrée directe sur **Chat** (pas de Home). Pages : **Chat** · **Feedback** · **FAQ** · **Settings / My Account**.

### Chat (écran principal)
Trois espaces : **Sidebar conversations** | **Conversation + prompt + timeline** | **Evidence Studio** (masquable).

- **Sidebar** : logo, New Chat, liste + recherche de conversations, conversation active mise en avant,
  accès Feedback/FAQ/Settings, menu utilisateur ; réductible.
- **Conversation** : messages user/assistant, réponse en cours, timeline live, actions sur message. Réponses
  claires, structurées, business-friendly, dans la langue de l'utilisateur si possible.
- **Prompt bar** : textarea, envoyer (désactivé si vide), micro, sélecteur d'agent discret, indicateur budget/état.
  `Enter` envoie, `Shift+Enter` saute une ligne ; envoi bloqué si budget atteint ou agent indisponible.
- **Sélecteur d'agent** : défaut = Orchestrateur ; un autre agent si l'utilisateur y a accès ; liste extensible ;
  par agent : nom, courte description, domaine, statut, badge (default/beta/restricted/offline).
- **Voice input** : transcription insérée dans la prompt bar pour édition - **n'envoie pas automatiquement**.

### Settings / My Account
Profil (nom, identifiant, agents autorisés, rôle/groupe) · Langue (FR/EN) · Préférences · **Budget dashboard** ·
Usage history · liens utiles.

### Feedback
Signaler bug / mauvaise réponse / demande de feature / suggestion, et suivre ses demandes.
Champs : nom prérempli, catégorie, message, priorité optionnelle, conversation liée optionnelle.
Catégories : General · Bug · Wrong answer · Feature request · UI/UX · Performance · Data · Agent routing.
Statuts : pending · reviewed · in progress · resolved · rejected · need more info.

### FAQ
Recherche + catégories + accordéons + CTA vers Feedback. Catégories : General · Agents · Data & Evidence ·
Charts · SQL & Trace · Budget · Privacy & Usage · Troubleshooting.

---

## 4. Live Execution Timeline

Montrer que l'agent travaille (réduit l'attente silencieuse / le doute ; augmente la confiance et le diagnostic).
Événements : démarrage agent, thinking, bloc démarré/terminé, outil démarré, sous-agent appelé, formatage,
trace reçue, terminé, erreur. États : pending / running / done / warning / failed / skipped.

**Labels humains** par défaut (mode debug = noms techniques). Exemples de mapping :
```
AGENT_THINKING                         → L'agent analyse la demande
AGENT_TOOL_START + revenue_semantic    → Interrogation du modèle de revenus
AGENT_BLOCK_DONE + resolve             → Résolution des filtres terminée
SUB_AGENT_FOOTER                       → Résultats et trace reçus
```

---

## 5. Evidence Studio (DIFFÉRÉ - intention à conserver)

> ⏸️ **Non livré en V1, différé par décision user.** C'est la principale fonction future à laquelle ce cahier
> sert encore de cadrage. Points d'extension déjà réservés côté front (aside `AppLayout`, registres) →
> `PROJECT_STATE.md §12-13`. ⚠️ **Blocage connu** : `generated_sql` stocké = SQL + row_count (**pas les lignes**)
> et la trace = dataset Flow **write-only** (plus lisible en ligne) → onglets Dataset/Trace à repenser sans source.

Panneau de confiance répondant à « pourquoi faire confiance à cette réponse ? ». Ouverture auto (dataset/SQL/chart
détecté), manuelle (« Open evidence ») ou depuis une étape de timeline. **6 onglets :**

1. **Evidence** (prioritaire) : ce qui a réellement servi - résultat exact, agrégation, row count, scope,
   filtres, période, agent/dataset source, statut.
2. **Dataset** : explorer les données de l'agent actif - aperçu, recherche, tri, filtres colonnes, pagination,
   **lazy loading strict** (charger à l'ouverture de l'onglet, seulement l'agent actif). Si sample, warning :
   « Cette vue affiche un échantillon ; le calcul de l'agent peut porter sur le dataset complet. »
3. **Chart** : visualisations depuis les résultats (auto si série temporelle / group by détectable, sinon bouton
   « Generate chart »). Types initiaux : line, bar, grouped/stacked bar, KPI card, table+chart, donut/pie ;
   waterfall plus tard. Moteur extensible.
4. **SQL** : SQL généré quand il existe + statut/row count/source + copy/show-hide. Ne pollue pas la réponse.
   Absence de SQL = message neutre (normal pour agents RAG/non-SQL).
5. **Trace** : déroulé agentique - vue utilisateur (étapes lisibles, agent/outil, durée, statut, erreurs) +
   vue debug (eventKind/blockId/nextBlockId/toolName/raw).
6. **Cost** : tokens (prompt/completion/total), coût estimé, nb d'appels LLM, coût par agent/sous-agent, durée.
   Ton pédagogique, pas anxiogène.

### Multi-agent
Une question peut mobiliser plusieurs agents (« analyse 360 sur X »). Garder une conversation unique + timeline
globale, montrer les agents appelés, un espace Evidence par agent, **lazy-loader seulement l'agent actif**.
États par agent : not started / running / completed / loaded / not loaded / failed / no evidence / restricted.

---

## 6. Règles métier & contraintes

- **Budget** (configurable, ex. 50 €/user/mois) : seuils **50 %** info · **80 %** warning · **100 %** blocage
  d'envoi (ou demande d'extension). Dashboard : mensuel, utilisé/restant/%, nb requêtes, coût moyen, coût par
  agent, tendance, alertes. Usage history : par jour/conversation/agent (tokens, coût, appels, date).
- **Confidentialité** : l'utilisateur ne voit que **ses** conversations + les **agents autorisés** ; données
  sensibles non affichées inutilement ; coûts limités à l'utilisateur / admins ; actions externes (email) contrôlées.
- **Gestion d'erreurs** : message clair + détail technique masqué par défaut + action possible (retry / copy
  technical details / lien feedback). États clés à designer : Agent error · No evidence available · No data found ·
  Budget limit reached. Cas à couvrir : agent indisponible, timeout, budget dépassé, erreur outil/sous-agent/
  streaming, SQL absent/échoué, aucune donnée, accès interdit, réponse/evidence partielle.
- **Design** : dark, professionnel, sobre, premium, univers Orange ; dense mais lisible ; desktop multi-tailles
  (sidebar compressible, Evidence réductible, tableaux scrollables, prompt bar toujours accessible).
  Le design system réel (tokens, thème light/dark, branding Orange `#ff7900`) est décrit dans `PROJECT_STATE.md §9/§13`.

---

## 7. Fonctionnalités futures à anticiper

- **Export / report** : Markdown, PDF, PowerPoint, fiche client 360, executive summary, envoi email.
- **Nouveaux artefacts** : image, carte, document, rapport, slide, contrat, Excel, dashboard externe.
- **Admin registry** (page future) : agents, descriptions, domaines, datasets associés, icônes, permissions,
  labels d'étapes, ordre d'affichage. _(Un espace admin de base - users, agents whitelist, storage - est déjà livré ;
  cf. `PROJECT_STATE.md`.)_
- **Évaluation agent** : note de qualité, benchmark, golden questions, comparaison de versions, taux de réussite.

---

## 8. Décisions fonctionnelles actées

| Sujet | Décision |
|---|---|
| Type de produit | Portail agentique OWI professionnel |
| Page d'entrée | Chat directement (Home supprimée) |
| Feedback / FAQ / Settings | Conservés / renforcés |
| Budget | Fonctionnalité importante (seuils 50/80/100 %) |
| Agent par défaut | Orchestrateur OWIsMind ; sélecteur dans la prompt bar |
| Voice input | Conservé, n'envoie pas automatiquement |
| Bloc preuves | Evidence Studio (différé) |
| SQL | Onglet dédié discret, jamais dans la réponse |
| Graphiques | Auto si détectable + bouton manuel |
| Multi-agent | Onglets par agent + lazy loading |
| Langues V1 | FR + EN ; mobile non prioritaire ; responsive desktop obligatoire |
| Architecture produit | Modulaire et extensible |

---

## 9. Critères d'acceptation (résumé)

- **Conversation** : créer une conversation, choisir un agent, poser une question, voir la réponse, reprendre une
  conversation passée.
- **Streaming** : progression visible, étapes principales + outil courant si dispo, erreurs visibles, réponse
  finale correcte.
- **Evidence Studio** : panneau ouvrable, onglets principaux présents, SQL/trace/coût visibles si dispo,
  evidence ou dataset affiché selon disponibilité.
- **Graphiques** : proposition auto pour une série temporelle simple + bouton manuel + table associée accessible.
- **Budget** : budget mensuel, utilisé/restant, usage par agent/conversation, warning près de la limite, blocage/
  alerte à 100 %.
- **Feedback / FAQ** : envoyer un feedback + suivre ses demandes ; chercher et ouvrir une question FAQ.
