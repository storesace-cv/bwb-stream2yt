"""Destino YouTube RTMPS: validação, migração legado e armazenamento da chave."""

from __future__ import annotations

import base64
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse

from effective_config import (
    ALLOWED_YT_HOSTS,
    DEFAULT_YT_BASE,
    EffectiveConfig,
    ensure_data_dir,
    key_blob_path,
    load_effective_config,
    save_effective_config,
)

_KEY_RE = re.compile(r"^[A-Za-z0-9_\-]{4,200}$")


class DestinationError(ValueError):
    """Erro de destino (mensagem segura, sem chave)."""


@dataclass(frozen=True)
class ResolvedDestination:
    ingest_base: str
    stream_key: str
    full_url: str
    source: str  # effective | legacy_url | legacy_key | none


def _protect_blob(plain: bytes) -> bytes:
    if os.name == "nt":
        try:
            import win32crypt  # type: ignore

            # CRYPTPROTECT_LOCAL_MACHINE = 0x4
            encrypted = win32crypt.CryptProtectData(
                plain, "stream2yt-stream-key", None, None, None, 0x4
            )
            return encrypted
        except Exception as exc:  # noqa: BLE001
            raise DestinationError(
                f"Falha ao proteger a chave de transmissão: {exc.__class__.__name__}"
            ) from exc
    # Desenvolvimento / testes fora de Windows: ofuscação local (não produção).
    return base64.urlsafe_b64encode(plain)


def _unprotect_blob(blob: bytes) -> bytes:
    if os.name == "nt":
        try:
            import win32crypt  # type: ignore

            _desc, plain = win32crypt.CryptUnprotectData(blob, None, None, None, 0)
            return plain
        except Exception as exc:  # noqa: BLE001
            raise DestinationError(
                "Não foi possível desencriptar a chave de transmissão."
            ) from exc
    try:
        return base64.urlsafe_b64decode(blob)
    except Exception as exc:  # noqa: BLE001
        raise DestinationError(
            "Não foi possível ler a chave de transmissão armazenada."
        ) from exc


