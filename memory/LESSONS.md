# LESSONS - OWIsMind (ce qui a echoue puis marche)

> Condense le 2026-10-16 : une ligne par lecon ENCORE VALABLE pour la V2, numeros d'origine conserves
> (les `.claude/rules/*.md` les citent). Lecons obsoletes retirees (v1.x, LAB, graphify, durable,
> promotion prod) ; texte integral dans git (`git show e28f752:memory/LESSONS.md`).
> Nouvelle lecon = append en bas, prochain numero (L197+) : Contexte / Echec / Solution / Preuve / Date.

## DSS, plugin, build
- L001 Les noms des guides `docs/cadrage/` sont des EXEMPLES : utiliser les identifiants de `PROJECT_STATE.md`.
- L006/L054 Deux code envs : backend webapp = Python 3.9.23 (pas de langchain), Code Agents = 3.11.
- L007 `dataiku.default_project_key()` marche depuis le backend webapp : la project key se resout au runtime.
- L010 Zip runtime propre : `plugin.json` + `python-lib` + `resource` + `webapps`, jamais `frontend/` ni `node_modules/`.
- L011 `get_auth_info_from_browser_headers` : forme reelle validee, identite = `authIdentifier`.
- L012/L014 Webapp STANDARD : pas de dropdown via `getChoicesFromPython` ; config par params + `hideWebAppConfig=false`.
- L019 SSE bufferise par DSS : streaming = POLLING via thread worker (500 ms).
- L094 Plugin coexistant : UNE source + cible de build (id, base Vite, package renommes), renommer aussi le label webapp.
- L169 Project library : recoller TOUS les fichiers modifies ENSEMBLE puis restart backend.

## SQL direct
- L008 Tables `{PROJECT_KEY}_owismind_{logical}` (non negociable), creees si absentes, zero ALTER.
- L009 INSERT + relecture en UN aller-retour `SQLExecutor2`.
- L013/L102 NaN -> None : passer par `astype(object)` ; `df.where(notnull)` ne suffit pas sur colonne numerique.
- L036 Endpoint qui rejoue du SQL : le vrai risque est DoS/perf (timeout, LIMIT, throttle), pas l'injection.
- L037 Datasets Evidence = decouverte auto des datasets SQL du projet, pas de whitelist admin.
- L049 `chat_vN` = source de verite par echange ; agregats denormalises reconstructibles.
- L103/L110 NAMEDATALEN 63 octets : noms d'index ET de table doivent etre length-safe.
- L104 Une lecture qui avale ses erreurs ne doit jamais alimenter une reecriture de dataset.
- L125 Analytics : jamais de query string ni de texte user brut dans les events.
- L126 Colonne additive sur `_vN` : `ADD COLUMN IF NOT EXISTS` plutot qu'un bump qui casse la continuite.
- L158 Fuzzer une garde SQL avec des variantes equivalentes (commentaires, FROM/JOIN).
- L165 Lire un dataset DSS : `iter_tuples` + schema, jamais `iter_rows` devine.
- L170 `get_physical_table` renvoie un litteral DEJA quote ; les mocks doivent reproduire le contrat reel.
- L190 Un extrait capture n'est pas un total : compter avant la coupe.
- L191 Un module "OFF par flag" peut parler a la base : verifier ce qui demarre.

## Agents (LangGraph, LLM Mesh)
- L047 Appeler les tools manages DIRECTEMENT rend la capture Evidence deterministe.
- L048 Boucles de clarification = probleme de memoire conversationnelle, jamais de regle par valeur.
- L050 L'orchestrateur n'affirme jamais un fait metier : il route, il ne nie pas.
- L051/L052 Expertise = artefacts du Flow (profil, value index) ; le SQL appartient au modele semantique.
- L055 LangGraph sur Code Agent DSS 14 : `get_stream_writer` en noeud SYNC + appels Mesh NATIFS.
- L056 `with_json_output` force sur les extractions ; le reasoning reserve au routing et a la prose.
- L057 Artefacts : tool show_* -> event ARTIFACT -> payload Chart.js construit en Python.
- L058/L081 Le sous-agent ASSISTE, ne DICTE pas : terme d'offre ambigu = laisser trancher le modele semantique.
- L060/L063/L120 Petits modeles : ne pas leur tendre une table prete ; narration fiable via un TOOL, jamais "narrate first".
- L061 `strict:True` sur les tool specs exige toutes les proprietes en `required` (OpenAI) : ne pas l'utiliser.
- L064 Multi-SQL : Evidence lie chaque resultat a SON span (`sql_id`), jamais au premier ou au dernier.
- L066 Langue de reponse : bloc contexte en FIN de message + detection deterministe.
- L068 Rejeu de transcript : appariement tool_call <-> output + roles alternes, sinon 400.
- L086/L087 `attribute_lookup` = built-in orchestrateur, un ILIKE read-only, fallback Value_Catalog.
- L097 `get_dataframe(infer_with_pandas=False)` leve sur une colonne entiere nullable.
- L100 Sans colonne `indexed` dans le profil, l'agent invente : parite profileur <-> value_index.
- L118 Une capacite agent ne vaut que si le consommateur final (webapp) la rend : verifier de bout en bout.
- L119 Un jeton de controle `owi:*` doit respecter les 3 proprietes du protocole, teste dans la vraie sequence.
- L146/L162 Dupliquer un projet DSS ne repointe NI les modeles semantiques NI les tools Semantic Model Query.
- L150 Loader de config module-level : incassable (mais aucun repli de modele, voir L195).
- L166 Jamais de knob de sampling force sur une completion Mesh (Claude + thinking = temperature 1).
- L168 Le hub est charge au demarrage du PROCESS : re-sauver l'orchestrateur apres changement de capability.
- L172 Claude 5 via LiteLLM : decocher "Reasoning Model" dans l'entree Mesh.
- L175 Generateur d'agents : prouver la regeneration byte-identique avant de regenerer.
- L177 La capture brute = `{columns, rows, truncated}`, jamais de cle `captured`.
- L178 Le persona orchestrateur vit en 3 copies (dont notebook 01) : les editer ensemble.
- L179 Toute logique AVANT le try du worker de stream tue le thread sans liberer le slot.
- L192 Garde-fous prompt-injection : un plafond de volume ne coupe jamais les regles HIGH.
- L195 `models.json` = SEULE source des modeles, zero id en dur, zero repli, relu toutes les 30 s.
- L196 "Source Data n'affiche pas mes datasets" : verifier d'abord l'agent ET le projet selectionnes.

