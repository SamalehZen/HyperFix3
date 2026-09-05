"""HyperFix : auto-connexion persistante du MCP gamme-engine.

Contexte : le MCP ``gamme-engine`` (HyperFix2, inchangé) exige un OAuth avec
consentement navigateur. Sans garde-fou, la moindre expiration/révocation ou
un clic "disconnect" coupe la gamme jusqu'à une reconnexion manuelle.

Principe (zéro touche à HyperFix2, tout ici) :
1. À chaque OAuth réussi sur le serveur gamme, le ``refresh_token`` est mis
   sous séquestre (chiffré Fernet, collection Mongo ``gamme_escrow``).
2. Au boot puis toutes les 15 min, ``heal`` vérifie chaque séquestre : si la
   connexion est absente/expirée, il rafraîchit le token (grant
   ``refresh_token``, machine-to-machine, SANS navigateur), recrée la fiche
   d'intégration si elle a été supprimée, restaure les credentials, remet le
   statut à jour et reconnecte (handshake + tools/list + indexation).
3. Si le refresh est mort (révoqué côté nao), on logue une action manuelle
   claire ("reconnecte-toi une fois via l'UI") au lieu de tourner en boucle
   silencieusement — le prochain OAuth remplit à nouveau le séquestre.

Réutilise les briques existantes (DCR stocké, ``try_refresh_token``,
``create_custom_integration``, ``connect``) au lieu de les dupliquer ; les
imports lourds sont locaux aux fonctions pour éviter tout cycle d'import
(ce module est importé par ``mcp_client`` pour le hook).
"""

import asyncio
from datetime import datetime, timezone

from cryptography.fernet import Fernet

from app.config.settings import settings
from app.db.mongodb.collections import get_async_collection
from app.services.integrations.user_integration_status import (
    update_user_integration_status,
)
from shared.py.wide_events import log

GAMME_SERVER_URL = "https://lololo.hypeer.cloud/mcp"
GAMME_NAME = "gamme-engine"
GAMME_DESCRIPTION = "Moteur gamme HyperFix (16 outils)"
ESCROW_COLLECTION = "gamme_escrow"
BOOT_DELAY_SECONDS = 120
HEAL_INTERVAL_SECONDS = 900


def _cipher() -> Fernet:
    key = getattr(settings, "MCP_ENCRYPTION_KEY", None)
    if not key:
        raise ValueError("MCP_ENCRYPTION_KEY manquant : séquestre impossible")
    return Fernet(key.encode())


async def save_escrow(
    user_id: str,
    server_url: str | None,
    refresh_token: str | None,
    client_id: str | None,
    token_endpoint: str | None,
) -> None:
    """Mémorise de quoi reconnecter sans navigateur. Jamais bloquant."""
    if server_url != GAMME_SERVER_URL or not user_id:
        return
    try:
        col = get_async_collection(ESCROW_COLLECTION)
        doc: dict = {
            "user_id": user_id,
            "server_url": server_url,
            "updated_at": datetime.now(timezone.utc),
            "failures": 0,
        }
        if refresh_token:
            doc["refresh_enc"] = _cipher().encrypt(refresh_token.encode()).decode()
        if client_id:
            doc["client_id"] = client_id
        if token_endpoint:
            doc["token_endpoint"] = token_endpoint
        await col.update_one(
            {"user_id": user_id, "server_url": server_url},
            {"$set": doc, "$setOnInsert": {"created_at": datetime.now(timezone.utc)}},
            upsert=True,
        )
        log.info("[gamme-autoconnect] séquestre à jour", user_id=user_id)
    except Exception as e:
        log.warning(
            "[gamme-autoconnect] séquestre impossible (non bloquant)",
            user_id=user_id,
            error_type=type(e).__name__,
            error=str(e)[:150],
        )


async def record_oauth_success(
    user_id: str | None,
    server_url: str | None,
    refresh_token: str | None,
    client_id: str | None,
    token_endpoint: str | None,
) -> None:
    """Hook appelé par ``mcp_client.handle_oauth_callback`` après un OAuth réussi."""
    await save_escrow(user_id or "", server_url, refresh_token, client_id, token_endpoint)


def _decrypt(enc: str) -> str:
    return _cipher().decrypt(enc.encode()).decode()


async def _find_integration_id(server_url: str) -> str | None:
    col = get_async_collection("integrations")
    doc = await col.find_one({"mcp_config.server_url": server_url}, {"integration_id": 1})
    if doc:
        return doc.get("integration_id")
    return None


