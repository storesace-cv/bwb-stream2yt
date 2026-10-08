#!/usr/bin/env python3
"""Download verificado (CI/dev). No cliente usa-se download_deps.ps1 (sem Python)."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

_PLACEHOLDER_RE = re.compile(r"REPLACE_WITH_|YOUR_|TODO_|XXX_|changeme", re.I)


class DownloadError(RuntimeError):
    pass


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DownloadError(f"Manifesto inválido: {exc}") from exc
    if not isinstance(payload, dict) or "components" not in payload:
        raise DownloadError("Manifesto sem componentes.")
    raw = path.read_text(encoding="utf-8")
    if _PLACEHOLDER_RE.search(raw):
        raise DownloadError("Manifesto contém placeholders; release bloqueada.")
    return payload


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_https(url: str, dest: Path, *, expected_sha256: str) -> Path:
    if not url.lower().startswith("https://"):
        raise DownloadError("Apenas HTTPS é permitido.")
    if "/download/latest/" in url.lower():
        raise DownloadError("URL usa canal 'latest' flutuante.")
    expected = (expected_sha256 or "").strip().lower()
    if not expected or _PLACEHOLDER_RE.search(expected) or len(expected) != 64:
        raise DownloadError(
            "SHA256 esperado em falta/ inválido no manifesto; não descarregar."
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".partial")
    context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(url, context=context, timeout=300) as response:
            with tmp.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        if tmp.exists():
            tmp.unlink(missing_ok=True)  # type: ignore[arg-type]
        raise DownloadError(f"Falha no download: {exc.__class__.__name__}") from exc

    actual = sha256_file(tmp)
    if actual != expected:
        tmp.unlink(missing_ok=True)  # type: ignore[arg-type]
        raise DownloadError(
            f"Hash SHA256 não coincide (esperado {expected[:12]}…, obtido {actual[:12]}…)."
        )
    tmp.replace(dest)
    return dest


def ensure_component(
    manifest: dict[str, Any],
    name: str,
    *,
    cache_dir: Path,
    force: bool = False,
) -> Path:
    components = manifest["components"]
    if name not in components:
        raise DownloadError(f"Componente desconhecido: {name}")
    comp = components[name]
    if comp.get("bundled_with_app"):
        raise DownloadError(f"Componente {name} é empacotado com a app.")
    cache_name = comp.get("offline_cache_name") or f"{name}.bin"
    dest = cache_dir / cache_name
    expected = str(comp.get("sha256") or "").strip().lower()
    if dest.is_file() and not force:
        if expected and not _PLACEHOLDER_RE.search(expected):
            actual = sha256_file(dest)
            if actual == expected:
                return dest
            raise DownloadError(
                f"Cache inválida para {name} (hash). Apague ou use --force."
            )
        raise DownloadError(f"Cache presente mas SHA256 do manifesto inválido ({name}).")
    return download_https(
        str(comp["url"]), dest, expected_sha256=str(comp.get("sha256") or "")
    )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Download verificado de deps BWB")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(__file__).with_name("deps_manifest.json"),
    )
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument(
        "--component",
        action="append",
        dest="components",
        help="ffmpeg | gstreamer_runtime (repetível)",
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    try:
        manifest = load_manifest(args.manifest)
        names = args.components or ["ffmpeg", "gstreamer_runtime"]
        for name in names:
            path = ensure_component(
                manifest, name, cache_dir=args.cache_dir, force=args.force
            )
            print(f"OK {name}: {path}")
    except DownloadError as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        print(
            "Pode repetir a operação após corrigir rede/manifesto/cache.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
