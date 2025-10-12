#!/usr/bin/env python3
"""Collect diagnostic information for the secondary streaming stack."""

from __future__ import annotations

import argparse
import datetime as _dt
import getpass
import os
import pwd
import re
import shlex
import stat as stat_module
import subprocess
import time
from grp import getgrgid
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


DEFAULT_SERVICES: Tuple[str, ...] = (
    "ytc-web-backend.service",
    "yt-restapi.service",
    "youtube-fallback.service",
)

SERVICE_LOG_LINES = 120
SERVICE_STATUS_ARGS = ("systemctl", "status", "--no-pager")
SERVICE_JOURNAL_ARGS = ("journalctl", "-o", "short-iso", "--no-pager")
DEFAULT_LOG_PATH = Path("/root/bwb_services.log")
DEFAULT_PROGRESS_PATH = Path("/run/youtube-fallback.progress")
DEFAULT_ENV_PATH = Path("/etc/youtube-fallback.env")
DEFAULT_HISTORY_DIR = Path(__file__).resolve().parent / "history"
DEFAULT_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EXPECTED_PORT = 8081

MASK_RE = re.compile(r'(?P<prefix>YT_KEY\s*=\s*")(?P<secret>[^"]+)(?P<suffix>")')
ERROR_PATTERNS = (
    "error",
    "traceback",
    "permission denied",
    "oserror",
    "importerror",
    "filenotfounderror",
    "denied",
)


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
            body_parts.append("(sem saída)")
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


def parse_systemctl_show(output: str) -> Dict[str, str]:
    data: Dict[str, str] = {}
    for line in output.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def systemctl_show(service: str, properties: Iterable[str]) -> Tuple[Dict[str, str], CommandResult]:
    args = ["systemctl", "show", service]
    for prop in properties:
        args.append(f"-p{prop}")
    result = run_command(args)
    return parse_systemctl_show(result.stdout), result


def detect_expected_port(env_path: Path, fallback_port: int) -> int:
    try:
        content = env_path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return fallback_port

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().upper()
        value = value.strip().strip('"').strip("'")
        if key in {"FALLBACK_PORT", "PORT", "HTTP_PORT"}:
            try:
                return int(value)
            except ValueError:
                continue
        if key in {"BIND_ADDRESS", "BIND_HOST", "LISTEN"} and ":" in value:
            candidate = value.rsplit(":", 1)[-1]
            try:
                return int(candidate)
            except ValueError:
                continue
    return fallback_port


def parse_exec_command(raw_exec: str) -> Tuple[Optional[str], Optional[str]]:
    if not raw_exec:
        return None, None
    candidate = raw_exec.strip()
    if candidate.startswith("{") and candidate.endswith("}"):
        candidate = candidate[1:-1]
    parts = [part.strip() for part in candidate.split(";") if part.strip()]
    if not parts:
        parts = [candidate]
    for part in parts:
        try:
            tokens = shlex.split(part)
        except ValueError:
            tokens = part.split()
        if tokens:
            return tokens[0], " ".join(tokens)
    return None, None


def format_path_permissions(path: Path) -> str:
    try:
        stats = path.stat()
    except FileNotFoundError:
        return f"{path} (inexistente)"
    except PermissionError:
        return f"{path} (sem permissões)"
    owner = pwd.getpwuid(stats.st_uid).pw_name
    group = getgrgid(stats.st_gid).gr_name
    perms = stat_module.filemode(stats.st_mode)
    return f"{path} ({perms} {owner}:{group}, tamanho={stats.st_size} bytes)"


