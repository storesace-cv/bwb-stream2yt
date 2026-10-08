#!/usr/bin/env python3
"""Checks locais pós-instalação. Não declara sucesso se falharem deps."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional


def _run_version(exe: Path) -> tuple[bool, str]:
    if not exe.is_file():
        return False, f"Ausente: {exe}"
    try:
        completed = subprocess.run(
            [str(exe), "-version"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"{exe.name}: {exc.__class__.__name__}"
    ok = completed.returncode == 0
    # Nunca incluir possíveis segredos; só a primeira linha da versão.
    line = (completed.stdout or completed.stderr or "").splitlines()
    summary = line[0] if line else f"exit={completed.returncode}"
    return ok, summary


def verify_ffmpeg(bin_dir: Path) -> dict[str, Any]:
    ffmpeg = bin_dir / "ffmpeg" / "bin" / "ffmpeg.exe"
    ffprobe = bin_dir / "ffmpeg" / "bin" / "ffprobe.exe"
    ok_ff, msg_ff = _run_version(ffmpeg)
    ok_fp, msg_fp = _run_version(ffprobe)
    return {
        "ok": ok_ff and ok_fp,
        "ffmpeg": msg_ff,
        "ffprobe": msg_fp,
    }


def verify_gstreamer(bin_dir: Path, helper: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": False, "helper": None, "prove": None}
    if not helper.is_file():
        # Fallback ao .py empacotado junto da app
        helper_py = Path(__file__).resolve().parents[2] / "src" / "gst_rtmps_helper.py"
        if helper_py.is_file():
            cmd = [sys.executable, str(helper_py), "--prove"]
        else:
            result["helper"] = "auxiliar ausente"
            return result
    else:
        cmd = [str(helper), "--prove"]

    env = os.environ.copy()
    gst_bin = bin_dir / "gstreamer" / "bin"
    if gst_bin.is_dir():
        env["PATH"] = str(gst_bin) + os.pathsep + env.get("PATH", "")
        plugin = bin_dir / "gstreamer" / "lib" / "gstreamer-1.0"
        if plugin.is_dir():
            env["GST_PLUGIN_PATH"] = str(plugin)

    try:
        completed = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60, env=env, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        result["helper"] = exc.__class__.__name__
        return result

    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        result["prove"] = (completed.stdout or completed.stderr or "")[:200]
        return result
    result["prove"] = {
        "bindings": payload.get("bindings"),
        "missing_elements": payload.get("missing_elements"),
        "error": payload.get("error"),
    }
    result["ok"] = bool(payload.get("ok"))
    return result


def verify_data_access(data_dir: Path) -> dict[str, Any]:
    """Confirma leitura da config/chave sem expor segredos."""

    config = data_dir / "effective_config.json"
    keys = list(data_dir.glob("stream_key_*.dpapi"))
    readable_config = config.is_file()
    key_present = bool(keys)
    key_readable = False
    if key_present:
        try:
            _ = keys[0].read_bytes()[:4]
            key_readable = True
        except OSError:
            key_readable = False
    return {
        "ok": True,  # ausência de chave no install fresco é OK
        "config_present": readable_config,
        "key_present": key_present,
        "key_readable": key_readable if key_present else None,
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bin-dir", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--require-gstreamer", action="store_true")
    args = parser.parse_args(argv)

    report: dict[str, Any] = {}
    report["ffmpeg"] = verify_ffmpeg(args.bin_dir)
    report["data"] = verify_data_access(args.data_dir)
    helper = args.bin_dir / "gst_rtmps_helper.exe"
    report["gstreamer"] = verify_gstreamer(args.bin_dir, helper)

    ok = bool(report["ffmpeg"]["ok"]) and bool(report["data"]["ok"])
    if args.require_gstreamer:
        ok = ok and bool(report["gstreamer"]["ok"])

    print(json.dumps({"ok": ok, "checks": report}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
