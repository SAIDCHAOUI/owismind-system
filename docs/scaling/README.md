# OWIsMind - Plans de scaling (session 2026-06-19, nuit)

Deux plans d'amelioration step-by-step / feature-by-feature, produits en session multi-agents a ta demande. **Aucun code touche, aucun commit, aucun push.** Juste de la reflexion, du debat entre agents, et la synthese.

## Les deux livrables

- **[`PLAN_WEBAPP.md`](PLAN_WEBAPP.md)** - Mission 1 : la webapp et ses capacites (nouveaux types de sortie, livrables PDF/PNG/CSV/XLSX/email, relances, explain-this-number, comparaison, onglets Evidence, reconciliation/confiance, soft-quota, **et la reponse a "exposer les tools de la webapp aux agents, meme visuels"**).
- **[`PLAN_AGENTS.md`](PLAN_AGENTS.md)** - Mission 2 : transformer l'orchestrateur + l'agent revenus en **factory** de sous-agents (spec declaratif, template par codegen, harnais de calibration, playbook "ajouter un agent"), l'ordre des nouveaux domaines (tickets d'abord), la **fiche client 360**, et le socle de gouvernance/eval/cout.

## Comment ils ont ete produits

1. **Comprehension** : 6 agents ont lu le code reel (frontend, backend, agents, mecanisme d'exposition des tools, data/semantic, capacites plugin DSS).
2. **Recherche etat de l'art** : 5 agents (BI agentique par persona, factory multi-agents, tools DSS pour agents visuels, livrables PDF/PNG/email, gouvernance/eval/cout).
3. **Idéation** : 4 personas (AM, PO, directeur marketing, dirigeant) + 5 architectes seniors.
4. **Critique adversariale** : 5 critiques (fidelite Dataiku/faisabilite, surete instance, securite/gouvernance, charte/UX, cout/sequencement/YAGNI) ont stress-teste chaque proposition. **Leurs corrections sont gravees dans les plans.**

Provenance brute : `docs/scaling/.workdir/` (scratch, supprimable). ~1,9M tokens d'analyse au total.

## La vue transverse en 6 points

1. **Le MVP gratuit, cette semaine** : telechargement PNG (client, `toBase64Image()`) + CSV (stdlib), zero install, ~80% de la valeur "sortir ca de l'app". Ne jamais laisser le PDF retarder ces deux gains.
2. **Le socle de gouvernance d'abord** : journal d'audit + reconciliation (en mode shadow) + semaphore de concurrence AVANT le 2e agent ; quota soft + semaphore AVANT le 360. La ligne rouge ("un faux chiffre = desengagement") se multiplie par domaine.
3. **La factory est a 90% deja la** : l'orchestrateur est data-driven, le sous-agent est pilote par le Profile. Le travail = consolider ~7 constantes (codegen Path B) + un harnais de golden queries. **Mais** : la calibration semantique reste chere et irreductible (~2-3 sessions/domaine simple), ne jamais promettre "un agent en jours".
4. **Exposer les tools aux agents** : oui via les **plugin agent tools** (`python-agent-tools/`, selectionnables par agents visuels ET code) - mais le panneau Evidence est une propriete de NOTRE session, pas du tool. PDF/email/CSV s'externalisent proprement ; chart-dans-le-panneau pour un agent etranger est conditionne a un spike `exchange_id`.
5. **Honnetete VERIFIED vs NEEDS-DSS-VALIDATION** : chaque affirmation technique est etiquetee. On ne parie pas une archi sur du non-prouve.
6. **Charte + securite sur chaque nouvelle surface** : confiance = plein/pointille/gris (jamais feu tricolore), exports = extrait plafonne audite, email = brouillon HITL sans envoi serveur v1, PDF = vraie image logo + suppression des tirets longs.

## A faire en PREMIER : les spikes sur l'instance (un apres-midi)

Avant de parier l'architecture (detail dans `PLAN_WEBAPP.md` section 2) :
- **S1** : un agent VISUEL peut-il selectionner un plugin tool ? (valide tout le Track A)
- **S2** : version Python de l'env d'un plugin tool ? (conditionne reportlab/openpyxl/matplotlib)
- **S3** : handoff `exchange_id` + binding proprietaire serveur ? (conditionne `render_chart` pour agents etrangers ; **et c'est aussi une correction securite** : l'ecriture d'artefact actuelle est exploitable cross-tenant)
- **S4** : `get_agent_tool().run()` depuis Flask tourne sous quelle identite ? (gouvernance d'acces)
- **S5** : `openpyxl`/`matplotlib`/`reportlab` presents dans l'env backend 3.9 ?

## Note

Les plans respectent tous les non-negociables (NO INSTALL par l'agent, surete instance, SQL direct, whitelist, Python 3.9, aucun tiret long, charte Orange). Rien n'est implemente : ce sont des feuilles de route a valider et a sequencer avec toi.
