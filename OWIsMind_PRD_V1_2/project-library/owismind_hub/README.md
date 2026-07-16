# owismind_hub/ - graines du Config & Prompt Hub

Le hub est le panneau de reglages des agents : un dossier `/owismind_hub/` dans la
project library DSS, que chaque agent lit a son demarrage. Il permet de changer les
prompts et de declarer des agents SANS recoller le code des agents. Si un fichier du
hub est absent ou invalide, l'agent retombe sur ses defauts embarques : le hub ne
peut pas casser la prod.

## Dans Dataiku

Le hub vit a la racine de la project library du projet DSS, sous `/owismind_hub/`.
Il est pousse par le notebook [`../../notebooks/01_push_config_hub.py`](../../notebooks/01_push_config_hub.py),
qui embarque le contenu de ce dossier. Ce dossier repo est le miroir lisible des graines (seeds).

## Dans ce dossier

| Fichier | Pousse vers | Lu par |
|---|---|---|
| `capabilities.json` | `/owismind_hub/capabilities.json` | orchestrator (section 7b loader) |
| `prompts/orchestrator_persona.md` | `/owismind_hub/prompts/orchestrator_persona.md` | orchestrator (PERSONA override) |
| `factory_settings.json` | `/owismind_hub/factory_settings.json` | owismind_factory (reglages d'instance) |
| (cree en DSS) | `/owismind_hub/prompts/<domain>/understand_extra.md` | le specialiste du domaine (regles UNDERSTAND additives) |
| (cree en DSS) | `/owismind_hub/templates/dataset_expert.py` | agent_builder (template moteur) |
| (cree en DSS) | `/owismind_hub/generated/`, `/wizard/`, `/doctor/`, `/backups/` | sorties de la factory |

S'y ajoute [`regenerate_seeds.py`](regenerate_seeds.py), un script repo-only (jamais pousse en DSS).

## Garantie d'equivalence (ne pas casser)

Les graines sont GENEREES depuis le code : `capabilities.json` et
`orchestrator_persona.md` depuis les defauts embarques de
[`../../genai/agents/OWIsMind_orchestrator.py`](../../genai/agents/OWIsMind_orchestrator.py)
(CAPABILITIES_DEFAULT / PERSONA_DEFAULT), `factory_settings.json` depuis
DEFAULT_SETTINGS de [`../python/owismind_factory/hub.py`](../python/owismind_factory/hub.py).
Pousser le hub ne change donc RIEN au comportement, tant qu'un humain n'edite pas un fichier.

- Regenerer apres une edition des defauts embarques : `python3 regenerate_seeds.py` (et inversement : si on edite une graine geree, aligner le code).
- Detecter la derive sans rien ecrire : `python3 regenerate_seeds.py --check` (exit 1 + liste des fichiers en ecart).
- Le test [`../../tests/test_factory_registry.py`](../../tests/test_factory_registry.py) impose l'equivalence : le relancer apres toute edition.

## Regles d'edition

- `capabilities.json` est valide au chargement : ids `agent:` avec un suffixe
  alphanumerique (un placeholder comme `agent:FILL_ME` ou un id vide est rejete),
  UNE seule capability `enabled` par domaine, cles de labels (blocks / tools) gelees.
  Le meme validateur tourne cote factory (`hub.validate_capabilities`) et cote
  orchestrateur (section 7b loader).
- Un fichier invalide est IGNORE par l'orchestrateur (retour aux defauts embarques,
  warning dans le log de l'agent) : verifier le log apres chaque edition.
- Les ecritures de capabilities sont serialisees en process (verrou partage par
  `write_capabilities` / `append_capability`) et un backup automatique est pose sous
  `/owismind_hub/backups/` (chemin de recuperation).
- Prompts : markdown / texte brut. Le persona doit rester entre 500 et 20000
  caracteres ; les fichiers `understand_extra` sont ADDITIFS et limites a 4000 caracteres.
- Toute edition prend effet au prochain demarrage du process de l'agent
  (re-sauver l'agent ou shutdown / wake en DSS).
- JAMAIS de secrets ici : la library est lisible par tous les lecteurs du projet.
- Zero tiret cadratin / demi-cadratin (regle projet #9).

## Deploiement

1. Editer ici (ou regenerer via `regenerate_seeds.py`), puis relancer la suite de tests.
2. Pousser en DSS en executant le notebook [`../../notebooks/01_push_config_hub.py`](../../notebooks/01_push_config_hub.py).
3. Guide complet (phases, gates) : [`../../docs/DEPLOY_V1_3_DEV.md`](../../docs/DEPLOY_V1_3_DEV.md).
