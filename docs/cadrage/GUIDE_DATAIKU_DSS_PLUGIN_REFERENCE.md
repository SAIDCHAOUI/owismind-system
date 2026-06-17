# Référence technique - Plugin WebApp Dataiku DSS (OWIsMind)

> Référence d'ingénierie condensée : build/package/zip, stockage SQL direct, agents LLM Mesh + streaming,
> et gotchas Dataiku. Fusion des deux anciens guides `cadrage/`, dépouillée de leurs redondances et de tout
> ce que la mémoire décrit désormais mieux.
>
> **⚠️ Source de vérité = `memory/PROJECT_STATE.md` + `memory/LESSONS.md`** (et `memory/CONTEXT.md` au démarrage).
> Ce fichier n'est qu'un point de départ : noms réels, schéma de tables courant, solutions validées EN DSS vivent
> en mémoire et **priment**. Les anciens guides employaient des **noms d'exemple** (`owismind-vue`, `owismindvue`,
> `webapp-owismind-vue`) - **ne pas les recopier** : utiliser les identifiants canoniques de `CLAUDE.md` /
> `PROJECT_STATE.md §3`.
>
> Plateforme observée : Dataiku DSS 14.4.x · backend Python **3.9.23** (3.11/FastAPI **non validés** - voir §6).
> Code agent réutilisable (appel agent streamé + extraction SQL/usage, création table SQL) :
> `docs/cadrage/code_samples_dataiku.md` (snippets notebook validés, **gardés à part, non recopiés ici**).

---

## 1. Modèle d'exécution DSS

DSS **n'exécute pas** Node/Vite. Le frontend est buildé localement ; DSS sert seulement les assets statiques.
DSS **exécute** le backend Python à partir de `webapps/<webapp>/backend.py`.

```
frontend/      = source Vue (local uniquement ; JAMAIS dans le zip)
resource/<app>/= build Vite réellement servi au navigateur
webapps/<wa>/  = descripteur + points d'entrée DSS (body.html, backend.py, app.js, style.css, webapp.json)
python-lib/<pkg>/ = backend applicatif modulaire (mis sur le path d'import par DSS)
```

`backend.py` reste un **bootstrap minimal** ; toute la logique vit dans `python-lib/`.

```python
# webapps/<webapp>/backend.py  (DSS fournit `app`)
from owismind.api.routes import register_routes
register_routes(app)
```

```python
# python-lib/owismind/api/routes.py
from flask import Blueprint, jsonify
api = Blueprint("owismind_api", __name__, url_prefix="/owismind-api")

@api.route("/ping", methods=["GET"])
def ping():
    return jsonify({"status": "ok", "python": __import__("sys").version.split()[0]})

def register_routes(app):
    app.register_blueprint(api)
```

