#!/usr/bin/env python3
"""Falhar o build se o manifesto tiver placeholders ou SHA256 inválidos."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

_PLACEHOLDER_RE = re.compile(r"REPLACE_WITH_|YOUR_|TODO_|XXX_|changeme", re.I)
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def _walk(obj: Any, path: str = "") -> list[str]:
    errors: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            errors.extend(_walk(value, f"{path}.{key}" if path else key))
    elif isinstance(obj, list):
        for idx, value in enumerate(obj):
            errors.extend(_walk(value, f"{path}[{idx}]"))
    elif isinstance(obj, str):
        if _PLACEHOLDER_RE.search(obj):
            errors.append(f"{path}: placeholder '{obj[:48]}'")
        if path.endswith("sha256") or path.endswith(".sha256"):
            if not _SHA_RE.match(obj.strip().lower()):
                errors.append(f"{path}: SHA256 inválido")
        if path.endswith("url") and obj and not obj.lower().startswith("https://"):
            errors.append(f"{path}: URL deve ser HTTPS")
        if "latest" in obj.lower() and path.endswith("url"):
            # Permitir apenas se o path do URL não usar o tag flutuante /latest/
            if "/download/latest/" in obj.lower() or obj.rstrip("/").endswith(
                "/latest"
            ):
                errors.append(f"{path}: URL usa tag/canal 'latest' flutuante")
    return errors


def validate(manifest_path: Path) -> list[str]:
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"manifesto ilegível: {exc}"]
    if not isinstance(payload, dict):
        return ["manifesto não é um objeto JSON"]
    errors = _walk(payload)
    components = payload.get("components") or {}
    for name in ("ffmpeg", "gstreamer_runtime"):
        if name not in components:
            errors.append(f"componente obrigatório ausente: {name}")
            continue
        comp = components[name]
        if comp.get("bundled_with_app"):
            continue
        for field in ("url", "sha256", "version"):
            if not comp.get(field):
                errors.append(f"{name}.{field} em falta")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(__file__).with_name("deps_manifest.json"),
    )
    args = parser.parse_args(argv)
    errors = validate(args.manifest)
    if errors:
        print("ERRO: manifesto inválido para release:", file=sys.stderr)
        for item in errors:
            print(f"  - {item}", file=sys.stderr)
        return 1
    print(f"Manifesto OK: {args.manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