def gather_service_inspection(service: str) -> Dict[str, object]:
    properties = (
        "ActiveState",
        "SubState",
        "MainPID",
        "ExecMainPID",
        "ExecMainStatus",
        "Result",
        "ExecStart",
        "FragmentPath",
        "FragmentTimestamp",
        "User",
    )
    show_data, show_result = systemctl_show(service, properties)
    status = run_command((*SERVICE_STATUS_ARGS, service))
    is_enabled = run_command(("systemctl", "is-enabled", service))
    is_active = run_command(("systemctl", "is-active", service))
    journal = run_command((*SERVICE_JOURNAL_ARGS, "-u", service, "-n", str(SERVICE_LOG_LINES)))
    unit_cat = run_command(("systemctl", "cat", service))

    raw_exec = show_data.get("ExecStart", "")
    binary, exec_cmd = parse_exec_command(raw_exec)

    error_lines = []
    for line in journal.stdout.splitlines():
        lower = line.lower()
        if any(pattern in lower for pattern in ERROR_PATTERNS):
            error_lines.append(line)

    return {
        "service": service,
        "show_data": show_data,
        "show_result": show_result,
        "status": status,
        "is_enabled": is_enabled,
        "is_active": is_active,
        "journal": journal,
        "errors": error_lines,
        "unit_cat": unit_cat,
        "binary": binary,
        "exec_cmd": exec_cmd,
    }


def gather_binary_details(binary: Optional[str]) -> List[str]:
    lines: List[str] = []
    if not binary:
        lines.append("ExecStart não apresenta um executável identificável.")
        return lines

    which_result = run_command(("which", binary)) if not Path(binary).is_absolute() else None
    if which_result:
        if which_result.returncode == 0 and which_result.stdout:
            resolved = Path(which_result.stdout.splitlines()[-1].strip())
            lines.append(f"which {binary}: {which_result.stdout}")
        else:
            resolved = Path(binary)
            lines.append(f"which {binary} falhou: {which_result.stderr or which_result.stdout}")
    else:
        resolved = Path(binary)

    lines.append(f"Executável primário: {resolved}")
    lines.append(f"Permissões: {format_path_permissions(resolved)}")

    readlink_result = run_command(("readlink", "-f", str(resolved)))
    if readlink_result.returncode == 0 and readlink_result.stdout:
        lines.append(f"Destino real: {readlink_result.stdout}")
    else:
        lines.append(f"readlink -f falhou: {readlink_result.stderr or readlink_result.stdout}")

    ldd_result = run_command(("ldd", str(resolved)))
    lines.append(ldd_result.format())

    return lines


