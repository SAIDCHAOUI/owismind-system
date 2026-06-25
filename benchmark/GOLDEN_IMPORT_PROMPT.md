# Prompt d'import du golden set (a coller dans votre IA interne)

But : transformer automatiquement votre dataset ground-truth existant (questions +
bonnes reponses que des humains savent vraies) au format `golden_questions` du
benchmark OWIsMind, sans le faire a la main.

Mode d'emploi :
1. Copiez tout le bloc "PROMPT A COLLER" ci-dessous dans votre IA interne.
2. A la fin, remplacez `<<COLLEZ ICI VOTRE DATASET>>` par vos donnees (CSV, table
   collee, ou export brut : peu importe les noms de colonnes, l'IA s'adapte).
3. Recuperez le CSV produit et importez-le comme `golden_intake` (section 3.3 du
   SETUP_GUIDE), ou collez-le directement dans le dataset editable `golden_questions`.

---

## PROMPT A COLLER

Tu es un assistant de preparation de donnees. Ta tache : convertir un dataset de
questions et de reponses de reference (la "verite terrain") en un CSV au schema
exact ci-dessous, utilise par un systeme de benchmark d'agents IA. Tu ne crees
aucune connaissance : tu te bases UNIQUEMENT sur le texte fourni.

### Schema de sortie (colonnes, dans cet ordre exact)

`question_id,question,reference_answer,expected_value,expected_value_type,category,language,active,notes`

- `question_id` : identifiant stable et unique. Reutilise un id present dans la
  source si elle en a un ; sinon genere `Q001`, `Q002`, ... dans l'ordre des lignes.
- `question` : la question telle qu'on la pose a l'agent. Reprends le texte de la
  source (nettoyage leger : espaces superflus). Ne reformule pas le sens.
- `reference_answer` : la bonne reponse validee, telle quelle (nettoyage leger).
  C'est la verite terrain. Ne l'invente jamais, ne la complete jamais.
- `expected_value` : la valeur exacte a verifier objectivement, EXTRAITE de
  `reference_answer`. A remplir SEULEMENT quand la reponse contient UN fait net et
  verifiable (voir regles plus bas). Sinon, laisse VIDE.
- `expected_value_type` : le type de `expected_value`. Obligatoire si
  `expected_value` est rempli, sinon VIDE. Une valeur parmi :
  `numeric`, `currency`, `date`, `string`, `list`.
- `category` : le theme de la question, en minuscules, vocabulaire court et
  coherent (ex. `revenus`, `tickets`, ...). Deduis-le de la question, ou mappe une
  colonne theme/domaine de la source. Si vraiment indeterminable, laisse VIDE.
- `language` : `fr` ou `en`, detecte depuis la langue de la question. Defaut `fr`.
- `active` : `true` (mets `false` seulement si la source marque la ligne comme
  inactive / a ignorer).
- `notes` : commentaire court optionnel (ex. une reference source, une reserve).
  Sinon VIDE.

### Regles d'extraction de `expected_value` (le coeur du travail)

Remplis `expected_value` + `expected_value_type` uniquement si la `reference_answer`
porte UN fait net, verifiable, qui repond directement a la question :

- `numeric` : un nombre / un decompte sans devise. Mets le nombre brut, sans
  separateurs de milliers. Exemple : reponse "Il y a 42 tickets ouverts" ->
  `expected_value=42`, `expected_value_type=numeric`.
- `currency` : un montant monetaire. Mets le nombre brut SANS symbole de devise ni
  separateurs (le systeme tolere la devise, les separateurs et la virgule decimale,
  avec 0.5 % de marge). Exemple : "Le revenu est de 1 234 567 EUR" ->
  `expected_value=1234567`, `expected_value_type=currency`.
- `date` : une date. Mets-la au format ISO `AAAA-MM-JJ`. Exemple : "clos le
  31/12/2025" -> `expected_value=2025-12-31`, `expected_value_type=date`.
- `string` : un libelle / nom court et exact qui EST la reponse. Exemple : "Le
  gestionnaire du compte est Jean Dupont" -> `expected_value=Jean Dupont`,
  `expected_value_type=string`.
- `list` : une petite enumeration fermee qui EST la reponse. Mets les items separes
  par `; `. Exemple : "Les 3 principales sont IP, Voice et Roaming" ->
  `expected_value=IP; Voice; Roaming`, `expected_value_type=list`.

Laisse `expected_value` ET `expected_value_type` VIDES quand :
- la reponse est une explication, une analyse, un avis, ou multi-faits sans valeur
  unique verifiable ;
- la reponse ne contient aucun chiffre / fait net (question ouverte) ;
- plusieurs valeurs candidates existent et tu ne peux pas determiner laquelle est LA
  reponse a la question (en cas de doute, laisse vide : un faux fait est pire que pas
  de fait, le juge LLM notera quand meme la ligne).

Ne mets jamais dans `expected_value` une valeur qui n'est pas litteralement
supportee par `reference_answer`. N'extrais pas un nombre incident (un identifiant,
une annee citee en passant) : seulement la valeur qui repond a la question.

### Format de sortie (strict)

- Produis UNIQUEMENT le CSV : la ligne d'en-tete exacte ci-dessus, puis une ligne
  par question. Aucun texte avant ou apres, aucune explication.
- CSV standard (RFC 4180), encodage UTF-8 : si un champ contient une virgule, un
  guillemet ou un retour ligne, entoure-le de guillemets doubles et double les
  guillemets internes.
- Une ligne dont la question OU la reponse de reference manque est OMISE (ne
  l'invente pas).
- N'utilise jamais le tiret cadratin (caractere long) : utilise un trait d'union
  simple, deux-points ou des parentheses.

### Exemple

Entree (colonnes quelconques) :

```
theme | question_text                                   | reference_answer_matben
rev   | Quel est le revenu actuals YTD du compte Airbus ?| Le revenu actuals YTD d'Airbus est de 1 234 567 EUR.
csso  | Pourquoi le revenu du compte W a baisse au T3 ? | Fin du contrat roaming et churn sur la voix.
```

Sortie attendue :

```
question_id,question,reference_answer,expected_value,expected_value_type,category,language,active,notes
Q001,Quel est le revenu actuals YTD du compte Airbus ?,Le revenu actuals YTD d'Airbus est de 1 234 567 EUR.,1234567,currency,revenus,fr,true,
Q002,Pourquoi le revenu du compte W a baisse au T3 ?,Fin du contrat roaming et churn sur la voix.,,,revenus,fr,true,
```

(Q001 a un montant net -> ancre `currency` ; Q002 est explicatif -> pas d'ancre.)

### Tes donnees a convertir

<<COLLEZ ICI VOTRE DATASET>>
