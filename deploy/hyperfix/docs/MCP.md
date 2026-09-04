# MCP gamme-engine ↔ Gaia (sans toucher HyperFix2)

## Endpoint (déjà en prod, lecture seule pour ce chantier)

- Découverte : `https://lololo.hypeer.cloud/.well-known/oauth-protected-resource/mcp`
- MCP : `https://lololo.hypeer.cloud/mcp` (streamable-http, RFC 9728)
- Testé le 2026-09-04 : PRM ✅, défi `401 WWW-Authenticate` ✅,
  métadonnées OAuth (DCR + PKCE + JWKS) ✅.

## Déclaration côté Gaia (phase exécution)

Ajouter `https://lololo.hypeer.cloud/mcp` en MCP custom. Le client Gaia
découvre les **16 outils `gamme_*`** tout seul (`listTools`).

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
