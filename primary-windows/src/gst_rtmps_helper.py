"""Auxiliar GStreamer: prova de runtime + envio por gst-launch-1.0.

Não depende de bindings Python (gi/PyGObject) no cliente.
O runtime GStreamer (gst-launch/gst-inspect) é fornecido pelo instalador.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional, Sequence


REQUIRED_ELEMENTS = (
    "rtspsrc",
    "rtph264depay",
    "h264parse",
    "flvmux",
    "rtmpsink",
    "qtdemux",
    "aacparse",
    "audioconvert",
    "audiotestsrc",
)

# Elementos/plugins relevantes para TLS/RTMPS (presença ≠ envio real ao YouTube).
TLS_RELATED = ("rtmpsink", "souphttpsrc", "tls")


def _gst_root() -> Path:
    override = os.environ.get("BWB_GST_ROOT", "").strip()
    if override:
        return Path(override)
    bin_override = os.environ.get("BWB_SHARED_BIN_DIR", "").strip()
    if bin_override:
        return Path(bin_override) / "gstreamer"
    if os.name == "nt":
        return Path(r"C:\bwb\apps\youtube\bin\gstreamer")
    return Path.home() / ".bwb-stream2yt" / "bin" / "gstreamer"


def _tool_path(name: str) -> Optional[Path]:
    root = _gst_root()
    candidates = [
        root / "bin" / name,
        root / "bin" / f"{name}.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    found = shutil.which(name) or shutil.which(f"{name}.exe")
    return Path(found) if found else None


def _run(
    cmd: Sequence[str], *, timeout: float = 30.0, env: Optional[dict[str, str]] = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(cmd),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=env,
    )


def _gst_env() -> dict[str, str]:
    env = os.environ.copy()
    root = _gst_root()
    bin_dir = root / "bin"
    if bin_dir.is_dir():
        env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
    for plugin_candidate in (
        root / "lib" / "gstreamer-1.0",
        root / "lib" / "x86_64-linux-gnu" / "gstreamer-1.0",
    ):
        if plugin_candidate.is_dir():
            env["GST_PLUGIN_PATH"] = str(plugin_candidate)
            break
    env.setdefault("GST_PLUGIN_SYSTEM_PATH_1_0", env.get("GST_PLUGIN_PATH", ""))
    return env


def prove_runtime() -> dict[str, Any]:
    """Prova: gst-inspect + elementos + indício TLS. Sem iniciar YouTube."""

    result: dict[str, Any] = {
        "ok": False,
        "bindings": False,
        "launch_tool": False,
        "inspect_tool": False,
        "missing_elements": [],
        "tls_ok": False,
        "error": None,
        "mode": "gst-launch",
    }
    # Bindings Python são opcionais; o caminho suportado é gst-launch.
    try:
        import gi  # type: ignore  # noqa: F401

        result["bindings"] = True
    except Exception:
        result["bindings"] = False

    inspect_tool = _tool_path("gst-inspect-1.0")
    launch_tool = _tool_path("gst-launch-1.0")
    result["inspect_tool"] = bool(inspect_tool)
    result["launch_tool"] = bool(launch_tool)
    if not inspect_tool or not launch_tool:
        result["error"] = (
            "gst-inspect-1.0/gst-launch-1.0 ausentes no runtime empacotado."
        )
        return result

    env = _gst_env()
    missing: list[str] = []
    tls_hits = 0
    try:
        for name in REQUIRED_ELEMENTS:
            completed = _run([str(inspect_tool), name], timeout=20.0, env=env)
            if completed.returncode != 0:
                missing.append(name)
        for name in TLS_RELATED:
            completed = _run([str(inspect_tool), name], timeout=20.0, env=env)
            if completed.returncode == 0:
                tls_hits += 1
            else:
                # Pesquisa por plugin tls*
                listing = _run([str(inspect_tool), name], timeout=20.0, env=env)
                if listing.returncode == 0:
                    tls_hits += 1
    except (OSError, subprocess.TimeoutExpired) as exc:
        result["error"] = f"{exc.__class__.__name__}"
        return result

    result["missing_elements"] = missing
    result["tls_ok"] = tls_hits > 0
    if missing:
        result["error"] = "Elementos em falta: " + ", ".join(missing)
        return result
    if not result["tls_ok"]:
        result["error"] = "Nenhum elemento/plugin TLS/RTMPS detetado via gst-inspect."
        return result
    result["ok"] = True
    return result


def _build_launch_args(
    source_uri: str,
    rtmps_url: str,
    *,
    silent_audio: bool,
    is_file: bool,
) -> list[str]:
    launch = _tool_path("gst-launch-1.0")
    if launch is None:
        raise FileNotFoundError("gst-launch-1.0 ausente")
    # Não registar rtmps_url em logs externos.
    if is_file:
        video = [
            "filesrc",
            f"location={source_uri}",
            "!",
            "qtdemux",
            "name=d",
            "d.video_0",
            "!",
            "queue",
            "!",
            "h264parse",
            "!",
            "queue",
            "!",
            "mux.",
        ]
        if silent_audio:
            audio = [
                "audiotestsrc",
                "is-live=true",
                "wave=silence",
                "!",
                "audioconvert",
                "!",
                "avenc_aac",
                "!",
                "aacparse",
                "!",
                "queue",
                "!",
                "mux.",
            ]
        else:
            audio = [
                "d.audio_0",
                "!",
                "queue",
                "!",
                "aacparse",
                "!",
                "queue",
                "!",
                "mux.",
            ]
        rest = [
            "flvmux",
            "name=mux",
            "streamable=true",
            "!",
            "rtmpsink",
            f"location={rtmps_url}",
        ]
        return [str(launch), "-e", *video, *audio, *rest]

    video = [
        "rtspsrc",
        f"location={source_uri}",
        "latency=200",
        "name=src",
        "src.",
        "!",
        "application/x-rtp,media=video,encoding-name=H264",
        "!",
        "queue",
        "!",
        "rtph264depay",
        "!",
        "h264parse",
        "!",
        "queue",
        "!",
        "mux.",
    ]
    if silent_audio:
        audio = [
            "audiotestsrc",
            "is-live=true",
            "wave=silence",
            "!",
            "audioconvert",
            "!",
            "avenc_aac",
            "!",
            "aacparse",
            "!",
            "queue",
            "!",
            "mux.",
        ]
    else:
        audio = [
            "src.",
            "!",
            "application/x-rtp,media=audio",
            "!",
            "queue",
            "!",
            "decodebin",
            "!",
            "audioconvert",
            "!",
            "avenc_aac",
            "!",
            "aacparse",
            "!",
            "queue",
            "!",
            "mux.",
        ]
    rest = [
        "flvmux",
        "name=mux",
        "streamable=true",
        "!",
        "rtmpsink",
        f"location={rtmps_url}",
    ]
    return [str(launch), "-e", *video, *audio, *rest]


def run_pipeline(
    source_uri: str,
    rtmps_url: str,
    *,
    silent_audio: bool = True,
    is_file: bool = False,
) -> int:
    env = _gst_env()
    print("[gst-helper] A iniciar pipeline de cópia H.264 via gst-launch.", flush=True)
    try:
        cmd = _build_launch_args(
            source_uri, rtmps_url, silent_audio=silent_audio, is_file=is_file
        )
    except FileNotFoundError as exc:
        print(f"[gst-helper] {exc}", file=sys.stderr, flush=True)
        return 1
    try:
        completed = subprocess.run(cmd, env=env, check=False)
    except OSError as exc:
        print(f"[gst-helper] Falha: {exc.__class__.__name__}", file=sys.stderr)
        return 1
    return int(completed.returncode)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="BWB GStreamer RTMPS helper")
    parser.add_argument(
        "--prove", action="store_true", help="Prova runtime (sem YouTube)"
    )
    parser.add_argument("--source", default="", help="URI RTSP ou caminho MP4")
    parser.add_argument("--rtmps", default="", help="URL RTMPS (não registada em logs)")
    parser.add_argument("--file", action="store_true", help="Fonte é ficheiro MP4")
    parser.add_argument("--silent-audio", action="store_true", default=True)
    parser.add_argument("--with-source-audio", action="store_true")
    args = parser.parse_args(argv)

    if args.prove:
        result = prove_runtime()
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get("ok") else 2

    if not args.source or not args.rtmps:
        print("Indique --source e --rtmps (ou --prove).", file=sys.stderr)
        return 2

    silent = not args.with_source - audio
    return run_pipeline(
        args.source,
        args.rtmps,
        silent_audio=silent,
        is_file=args.file,
    )


if __name__ == "__main__":
    raise SystemExit(main())
