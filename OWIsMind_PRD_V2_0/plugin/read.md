# plugin/ : le plugin Dataiku OWIsMind (WebApp Vue 3 + backend Flask)

Le plugin est un objet d'INSTANCE Dataiku (pas un objet du projet) : il s'installe
via Administration > Plugins > Upload. Il vit dans ce dossier projet parce qu'il
evolue avec chaque version du projet (regle : une branche git par version).

| Sous-dossier | Contenu | A la main ? |
|---|---|---|
| `owismind/` | LA source du plugin : `plugin.json`, `python-lib/` (backend Flask), `frontend/` (source Vue 3, jamais dans le zip), `resource/owismind-app/` (front builde, genere par `/build-plugin`), `webapps/`, `tests/` | Editer `python-lib/` et `frontend/src/` uniquement |
| `ready-for-dataiku/` | Les zips a uploader dans DSS (git-ignore, regenere par `/package-plugin` et `/package-plugin-dev`). Zip DEV courant : `owismind-v1_3-dev-upload.zip` (plugin id `owismind_dev`, coexiste avec la prod v1.2) | Jamais editer, jamais commiter |
| `tools/` | `build_dev_plugin.py` : script LOCAL (macOS, repo) qui fabrique le zip DEV. Ne se met JAMAIS dans DSS | Lancer depuis la racine du repo |

Rappels non negociables : pas de `npm install` / `pip install` par l'agent ;
`frontend/` et `node_modules/` ne vont jamais dans le zip ; ne pas editer
`resource/owismind-app/` a la main (genere).
