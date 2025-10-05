"""Microserviço FastAPI que expõe o estado actual do canal YouTube."""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import FastAPI, Response
from fastapi.responses import JSONResponse
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger("ytc_web_backend")
logging.basicConfig(level=logging.INFO)

SCOPES = (
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube",
)

def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        logger.warning("Variável %s com valor inválido '%s'; usando %s", name, value, default)
        return default
    return parsed

TOKEN_PATH = os.getenv("YT_OAUTH_TOKEN_PATH", "/root/token.json")
CACHE_TTL_SECONDS = max(5, _env_int("YTC_WEB_CACHE_TTL", 30))
HTTP_CACHE_SECONDS = max(0, _env_int("YTC_WEB_HTTP_CACHE", 10))

app = FastAPI()

_cache: Dict[str, Any] = {"expires": 0.0, "payload": None}

def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _status_from_lifecycle(lifecycle: Optional[str]) -> str:
    if lifecycle in {"live"}:
        return "live"
    if lifecycle in {"testing", "ready"}:
        return "starting"
    if lifecycle:
        return "offline"
    return "unknown"


def _build_payload() -> Dict[str, Any]:
    logger.info("Consultando API do YouTube para estado do canal")
    creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)

    broadcasts = (
        yt.liveBroadcasts()
        .list(
            part="id,snippet,contentDetails,status",
            mine=True,
            maxResults=5,
        )
        .execute()
    )
    items = broadcasts.get("items", [])

    target = next(
        (
            it
            for it in items
            if it.get("status", {}).get("lifeCycleStatus") in {"live", "testing", "ready"}
        ),
        None,
    )

    payload: Dict[str, Any] = {"status": "offline", "updatedAt": _iso_now()}

    if not target:
        payload["message"] = "Transmissão indisponível. Voltamos já."
        return payload

    lifecycle = target.get("status", {}).get("lifeCycleStatus")
    payload["status"] = _status_from_lifecycle(lifecycle)
    payload["videoId"] = target.get("id")

    snippet = target.get("snippet", {})
    if title := snippet.get("title"):
        payload["title"] = title
    if scheduled := snippet.get("scheduledStartTime"):
        payload["scheduledStartTime"] = scheduled
    if actual := snippet.get("actualStartTime"):
        payload["actualStartTime"] = actual

    stream_id = target.get("contentDetails", {}).get("boundStreamId")
    if stream_id:
        streams = (
            yt.liveStreams()
            .list(part="id,status,cdn", id=stream_id)
            .execute()
        )
        stream_items = streams.get("items", [])
        if stream_items:
            stream = stream_items[0]
            status = stream.get("status", {})
            health = status.get("healthStatus", {})
            health_payload = {
                "streamStatus": status.get("streamStatus"),
                "healthStatus": health.get("status"),
            }
            if any(health_payload.values()):
                payload["health"] = health_payload

    if payload["status"] != "live" and "message" not in payload:
        payload["message"] = "Transmissão prestes a iniciar ou temporariamente offline."

    return payload


def fetch_live_status(force: bool = False) -> Dict[str, Any]:
    now = time.monotonic()
    if not force and _cache["payload"] is not None and now < _cache["expires"]:
        return _cache["payload"]

    try:
        payload = _build_payload()
    except HttpError as exc:
        logger.exception("Erro na API do YouTube: %s", exc)
        payload = {
            "status": "unknown",
            "message": "Não foi possível contactar a API do YouTube.",
            "updatedAt": _iso_now(),
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("Falha inesperada ao consultar stream: %s", exc)
        payload = {
            "status": "unknown",
            "message": "Erro inesperado ao obter estado da transmissão.",
            "updatedAt": _iso_now(),
        }

    _cache["payload"] = payload
    _cache["expires"] = now + CACHE_TTL_SECONDS
    return payload


@app.get("/api/live-status")
async def live_status() -> Response:
    payload = fetch_live_status()
    headers = {"Cache-Control": f"public, max-age={HTTP_CACHE_SECONDS}"}
    return JSONResponse(payload, headers=headers)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app:app",
        host=os.getenv("YTC_WEB_BACKEND_HOST", "127.0.0.1"),
        port=int(os.getenv("YTC_WEB_BACKEND_PORT", "8081")),
        reload=False,
    )
