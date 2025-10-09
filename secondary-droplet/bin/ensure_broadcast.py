#!/usr/bin/env python3
"""Ensure a YouTube broadcast is ready and bound to an ingest stream."""
from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Sequence

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES: Sequence[str] = (
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube",
)
TOKEN_PATH = os.getenv("YT_OAUTH_TOKEN_PATH", "/root/token.json")


logger = logging.getLogger("ensure")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[ensure] %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)


class EnsureBroadcastError(RuntimeError):
    """Raised when the broadcast could not be validated."""


@dataclass
class BroadcastCandidate:
    """Holder for broadcast data that we care about."""

    raw: Dict[str, Any]

    @property
    def broadcast_id(self) -> str:
        return self.raw.get("id", "")

    @property
    def lifecycle(self) -> str:
        return self.raw.get("status", {}).get("lifeCycleStatus", "")

    @property
    def bound_stream_id(self) -> str:
        return self.raw.get("contentDetails", {}).get("boundStreamId", "")


def build_api(token_path: str = TOKEN_PATH):
    """Return a YouTube Data API client."""

    creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def _fetch_with_status(yt: Any, status: str) -> List[Dict[str, Any]]:
    """Fetch broadcasts for a single status value."""

    response = (
        yt.liveBroadcasts()
        .list(
            part="id,snippet,contentDetails,status",
            mine=True,
            broadcastStatus=status,
            maxResults=25,
        )
        .execute()
    )
    return list(response.get("items", []))


def load_candidates(yt: Any) -> List[BroadcastCandidate]:
    """Load active and upcoming broadcasts from the API."""

    candidates: List[Dict[str, Any]] = []
    for status in ("active", "upcoming"):
        candidates.extend(_fetch_with_status(yt, status))

    return [BroadcastCandidate(raw=item) for item in candidates]


def _candidate_priority(candidate: BroadcastCandidate) -> int:
    order = {
        "live": 0,
        "testing": 1,
        "ready": 2,
        "created": 3,
        "scheduled": 4,
    }
    return order.get(candidate.lifecycle, 99)


def choose_candidate(candidates: Iterable[BroadcastCandidate]) -> BroadcastCandidate:
    """Pick the most relevant broadcast from the list."""

    try:
        return min(candidates, key=_candidate_priority)
    except ValueError as exc:  # no candidates
        raise EnsureBroadcastError(
            "Nenhuma transmissão active/upcoming encontrada."
        ) from exc


def ensure_stream_bound(yt: Any, candidate: BroadcastCandidate) -> Dict[str, Any]:
    """Check that the broadcast is bound to an existing stream."""

    stream_id = candidate.bound_stream_id
    if not stream_id:
        raise EnsureBroadcastError(
            f"Transmissão {candidate.broadcast_id or '<sem id>'} sem stream associado."
        )

    response = yt.liveStreams().list(part="id,status,cdn", id=stream_id).execute()
    items = response.get("items", [])
    if not items:
        raise EnsureBroadcastError(
            f"Stream associado {stream_id} não encontrado na API."
        )

    return items[0]


def describe_success(candidate: BroadcastCandidate, stream: Dict[str, Any]) -> str:
    lifecycle = candidate.lifecycle or "desconhecido"
    stream_status = stream.get("status", {}).get("streamStatus", "?")
    return "Transmissão %s (%s) com stream %s (%s)." % (
        candidate.broadcast_id or "<sem id>",
        lifecycle,
        candidate.bound_stream_id or "<sem stream>",
        stream_status,
    )


def main() -> int:
    try:
        yt = build_api()
        candidates = load_candidates(yt)
        candidate = choose_candidate(candidates)
        stream = ensure_stream_bound(yt, candidate)
        logger.info(describe_success(candidate, stream))
        return 0
    except EnsureBroadcastError as exc:
        logger.error(str(exc))
        return 1
    except HttpError as exc:
        logger.error("Erro na API do YouTube: %s", exc)
        return 2
    except Exception as exc:  # noqa: BLE001
        logger.exception("ERRO inesperado: %s", exc)
        return 3


if __name__ == "__main__":
    sys.exit(main())
