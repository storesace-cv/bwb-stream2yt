import importlib
import importlib.machinery
import importlib.util
import sys
import types
from pathlib import Path

import pytest


def _ensure_module(name: str, *, package: bool) -> types.ModuleType:
    module = types.ModuleType(name)
    spec = importlib.machinery.ModuleSpec(name, loader=None, is_package=package)
    if package:
        spec.submodule_search_locations = []  # type: ignore[attr-defined]
        module.__path__ = []  # type: ignore[attr-defined]
    module.__spec__ = spec  # type: ignore[attr-defined]
    sys.modules[name] = module
    return module


def _missing_module(name: str) -> bool:
    if name in sys.modules:
        return False
    return importlib.util.find_spec(name) is None


googleapiclient = _ensure_module("googleapiclient", package=True)
discovery = _ensure_module("googleapiclient.discovery", package=False)
errors = _ensure_module("googleapiclient.errors", package=False)


class _DummyHttpError(Exception):
    pass


def _unused_build(*_args, **_kwargs):
    raise NotImplementedError


discovery.build = _unused_build  # type: ignore[attr-defined]
errors.HttpError = _DummyHttpError  # type: ignore[attr-defined]
googleapiclient.discovery = discovery  # type: ignore[attr-defined]
googleapiclient.errors = errors  # type: ignore[attr-defined]


google_module = _ensure_module("google", package=True)
oauth2_module = _ensure_module("google.oauth2", package=True)
credentials_module = _ensure_module("google.oauth2.credentials", package=False)


class _DummyCredentials:
    @classmethod
    def from_authorized_user_file(cls, *_args, **_kwargs):
        raise NotImplementedError


credentials_module.Credentials = _DummyCredentials  # type: ignore[attr-defined]
google_module.oauth2 = oauth2_module  # type: ignore[attr-defined]
oauth2_module.credentials = credentials_module  # type: ignore[attr-defined]

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "secondary-droplet"
    / "bin"
    / "ensure_broadcast.py"
)
SPEC = importlib.util.spec_from_file_location("ensure_broadcast_test", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules["ensure_broadcast_test"] = module
SPEC.loader.exec_module(module)


class DummyRequest:
    def __init__(self, payload):
        self._payload = payload

    def execute(self):
        return self._payload


class DummyLiveBroadcasts:
    def __init__(self, payloads):
        self.payloads = payloads
        self.calls = []

    def list(self, **kwargs):
        self.calls.append(kwargs)
        status = kwargs["broadcastStatus"]
        payload = self.payloads.get(status, {"items": []})
        return DummyRequest(payload)


class DummyLiveStreams:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def list(self, **kwargs):
        self.calls.append(kwargs)
        return DummyRequest(self.payload)


class DummyYouTube:
    def __init__(self, broadcasts, streams):
        self._broadcasts = broadcasts
        self._streams = streams

    def liveBroadcasts(self):
        return self._broadcasts

    def liveStreams(self):
        return self._streams


def test_load_candidates_queries_active_and_upcoming():
    payloads = {
        "active": {"items": [{"id": "live", "status": {"lifeCycleStatus": "live"}}]},
        "upcoming": {"items": [{"id": "up", "status": {"lifeCycleStatus": "ready"}}]},
    }
    broadcasts = DummyLiveBroadcasts(payloads)
    yt = DummyYouTube(broadcasts, DummyLiveStreams({"items": []}))

    candidates = module.load_candidates(yt)

    assert [call["broadcastStatus"] for call in broadcasts.calls] == [
        "active",
        "upcoming",
    ]
    assert {candidate.broadcast_id for candidate in candidates} == {"live", "up"}


def test_ensure_stream_bound_requires_stream(monkeypatch):
    candidate = module.BroadcastCandidate(
        {
            "id": "vid1",
            "status": {"lifeCycleStatus": "testing"},
            "contentDetails": {"boundStreamId": "stream1"},
        }
    )

    streams = DummyLiveStreams(
        {"items": [{"id": "stream1", "status": {"streamStatus": "active"}}]}
    )
    yt = DummyYouTube(DummyLiveBroadcasts({}), streams)

    result = module.ensure_stream_bound(yt, candidate)

    assert result["id"] == "stream1"
    assert streams.calls[0]["id"] == "stream1"


def test_main_returns_error_when_no_broadcast(monkeypatch):
    empty_payloads = {
        "active": {"items": []},
        "upcoming": {"items": []},
    }
    dummy = DummyYouTube(
        DummyLiveBroadcasts(empty_payloads), DummyLiveStreams({"items": []})
    )
    monkeypatch.setattr(module, "build_api", lambda: dummy)

    exit_code = module.main()

    assert exit_code == 1


def test_main_succeeds_with_valid_candidate(monkeypatch):
    broadcasts = DummyLiveBroadcasts(
        {
            "active": {"items": []},
            "upcoming": {
                "items": [
                    {
                        "id": "vid2",
                        "status": {"lifeCycleStatus": "ready"},
                        "contentDetails": {"boundStreamId": "stream2"},
                    }
                ]
            },
        }
    )
    streams = DummyLiveStreams(
        {"items": [{"id": "stream2", "status": {"streamStatus": "ready"}}]}
    )
    monkeypatch.setattr(module, "build_api", lambda: DummyYouTube(broadcasts, streams))

    exit_code = module.main()

    assert exit_code == 0