def gather_environment_info(paths: Mapping[str, Path]) -> List[str]:
    sections: List[str] = []

    env_path = paths["env"]
    env_content = mask_secret(load_file(env_path))
    sections.append(f"--- {env_path} ---\n{env_content}".rstrip())

    if env_path.exists():
        try:
            raw_env = env_path.read_text(encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            sections.append(f"<erro ao analisar {env_path}: {exc}>")
        else:
            parsed: Dict[str, str] = {}
            for raw_line in raw_env.splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                parsed[key.strip()] = value.strip()

            highlights: List[str] = []
            video_src = parsed.get("VIDEO_SRC")
            duration = parsed.get("DURATION_PER_SCENE")
            scenes_raw = parsed.get("SCENES_TXT")
            if video_src:
                highlights.append(f"VIDEO_SRC={video_src}")
            if duration:
                highlights.append(f"DURATION_PER_SCENE={duration}")
            if scenes_raw:
                normalized = scenes_raw
                if normalized.startswith("$'") and normalized.endswith("'"):
                    normalized = normalized[2:-1]
                    try:
                        normalized = normalized.encode("utf-8").decode("unicode_escape")
                    except UnicodeDecodeError:
                        pass
                elif (normalized.startswith("\"") and normalized.endswith("\"")) or (
                    normalized.startswith("'") and normalized.endswith("'")
                ):
                    normalized = normalized[1:-1]
                expanded = normalized.replace("\\r", "").replace("\\n", "\n")
                scenes = [entry for entry in expanded.splitlines() if entry]
                if scenes:
                    highlights.append("SCENES_TXT (expandido):")
                    for idx, scene in enumerate(scenes, start=1):
                        highlights.append(f"  [{idx}] {scene}")
                else:
                    highlights.append(f"SCENES_TXT={scenes_raw}")
            if highlights:
                sections.append("Variáveis detectadas:\n" + "\n".join(highlights))

    progress_content = load_file(paths["progress"]) if paths["progress"].exists() else "<sem progresso disponível>"
    sections.append(f"--- {paths['progress']} ---\n{progress_content}".rstrip())

    log_path = paths["log"]
    if log_path.exists():
        stat_line = format_path_permissions(log_path)
        sections.append(f"--- {log_path} (metadados) ---\n{stat_line}")
        tail_result = run_command(("tail", "-n", "120", str(log_path)))
        sections.append(
            f"--- tail -n 120 {log_path} ---\n{tail_result.stdout or tail_result.stderr}".rstrip()
        )
    else:
        sections.append(f"--- {log_path} ---\n<ficheiro não encontrado>")

    return sections


def gather_repo_status(repo_root: Path) -> List[CommandResult]:
    commands = [
        ("git", "-C", str(repo_root), "status", "-sb"),
        ("git", "-C", str(repo_root), "rev-parse", "HEAD"),
        ("git", "-C", str(repo_root), "log", "-1", "--oneline"),
    ]
    return [run_command(cmd) for cmd in commands]


def gather_network_info(port: int) -> List[CommandResult]:
    results: List[CommandResult] = []
    ss_result = run_command(("ss", "-ltnp"))
    results.append(ss_result)
    if ss_result.stdout:
        matching = [line for line in ss_result.stdout.splitlines() if f":{port}" in line]
        combined = "\n".join(matching) if matching else "<nenhum processo a ouvir>"
        results.append(CommandResult(("ss", f"grep-port-{port}"), 0, combined, ""))
    else:
        results.append(CommandResult(("ss", f"grep-port-{port}"), 1, "", "sem dados"))
    firewall = run_command(("ufw", "status"))
    iptables = run_command(("iptables", "-L"))
    results.extend([firewall, iptables])
    return results


def gather_resource_info() -> List[CommandResult]:
    commands = [
        ("free", "-h"),
        ("df", "-h"),
        ("uptime",),
        ("cat", "/proc/loadavg"),
        ("bash", "-lc", "ulimit -a"),
    ]
    return [run_command(cmd) for cmd in commands]


def gather_process_checks(services: Sequence[str], inspections: Mapping[str, Dict[str, object]]) -> List[str]:
    lines: List[str] = []
    for service in services:
        inspection = inspections.get(service)
        show_data_value = inspection.get("show_data") if inspection else None
        show_data: Dict[str, str] = show_data_value if isinstance(show_data_value, dict) else {}
        main_pid = show_data.get("MainPID")
        if main_pid and main_pid != "0":
            ps_result = run_command(("ps", "-fp", main_pid))
            lines.append(ps_result.format())
        else:
            lines.append(f"Sem processo activo para {service} (MainPID={main_pid or 'desconhecido'}).")
        grep_boot = run_command(
            (
                "bash",
                "-lc",
                f"journalctl -b --no-pager | grep -F '{service}' || true",
            )
        )
        lines.append(grep_boot.format())
    zombies = run_command(
        (
            "bash",
            "-lc",
            "ps -eo pid,ppid,stat,comm | awk '$3 ~ /Z/ {print}'",
        )
    )
    if zombies.stdout:
        lines.append("Processos zombie detectados:")
        lines.append(zombies.stdout)
    else:
        lines.append("Sem processos zombie detectados (comando: ps -eo pid,ppid,stat,comm | awk '$3 ~ /Z/ {print}' ).")
        if zombies.stderr:
            lines.append(f"stderr: {zombies.stderr}")
    for service in services:
        duplicates = run_command(
            (
                "bash",
                "-lc",
                f"systemctl list-units --type=service --all | grep -F '{service}' || true",
            )
        )
        if duplicates.stdout:
            lines.append(f"Instâncias systemd correspondentes a {service}:\n{duplicates.stdout}")
        else:
            lines.append(f"Sem instâncias duplicadas para {service}.")
            if duplicates.stderr:
                lines.append(f"stderr: {duplicates.stderr}")
    return lines


def gather_security_info() -> List[CommandResult]:
    commands = [
        ("aa-status",),
        ("sestatus",),
        ("grep", "DENIED", "/var/log/syslog"),
    ]
    return [run_command(cmd) for cmd in commands]


def gather_updates_info(services: Sequence[str]) -> List[CommandResult]:
    results: List[CommandResult] = []
    for service in services:
        package = service.replace(".service", "")
        results.append(run_command(("apt", "list", "--installed", package)))
        results.append(run_command(("apt-get", "-s", "upgrade", package)))
    return results


def summarise_final(
    inspections: Mapping[str, Dict[str, object]],
    fallback_name: str,
    duration_s: float,
) -> List[str]:
    lines: List[str] = []
    fallback = inspections.get(fallback_name)
    if not fallback:
        lines.append("Serviço youtube-fallback não inspecionado.")
        return lines

    show_data: Dict[str, str] = fallback["show_data"]  # type: ignore[assignment]
    state = show_data.get("ActiveState", "desconhecido")
    sub_state = show_data.get("SubState", "")
    exec_status = show_data.get("ExecMainStatus", "")
    result = show_data.get("Result", "")
    verdict = f"Estado actual: {state} ({sub_state})."
    if exec_status:
        verdict += f" Último código do processo principal: {exec_status}."
    if result:
        verdict += f" Result= {result}."
    lines.append(verdict)

    errors = fallback.get("errors", [])
    if errors:
        lines.append("Últimos erros detectados no journal:")
        for entry in errors[:10]:
            lines.append(f"  - {entry}")
    else:
        lines.append("Journalctl não contém entradas com palavras-chave de erro nas últimas linhas.")

    is_active_rc = fallback["is_active"].returncode  # type: ignore[index]
    state_desc = fallback["is_active"].stdout or fallback["is_active"].stderr  # type: ignore[index]
    if is_active_rc != 0:
        lines.append(
            "Causa provável: service parado — 'systemctl is-active' devolveu "
            f"{state_desc!r} (rc={is_active_rc})."
        )
    else:
        lines.append("Causa provável: fallback reportado como activo pelo systemd.")

    lines.append(
        "Sugestão: validar logs acima, considerar 'systemctl restart youtube-fallback' após corrigir causa raiz."
    )
    timestamp = _dt.datetime.now(_dt.timezone.utc).isoformat()
    lines.append(f"Análise concluída em {timestamp}Z. Duração total: {duration_s:.1f}s.")
    return lines


def gather_diagnostics(args: argparse.Namespace) -> str:
    analysis_start = time.perf_counter()
    inspections: Dict[str, Dict[str, object]] = {}
    for service in args.services:
        inspections[service] = gather_service_inspection(service)

    now = _dt.datetime.now(_dt.timezone.utc)
    expected_port = detect_expected_port(args.env_path, DEFAULT_EXPECTED_PORT)
    lines: List[str] = []

    lines.append("== 1. Identificação e contexto ==")
    lines.append(f"Data/Hora (UTC): {now.strftime('%Y-%m-%d %H:%M:%SZ')}")
    lines.append(f"Utilizador: {getpass.getuser()}")
    lines.append(f"Host: {os.uname().nodename}")
    lines.append("Versão SO:")
    for cmd in (("lsb_release", "-a"), ("uname", "-r")):
        result = run_command(cmd)
        lines.append(result.format())
    lines.append(run_command(("uptime", "-p")).format())
    lines.append(run_command(("last", "reboot", "-n", "1")).format())
    for service, inspection in inspections.items():
        exec_cmd_value = inspection.get("exec_cmd") if inspection else None
        exec_cmd = exec_cmd_value if isinstance(exec_cmd_value, str) else None
        lines.append(f"Serviço {service}: ExecStart -> {exec_cmd or '<indisponível>'}")
        binary_value = inspection.get("binary") if inspection else None
        binary_path = binary_value if isinstance(binary_value, str) else None
        lines.append(f"  Executável principal: {binary_path or '<não encontrado>'}")
    lines.append("")

    lines.append("== 2. Estado do systemd (serviço) ==")
    for service, inspection in inspections.items():
        lines.append(f"-- {service} --")
        lines.append(inspection["status"].format())
        lines.append(inspection["is_enabled"].format())
        lines.append(inspection["is_active"].format())
        show_data: Dict[str, str] = inspection["show_data"]  # type: ignore[assignment]
        lines.append(
            "Resumo: ActiveState=%s SubState=%s MainPID=%s User=%s" % (
                show_data.get("ActiveState", "?"),
                show_data.get("SubState", "?"),
                show_data.get("MainPID", "?"),
                show_data.get("User", "?"),
            )
        )
        lines.append("")

    lines.append("== 3. Logs do serviço ==")
    for service, inspection in inspections.items():
        lines.append(f"-- {service} --")
        lines.append(inspection["journal"].format())
        errors = inspection.get("errors", [])
        if errors:
            lines.append("Erros filtrados:")
            for entry in errors:
                lines.append(f"  {entry}")
        else:
            lines.append("Sem erros detectados nas últimas linhas do journal.")
        lines.append("")

    lines.append("== 4. Binário e dependências ==")
    for service, inspection in inspections.items():
        lines.append(f"-- {service} --")
        binary_value = inspection.get("binary") if inspection else None
        binary_path = binary_value if isinstance(binary_value, str) else None
        lines.extend(gather_binary_details(binary_path))
        lines.append("")
    venv_path = args.repo_root / ".venv"
    if venv_path.exists():
        lines.append(f"Ambiente virtual detectado: {format_path_permissions(venv_path)}")
        lines.append(run_command(("bash", "-lc", f"source {venv_path}/bin/activate && python -m pip check")).format())
    else:
        lines.append("Sem ambiente virtual '.venv' detectado na raiz do repositório.")


    lines.append("== 5. Configuração da Unit e Environment ==")
    for service, inspection in inspections.items():
        show_data: Dict[str, str] = inspection["show_data"]  # type: ignore[assignment]
        fragment_path = show_data.get("FragmentPath", "<desconhecido>")
        fragment_ts = show_data.get("FragmentTimestamp", "<desconhecido>")
        lines.append(f"-- {service} --")
        lines.append(f"FragmentPath: {fragment_path}")
        lines.append(f"FragmentTimestamp: {fragment_ts}")
        lines.append(inspection["unit_cat"].format())
    env_sections = gather_environment_info(
        {
            "env": args.env_path,
            "progress": args.progress_path,
            "log": args.log_path,
        }
    )
    lines.extend(section + "\n" for section in env_sections)
    lines.append("-- Repositório de configuração --")
    for result in gather_repo_status(args.repo_root):
        lines.append(result.format())
        lines.append("")

    lines.append("== 6. Permissões e utilizadores ==")
    for service, inspection in inspections.items():
        show_data: Dict[str, str] = inspection["show_data"]  # type: ignore[assignment]
        user = show_data.get("User") or "root"
        try:
            pwd.getpwnam(user)
            exists = True
        except KeyError:
            exists = False
        lines.append(f"Utilizador {user}: {'existe' if exists else 'não existe'}.")
        log_path = args.log_path
        can_write = log_path.exists() and os.access(log_path.parent, os.W_OK)
        lines.append(f"Acesso ao directório de logs ({log_path.parent}): {'ok' if can_write else 'sem escrita'}")
    if expected_port < 1024:
        lines.append(
            f"Porta configurada ({expected_port}) é privilegiada: requer privilégios de root ou capabilities."
        )
    else:
        lines.append(
            f"Porta configurada ({expected_port}) está acima de 1024; não necessita privilégios especiais."
        )

    lines.append("== 7. Rede ==")
    lines.append(f"Porta monitorizada: {expected_port}")
    for result in gather_network_info(expected_port):
        lines.append(result.format())
        lines.append("")

    lines.append("== 8. Recursos de sistema ==")
    for result in gather_resource_info():
        lines.append(result.format())
        lines.append("")

    lines.append("== 9. Processos ==")
    lines.extend(gather_process_checks(tuple(inspections.keys()), inspections))

    lines.append("== 10. Segurança / SELinux / AppArmor ==")
    for result in gather_security_info():
        lines.append(result.format())
        lines.append("")

    lines.append("== 11. Actualizações e pacotes ==")
    for result in gather_updates_info(tuple(inspections.keys())):
        lines.append(result.format())
        lines.append("")

    analysis_duration = time.perf_counter() - analysis_start
    lines.append("== 12. Resultado final e resumo ==")
    lines.extend(
        summarise_final(
            inspections,
            "youtube-fallback.service",
            analysis_duration,
        )
    )

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
    parsed = parser.parse_args(argv)
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