## Frontend (Vue 3)
- L020 Chat live : reactivite Vue (remplacer, pas muter) + `min-height:0` sur les flex scrollables.
- L022 `<style scoped>` : `:global(ancetre) .descendant` perd le descendant ; utiliser des custom properties.
- L034/L073 Stop : arret cooperatif backend + arret OPTIMISTE cote front.
- L038 Panneau hors RouterView : garder route ET etat pour qu'il se ferme.
- L042/L045 Evidence best-effort : le parseur ne bloque jamais l'affichage ; les fausses preuves viennent des regles re-derivees.
- L084 Zero tiret cadratin/demi-cadratin, partout.
- L092 Charte : toujours la vraie image du logo, jamais un visuel reconstruit en CSS.
- L123/L184 `position:fixed` casse sous un ancetre transforme ou sur un grid item : Teleport.
- L124/L133 Les classifieurs et folds front sont les miroirs EXACTS des gates backend.
- L137 Un ref local miroir d'un champ de store casse des que le store a un ecrivain asynchrone.
- L138 Le schema DSS peut mentir sur le type SQL : les bornes BETWEEN miment le format observe.
- L163 Un remplacement global peut casser une regex JS litterale : `node --check` sur chaque .js touche.
- L180/L188 Composant partage multi-hotes : re-teinter par custom properties, ecrire dans le store hote.
- L181 Couleurs Chart.js : resoudre les tokens sur `document.body`.
- L182 Purger un effet interdit = balayer aussi les overrides `:global(body[data-theme])`.
- L183 Simulateur local (dev-harness Vite + mock) : zero install, plugin intouche.
- L185 Deux regles de meme specificite dans deux composants : qualifier le selecteur hote.
- L186/L189 `watch` sans `immediate` rate l'etat deja actif ; un defaut issu de donnees tardives n'est pas une init.
- L187 Un flag admin sans case dans l'UI est efface par l'editeur de profil.

## Process
- L044/L142 Un gros module en UNE reponse d'agent meurt a la limite de sortie : decouper.
- L096 Cadrer l'intention UX d'une feature tot.
- L128 Rerouter un point d'entree peut orpheliner un sous-systeme : tracer les appelants avant/apres.
- L132 QA : prouver que le bundle teste contient le fix (hash + marqueur).
- L140/L152 Sous-agents background : exiger un `SendMessage` vers la session principale.
- L151/L164/L171 Codex : projet trusted pour lire `.codex/config.toml`, `</dev/null`, `--write` pour editer.
- L161/L174 Un test-double infidele au contrat reel cache des cassures : mocks = contrat reel.
- L194 Ne jamais jeter des changements non commites.

## Ajouts 2026-10-22
- L197 Vue 3.5 : les watchers pre-flush d'UN composant s'executent dans l'ordre de DECLENCHEMENT, pas d'enregistrement (FIFO des jobs PRE de meme id). "Enregistre en premier, execute en premier" ne tient que si un seul ref declenche les deux. Echec : `openSession` faisait `sources.closePanel()` AVANT `activeSessionId = ...`, le replay du contexte de panneau rouvrait le Studio de l'ancien run dans la nouvelle conversation. Solution : ordonner les ecritures de store, prouver la course avec un test jetable qui pilote la sequence des watchers a la main. Preuve : confirme 2026-10-20 apres le tour de correction (memoire adversarial-reviewer). Date : 2026-10-22.
- L198 Charte V2 : sur les ecrans V2 (`OWIsMind_PRD_V2_0/docs/CHARTE_V2_UI.md`, decision D1 2026-10-15) les rayons 2-8 px par tokens (`--r-pill`, `--r-lg`) PRIMENT sur le "carre absolu" de la charte V1.3 citee par la regle #10. Echec recurrent (MeasurePicker 10-20, SuggestionChips 10-22) : un dev re-met `border-radius: 0` en citant la charte V1.3, le panneau melange carre et 4 px. Solution : sur un fichier V2, comparer au composant voisin (`SourceChips`, `ui/Menu.vue`) ; les signaux oranges pulses (attente, barre d'insertion de drag) sont des SIGNAUX V2, pas de la decoration. Date : 2026-10-22.
- L199 Le plugin V2 en DSS a l'id `owismind_v2_0` (zip `owismind_v2_0-upload.zip`, `build_dev_plugin.py --version 2.0`), PAS `owismind_dev`. Echec 2026-10-22 : zip `owismind_dev` livre, DSS l'a installe comme un 2e plugin, la webapp V2 est restee sur le code du 15-10 (Studio non deplacable). Solution : toujours lire l'id du zip deja deploye (`unzip -p <zip> plugin.json`) et reconstruire avec la MEME identite. Preuve : zip reconstruit, `id = owismind_v2_0`, base `/plugins/owismind_v2_0/`. Date : 2026-10-22.
