#!/usr/bin/env python3
"""Collect diagnostic information for the secondary streaming stack."""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import subprocess
from pathlib import Path
from typing import List, Mapping, Optional, Sequence, Tuple


DEFAULT_SERVICES: Tuple[str, ...] = (
    "ytc-web-backend.service",
    "yt-restapi.service",
    "youtube-fallback.service",
)

DEFAULT_COMMANDS: Tuple[Sequence[str], ...] = (
    ("uname", "-a"),
    ("lsb_release", "-a"),
    ("uptime",),
    ("who", "-b"),
    ("df", "-h"),
    ("free", "-h"),
    ("python3", "--version"),
    ("ffmpeg", "-version"),
    ("pgrep", "-af", "ffmpeg"),
    ("ss", "-tulpn"),
)

SERVICE_LOG_LINES = 200
SERVICE_STATUS_ARGS = ("systemctl", "status", "--no-pager")
SERVICE_JOURNAL_ARGS = ("journalctl", "-o", "short-iso", "--no-pager")
DEFAULT_LOG_PATH = Path("/root/bwb_services.log")
DEFAULT_PROGRESS_PATH = Path("/run/youtube-fallback.progress")
DEFAULT_ENV_PATH = Path("/etc/youtube-fallback.env")
DEFAULT_CONFIG_PATH = Path("/usr/local/config/youtube-fallback.defaults")
DEFAULT_HISTORY_DIR = Path(__file__).resolve().parent / "history"
DEFAULT_REPO_ROOT = Path(__file__).resolve().parent.parent

MASK_RE = re.compile(r'(?P<prefix>YT_KEY\s*=\s*")(?P<secret>[^"]+)(?P<suffix>")')


class CommandResult:
    """Represent the output of a command execution."""

    def __init__(self, args: Sequence[str], returncode: int, stdout: str, stderr: str):
        self.args = tuple(args)
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

    def format(self) -> str:
        header = f"$ {' '.join(self.args)}\n(returncode={self.returncode})"
        body_parts = []
        if self.stdout:
            body_parts.append("stdout:\n" + self.stdout)
        if self.stderr:
            body_parts.append("stderr:\n" + self.stderr)
        if not body_parts:
            body_parts.append("(no output)")
        return header + "\n" + "\n".join(body_parts)


def run_command(args: Sequence[str]) -> CommandResult:
    """Execute *args* collecting stdout/stderr without raising."""

    try:
        completed = subprocess.run(
            args,
            check=False,
            text=True,
            capture_output=True,
        )
    except FileNotFoundError:
        return CommandResult(args, 127, "", "comando não encontrado")
    except Exception as exc:  # noqa: BLE001 - include unexpected exceptions
        return CommandResult(args, 1, "", f"falha inesperada: {exc}")
    return CommandResult(args, completed.returncode, completed.stdout.strip(), completed.stderr.strip())


def ensure_history_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def build_output_path(history_dir: Path, label: Optional[str] = None) -> Path:
    timestamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d-%H%M%SZ")
    suffix = f"-{label}" if label else ""
    return history_dir / f"diagnostics{suffix}-{timestamp}.txt"


def mask_secret(text: str) -> str:
    if not text:
        return text

    def _replace(match: re.Match[str]) -> str:
        prefix = match.group("prefix")
        secret = match.group("secret")
        suffix = match.group("suffix")
        if len(secret) <= 4:
            masked = "***"
        else:
            masked = secret[:2] + "***" + secret[-2:]
        return prefix + masked + suffix

    return MASK_RE.sub(_replace, text)


def load_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return f"<ficheiro não encontrado: {path}>"
    except Exception as exc:  # noqa: BLE001
        return f"<erro ao ler {path}: {exc}>"


def gather_service_status(service: str) -> List[CommandResult]:
    status = run_command((*SERVICE_STATUS_ARGS, service))
    journal = run_command((*SERVICE_JOURNAL_ARGS, "-u", service, "-n", str(SERVICE_LOG_LINES)))
    return [status, journal]


