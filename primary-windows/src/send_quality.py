"""Perfis manuais de qualidade de envio (sessão UI, sem alterar .env)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence

DEFAULT_SEND_QUALITY = "alta"
SEND_QUALITY_SOURCE = "source"
SOURCE_QUALITY_LABEL = "Qualidade da fonte"


@dataclass(frozen=True)
class SendQualityProfile:
    key: str
    label: str
    width: int
    height: int
    fps: int
    bitrate_kbps: int
    maxrate_kbps: int
    bufsize_kbps: int

    @property
    def short_resolution(self) -> str:
        return f"{self.height}p"


SEND_QUALITY_PROFILES: Dict[str, SendQualityProfile] = {
    "alta": SendQualityProfile(
        key="alta",
        label="Alta",
        width=1920,
        height=1080,
        fps=30,
        bitrate_kbps=5000,
        maxrate_kbps=6000,
        bufsize_kbps=12000,
    ),
    "media": SendQualityProfile(
        key="media",
        label="Média",
        width=1280,
        height=720,
        fps=30,
        bitrate_kbps=2500,
        maxrate_kbps=3000,
        bufsize_kbps=6000,
    ),
    "baixa": SendQualityProfile(
        key="baixa",
        label="Baixa",
        width=854,
        height=480,
        fps=25,
        bitrate_kbps=1000,
        maxrate_kbps=1200,
        bufsize_kbps=2400,
    ),
    "emergencia": SendQualityProfile(
        key="emergencia",
        label="Emergência",
        width=640,
        height=360,
        fps=20,
        bitrate_kbps=500,
        maxrate_kbps=650,
        bufsize_kbps=1300,
    ),
}

SEND_QUALITY_ORDER: tuple[str, ...] = ("alta", "media", "baixa", "emergencia")


def normalize_send_quality(value: Optional[str]) -> str:
    if not value:
        return DEFAULT_SEND_QUALITY
    key = value.strip().lower()
    if key in {SEND_QUALITY_SOURCE, "fonte", "source_quality", "qualidade_fonte"}:
        return SEND_QUALITY_SOURCE
    if key in SEND_QUALITY_PROFILES:
        return key
    return DEFAULT_SEND_QUALITY


def quality_requires_transcode(value: Optional[str]) -> bool:
    """Presets que alteram resolução/FPS/bitrate exigem recodificação."""

    return normalize_send_quality(value) != SEND_QUALITY_SOURCE


def get_send_quality_profile(value: Optional[str] = None) -> SendQualityProfile:
    key = normalize_send_quality(value)
    if key == SEND_QUALITY_SOURCE:
        # Perfil sentinela: não aplica escala/bitrate (cópia / qualidade da fonte).
        return SendQualityProfile(
            key=SEND_QUALITY_SOURCE,
            label=SOURCE_QUALITY_LABEL,
            width=0,
            height=0,
            fps=0,
            bitrate_kbps=0,
            maxrate_kbps=0,
            bufsize_kbps=0,
        )
    return SEND_QUALITY_PROFILES[key]


def iter_send_quality_profiles() -> Iterable[SendQualityProfile]:
    for key in SEND_QUALITY_ORDER:
        yield SEND_QUALITY_PROFILES[key]


def format_quality_status(profile: SendQualityProfile) -> str:
    if profile.key == SEND_QUALITY_SOURCE:
        return f"Qualidade: {SOURCE_QUALITY_LABEL}"
    return (
        f"Qualidade: {profile.label} — {profile.short_resolution} / "
        f"{profile.fps} FPS / {profile.bitrate_kbps} kbps"
    )


def _set_arg_value(args: List[str], flag: str, value: str) -> None:
    try:
        index = args.index(flag)
    except ValueError:
        args.extend([flag, value])
        return
    if index + 1 < len(args):
        args[index + 1] = value
    else:
        args.append(value)


def apply_profile_to_output_args(
    output_args: Sequence[str], profile: SendQualityProfile
) -> List[str]:
    """Aplica escala, FPS e limites de bitrate do perfil aos args de saída."""

    if profile.key == SEND_QUALITY_SOURCE:
        # Sem transformação forçada — mantém args base (FFmpeg) / cópia (Gst).
        return list(output_args)

    updated = list(output_args)
    filter_value = (
        f"scale={profile.width}:{profile.height}:"
        "flags=bicubic:in_range=pc:out_range=tv,format=yuv420p"
    )
    _set_arg_value(updated, "-vf", filter_value)
    _set_arg_value(updated, "-r", str(profile.fps))
    _set_arg_value(updated, "-b:v", f"{profile.bitrate_kbps}k")
    _set_arg_value(updated, "-maxrate", f"{profile.maxrate_kbps}k")
    _set_arg_value(updated, "-bufsize", f"{profile.bufsize_kbps}k")
    _set_arg_value(updated, "-g", str(profile.fps * 2))
    return updated
