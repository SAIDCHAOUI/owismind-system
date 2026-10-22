// Reply-language rule of the live harness: a faithful port of the backend's
// plugin/owismind/python-lib/owismind/agents/context.py (detect_prompt_language_scored,
// detect_prompt_language, build_user_suffix). SAME word lists, SAME scoring, SAME
// suffix text, so a harness run sees exactly what the DSS agent sees. The algorithm
// is documented in the context.py module docstring; lang.test.mjs asserts the parity
// (word lists read from context.py, outputs compared with python3 when available).

// Tokens: runs of latin letters (accented included) and apostrophes.
const TOKEN_RE = /[a-zà-öø-ÿœæ']+/g
const APOSTROPHES_RE = /[’‘`´]/g
// French-only diacritics: a token carrying one is French evidence (weight 1).
const FR_ACCENT_RE = /[àâæçèéêëîïôœùûüÿ]/
// French elision at the start of a token ("l'évolution" -> +1 fr, then "évolution").
const FR_ELISION_RE = /^(?:l|d|j|c|n|s|m|t|qu|jusqu|lorsqu|puisqu)'(?=[a-zà-ÿœ])/
// English contractions: "n't" (head not scored) and 's 're 've 'll 'd 'm (head scored).
const EN_NEG_RE = /n't$/
const EN_CONTRACTION_RE = /'(?:s|re|ve|ll|d|m)$/

const words = (s) => new Set(s.split(/\s+/).filter(Boolean))

// Function words, weight 1 each. Keep IDENTICAL to context.py (_FR_WORDS / _EN_WORDS).
export const FR_WORDS = words(`
le la les un une des du de au aux ce cet cette ces ça ca ceci cela
mon ma mes ton ta tes sa ses notre nos votre vos leur leurs
je tu il elle ils elles nous vous moi toi lui eux se
qui que quoi quel quelle quels quelles lequel laquelle où ou
et mais donc ni si pour par avec sans sous sur dans chez entre vers depuis
pendant avant après apres selon contre comme
est sont suis es sommes êtes etes était etait étaient etaient été ete être etre
ai avons avez ont avoir avait aurait sera serait
fait faire fais faites peux peut pouvez pourrais pourriez pourrait
veux veut voulez voudrais souhaite souhaiterais dois doit devrait faut
montre montrez montrer donne donnez donner affiche affichez afficher
ajoute ajoutez ajouter rajoute rajoutez rajouter explique expliquez expliquer
comparez comparer liste lister analyser calcule calculer refais
combien comment pourquoi quand
merci bonjour bonsoir salut svp stp oui
ne pas moins très tres bien aussi encore déjà deja
tous toutes tout toute chaque quelques autre autres voici voilà voila
aujourd peu beaucoup trop mois année annee années annees semaine trimestre jour jours
`)
export const EN_WORDS = words(`
the of and to in is are was were be been being am
do does did done doing have has had having
i you he she it we they them us my your his her its our their
this that these those there here
what which who whom whose why how when where
can could would should will shall may might must
please thanks thank hello hi hey
with from by at for about into over under between than then
also just only very all each every some any no not yes
show give tell make add explain display list get need want see help let
more most less much many if so up out same other both
month year week quarter last next previous current
`)
// Shared business nouns and loanwords: zero weight, exempt from suffix cues.
export const NEUTRAL_WORDS = words(`
revenue revenues revenu revenus client clients budget budgets total totals
phase phases actuals actual forecast forecasts kpi ytd mtd segment segments
management investment payment payments department statement document moment
agreement requirement settlement engagement achievement improvement element
marketing pricing reporting billing booking consulting planning forecasting
ranking leasing trading roaming streaming meeting parking holding building
entrepreneur unique technique boutique critique
`)
const FR_SUFFIXES = ['ement', 'eur', 'eux', 'ais', 'ez', 'aux', 'ique']
const EN_SUFFIXES = ['ing', 'ed', 'ly', 'ness', 'ful']
const SUFFIX_MIN_LEN = 5
const SUFFIX_WEIGHT = 0.5
export const LANG_MIN_CONFIDENCE = 0.5

const LANG_LABEL = { fr: 'French', en: 'English' }
const labelOf = (lang) => (Object.prototype.hasOwnProperty.call(LANG_LABEL, lang) ? LANG_LABEL[lang] : undefined)
const MODEL_MODES = ['smart', 'pro', 'claude']

function scoreWord(word, scores) {
  if (!word || NEUTRAL_WORDS.has(word)) return
  if (FR_WORDS.has(word)) scores.fr += 1
  else if (EN_WORDS.has(word)) scores.en += 1
  else if (FR_ACCENT_RE.test(word)) scores.fr += 1
  else if (word.length >= SUFFIX_MIN_LEN) {
    if (FR_SUFFIXES.some((s) => word.endsWith(s))) scores.fr += SUFFIX_WEIGHT
    else if (EN_SUFFIXES.some((s) => word.endsWith(s))) scores.en += SUFFIX_WEIGHT
  }
}

function scoreToken(raw, scores) {
  const token = raw.replace(/^'+|'+$/g, '')
  if (!token) return
  const elision = FR_ELISION_RE.exec(token)
  if (elision) {
    scores.fr += 1
    scoreToken(token.slice(elision[0].length), scores)
    return
  }
  if (EN_NEG_RE.test(token)) {
    scores.en += 1
    return
  }
  const contraction = EN_CONTRACTION_RE.exec(token)
  if (contraction) {
    scores.en += 1
    scoreWord(token.slice(0, contraction.index), scores)
    return
  }
  for (const part of token.split("'")) scoreWord(part, scores)
}

// [lang, confidence]: lang 'fr' | 'en', confidence 0..1 (0 on a tie / no evidence).
export function detectPromptLanguageScored(message) {
  const scores = { fr: 0, en: 0 }
  const text = String(message || '').toLowerCase().replace(APOSTROPHES_RE, "'")
  for (const token of text.match(TOKEN_RE) || []) scoreToken(token, scores)
  const { fr, en } = scores
  const total = fr + en
  if (total <= 0 || fr === en) return ['fr', 0]
  const top = Math.max(fr, en)
  const confidence = Math.min(1, top) * (0.5 + (0.5 * Math.abs(fr - en)) / total)
  return [fr > en ? 'fr' : 'en', confidence]
}

// Reply language of the LAST user prompt; defaultLang (the web-app language) when
// the message is neutral or too short ("42", "ok", "revenue 2025 EMEA").
export function detectPromptLanguage(message, defaultLang = 'fr') {
  const fallback = labelOf(defaultLang) ? defaultLang : 'fr'
  const [lang, confidence] = detectPromptLanguageScored(message)
  return confidence > LANG_MIN_CONFIDENCE ? lang : fallback
}

const DAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
  'August', 'September', 'October', 'November', 'December']
const pad2 = (n) => String(n).padStart(2, '0')

// Python strftime("%A, %B %d, %Y at %H:%M") in the C locale, local time.
function formatDate(d) {
  return `${DAYS[d.getDay()]}, ${MONTHS[d.getMonth()]} ${pad2(d.getDate())}, ${d.getFullYear()}`
    + ` at ${pad2(d.getHours())}:${pad2(d.getMinutes())}`
}

// The context block appended to the END of the current user message, character for
// character the output of context.build_user_suffix.
export function buildUserSuffix({ fullName, now, webappLang, promptLang, mode } = {}) {
  const name = fullName || 'Unknown user'
  const date = formatDate(now || new Date())
  const webappLabel = labelOf(webappLang)
  const promptLabel = labelOf(promptLang)
  let tokens = ''
  if (MODEL_MODES.includes(mode)) tokens += `⟦owi:mode=${mode}⟧`
  if (promptLabel) tokens += `⟦owi:lang=${promptLang}⟧`
  let head = `\n\n[Context - User: ${name} · Today: ${date}`
  if (webappLabel) head += ` · Web app language: ${webappLabel}`
  head += ']'
  if (tokens) head += ' ' + tokens
  const parts = [head]
  if (promptLabel) {
    const webappRule = webappLabel && webappLabel !== promptLabel
      ? `The web-app language (${webappLabel}) is NOT the reply language.`
      : 'The web-app language never sets the reply language.'
    parts.push(
      `IMPORTANT - reply in ${promptLabel}, the language of my message above: write EVERYTHING `
        + `in ${promptLabel}, the chat reply AND every tool argument (plan steps, widget titles, `
        + `subtitles, texts, scope). ${webappRule} This rule takes priority over earlier turns.`,
    )
  }
  return parts.join('\n')
}
