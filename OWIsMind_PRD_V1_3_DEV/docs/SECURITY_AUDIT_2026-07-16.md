# Audit de securite Agent Factory v1.3 - synthese (2026-07-16)

Deux audits independants en lecture seule, AVANT tout premier deploiement DSS :

- **Audit interne** (Claude, grille Dataiku) : verdict "deployable sous conditions",
  3 gates + 4 P2 + 7 P3.
- **Audit GPT-5.6 Sol** (Codex, meme perimetre, 4 recherches developer.dataiku.com) :
  verdict "not safe to deploy as-is", 6 P1.

Perimetre : `project-library/python/owismind_factory/` (moteur), notebooks 00-06,
console `Standard-webapps/agent-factory-console/`, seeds du hub, section hub de
l'orchestrateur. Rapports complets archives hors repo (scratchpad de session) ;
l'essentiel est ici.

## Ce que les deux audits ont valide (sain)

- **Zero delete** : la seule suppression de toute la factory est celle des deux
  objets jetables de la sonde 00 (`zz_factory_probe*`), gardee par nom, jamais
  accessible depuis la console.
- **Dry-run reel** : `FactoryContext.act()` n'execute rien en dry-run ; la console
  exige `confirm: true` sur toute route mutante.
- **Zero secret en dur**, zero SQL execute par le moteur, zero `eval`/`exec`/
  reseau externe, zero ligne brute de dataset envoyee a un LLM.
- Scenario de refresh force inactif, premier build manuel, existence checks
  fail-closed (`ExistenceCheckError`).

## Corrige en code (commits du 2026-07-16, suite de tests 516 verts)

| Constat (interne / Sol) | Fix |
|---|---|
| Scenario refresh : `active` reposait sur un defaut API non documente (G2) | `settings.active = False` force dans le meme save que le trigger + test |
| Denylist read-only incomplete (P2-B / P1-5) | + `INTO, MERGE, COPY, CALL, DO, LOCK, SET, VACUUM` + tests |
| Persona ecrasable sans backup (P3-1) | `hub.write_prompt` = backup sous `/python/owismind_hub/backups/` avant ecriture |
| `apply_config` ecrasait un modele preexistant, y compris cure ou etranger (P2-A / P1-1) | Marqueur `owismindFactory` pose au seed ; sans marqueur = refus (MANUAL) ; avec marqueur = backup de version `pre-apply-backup-<n>` + re-pin de la version active AVANT toute mutation ; echec du backup = refus |
| Aligneur remappait TOUTE cle etrangere (P1-2) | `expected_source_keys` : liste vide = decouverte (zero remap), sinon seules les cles listees sont remappees |
| Console : jobs illimites, ids previsibles, tailles non bornees (P1-3 / P2) | Max 4 jobs actifs, 1 seul `execute` a la fois, 429 au-dela, slot libere en finally ; ids `uuid4` ; persona max 20000 chars, capabilities max 50 entrees / 200 KB |
| Suppression de sonde fail-open (P3-6 / P2) | Fail-closed : nom illisible = refus de supprimer (nettoyage manuel des `zz_*`) |
| Params bruts de tools/agents persistes par la sonde (secrets potentiels) | `_redact_sensitive` : toute cle token/password/secret/credential/apikey/private_key/authorization est `[REDACTED]` avant persistance/impression |
| Doctor : extraits verbatim de conversations dans la library (P2-D / P1-4) | Evidence RETENUE dans le fichier persiste (`[evidence withheld...]`) ; verbatim uniquement dans la sortie ephemere du notebook |
| Settings du hub : cles arbitraires republiees par `/api/state` (P3) | `get_settings` : overlay STRICT limite aux cles de `DEFAULT_SETTINGS` |
| Rapport de sonde ecrase silencieusement (P2 Sol) | Ecriture avec backup (`write_prompt`) + en-tete honnete du notebook 00 |

## Gates de deploiement (a regler COTE DSS, voir DEPLOY_V1_3_DEV.md phase 0)

1. **G1 - console** : exposition restreinte aux admins + run-as dedie au projet.
   La console n'a pas d'autorisation applicative par viewer (limites DSS webapp
   Standard) ; le durcissement code (bornes, tailles, ids) reduit la surface
   mais ne remplace pas la restriction d'acces.
2. **G3 - SQL read-only** : role base SELECT-only + statement timeout sur
   `SQL_owi`. C'est LA frontiere read-only ; le validateur offline n'est qu'une
   defense en profondeur.
3. **Logging (phase G)** : le dataset de logs contient des conversations reelles ;
   decider acces + retention avant activation.

## Assume par conception (documente, pas un bug)

- **Le wizard envoie des valeurs du profil au LLM** (noms de comptes, valeurs
  enumerees) : c'est le fonctionnement du systeme en production (le grounding
  exige ces valeurs ; memes connexions LLM Mesh que les agents live, meme
  frontiere de confiance). Sol le classait P1 ; decision : assume, borne
  (400 cles / 12000 chars), a re-evaluer si la politique data change.

## Backlog durcissement (non bloquant, a prioriser plus tard)

- Autorisation applicative par viewer dans la console (WebappImpersonationContext,
  a tester sur l'instance) - complement de G1.
- Manifeste de reprise par domaine (ids DSS attendus + empreintes) pour les
  collisions de noms datasets/recipes et les creations non atomiques (Sol P1-1
  au-dela du modele semantique, P2) ; rejoint le backlog v1.3 existant
  ("manifeste canonique versionne").
- Parser AST des golden queries + allowlist de fonctions SQL (Sol) ; timeout
  reel du fan-out parallele de l'orchestrateur (Sol P2) ; suffixe aleatoire des
  objets sonde + journal de nettoyage (Sol P2) ; verif CSRF du proxy DSS sur la
  version cible (Sol P3) ; coherence connexion source vs datasets derives
  (Sol P2) ; partitionnement/retention du dataset de logs (Sol P2).