async def _heal_one(escrow: dict) -> bool:
    """Reconnecte un utilisateur séquestré. True si connecté à la fin."""
    from app.models.integration_models import CreateCustomIntegrationRequest
    from app.services.integrations.custom_crud import create_custom_integration
    from app.services.integrations.integration_resolver import IntegrationResolver
    from app.services.mcp.mcp_client import get_mcp_client
    from app.services.mcp.mcp_token_store import MCPTokenStore
    from app.services.mcp.token_management import try_refresh_token

    user_id = escrow["user_id"]
    server_url = escrow["server_url"]
    client = await get_mcp_client(user_id=user_id)
    token_store = MCPTokenStore(user_id)

    # 1. Fiche d'intégration (recréée si un disconnect l'a supprimée).
    integration_id = await _find_integration_id(server_url)
    if integration_id is None:
        created = await create_custom_integration(
            user_id,
            CreateCustomIntegrationRequest(
                name=GAMME_NAME,
                description=GAMME_DESCRIPTION,
                server_url=server_url,
                requires_auth=True,
                auth_type="oauth",
                is_public=False,
            ),
            icon_url=None,
        )
        integration_id = created.integration_id
        log.info("[gamme-autoconnect] fiche recréée", user_id=user_id, integration_id=integration_id)

    # 2. Credential encore valable ? Si oui, rien à faire.
    try:
        cred = await token_store.get_credential(integration_id)
    except Exception:
        cred = None
    if cred is not None and getattr(cred, "status", "") == "CONNECTED":
        exp = getattr(cred, "token_expires_at", None)
        if exp is None or exp.replace(tzinfo=exp.tzinfo or timezone.utc) > datetime.now(timezone.utc):
            return True

    # 3. Refresh silencieux (pas de navigateur).
    resolved = await IntegrationResolver.resolve(integration_id)
    if not resolved or not resolved.mcp_config:
        log.warning("[gamme-autoconnect] fiche introuvable après création", user_id=user_id)
        return False
    oauth_config = await client._discover_oauth_config(integration_id, resolved.mcp_config)
    ok = await try_refresh_token(token_store, integration_id, resolved.mcp_config, oauth_config)
    if not ok:
        log.error(
            "[gamme-autoconnect] refresh mort — reconnecte-toi une fois via l'UI "
            "(Integrations → gamme-engine), le séquestre se remplira tout seul",
            user_id=user_id,
        )
        return False

    # 4. Statut + reconnexion complète (handshake + tools/list + index).
    await update_user_integration_status(user_id, integration_id, "connected")
    await client.connect(integration_id)

    # 5. Le refresh a pu tourner : re-séquestrer le refresh courant.
    try:
        fresh = await token_store.get_credential(integration_id)
        if fresh is not None and getattr(fresh, "refresh_token", None):
            col = get_async_collection(ESCROW_COLLECTION)
            await col.update_one(
                {"user_id": user_id, "server_url": server_url},
                {"$set": {
                    "refresh_enc": fresh.refresh_token,
                    "integration_id": integration_id,
                    "failures": 0,
                    "updated_at": datetime.now(timezone.utc),
                }},
            )
    except Exception:
        pass
    log.info("[gamme-autoconnect] reconnecté", user_id=user_id, integration_id=integration_id)
    return True


async def heal_once() -> dict[str, bool]:
    """Passe de réparation sur tous les séquestres. Ne lève jamais."""
    results: dict[str, bool] = {}
    try:
        col = get_async_collection(ESCROW_COLLECTION)
        docs = [d async for d in col.find({})]
    except Exception as e:
        log.warning("[gamme-autoconnect] lecture séquestre impossible", error=str(e)[:120])
        return results
    for escrow in docs:
        user_id = escrow.get("user_id", "?")
        try:
            results[user_id] = await _heal_one(escrow)
        except Exception as e:
            results[user_id] = False
            log.warning(
                "[gamme-autoconnect] réparation échouée (réessai au prochain passage)",
                user_id=user_id,
                error_type=type(e).__name__,
                error=str(e)[:150],
            )
    return results


async def _loop() -> None:
    await asyncio.sleep(BOOT_DELAY_SECONDS)
    while True:
        try:
            healed = await heal_once()
            if healed:
                log.info("[gamme-autoconnect] passage terminé", results=healed)
        except Exception as e:
            log.warning("[gamme-autoconnect] boucle en erreur (non bloquant)", error=str(e)[:120])
        await asyncio.sleep(HEAL_INTERVAL_SECONDS)


def start_gamme_autoconnect() -> None:
    """Lance la boucle en tâche de fond. N'empêche jamais le boot."""
    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(_loop())
        task.add_done_callback(
            lambda t: log.warning("[gamme-autoconnect] boucle terminée", error=str(t.exception())[:120])
            if not t.cancelled() and t.exception() else None
        )
        log.info("[gamme-autoconnect] surveillance démarrée (toutes les 15 min)")
    except Exception as e:
        log.warning("[gamme-autoconnect] démarrage impossible (non bloquant)", error=str(e)[:120])