def save_stream_key(
    key: str, *, ref: str = "default", data_dir: Optional[Path] = None
) -> Path:
    cleaned = (key or "").strip()
    if not cleaned or not _KEY_RE.match(cleaned):
        raise DestinationError("Chave de transmissão inválida ou vazia.")
    root = ensure_data_dir(data_dir)
    path = key_blob_path(root, ref)
    fd, tmp_name = tempfile.mkstemp(
        prefix=".stream_key.", suffix=".tmp", dir=str(root)
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(_protect_blob(cleaned.encode("utf-8")))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
        try:
            from windows_acl import secure_file

            secure_file(path)
        except Exception:
            pass
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
    return path


def load_stream_key(
    *, ref: str = "default", data_dir: Optional[Path] = None
) -> Optional[str]:
    path = key_blob_path(data_dir, ref)
    if not path.is_file():
        return None
    try:
        plain = _unprotect_blob(path.read_bytes())
    except DestinationError:
        raise
    except OSError as exc:
        raise DestinationError("Ficheiro da chave inacessível.") from exc
    text = plain.decode("utf-8", errors="strict").strip()
    return text or None


def parse_full_rtmps_url(url: str) -> Tuple[str, str]:
    """Devolve (base sem chave, chave)."""

    raw = (url or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme.lower() != "rtmps":
        raise DestinationError("O destino deve usar o esquema rtmps.")
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_YT_HOSTS and not host.endswith(".rtmps.youtube.com"):
        raise DestinationError("Host de ingestão YouTube não autorizado.")
    path = (parsed.path or "").rstrip("/")
    if not path:
        raise DestinationError("URL de ingestão incompleta.")
    parts = [p for p in path.split("/") if p]
    if len(parts) < 2:
        raise DestinationError("URL de ingestão sem chave.")
    key = parts[-1]
    base_path = "/" + "/".join(parts[:-1])
    base = f"rtmps://{host}{base_path}"
    if not _KEY_RE.match(key):
        raise DestinationError("Chave de transmissão inválida na URL.")
    return base, key


def validate_ingest_base(base: str) -> str:
    raw = (base or "").strip().rstrip("/")
    parsed = urlparse(raw)
    if parsed.scheme.lower() != "rtmps":
        raise DestinationError("A URL base deve usar o esquema rtmps.")
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_YT_HOSTS and not host.endswith(".rtmps.youtube.com"):
        raise DestinationError("Host de ingestão YouTube não autorizado.")
    if not parsed.path or parsed.path == "/":
        raise DestinationError("URL base de ingestão incompleta.")
    return f"rtmps://{host}{parsed.path.rstrip('/')}"


def build_full_url(base: str, key: str) -> str:
    b = validate_ingest_base(base)
    k = (key or "").strip()
    if not k or not _KEY_RE.match(k):
        raise DestinationError("Chave de transmissão inválida ou vazia.")
    return f"{b}/{k}"


def migrate_from_legacy_env(
    *, data_dir: Optional[Path] = None, force: bool = False
) -> Optional[EffectiveConfig]:
    """Importa YT_URL / YT_KEY para config efectiva se ainda não existir destino app."""

    root = ensure_data_dir(data_dir)
    cfg = load_effective_config(root)
    has_key = load_stream_key(ref=cfg.stream_key_ref, data_dir=root) is not None
    if has_key and not force:
        return cfg

    yt_url = os.environ.get("YT_URL", "").strip()
    yt_key = os.environ.get("YT_KEY", "").strip()
    if yt_url:
        # YT_URL válido tem precedência sobre construir com YT_KEY.
        base, key = parse_full_rtmps_url(yt_url)
        save_stream_key(key, ref=cfg.stream_key_ref, data_dir=root)
        cfg.yt_ingest_base = base
        save_effective_config(cfg, root)
        return cfg
    if yt_key:
        base = DEFAULT_YT_BASE
        save_stream_key(yt_key, ref=cfg.stream_key_ref, data_dir=root)
        cfg.yt_ingest_base = base
        save_effective_config(cfg, root)
        return cfg
    return cfg


def resolve_destination(
    *,
    data_dir: Optional[Path] = None,
    allow_legacy_fallback: bool = True,
) -> ResolvedDestination:
    """Resolve destino partilhado.

    Config efectiva inválida → DestinationError (sem cair em legado).
    Sem config/chave app → migra/usa legado se allow_legacy_fallback.
    """

    root = ensure_data_dir(data_dir)
    try:
        cfg = load_effective_config(root)
    except ValueError as exc:
        raise DestinationError(str(exc)) from exc

    # Validar base guardada (se não for default vazio).
    try:
        base = validate_ingest_base(cfg.yt_ingest_base or DEFAULT_YT_BASE)
    except DestinationError:
        # Base guardada inválida: erro explícito, sem legado silencioso.
        raise DestinationError(
            "URL base de ingestão guardada é inválida. Corrija nas definições."
        )

    key = load_stream_key(ref=cfg.stream_key_ref, data_dir=root)
    if key:
        full = build_full_url(base, key)
        return ResolvedDestination(
            ingest_base=base, stream_key=key, full_url=full, source="effective"
        )

    if not allow_legacy_fallback:
        raise DestinationError("Chave de transmissão não configurada.")

    # Migração / legado: YT_URL primeiro, depois YT_KEY.
    yt_url = os.environ.get("YT_URL", "").strip()
    yt_key = os.environ.get("YT_KEY", "").strip()
    if yt_url:
        legacy_base, legacy_key = parse_full_rtmps_url(yt_url)
        save_stream_key(legacy_key, ref=cfg.stream_key_ref, data_dir=root)
        cfg.yt_ingest_base = legacy_base
        save_effective_config(cfg, root)
        return ResolvedDestination(
            ingest_base=legacy_base,
            stream_key=legacy_key,
            full_url=build_full_url(legacy_base, legacy_key),
            source="legacy_url",
        )
    if yt_key:
        save_stream_key(yt_key, ref=cfg.stream_key_ref, data_dir=root)
        cfg.yt_ingest_base = DEFAULT_YT_BASE
        save_effective_config(cfg, root)
        return ResolvedDestination(
            ingest_base=DEFAULT_YT_BASE,
            stream_key=yt_key,
            full_url=build_full_url(DEFAULT_YT_BASE, yt_key),
            source="legacy_key",
        )

    raise DestinationError(
        "Destino YouTube não configurado. Defina a URL/chave nas definições."
    )


def redact_secrets(text: str, key: Optional[str] = None) -> str:
    out = text or ""
    if key:
        out = out.replace(key, "***")
    out = re.sub(
        r"(rtmps://[^\s/]+/live2/)[A-Za-z0-9_\-]{4,}",
        r"\1***",
        out,
        flags=re.IGNORECASE,
    )
    return out
