# MCP gamme-engine ↔ Gaia (sans toucher HyperFix2)

## Endpoint (déjà en prod, lecture seule pour ce chantier)

- Découverte : `https://lololo.hypeer.cloud/.well-known/oauth-protected-resource/mcp`
- MCP : `https://lololo.hypeer.cloud/mcp` (streamable-http, RFC 9728)
- Testé le 2026-09-04 : PRM ✅, défi `401 WWW-Authenticate` ✅,
  métadonnées OAuth (DCR + PKCE + JWKS) ✅.

## Déclaration côté Gaia (FAIT le 2026-09-04)

Intégration custom créée via `POST /api/v1/integrations/custom`
(`server_url=https://lololo.hypeer.cloud/mcp`, dev bypass `X-Dev-User`).

Flux OAuth complet **testé et connecté** :
1. `POST /integrations/custom` → DCR chez nao + `oauthUrl`
2. login nao (`sign-in/email`, compte avec rayon) → `GET authorize` → 302 `/consent`
3. `POST /api/auth/oauth2/consent {accept:true, oauth_query}` (Origin requis)
4. callback Gaia → token exchange → tokens chiffrés (MCP_ENCRYPTION_KEY, Postgres)
5. background connect : `tools/list` → **16 outils stockés dans Mongo**
   (`db.integrations.tools`) + indexés Chroma (`subagents` namespace)

⚠️ L'URL d'autorisation expire vite (~5 min) : enchaîner login→consent→callback
dans la minute. Le `POST /mcp/test/{id}` re-sonde à froid (renvoie
`requires_oauth` même connecté) — l'état vrai est dans
`db.user_integrations.status=connected`.

## Auth

Consentement OAuth une fois, avec un **compte nao qui a un rayon assigné**
dans `rayons.json` — sinon « Accès refusé » même avec un bon token
(`gamme_mon_rayon` fait foi). Aucune modif côté `gamme-engine`.

## Outils (16)

`gamme_mon_rayon`, `gamme_rayons`, `gamme_query`, `gamme_history_query`,
`gamme_negatifs`, `gamme_anomalies`, `gamme_rapports`, `gamme_serie`,
`gamme_article`, `gamme_recherche_articles`, `gamme_import_file`,
`gamme_imports`, `gamme_etiquettes`, `gamme_image_article`,
`gamme_libeller`, `gamme_structure_articles`.
