# HyperFix + Gaia — déploiement minimal

> HyperFix, la fixation — notre raison d'être.

Chat **Gaia** (web) + cerveau métier **gamme-engine** (HyperFix2, via MCP).
Le backend `nao` n'est pas utilisé ici.

## Services (8 + rabbitmq en test)

`gaia-backend` · `gaia-web` · `mongo` · `postgres` · `redis` · `chromadb` ·
`arq_worker` · `searxng` (+ `rabbitmq` en test — viré s'il ne sert qu'aux bots).

Virés vs upstream : voix, 5 bots, observabilité (loki/grafana/promtail),
`embedding-sidecar`, `mongo_express`. Tout écoute sur `127.0.0.1` seul,
avec `mem_limit` partout (serveur 8 Go, pas de swap par défaut — voir
`../../scripts/setup-swap.sh`).

## Démarrage

```bash
cp .env.example .env   # puis renseignez les secrets (hors chat !)
nano .env
docker compose up -d --build
docker compose ps      # backend/web healthy
```

## Vérifications

```bash
curl -s http://127.0.0.1:8000/health        # backend
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:3000/  # web
```

Docs : `docs/MCP.md` (branchement gamme), `docs/RUNBOOK.md` (commandes, rollback).