def gather_environment_info(paths: Mapping[str, Path]) -> List[str]:
    sections: List[str] = []

    env_content = mask_secret(load_file(paths["env"]))
    sections.append(f"--- {paths['env']} ---\n{env_content}".rstrip())

    defaults_content = load_file(paths["defaults"])
    sections.append(f"--- {paths['defaults']} ---\n{defaults_content}".rstrip())

    progress_content = load_file(paths["progress"]) if paths["progress"].exists() else "<sem progresso disponível>"
    sections.append(f"--- {paths['progress']} ---\n{progress_content}".rstrip())

    if paths["log"].exists():
        tail_result = run_command(("tail", "-n", "200", str(paths["log"])) )
        sections.append(f"--- tail -n 200 {paths['log']} ---\n{tail_result.stdout or tail_result.stderr}".rstrip())
    else:
        sections.append(f"--- {paths['log']} ---\n<ficheiro não encontrado>")

    return sections


def gather_repo_status(repo_root: Path) -> List[CommandResult]:
    commands = [
        ("git", "-C", str(repo_root), "status", "-sb"),
        ("git", "-C", str(repo_root), "rev-parse", "HEAD"),
        ("git", "-C", str(repo_root), "log", "-1", "--oneline"),
    ]
    return [run_command(cmd) for cmd in commands]


def gather_diagnostics(args: argparse.Namespace) -> str:
    lines: List[str] = []
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    lines.append(f"Diagnóstico gerado em: {now}")
    lines.append(f"Host: {os.uname().nodename}")
    lines.append("")

    lines.append("== Informações de sistema ==")
    for cmd in args.commands:
        result = run_command(cmd)
        lines.append(result.format())
        lines.append("")

    lines.append("== Serviços principais ==")
    for service in args.services:
        lines.append(f"-- {service} --")
        for result in gather_service_status(service):
            lines.append(result.format())
            lines.append("")

    lines.append("== Ambiente e ficheiros relevantes ==")
    env_sections = gather_environment_info(
        {
            "env": args.env_path,
            "defaults": args.defaults_path,
            "progress": args.progress_path,
            "log": args.log_path,
        }
    )
    lines.extend(section + "\n" for section in env_sections)

    lines.append("== Repositório de configuração ==")
    for result in gather_repo_status(args.repo_root):
        lines.append(result.format())
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--history-dir",
        type=Path,
        default=DEFAULT_HISTORY_DIR,
        help="Directório onde o ficheiro de diagnóstico será escrito.",
    )
    parser.add_argument(
        "--label",
        help="Etiqueta adicional para o nome do ficheiro (ex: 'pre-deploy').",
    )
    parser.add_argument(
        "--services",
        nargs="*",
        default=list(DEFAULT_SERVICES),
        help="Lista de unidades systemd a inspecionar.",
    )
    parser.add_argument(
        "--commands",
        nargs="*",
        default=[list(cmd) for cmd in DEFAULT_COMMANDS],
        help="Comandos extra para executar (usar sintaxe JSON).",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=DEFAULT_REPO_ROOT,
        help="Directório raiz do repositório synchronizado.",
    )
    parser.add_argument(
        "--log-path",
        type=Path,
        default=DEFAULT_LOG_PATH,
        help="Ficheiro de log partilhado entre os serviços.",
    )
    parser.add_argument(
        "--progress-path",
        type=Path,
        default=DEFAULT_PROGRESS_PATH,
        help="Ficheiro de progresso do ffmpeg (se existir).",
    )
    parser.add_argument(
        "--env-path",
        type=Path,
        default=DEFAULT_ENV_PATH,
        help="Ficheiro de configuração com credenciais do fallback.",
    )
    parser.add_argument(
        "--defaults-path",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="Ficheiro de defaults do fallback.",
    )
    parsed = parser.parse_args(argv)

    parsed.commands = [
        cmd if isinstance(cmd, (list, tuple)) else json.loads(cmd)
        for cmd in parsed.commands
    ]
    parsed.services = list(dict.fromkeys(parsed.services))
    return parsed


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    ensure_history_dir(args.history_dir)
    output_path = build_output_path(args.history_dir, args.label)
    content = gather_diagnostics(args)
    output_path.write_text(content, encoding="utf-8")
    print(f"[diags] Ficheiro gerado: {output_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
