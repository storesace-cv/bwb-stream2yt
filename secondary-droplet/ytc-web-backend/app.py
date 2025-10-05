"""FastAPI app exposing the /api/live-status endpoint for the secondary droplet.

This module reuses the logic from the legacy yt_api_probe_once.py helper to query
YouTube's LiveBroadcasts and LiveStreams API endpoints, applying an in-memory cache
to respect API quotas.
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube",
]
DEFAULT_CACHE_TTL = 30

app = FastAPI(title="YTC Web Backend", version="1.0.0")

_logger = logging.getLogger("ytc-web-backend")
if not _logger.handlers:
    logging.basicConfig(level=logging.INFO)

_cache_lock = threading.Lock()
_cache: Dict[str, Any] = {"expires_at": None, "value": None}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _isoformat(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _token_path() -> str:
    token_path = os.getenv("YT_OAUTH_TOKEN_PATH")
    if not token_path:
        raise RuntimeError("YT_OAUTH_TOKEN_PATH não definido nas variáveis de ambiente.")
    return token_path


def _cache_ttl_seconds() -> int:
    raw = os.getenv("YTC_WEB_BACKEND_CACHE_TTL_SECONDS", str(DEFAULT_CACHE_TTL))
    try:
        value = int(raw)
    except ValueError as exc:  # pragma: no cover - defensive
        raise RuntimeError("Valor inválido para YTC_WEB_BACKEND_CACHE_TTL_SECONDS.") from exc
    return max(value, 0)


def _fetch_from_api() -> Dict[str, Any]:
    token_path = _token_path()
    creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)

    broadcast_response = (
        yt.liveBroadcasts()
        .list(part="id,contentDetails,status,snippet", mine=True, maxResults=5)
        .execute()
    )
    broadcasts = broadcast_response.get("items", [])
    live_broadcast = next(
        (
            item
            for item in broadcasts
            if item.get("status", {}).get("lifeCycleStatus") in {"live", "testing", "ready"}
        ),
        None,
    )

    updated_at = _isoformat(_now())

    if not live_broadcast:
        return {
            "status": "offline",
            "message": "Nenhuma transmissão ao vivo detectada pela API.",
            "updatedAt": updated_at,
        }

    lifecycle_status = live_broadcast.get("status", {}).get("lifeCycleStatus")
    aggregated_status = "live"
    if lifecycle_status in {"testing", "ready"}:
        aggregated_status = "starting"
    elif lifecycle_status not in {"live", "testing", "ready"}:
        aggregated_status = "offline"

    stream_id = live_broadcast.get("contentDetails", {}).get("boundStreamId")
    stream_status: Dict[str, Optional[str]] = {}
    if stream_id:
        stream_response = (
            yt.liveStreams().list(part="id,status,cdn", id=stream_id, maxResults=1).execute()
        )
        stream_items = stream_response.get("items", [])
        if stream_items:
            stream = stream_items[0]
            health = stream.get("status", {}).get("healthStatus", {})
            stream_status = {
                "streamStatus": stream.get("status", {}).get("streamStatus"),
                "healthStatus": health.get("status"),
            }

    snippet = live_broadcast.get("snippet", {})
    result: Dict[str, Any] = {
        "status": aggregated_status,
        "videoId": live_broadcast.get("id"),
        "title": snippet.get("title"),
        "scheduledStartTime": snippet.get("scheduledStartTime"),
        "actualStartTime": snippet.get("actualStartTime"),
        "health": stream_status or None,
        "updatedAt": updated_at,
    }
    if aggregated_status != "live":
        result.setdefault("message", "Transmissão preparada, aguardando início.")
    return result


def fetch_live_status(*, force_refresh: bool = False) -> Dict[str, Any]:
    """Fetch live status, optionally bypassing the cache."""
    ttl = _cache_ttl_seconds()
    if not force_refresh:
        with _cache_lock:
            expires_at: Optional[datetime] = _cache.get("expires_at")
            if expires_at and expires_at > _now():
                return _cache["value"]

    try:
        result = _fetch_from_api()
    except HttpError as exc:
        _logger.exception("Erro ao consultar API do YouTube: %s", exc)
        result = {
            "status": "unknown",
            "message": "Falha ao consultar API do YouTube.",
            "updatedAt": _isoformat(_now()),
        }
    except Exception as exc:  # pragma: no cover - proteção adicional
        _logger.exception("Erro inesperado ao obter status: %s", exc)
        raise

    with _cache_lock:
        _cache["value"] = result
        _cache["expires_at"] = _now() + timedelta(seconds=ttl)
    return result


@app.get("/api/live-status")
def get_live_status(force_refresh: bool = False) -> Dict[str, Any]:
    """Return the cached live status."""
    try:
        return fetch_live_status(force_refresh=force_refresh)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - unexpected runtime errors
        _logger.exception("Erro crítico no endpoint /api/live-status: %s", exc)
        raise HTTPException(status_code=500, detail="Erro interno ao obter status.") from exc
