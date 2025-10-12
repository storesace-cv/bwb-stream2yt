#!/usr/bin/env python3
"""Watcher that controls the YouTube fallback stream based on an HTTP API."""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, Mapping, Optional, Tuple
from urllib import error as urlerror
from urllib import request as urlrequest

LOGGER = logging.getLogger("youtube_fallback_watcher")

DEFAULT_CONFIG_PATH = Path("/etc/youtube-fallback-watcher.conf")
DEFAULT_ENV_FILE = Path("/etc/youtube-fallback.env")
DEFAULT_MODE_FILE = Path("/run/youtube-fallback.mode")
DEFAULT_SERVICE_NAME = "youtube-fallback.service"
DEFAULT_CHECK_INTERVAL = 3.0
DEFAULT_STALE_SECONDS = 15.0
DEFAULT_SCENE_LIFE = "life=size=1280x720:rate=30"
DEFAULT_SCENE_BARS = "smptehdbars=s=1280x720:rate=30"
DEFAULT_TIMEOUT = 3.0


class Mode(Enum):
    """Operating modes for the fallback service."""

    OFF = "off"
    LIFE = "life"
    BARS = "smptehdbars"

    @property
    def base_value(self) -> str:
        return self.value


@dataclass
class FetcherResult:
    ok: bool
    payload: Optional[Dict[str, object]] = None
    error: Optional[str] = None


@dataclass
class WatcherConfig:
    api_url: str
    check_interval: float = DEFAULT_CHECK_INTERVAL
    heartbeat_stale_sec: float = DEFAULT_STALE_SECONDS
    scene_life: str = DEFAULT_SCENE_LIFE
    scene_bars: str = DEFAULT_SCENE_BARS
    env_file: Path = DEFAULT_ENV_FILE
    mode_file: Path = DEFAULT_MODE_FILE
    service_name: str = DEFAULT_SERVICE_NAME
    request_timeout: float = DEFAULT_TIMEOUT

    @staticmethod
    def _parse_positive_float(value: str, default: float) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            LOGGER.warning(
                "Valor inválido para parâmetro numérico (%r); utilizando %s",
                value,
                default,
            )
            return default
        if parsed <= 0:
            LOGGER.warning(
                "Valor não positivo fornecido (%r); utilizando %s", value, default
            )
            return default
        return parsed

    @staticmethod
    def _parse_config_file(path: Path) -> Dict[str, str]:
        if not path.exists():
            return {}
        values: Dict[str, str] = {}
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            LOGGER.warning("Não foi possível ler %s: %s", path, exc)
            return values
        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            values[key.strip().upper()] = value.strip()
        return values

    @classmethod
    def from_sources(
        cls, path: Path = DEFAULT_CONFIG_PATH, env: Optional[Mapping[str, str]] = None
    ) -> "WatcherConfig":
        env = env or os.environ
        data = cls._parse_config_file(path)

        def _override(key: str, *env_keys: str) -> Optional[str]:
            for candidate in env_keys:
                value = env.get(candidate)
                if value:
                    return value
            return data.get(key)

        api_url = _override("API_URL", "YFW_API_URL", "YTR_API_URL")
        if not api_url:
            raise ValueError(
                "API_URL não definido em /etc/youtube-fallback-watcher.conf nem em variáveis de ambiente"
            )

        check_interval_raw = _override("CHECK_INTERVAL", "YFW_CHECK_INTERVAL")
        stale_raw = _override("HEARTBEAT_STALE_SEC", "YFW_HEARTBEAT_STALE_SEC")
        timeout_raw = _override("REQUEST_TIMEOUT", "YFW_REQUEST_TIMEOUT")

        scene_life = _override("SCENE_LIFE", "YFW_SCENE_LIFE") or DEFAULT_SCENE_LIFE
        scene_bars = _override("SCENE_BARS", "YFW_SCENE_BARS") or DEFAULT_SCENE_BARS

        env_file_raw = _override("ENV_FILE", "YFW_ENV_FILE")
        mode_file_raw = _override("MODE_FILE", "YFW_MODE_FILE", "YTR_FALLBACK_MODE_FILE")
        service_name = _override("SERVICE_NAME", "YFW_SERVICE_NAME") or DEFAULT_SERVICE_NAME

        check_interval = (
            cls._parse_positive_float(check_interval_raw, DEFAULT_CHECK_INTERVAL)
            if check_interval_raw
            else DEFAULT_CHECK_INTERVAL
        )
        heartbeat_stale = (
            cls._parse_positive_float(stale_raw, DEFAULT_STALE_SECONDS)
            if stale_raw
            else DEFAULT_STALE_SECONDS
        )
        request_timeout = (
            cls._parse_positive_float(timeout_raw, DEFAULT_TIMEOUT)
            if timeout_raw
            else DEFAULT_TIMEOUT
        )

        env_file = Path(env_file_raw).expanduser() if env_file_raw else DEFAULT_ENV_FILE
        mode_file = Path(mode_file_raw).expanduser() if mode_file_raw else DEFAULT_MODE_FILE

        return cls(
            api_url=api_url,
            check_interval=check_interval,
            heartbeat_stale_sec=heartbeat_stale,
            scene_life=scene_life,
            scene_bars=scene_bars,
            env_file=env_file,
            mode_file=mode_file,
            service_name=service_name,
            request_timeout=request_timeout,
        )

    def scene_for(self, mode: Mode) -> str:
        if mode is Mode.BARS:
            return self.scene_bars
        if mode is Mode.LIFE:
            return self.scene_life
        raise ValueError(f"Mode {mode} não possui cena associada")


