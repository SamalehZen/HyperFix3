# HANDOFF — Chantier « Réponses riches dans Gaia » (session suivante)

> **Objectif** : retrouver dans Gaia le comportement de rendu de nao/HyperFix2
> (markdown riche, graphiques variés dans le chat, streaming, story player
> panneau droit) en adaptant l'UI/UX de Gaia — sans reprendre son interface.
> Contexte : l'utilisateur n'aime PAS les réponses actuelles de Gaia sur des
> questions comme « fais le récap d'aujourd'hui » — trop plates, pas de titres,
> pas de graphiques, pas de gras.

---

## 1. ÉTAT DE L'INFRASTRUCTURE (au 05/09/2026)

### Stack tournante (docker compose `deploy/hyperfix/docker-compose.yml`)
| Service | Port hôte | État |
|---|---|---|
| gaia-backend (API FastAPI) | 127.0.0.1:8000 | healthy |
| gaia-web (Next.js 16) | 127.0.0.1:3000 | healthy |
| mongo:8 | interne (réseau docker) | healthy |
| postgres:18 | interne | healthy |
| redis:8 | interne | healthy |
| chromadb:1.5.1 | interne | healthy |
| rabbitmq:4.1.8 | interne | healthy (trial : virable si inutile sans bots) |
| searxng | interne | healthy |

- **Domaine prod** : https://gaia.hypeer.cloud (Caddy, TLS direct, vhost dans
  HyperFix2 `Caddyfile`) → `/api/v1/*` → gaia-backend:8000 (SSE flush),
  le reste → gaia-web:3000.
- **HyperFix2 (nao)** : TOUJOURS EN PROD sur https://lololo.hypeer.cloud —
  ne pas toucher au code, ne pas arrêter (Telegram encore branché dessus).
- **Environnement Gaia** : `ENV=development` (auth par cookie + bypass dev
  actif). ⚠️ Avant une ouverture publique : retirer `DEV_AUTH_BYPASS_EMAIL`
  du `.env` et ajouter le redirect URI WorkOS
  `https://gaia.hypeer.cloud/api/v1/oauth/workos/callback` dans le dashboard
  WorkOS (Menu: Authentication → Redirects).

### Repo
- **HyperFix3** = `/opt/gaia-gamme` (fork du projet Gaia upstream, branche
  `master` poussée sur `main` GitHub `SamalehZen/HyperFix3`).
- Dossier de déploiement : `/opt/gaia-gamme/deploy/hyperfix/` (compose,
  `.env.example`, docs `MCP.md` + `RUNBOOK.md`).
- ~50 commits déjà poussés. **1 changement non commité** :
  `apps/api/app/agents/llm/exceptions.py` (commentaire MRO sur le bloc
  Exception — à committer en premier au prochain passage).

### LLM (chaîne validée)
| Priorité | Provider | Modèle | Endpoint | Note |
|---|---|---|---|---|
| 1 (défaut) | zen-muse | muse-spark-1.3-contributor-free | OpenCode Zen, API **/responses** | gratuit, quota free épuisé en ce moment (429) |
| 2 (repli) | openrouter (B.AI) | glm-5.3-flash | api.b.ai/v1 via ChatOpenAI | **marche**, réponds dans les tests |
| 3 | Gemini | gemini-3.1-flash-lite | — | inactif sans clé |

- Le repli est fonctionnel : `LLM_FALLBACK_EXCEPTIONS` contient `Exception`
  (apps/api/app/agents/llm/exceptions.py) → un 429 Zen déclenche B.AI.
- **BUG RESTANT** : le repli fonctionne au niveau `ainvoke_llm` (appel direct)
  mais le **middleware** `wrap_model_call` (executor.py:350) peut laisser fuir
  l'erreur 429 avant le fallback dans certains chemins du graphe → le message
  d'erreur brut remonte au chat. À corriger (voir §4 Phase A).

### MCP gamme-engine (16 outils)
- Serveur : `https://lololo.hypeer.cloud/mcp` (HyperFix2, OAuth RFC 9728).
- Intégration custom connectée dans Gaia : nom `gamme-engine`, status
  `connected`, 16 outils `gamme_*` indexés (Mongo `integrations.tools` +
  Chroma namespace `subagents`).
- **Auto-reconnexion** : module `apps/api/app/services/mcp/gamme_autoconnect.py`
  — séquestre du refresh_token (Mongo `gamme_escrow`, chiffré) rempli à chaque
  OAuth ; boucle au boot (+2 min) puis toutes les 15 min qui répare tout
  (fiche recréée, DCR restauré, credential réamorcée, refresh silencieux,
  reconnect). Si refresh mort → log « reconnecte-toi une fois via l'UI ».
