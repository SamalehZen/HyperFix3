# Runbook HyperFix + Gaia

## Commandes (depuis `deploy/hyperfix`)

```bash
docker compose up -d --build     # build + démarrage
docker compose ps                # états (backend/web healthy)
docker compose logs -f gaia-backend | gaia-web | arq_worker
docker compose restart gaia-backend
docker compose down              # arrêt (données conservées, volumes nommés)
```

## Test rabbitmq (trial)

```bash
docker compose stop rabbitmq
# utiliser le chat 10 min (messages, outils) :
docker compose logs gaia-backend | grep -i "rabbitmq\|amqp" | head
# silence radio → le retirer du compose (commit dédié)
```

## Rollback bascule Caddy

Avant toute modif Caddy : `cp Caddyfile Caddyfile.bak.$(date +%F)`.
Retour : restaurer le backup + `caddy reload`, redémarrer `nao`.

## Secrets — checklist

Jamais en chat, jamais en git (`.env` ignoré, vérifié par
`git check-ignore deploy/hyperfix/.env`) :
`WORKOS_API_KEY`, `WORKOS_CLIENT_ID`, `OPENCODE_ZEN_API_KEY`,
`POSTGRES_PASSWORD`, `SEARXNG_SECRET`, (`GOOGLE_GENERATIVE_AI_API_KEY` plus tard).

## Auto-reconnexion MCP gamme (module `gamme_autoconnect.py`)

Le refresh token est séquestré (chiffré, Mongo `gamme_escrow`) à chaque OAuth
réussi. Au boot (+2 min) puis toutes les 15 min, le backend vérifie et répare
tout seul : refresh silencieux → fiche recréée si supprimée → reconnect + index.

```bash
# Voir l'état du séquestre + dernier passage :
docker logs gaia-backend --since 20m 2>&1 | grep -i "gamme-autoconnect" | tail -n 5
# Forcer un passage immédiat (sans attendre 15 min) :
docker exec gaia-backend python -c "
import asyncio
from app.services.mcp.gamme_autoconnect import heal_once
print(asyncio.run(heal_once()))"
# Si le log dit "reconnecte-toi une fois via l'UI" : le refresh est mort
# (révoqué côté nao) → 1 connexion manuelle, le séquestre se remplit seul.
```

Ne JAMAIS cliquer "disconnect" sur gamme-engine par habitude : ça supprime
tout (comportement Gaia normal) — l'auto-réparation le reconstruira au
prochain passage, mais 15 min sans outils.