class SystemdService:
    """Wrapper around systemctl for the fallback service."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._lock = threading.Lock()

    def _systemctl_cmd(self, *args: str) -> Tuple[str, ...]:
        base_cmd = ("/bin/systemctl", "--no-ask-password", *args, self.name)
        if os.geteuid() == 0:
            return base_cmd
        return ("/usr/bin/sudo", "-n", *base_cmd)

    @staticmethod
    def _message(result: subprocess.CompletedProcess[str]) -> str:
        message = result.stderr.strip() or result.stdout.strip()
        if not message:
            message = f"systemctl retornou código {result.returncode}"
        return message

    def is_active(self) -> bool:
        result = subprocess.run(
            self._systemctl_cmd("is-active"),
            check=False,
            capture_output=True,
            text=True,
        )
        return result.returncode == 0 and result.stdout.strip() == "active"

    def ensure_started(self) -> bool:
        with self._lock:
            if self.is_active():
                return True
            result = subprocess.run(
                self._systemctl_cmd("start"),
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                LOGGER.error(
                    "Falha ao iniciar %s: %s", self.name, self._message(result)
                )
                return False
            LOGGER.info("Serviço %s iniciado", self.name)
            return True

    def ensure_stopped(self) -> bool:
        with self._lock:
            if not self.is_active():
                return True
            result = subprocess.run(
                self._systemctl_cmd("stop"),
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                LOGGER.error(
                    "Falha ao parar %s: %s", self.name, self._message(result)
                )
                return False
            LOGGER.info("Serviço %s parado", self.name)
            return True

    def restart(self) -> bool:
        with self._lock:
            result = subprocess.run(
                self._systemctl_cmd("restart"),
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                LOGGER.error(
                    "Falha ao reiniciar %s: %s", self.name, self._message(result)
                )
                return False
            LOGGER.info("Serviço %s reiniciado", self.name)
            return True


class EnvManager:
    """Helper to update keys in /etc/youtube-fallback.env."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def set(self, key: str, value: str) -> bool:
        existing_lines: list[str] = []
        try:
            if self.path.exists():
                existing_lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            LOGGER.warning("Não foi possível ler %s: %s", self.path, exc)
            existing_lines = []

        new_lines: list[str] = []
        found = False
        for line in existing_lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in line:
                new_lines.append(line)
                continue
            current_key, current_value = line.split("=", 1)
            if current_key.strip() != key:
                new_lines.append(line)
                continue
            if current_value.strip() == value:
                return True
            new_lines.append(f"{key}={value}")
            found = True

        if not found:
            new_lines.append(f"{key}={value}")

        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        try:
            self.path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        except OSError as exc:
            LOGGER.warning("Não foi possível escrever %s: %s", self.path, exc)
            return False
        LOGGER.info("Atualizado %s → %s", key, value)
        return True


class ModeFileManager:
    def __init__(self, path: Path) -> None:
        self.path = path

    def write(self, mode: Mode) -> bool:
        desired = f"{mode.base_value}\n"
        try:
            current = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            current = ""
        except OSError as exc:
            LOGGER.warning("Não foi possível ler modo de fallback (%s): %s", self.path, exc)
            current = ""
        if current == desired:
            return True
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        try:
            self.path.write_text(desired, encoding="utf-8")
        except OSError as exc:
            LOGGER.warning("Não foi possível escrever %s: %s", self.path, exc)
            return False
        LOGGER.info("Modo de fallback atualizado para %s", mode.base_value)
        return True


def _scene_base(scene: str) -> str:
    candidate = scene.split("=", 1)[0]
    return candidate.strip().split(":", 1)[0].strip().lower()


