"""ACLs restritas para dados/binários partilhados (Windows)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional


def _posix_restrict(path: Path, *, writable_group: bool = False) -> None:
    mode = 0o770 if (path.is_dir() and writable_group) else (0o750 if path.is_dir() else 0o640)
    try:
        path.chmod(mode)
    except OSError:
        pass


def apply_data_dir_acls(path: Path) -> None:
    """Diretório de config/chave: SYSTEM/Admins + escrita para Authenticated Users; sem Everyone."""

    path.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        _posix_restrict(path, writable_group=True)
        return
    _run_icacls(
        path,
        grants=(
            "SYSTEM:(OI)(CI)F",
            "Administrators:(OI)(CI)F",
            "NT AUTHORITY\\LOCAL SERVICE:(OI)(CI)M",
            "NT AUTHORITY\\NETWORK SERVICE:(OI)(CI)M",
            "Authenticated Users:(OI)(CI)M",
        ),
    )


def apply_bin_dir_acls(path: Path) -> None:
    """Binários/auxiliar/plugins: sem alteração por utilizadores comuns."""

    path.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        _posix_restrict(path, writable_group=False)
        return
    _run_icacls(
        path,
        grants=(
            "SYSTEM:(OI)(CI)F",
            "Administrators:(OI)(CI)F",
            "NT AUTHORITY\\LOCAL SERVICE:(OI)(CI)RX",
            "NT AUTHORITY\\NETWORK SERVICE:(OI)(CI)RX",
            "Authenticated Users:(OI)(CI)RX",
        ),
    )


def secure_file(path: Path) -> None:
    if not path.exists():
        return
    if os.name != "nt":
        _posix_restrict(path)
        return
    parent = path.parent
    # Ficheiros no data dir herdam; reforçar ACE no ficheiro.
    _run_icacls(
        path,
        grants=(
            "SYSTEM:F",
            "Administrators:F",
            "NT AUTHORITY\\LOCAL SERVICE:M",
            "NT AUTHORITY\\NETWORK SERVICE:M",
            "Authenticated Users:M",
        ),
        is_file=True,
    )
    _ = parent


def _run_icacls(path: Path, *, grants: tuple[str, ...], is_file: bool = False) -> None:
    target = str(path)
    commands = [
        ["icacls", target, "/inheritance:r"],
    ]
    for grant in grants:
        commands.append(["icacls", target, "/grant:r", grant])
    for cmd in commands:
        try:
            subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            break


def harden_shared_paths(
    data_dir: Optional[Path] = None, bin_dir: Optional[Path] = None
) -> None:
    from effective_config import shared_bin_dir, shared_data_dir

    apply_data_dir_acls(data_dir or shared_data_dir())
    apply_bin_dir_acls(bin_dir or shared_bin_dir())