Le frontend appelle **toujours** via `getWebAppBackendUrl('/owismind-api/...')` (jamais d'URL en dur). Cela exige
`"dataiku"` dans `standardWebAppLibraries` (sinon `getWebAppBackendUrl` est indisponible).

### Vérité d'environnement
Garder `/ping` qui renvoie `sys.version` : c'est la seule preuve de la version Python réellement exécutée.
Ne jamais affirmer qu'un autre environnement (3.11) ou framework (FastAPI) marche tant que `/ping` ne le prouve pas.

---

## 2. Configuration Vite (chemin public plugin)

Les assets sont servis sous `/plugins/<plugin-id>/resource/<dossier>/`, pas à la racine du domaine.
Valeurs canoniques réelles → `CLAUDE.md` (`base`, `outDir`).

```js
// frontend/vite.config.js
export default defineConfig({
  plugins: [vue()],
  base: '/plugins/owismind/resource/owismind-app/',  // doit matcher l'id plugin réel
  build: { outDir: '../resource/owismind-app', emptyOutDir: true },
})
```

- `base` doit matcher le plugin id : **s'il change → changer `base` ET rebuild** (sinon assets 404).
- `outDir` sort directement dans `resource/` (pas de `dist/` intermédiaire).
- `emptyOutDir: true` : les bundles sont **hashés** (`index-<hash>.js`) ; éviter d'accumuler d'anciens hashs.

---

## 3. Chaîne build → câblage → package

Mécanique de référence ; **commandes opérationnelles = skills `/build-plugin` et `/package-plugin`**
(ne pas réimplémenter les scripts bash des anciens guides).

1. **Build** (`npm run build` depuis `frontend/`) → assets hashés dans `resource/<app>/`.
   Pré-requis : `node_modules/` existe. **NO INSTALL** - l'agent n'installe jamais (cf. règle CLAUDE.md).
2. **Câbler `body.html`** : copier `resource/<app>/index.html` → `webapps/<wa>/body.html`, puis vérifier qu'il
   contient bien `/plugins/<plugin-id>/resource/<app>/`. L'entrée hashée change à chaque build, d'où la recopie
   systématique. (Cf. gotcha F10 : le `cp` peut être refusé par un hook → utiliser une écriture de fichier.)
3. **Package** : stager **runtime uniquement** dans le dossier d'upload - `plugin.json` (racine du zip) +
   `python-lib/` + `resource/` + `webapps/` - puis zipper depuis ce staging.

### Invariants de packaging (non négociables)
- Le zip ne contient **jamais** `frontend/`, `node_modules/`, ni de `plugin.json` mal placé.
  ⚠️ Piège export DSS : `plugin.json` peut arriver dans un dossier `_/` à l'export ; dans le **zip** il doit être
  à la **racine**. Ne jamais zipper depuis la racine source (`zip -r ... .` aspire `frontend/`+`node_modules/`).
- Slots STANDARD `app.js` / `style.css` : **vidés (commentaire), jamais supprimés** - DSS les exige.
  `app.js` ne doit **pas** garder le JS du template DSS qui manipule des éléments DOM absents de l'entrée Vue
  (sinon crash JS avant tout appel backend ; symptôme typique : backend up mais aucune requête applicative).
- `webapp.json` : ne pas réécrire le fichier entier ni « corriger » les types produits par DSS. Champs clés :
  `"baseType": "STANDARD"`, `"hasBackend": "true"` (**chaîne**, pas booléen), `"standardWebAppLibraries": ["jquery","dataiku"]`.

### Matrice rebuild (quoi refaire selon le changement)
| Changement | `npm run build` | recopier `body.html` | repackager | redémarrer backend |
|---|:--:|:--:|:--:|:--:|
| `frontend/**` (Vue, CSS, `vite.config.js`, `public/`) | oui | oui | oui | non |
| `webapps/**` (`app.js`/`body.html`/`style.css`/`webapp.json`) seuls | non | non | oui | oui si `webapp.json` change le backend |
| `python-lib/**` ou `backend.py` | non | non | oui | **oui** |

### Mise à jour du plugin dans DSS
Un plugin **Development** ne peut pas être mis à jour par upload ZIP du même id (`you cannot update it`).
Pour garder le même id (donc les chemins Vite déjà buildés) : supprimer le plugin Development, uploader le ZIP
(Origin = **Uploaded**), puis créer/recharger la webapp. Après upload : **Start/Restart backend** + refresh forcé.

---

## 4. Stockage SQL direct (`SQLExecutor2`)

Modèle : la WebApp stocke l'**expérience utilisateur** (conversations, messages, feedback, runs) ;
les **agents Dataiku produisent les réponses métier**. Le Flow n'est **pas** dans le chemin critique du chat.
Snippets notebook validés (CREATE/INSERT/SELECT/COMMIT) → `code_samples_dataiku.md`.

- `SQLExecutor2(connection=...)` via une **factory** qui renvoie une instance **fraîche par appel** (thread-safety).
  Lecture : `query_to_df(SELECT)`. Écriture : `pre_queries=[INSERT/UPDATE/CREATE]` + `post_queries=["COMMIT"]`
  (**COMMIT obligatoire** après tout effet de bord). Idiome **un seul aller-retour** : `pre=[INSERT]`, requête
  principale = `SELECT` de relecture par id, `post=[COMMIT]` (la SELECT voit sa propre écriture).
- **Nommage des tables** : `{PROJECT_KEY}_owismind_{logical}`, cité `public."OWISMIND_DEV_owismind_..."`.
  ⚠️ Le namespace `owismind_` (toujours après le project key) est la convention **réelle** - elle **prime sur**
  l'ancien exemple `{PROJECT_KEY}_{logical}` des guides. Centralisé dans `storage/sql_config.py`. Sans guillemets
  doubles, PostgreSQL force le nom en minuscules. Idiome `_vN` : nouvelle version = nouvelle table, **jamais d'ALTER**.
  Le project key est résolu **serveur** (`dataiku.default_project_key()`, validé en contexte plugin) - jamais fourni par le front.

### Sécurité SQL (non négociable)
- **Jamais** de f-string brute avec input utilisateur. Valeurs paramétrées via `dataiku.sql` :
  `from dataiku.sql import Constant, toSQL, Dialects` → `toSQL(Constant(value), dialect=Dialects.POSTGRES)`.
- **Identifiants** (table/colonne/schéma) : jamais via la valeur paramétrée ; générés serveur depuis des
  constantes contrôlées + validation regex (`^[A-Za-z_][A-Za-z0-9_]*$`) avant double-quote.
- **Interdits** : route SQL générique exposée (`/execute-sql`, `/run-query`…) ; frontend qui choisit
  table/colonne/connexion/schéma/requête ; SQLExecutor exposé au front ; DDL dans une route utilisateur publique ;
  Dataset/Flow dans le chemin critique du chat.

### Schéma réel (≠ schéma « V1 » aspirationnel des anciens guides)
Le schéma multi-tables `webapp_conversations/messages/runs/run_events/generated_sql/feedback` proposé dans
l'ancien guide **n'a pas été retenu tel quel**. Le schéma **effectif validé EN DSS** (table chat courante,
colonnes feedback + `parent_exchange_id`, trace = dataset Flow append write-only, etc.) est décrit dans
`PROJECT_STATE.md §7`. **S'y référer plutôt qu'au DDL des anciens guides.**

---

## 5. Agents LLM Mesh & streaming

### Appel agent
```python
client = dataiku.api_client()
llm = client.get_project(project_key).get_llm(agent_id)   # ⚠️ get_project(pk), pas get_default_project()
                                                          #    l'agent peut être hors projet courant
completion = llm.new_completion()
completion.with_message(content, role)                    # rejouable pour un contexte multi-tours
for chunk in completion.execute_streamed():
    ...
```

Parsing des chunks (détail + extraction usage/SQL → `code_samples_dataiku.md`) :
- `type == "event"` → events agent (`AGENT_BLOCK_START`, `AGENT_TOOL_START`, `AGENT_THINKING`, `AGENT_BLOCK_DONE`…) → timeline.
- `type in ("content","text")` → delta de réponse à concaténer.
- footer (`data.type == "footer"` ou `isinstance(chunk, DSSLLMStreamedCompletionFooter)`) → `footer.trace`
  → usage (`usageMetadata`) + SQL généré (`name == "semantic-model-query"` → `outputs.sql`, fallback
  `eventData.generatedSql`).

### Transport : POLLING-via-thread (PAS de SSE)
⚠️ **Le SSE est ABANDONNÉ** : le proxy interne DSS bufferise le flux HTTP long → tout arrive en bloc à la fin.
Pattern validé EN DSS (et utilisé par le Dash de prod) : un **worker daemon** par envoi itère
`execute_streamed`, empile des events normalisés en mémoire (dict sous lock, cap concurrence + TTL + scope
`user_id`) ; le front **poll** `/chat/start` → `/chat/poll` (~500 ms). La **réponse texte tombe en bloc à la fin**
(agent structuré) ; le live exploitable = la **timeline**. Détail → `PROJECT_STATE.md §8`, leçon **L019**.

Events normalisés vers le front : `run_started`, `agent_event`, `answer_delta`, `generated_sql`,
`usage_summary`, `final_answer`, `run_done`, `error`. Ne jamais relayer au front les objets bruts Dataiku.
Ne pas promettre un streaming token-par-token des résultats internes des tools (les appels d'outils restent bloquants).

### Whitelist agents (côté serveur)
⚠️ La whitelist `ALLOWED_AGENTS` codée en dur de l'ancien guide est **supersédée** par une **whitelist dynamique**
(table de settings, découverte DSS en lecture seule, re-validation serveur) : le front ne reçoit que des
**clés logiques opaques** `{key,label}` ; la résolution `key → (project_key, agent_id)` est **serveur**.
Jamais d'`agent_id`/`project_key` reçu du front. Détail → `PROJECT_STATE.md §8`, leçons **L017/L018**.

---

## 6. Sécurité webapp & identité

- **`Run backend as`** : la webapp s'exécute sous une identité configurée, **≠ utilisateur final**. Une webapp
  multi-utilisateurs ne doit pas exposer à tous les droits d'un compte backend puissant.
- **Identité réelle** de l'appelant : `dataiku.api_client().get_auth_info_from_browser_headers(dict(request.headers))`
  → `authIdentifier` / `associatedDSSUser` / groupes. À utiliser pour scoper les données (un user ne voit que ses
  conversations) et l'admin.
- **Impersonation** pour opérations sensibles : `with dataiku.WebappImpersonationContext(): ...`.
- API Dataiku côté backend : **lecture seule** (+ run agent). Décider explicitement par route ce qui tourne sous
  le compte backend vs l'utilisateur courant.
- **Python 3.11 / FastAPI** : officiellement supportés par DSS (FastAPI exige DSS ≥ 14.2 + code-env
  `fastapi`+`uvicorn-worker`) mais **non validés ici** (backend observé = 3.9.23 / Flask). Si besoin : passer par un
  code-env porté par le plugin (`code-env/python/`, **généré par DSS** plutôt qu'inventé), valider dans un plugin
  de laboratoire séparé, et ne conclure qu'après preuve `/ping`. **Ne pas migrer pendant qu'on stabilise la chaîne.**

---

## 7. Diagnostic rapide

| Symptôme | Piste |
|---|---|
| Interface Vue absente | assets/`base` Vite/`body.html`/zip plugin |
| Vue OK mais aucun appel backend | `app.js` crashe avant l'appel (DOM template DSS) ou cache navigateur |
| `getWebAppBackendUrl is not a function` | `"dataiku"` manquant dans `standardWebAppLibraries` |
| HTTP 404 sur la route | route non enregistrée / mauvais préfixe / `hasBackend` off / backend non redémarré |
| HTTP 500 | import Python cassé / `python-lib/` absent du zip / exception (lire les logs DSS) |
| `ModuleNotFoundError` sur le package | dossier `python-lib/<pkg>` absent du zip, mal nommé, ou `__init__.py` manquant |
| Streaming « tout en bloc » à la fin | SSE bufferisé par le proxy DSS → utiliser le polling-via-thread (§5) |
| `/ping` renvoie 3.9.x alors qu'on voulait 3.11 | code-env plugin non configuré/sélectionné (pas un bug du backend) |
| Zip énorme | zip créé depuis la mauvaise racine → refaire depuis le staging runtime uniquement |

---

## 8. Références officielles Dataiku
- WebApps (composant plugin) : <https://doc.dataiku.com/dss/latest/plugins/reference/webapps.html>
- Standard web apps : <https://doc.dataiku.com/dss/latest/webapps/standard.html>
- WebApp security / impersonation : <https://doc.dataiku.com/dss/latest/webapps/security.html>
- Code environments (+ plugins) : <https://doc.dataiku.com/dss/latest/code-envs/index.html> · <https://doc.dataiku.com/dss/latest/code-envs/plugins.html>
- SQLExecutor2 : <https://developer.dataiku.com/latest/concepts-and-examples/sql.html> · <https://developer.dataiku.com/latest/api-reference/python/sql.html>
- LLM Mesh (Python API) : <https://developer.dataiku.com/latest/concepts-and-examples/llm-mesh.html> · <https://developer.dataiku.com/latest/api-reference/python/llm-mesh.html>
- Vite `base` / build : <https://vite.dev/config/shared-options> · <https://vite.dev/config/build-options>