class APIWatcher:
    def __init__(
        self,
        config: WatcherConfig,
        service: SystemdService,
        env_manager: EnvManager,
        mode_manager: ModeFileManager,
        fetcher: Callable[[str, float], FetcherResult],
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._config = config
        self._service = service
        self._env = env_manager
        self._mode = mode_manager
        self._fetcher = fetcher
        self._clock = clock
        self._sleep = sleeper
        self._stop_event = threading.Event()
        self._last_success: Optional[float] = None
        self._current_mode: Optional[Mode] = None

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        LOGGER.info(
            "Watcher iniciado: API=%s | intervalo=%.1fs | stale=%.1fs",
            self._config.api_url,
            self._config.check_interval,
            self._config.heartbeat_stale_sec,
        )
        while not self._stop_event.is_set():
            start = self._clock()
            try:
                self.process_once()
            except Exception:  # pragma: no cover - defensive
                LOGGER.exception("Erro inesperado durante iteração do watcher")
            elapsed = self._clock() - start
            wait = max(0.0, self._config.check_interval - elapsed)
            if self._stop_event.wait(wait):
                break

    def process_once(self) -> Mode:
        now = self._clock()
        result = self._fetcher(self._config.api_url, self._config.request_timeout)
        mode, reason = self._determine_mode(result, now)
        if reason and (mode is not self._current_mode):
            LOGGER.info("Alterando modo para %s (%s)", mode.name, reason)
        self._apply_mode(mode)
        return mode

    def _determine_mode(self, result: FetcherResult, now: float) -> Tuple[Mode, str]:
        if result.ok and isinstance(result.payload, dict):
            payload = result.payload
            internet = payload.get("internet")
            camera = payload.get("camera")
            if isinstance(internet, bool):
                self._last_success = now
                if internet:
                    if isinstance(camera, bool):
                        if camera:
                            return Mode.OFF, "internet_ok_camera_ok"
                        return Mode.BARS, "camera_sem_sinal"
                    LOGGER.warning(
                        "Payload da API não possui camera=bool; assumindo câmera presente"
                    )
                    return Mode.OFF, "camera_estado_desconhecido"
                LOGGER.warning("API indica ausência de internet no emissor")
                return Mode.LIFE, "internet_indisponivel"
            LOGGER.warning(
                "Payload inválido recebido: campo 'internet' não é booleano → %r", payload
            )
        else:
            message = result.error or "resposta inválida"
            LOGGER.warning("Falha ao consultar API: %s", message)

        if self._last_success is None:
            return Mode.LIFE, "sem_heartbeat_sucesso"
        elapsed = now - self._last_success
        if elapsed >= self._config.heartbeat_stale_sec:
            return Mode.LIFE, f"heartbeat_stale ({elapsed:.1f}s)"
        return self._current_mode or Mode.OFF, "mantendo_estado"

    def _apply_mode(self, mode: Mode) -> None:
        if mode is Mode.OFF:
            # Garantir que próxima inicialização utilize 'life'.
            self._update_resources(Mode.LIFE)
            if self._current_mode is not Mode.OFF:
                if self._service.ensure_stopped():
                    self._current_mode = Mode.OFF
            return

        self._update_resources(mode)
        service_active = self._service.is_active()

        if not service_active:
            if self._service.ensure_started():
                self._current_mode = mode
            return

        if self._current_mode is mode:
            return

        if self._service.restart():
            self._current_mode = mode

    def _update_resources(self, mode: Mode) -> None:
        target_mode = Mode.LIFE if mode is Mode.OFF else mode
        scene = self._config.scene_for(target_mode)
        base = _scene_base(scene)
        try:
            mode_enum = Mode(base)
        except ValueError:
            LOGGER.warning(
                "Cena %s não corresponde a modo conhecido; utilizando 'life'", scene
            )
            mode_enum = Mode.LIFE
        self._env.set("SCENE", scene)
        self._mode.write(mode_enum)


def fetch_status(url: str, timeout: float) -> FetcherResult:
    req = urlrequest.Request(url, headers={"Accept": "application/json"})
    try:
        with urlrequest.urlopen(req, timeout=timeout) as response:
            if response.status != 200:
                return FetcherResult(False, error=f"HTTP {response.status}")
            try:
                payload = json.loads(response.read().decode("utf-8"))
            except json.JSONDecodeError as exc:
                return FetcherResult(False, error=f"JSON inválido: {exc}")
    except urlerror.HTTPError as exc:
        return FetcherResult(False, error=f"HTTP {exc.code}")
    except urlerror.URLError as exc:
        return FetcherResult(False, error=str(exc.reason))
    except Exception as exc:  # pragma: no cover - rede guard
        return FetcherResult(False, error=str(exc))

    if not isinstance(payload, dict):
        return FetcherResult(False, error="payload inesperado")
    return FetcherResult(True, payload=payload)


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        stream=sys.stdout,
    )


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Watcher do fallback do YouTube")
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG_PATH,
        type=Path,
        help="Arquivo de configuração (default: /etc/youtube-fallback-watcher.conf)",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    configure_logging()

    try:
        config = WatcherConfig.from_sources(args.config)
    except Exception as exc:
        LOGGER.error("Falha ao carregar configuração: %s", exc)
        return 1

    watcher = APIWatcher(
        config=config,
        service=SystemdService(config.service_name),
        env_manager=EnvManager(config.env_file),
        mode_manager=ModeFileManager(config.mode_file),
        fetcher=fetch_status,
    )

    def _handle_signal(signum, _frame) -> None:
        LOGGER.info("Sinal %s recebido; encerrando watcher.", signum)
        watcher.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _handle_signal)

    watcher.run()
    LOGGER.info("Watcher encerrado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