- Compte nao utilisé : `samaleh2017@gmail.com` (rayon frais-surgele dans
  HyperFix2 `/storage/gamme/rayons.json`). Mot de passe nao régénéré le
  05/09 (donné à l'utilisateur en session, pas stocké).
- Skill utilisateur installé : `hyperfix-gamme` (target executor) — règles
  métier gamme : rayon d'abord, FDJ, récap V2, plan 48h.

### Composio (integrations Gmail/GitHub/Sheets…)
- Clé `COMPOSIO_KEY` dans `.env`. 22 auth_configs créées via API v3 sur le
  compte (gmail, github, googlecalendar, googlesheets, notion, slack, teams,
  linear, asana, trello, clickup, airtable, zoom, meet, maps, docs, tasks,
  todoist, hubspot, instagram, linkedin, reddit).
- **Twitter** : impossible sans ton propre app OAuth (pas de managed
  credentials) — à créer sur developer.twitter.com si besoin.
- Les 4 intégrations (gmail, gcal, github, sheets) apparaissent `connected`
  ou `created` dans Gaia.

---

## 2. CE QUE NAO FAIT (référence à reproduire)

### Rendu texte (dans le chat, style ChatGPT)
- Markdown complet : titres en grand, sous-titres, gras, tableaux compacts
  (code, libellé, stock), listes.
- Règles projet : `nao-gamme/RULES.md` (français, chiffres sourcés, FDJ tels
  quels, total jour = nouveaux + persistants) + skills
  (`recap-rayon.md`, `import-fichier.md`).
- Récap V2 : constat 1 phrase → sections (évolution, capital PRMP,
  anomalies) → **plan d'action 48h** → lien dashboard mix2.
- **Chaque graphique vient avec son explication** : paragraphe court
  (chiffre clé + sens) par défaut, version longue (constat + cause +
  action) si critique (PRMP élevé, chute forte, marge très négative).

### Graphiques dans le chat
- Outil `display_chart` : 13 types natifs (bar, stacked_bar, stacked_bar_100,
  line, area, stacked_area, stacked_area_100, mixed, pie, donut, kpi_card,
  scatter, radar) + table + custom (`product_image`).
- Alimentés par `execute_sql` → query_id → display_chart.
- Choix imposé par skill : line = série temporelle, area = PRMP,
  bar/stacked_bar = catégories, mixed = 2 échelles, pie = part ≤10,
  table = détail.

### Story player (PANNEAU SÉPARÉ du chat)
- Outil `story` : action create/update/replace, slug kebab-case,
  markdown + `<chart/>` `<table/>` `<grid/>` `<tab/>`.
- S'ouvre en panneau latéral à la création, versions gérées,
  éditable par l'utilisateur, indépendant du chat.

### Streaming
- SSE token-par-token via AI-SDK, rendu incrémental (Streamdown).

---

## 3. ÉTAT ACTUEL DE GAIA (écart vs nao)

### Ce qui marche déjà
- Streaming SSE identique (token-par-token, Redis Streams).
- Rendu markdown COMPLET côté frontend : `apps/web/src/features/chat/
  components/bubbles/bot/interface/MarkdownRenderer.tsx` — titres h1-h3,
  tableaux, gras, code, KaTeX, Streamdown. **Le renderer ne manque de rien.**

### Ce qui bride (tout est dans le PROMPT, pas le renderer)
1. `apps/api/app/agents/prompts/comms_prompts.py` :
   - ligne ~68 : « jamais bold/italics/CAPS en chat »
   - ligne ~73-76 (text_only) : NO tables, NO bold
   - ligne ~78-90 : mode « conversational (<10 mots) » par défaut
   - ligne ~56 : pas d'em-dash
2. `apps/api/app/agents/templates/agent_template.py:73-81` : canaux texte =
   NO markdown.
3. Graphiques : la seule voie vivante est `:::openui` (Bar/Line/Area/Pie/
   Radar/Radial/RadialChart + Table + NumberTicker) — voir
   `apps/api/app/agents/prompts/openui_prompts.py:72-74` et quality notes
   `:68-95`. Le vieux `ChartDisplay.tsx` (3 types) est mort/legacy.
4. Skill `hyperfix-gamme` existe mais ne décrit PAS encore le format de
   réponse riche (c'est le prompt global qui bride).

---

## 4. PLAN D'EXÉCUTION (phases A/B/C)

### Phase A — Stabiliser le chat (2 commits backend)
**A1. Commiter le changement en attente** : `exceptions.py` (commentaire MRO).
**A2. Réparer le middleware 429** : `apps/api/app/agents/middleware/executor.py:350`
   (« Middleware wrap_model_call chain failed ») — envelopper l'appel
   `wrap_model_call` pour qu'un 429/quota remonte DANS `ainvoke_llm` (où le
   fallback existe) au lieu de tuer le tour. C'est LE bug qui fait que
   l'utilisateur voit l'erreur 429 brute au lieu d'une réponse B.AI.
   → rebuild backend, test : chat fonctionne MÊME avec quota Zen épuisé.

### Phase B — Rendu riche partout (1 commit backend + 1 commit skill)
**B1. Lever les brides du prompt** dans `comms_prompts.py` (et
`agent_template.py` pour web) :
   - autoriser bold/italics/titres/tableaux markdown dans le chat web,
   - passer le mode par défaut de « conversational » à « détaillé structuré »
     (l'utilisateur veut le style ChatGPT PARTOUT, pas que la gamme),
   - garder le mode compact pour telegram/whatsapp (déjà séparé).
**B2. Étendre le skill `hyperfix-gamme`** (via `PUT /api/v1/skills/{id}` ou
réinstall inline) avec le format récap V2 : sections, graphiques
`:::openui`, explication sous chaque graphique, plan 48h, lien dashboard.
**B3. Test A/B** : même question (« fais le récap d'aujourd'hui ») sur nao
et Gaia, comparer markdown/graphiques.

### Phase C — Story player panneau droit (2-3 commits frontend)
**C1. Backend** : ajouter un outil `story` à Gaia (create/update/replace,
markdown + composants openui stockés dans Mongo `stories` collection,
versions) — OU plus simple : utiliser les artifacts existants
(`publish_artifact` + RightSidebar) en stockant le markdown du récap
comme artifact `story-recap-<jour>.md`.
**C2. Frontend** : bouton/rendu dans `RightSidebar.tsx` (déjà dark-first
zinc/cyan, clamp 520-980px) via `FileViewerPanel` (rendu markdown existant).
Auto-open à la création.
**C3. Test** : récap → panneau droit s'ouvre avec le récap complet.

---

## 5. COMMANDES UTILES

```bash
# rebuild backend (OBLIGATOIRE après tout changement apps/api)
cd /opt/gaia-gamme && docker compose -f deploy/hyperfix/docker-compose.yml build gaia-backend
docker compose -f deploy/hyperfix/docker-compose.yml up -d --force-recreate gaia-backend arq_worker

# rebuild web (après changement apps/web) — ~12 min, disque : purger avant si <6G
docker compose -f deploy/hyperfix/docker-compose.yml build gaia-web
docker compose -f deploy/hyperfix/docker-compose.yml up -d --force-recreate gaia-web

# purge disque (le build échoue en "no space left" si <6G libres)
docker builder prune -af && docker image prune -f

# logs
docker logs -f gaia-backend 2>&1 | grep -iE "error|gamme|mcp" | tail -n 20

# test LLM direct
docker exec gaia-backend python -c "
from app.core.lazy_loader import providers
from app.core.provider_registration import register_lazy_providers
register_lazy_providers('main_app')
import asyncio
async def m():
    llm = await providers.aget('zen_muse_llm')  # ou 'openrouter_llm'
    out = await llm.ainvoke('dis OK')
    print(out.content)
asyncio.run(m())"

# test santé
curl -s http://127.0.0.1:8000/health
curl -s -o /dev/null -w "%{http_code}" https://gaia.hypeer.cloud/
```

⚠️ **Web build** : Next 16, ~11 min, génère 4798 pages statiques. Si erreur
TS sur `onboarding/demo/page.tsx`, c'est que les props d'OnboardingInput ont
changé (déjà patché une fois — refaire).

---

## 6. PIÈGES CONNUS (déjà tombés dedans)

1. **Décorateur lazy_provider** : il décore la fonction juste après — ne
   JAMAIS insérer une classe/déf entre `@lazy_provider(...)` et `def init_x`.
2. **`configurable_fields`** : ChatOpenAI expose `model_name`,
   ChatOpenRouter expose `model`. Le zen-muse utilise `model_name=`.
3. **Blocs reasoning Zen** : expirés en minutes → `_ZenMuseChat._get_request_payload`
   les strip de l'historique (sinon 400 "Referenced reasoning item expired").
4. **`providers.get()`** : renvoie `None` (plus de KeyError) si le provider
   n'est pas enregistré — posthog etc. ne tuent plus les tours.
5. **build web sans node_modules local** : le typecheck se fait dans le
   build Docker. Erreurs TS = build fail.
6. **Disque 48G** : le build backend échoue si <6G libres (browsers
   retirés du Dockerfile mais les layers restent gros). Purger avant.
7. **`arq_worker`** : partage l'image du backend — re-tagguer après rebuild
   (`docker tag gaia-hyperfix-gaia-backend:latest gaia-hyperfix-arq_worker:latest`)
   sinon il tourne sur l'ancienne image.
8. **MCP disconnect = suppression totale** de la fiche + outils (comportement
   Gaia normal). L'auto-reconnexion répare en ≤15 min.

---

## 7. SECRETS / COMPTES

- `.env` : `/opt/gaia-gamme/deploy/hyperfix/.env` (jamais en git).
- WorkOS test : `WORKOS_API_KEY` (sk_test_...) + `WORKOS_CLIENT_ID`
  (client_01M1P8...) — dans le .env.
- LLM : Zen (gratuit, quota périodique) + B.AI (repli, glm-5.3-flash).
- Composio : `COMPOSIO_KEY` (ak_...) — 22 toolkits auth_configs créés.
- Compte nao : `samaleh2017@gmail.com` (mdp régénéré le 05/09, donné en
  session — le re-régénérer si perdu, voir session d'avant).
- Compte test MCP OAuth : `test.gestionnaire@example.com` (mdp réinitialisé
  à `TestDebug123!` le 05/09 pour les tests automatisés).
- GitHub : le token utilisé pour les push a été donné en session et doit être
  **révoqué** (il a circulé en clair). En créer un nouveau avant tout push.
