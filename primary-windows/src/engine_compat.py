"""Sondagem limitada, capacidades locais e seleção Automático/manual de motor."""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

from effective_config import (
    ENGINE_AUTOMATIC,
    ENGINE_FFMPEG,
    ENGINE_GSTREAMER,
    EffectiveConfig,
    load_effective_config,
    normalize_engine_preference,
    shared_bin_dir,
    shared_data_dir,
)
from send_quality import (
    SEND_QUALITY_SOURCE,
    normalize_send_quality,
    quality_requires_transcode,
)

ANALYSIS_COMPATIBLE = "compatible"
ANALYSIS_INCOMPATIBLE = "incompatible"
ANALYSIS_INDETERMINATE = "indeterminate"

MODE_COPY = "copy"
MODE_TRANSCODE = "transcode"

CACHE_TTL_SECONDS = 120.0


@dataclass(frozen=True)
class SourceProbeSummary:
    video_codec: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    fps: Optional[float] = None
    audio_codec: Optional[str] = None
    audio_channels: Optional[int] = None
    audio_rate: Optional[int] = None
    is_h264: Optional[bool] = None
    gop_known: bool = False
    bitrate_known: bool = False
    analysis: str = ANALYSIS_INDETERMINATE
    reason: str = ""
    config_fingerprint: str = ""


@dataclass(frozen=True)
class EngineCapability:
    engine: str
    available: bool
    mode: str
    reason: str = ""


@dataclass(frozen=True)
class EngineEligibility:
    engine: str
    mode: str
    eligible: bool
    analysis: str
    reason: str


@dataclass(frozen=True)
class EngineSelection:
    preference: str
    engine: str
    mode: str
    reason: str
    probe: Optional[SourceProbeSummary] = None
    eligibilities: tuple[EngineEligibility, ...] = ()


@dataclass
class CompatCache:
    fingerprint: str
    saved_at: float
    probe: dict[str, Any] = field(default_factory=dict)

    def is_fresh(self, fingerprint: str, ttl: float = CACHE_TTL_SECONDS) -> bool:
        if self.fingerprint != fingerprint:
            return False
        return (time.time() - self.saved_at) <= ttl


def _cache_path(data_dir: Optional[Path] = None) -> Path:
    return (data_dir or shared_data_dir()) / "engine_compat_cache.json"


def load_compat_cache(data_dir: Optional[Path] = None) -> Optional[CompatCache]:
    path = _cache_path(data_dir)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return CompatCache(
        fingerprint=str(payload.get("fingerprint") or ""),
        saved_at=float(payload.get("saved_at") or 0.0),
        probe=dict(payload.get("probe") or {}),
    )


def save_compat_cache(cache: CompatCache, data_dir: Optional[Path] = None) -> None:
    root = data_dir or shared_data_dir()
    root.mkdir(parents=True, exist_ok=True)
    path = _cache_path(root)
    path.write_text(
        json.dumps(asdict(cache), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def config_fingerprint(
    *,
    input_hint: str,
    send_quality: str,
    audio_mode: str,
    contingency_on: bool,
    demo_path: str,
    ffmpeg_path: str,
    gst_available: bool,
) -> str:
    raw = "|".join(
        [
            input_hint,
            normalize_send_quality(send_quality),
            audio_mode or "",
            "1" if contingency_on else "0",
            demo_path or "",
            ffmpeg_path or "",
            "gst1" if gst_available else "gst0",
        ]
    )
    return str(abs(hash(raw)))


def detect_ffmpeg_capability(ffmpeg_path: Optional[str] = None) -> EngineCapability:
    from effective_config import shared_bin_dir

    candidates: list[Path] = []
    if ffmpeg_path:
        candidates.append(Path(ffmpeg_path))
    candidates.append(shared_bin_dir() / "ffmpeg" / "bin" / "ffmpeg.exe")
    candidates.append(shared_bin_dir() / "ffmpeg.exe")
    env = os.environ.get("FFMPEG", "").strip()
    if env:
        candidates.append(Path(env))
    for candidate in candidates:
        if candidate.is_file():
            return EngineCapability(
                engine=ENGINE_FFMPEG,
                available=True,
                mode=MODE_TRANSCODE,
                reason="FFmpeg disponível.",
            )
    # Em desenvolvimento Unix, aceitar nome no PATH apenas se existir como ficheiro absoluto.
    return EngineCapability(
        engine=ENGINE_FFMPEG,
        available=False,
        mode=MODE_TRANSCODE,
        reason="FFmpeg não encontrado nos caminhos da instalação.",
    )


def detect_gstreamer_capability(
    bin_dir: Optional[Path] = None,
) -> EngineCapability:
    """Runtime oficial + auxiliar empacotado (gst-launch). Sem exigir gi/PyGObject."""

    root = bin_dir or shared_bin_dir()
    helper = root / "gst_rtmps_helper.exe"
    if not helper.is_file():
        helper_py = Path(__file__).with_name("gst_rtmps_helper.py")
        helper_ok = helper_py.is_file()
    else:
        helper_ok = True

    gst_bin = root / "gstreamer" / "bin"
    launch = gst_bin / "gst-launch-1.0.exe"
    inspect = gst_bin / "gst-inspect-1.0.exe"
    runtime_ok = (launch.is_file() and inspect.is_file()) or bool(
        os.environ.get("BWB_GST_TEST_AVAILABLE")
    )

    available = bool(helper_ok and runtime_ok)
    if available:
        return EngineCapability(
            engine=ENGINE_GSTREAMER,
            available=True,
            mode=MODE_COPY,
            reason="GStreamer (cópia via gst-launch) disponível.",
        )
    reasons = []
    if not helper_ok:
        reasons.append("auxiliar ausente")
    if not runtime_ok:
        reasons.append("runtime/gst-launch ausente")
    return EngineCapability(
        engine=ENGINE_GSTREAMER,
        available=False,
        mode=MODE_COPY,
        reason="GStreamer indisponível (" + ", ".join(reasons) + ").",
    )


def probe_source_from_ffprobe(
    *,
    ffprobe: str,
    input_args: Sequence[str],
    timeout: float = 7.0,
    cancel_event: Any = None,
) -> SourceProbeSummary:
    """Sondagem curta; indeterminado ≠ incompatível."""

    import subprocess

    if cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)():
        return SourceProbeSummary(
            analysis=ANALYSIS_INDETERMINATE, reason="Sondagem cancelada."
        )

    if not ffprobe:
        return SourceProbeSummary(
            analysis=ANALYSIS_INDETERMINATE,
            reason="ffprobe indisponível; análise incompleta.",
        )

    # Extrair URL/ficheiro de -i
    media = None
    args_list = list(input_args)
    try:
        idx = args_list.index("-i")
        if idx + 1 < len(args_list):
            media = args_list[idx + 1]
    except ValueError:
        media = None
    if not media:
        return SourceProbeSummary(
            analysis=ANALYSIS_INDETERMINATE,
            reason="Fonte de entrada não identificada.",
        )

    cmd = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "stream=codec_type,codec_name,width,height,r_frame_rate,channels,sample_rate",
        "-of",
        "json",
        media,
    ]
    # Reutilizar flags RTSP comuns se presentes
    for flag in ("-rtsp_transport", "-rtsp_flags"):
        if flag in args_list:
            i = args_list.index(flag)
            if i + 1 < len(args_list):
                cmd[1:1] = [flag, args_list[i + 1]]

    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return SourceProbeSummary(
            analysis=ANALYSIS_INDETERMINATE,
            reason="Sondagem excedeu o tempo limite.",
        )
    except FileNotFoundError:
        return SourceProbeSummary(
            analysis=ANALYSIS_INDETERMINATE,
            reason="ffprobe não encontrado.",
        )
    except OSError as exc:
        return SourceProbeSummary(
            analysis=ANALYSIS_INDETERMINATE,
            reason=f"Falha de sondagem ({exc.__class__.__name__}).",
        )

    if completed.returncode != 0:
        err = (completed.stderr or "").strip().lower()
        if "401" in err or "403" in err or "auth" in err:
            return SourceProbeSummary(
                analysis=ANALYSIS_INDETERMINATE,
                reason="Autenticação/rede impediu a sondagem.",
            )
        return SourceProbeSummary(
            analysis=ANALYSIS_INDETERMINATE,
            reason="Sondagem sem dados suficientes.",
        )

    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        return SourceProbeSummary(
            analysis=ANALYSIS_INDETERMINATE,
            reason="Resposta de sondagem inválida.",
        )

    streams = payload.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None:
        return SourceProbeSummary(
            analysis=ANALYSIS_INCOMPATIBLE,
            reason="Fonte sem fluxo de vídeo.",
        )

    codec = str(video.get("codec_name") or "").lower() or None
    is_h264 = codec in {"h264", "avc1", "avc"} if codec else None
    fps = None
    rate = video.get("r_frame_rate")
    if isinstance(rate, str) and "/" in rate:
        try:
            num, den = rate.split("/", 1)
            fps = float(num) / float(den) if float(den) else None
        except (TypeError, ValueError, ZeroDivisionError):
            fps = None

    return SourceProbeSummary(
        video_codec=codec,
        width=int(video["width"]) if video.get("width") else None,
        height=int(video["height"]) if video.get("height") else None,
        fps=fps,
        audio_codec=(str(audio.get("codec_name")).lower() if audio else None),
        audio_channels=(
            int(audio["channels"]) if audio and audio.get("channels") else None
        ),
        audio_rate=(
            int(audio["sample_rate"]) if audio and audio.get("sample_rate") else None
        ),
        is_h264=is_h264,
        gop_known=False,
        bitrate_known=False,
        analysis=(
            ANALYSIS_COMPATIBLE
            if is_h264
            else (ANALYSIS_INCOMPATIBLE if is_h264 is False else ANALYSIS_INDETERMINATE)
        ),
        reason=(
            "Fonte H.264 detetada."
            if is_h264
            else (
                f"Codec de vídeo incompatível com cópia GStreamer ({codec})."
                if is_h264 is False
                else "Codec de vídeo indeterminado na sondagem curta."
            )
        ),
    )


def evaluate_eligibility(
    *,
    preference: str,
    send_quality: str,
    contingency_on: bool,
    mp4_ok: Optional[bool],
    ffmpeg_cap: EngineCapability,
    gst_cap: EngineCapability,
    probe: SourceProbeSummary,
) -> list[EngineEligibility]:
    """Calcula elegibilidade; incompatível conhecido nunca é contornado por indeterminado."""

    requires_xform = quality_requires_transcode(send_quality)
    results: list[EngineEligibility] = []

    # FFmpeg (transcode): elegível se disponível; não bloquear por GOP/bitrate
    # desconhecidos nem por codec não-H.264 (recodifica).
    if ffmpeg_cap.available:
        no_video = (
            probe.analysis == ANALYSIS_INCOMPATIBLE
            and probe.is_h264 is None
            and not probe.video_codec
            and "sem fluxo de vídeo" in (probe.reason or "").lower()
        )
        ff_analysis = ANALYSIS_INCOMPATIBLE if no_video else ANALYSIS_COMPATIBLE
        ff_reason = (
            (probe.reason or "Fonte sem vídeo.")
            if no_video
            else "FFmpeg (recodificação) elegível."
        )
        results.append(
            EngineEligibility(
                engine=ENGINE_FFMPEG,
                mode=MODE_TRANSCODE,
                eligible=not no_video,
                analysis=ff_analysis,
                reason=ff_reason,
            )
        )
    else:
        results.append(
            EngineEligibility(
                engine=ENGINE_FFMPEG,
                mode=MODE_TRANSCODE,
                eligible=False,
                analysis=ANALYSIS_INCOMPATIBLE,
                reason=ffmpeg_cap.reason,
            )
        )

    # GStreamer copy
    if not gst_cap.available:
        results.append(
            EngineEligibility(
                engine=ENGINE_GSTREAMER,
                mode=MODE_COPY,
                eligible=False,
                analysis=ANALYSIS_INCOMPATIBLE,
                reason=gst_cap.reason,
            )
        )
    elif requires_xform:
        results.append(
            EngineEligibility(
                engine=ENGINE_GSTREAMER,
                mode=MODE_COPY,
                eligible=False,
                analysis=ANALYSIS_INCOMPATIBLE,
                reason=(
                    "GStreamer (cópia) não é elegível quando a qualidade "
                    "exige transformação/recodificação."
                ),
            )
        )
    elif contingency_on and mp4_ok is False:
        results.append(
            EngineEligibility(
                engine=ENGINE_GSTREAMER,
                mode=MODE_COPY,
                eligible=False,
                analysis=ANALYSIS_INCOMPATIBLE,
                reason="Contingência ON: MP4 local incompatível com cópia H.264.",
            )
        )
    elif probe.analysis == ANALYSIS_INCOMPATIBLE and probe.is_h264 is False:
        results.append(
            EngineEligibility(
                engine=ENGINE_GSTREAMER,
                mode=MODE_COPY,
                eligible=False,
                analysis=ANALYSIS_INCOMPATIBLE,
                reason=probe.reason or "Fonte incompatível com cópia H.264.",
            )
        )
    elif probe.analysis == ANALYSIS_INDETERMINATE:
        results.append(
            EngineEligibility(
                engine=ENGINE_GSTREAMER,
                mode=MODE_COPY,
                eligible=False,
                analysis=ANALYSIS_INDETERMINATE,
                reason="Análise indeterminada; GStreamer cópia não confirmado.",
            )
        )
    else:
        results.append(
            EngineEligibility(
                engine=ENGINE_GSTREAMER,
                mode=MODE_COPY,
                eligible=True,
                analysis=ANALYSIS_COMPATIBLE,
                reason="GStreamer (cópia H.264) elegível.",
            )
        )

    _ = preference  # preferência aplicada em select_engine
    return results


def select_engine(
    *,
    preference: str,
    eligibilities: Sequence[EngineEligibility],
    last_successful: Optional[str] = None,
    ffmpeg_available: bool = True,
) -> EngineSelection:
    pref = normalize_engine_preference(preference)
    by_engine = {item.engine: item for item in eligibilities}

    def _pick(engine: str, reason: str) -> EngineSelection:
        item = by_engine[engine]
        return EngineSelection(
            preference=pref,
            engine=engine,
            mode=item.mode,
            reason=reason,
            eligibilities=tuple(eligibilities),
        )

    if pref in {ENGINE_FFMPEG, ENGINE_GSTREAMER}:
        item = by_engine.get(pref)
        if item is None or not item.eligible:
            reason = item.reason if item is not None else f"Motor {pref} indisponível."
            raise ValueError(
                f"Motor '{pref}' não pode iniciar: {reason} "
                "Altere o motor ou as definições e reinicie."
            )
        return _pick(pref, f"Seleção manual: {pref} ({item.mode}).")

    # Automático
    eligible = [e for e in eligibilities if e.eligible]
    if not eligible:
        # Indeterminado → FFmpeg apenas se disponível e sem incompatibilidade conhecida.
        ff = by_engine.get(ENGINE_FFMPEG)
        known_incompatible = bool(
            ff is not None and ff.analysis == ANALYSIS_INCOMPATIBLE
        )
        if (
            ffmpeg_available
            and ff is not None
            and not known_incompatible
            and ff.analysis == ANALYSIS_INDETERMINATE
        ):
            return EngineSelection(
                preference=pref,
                engine=ENGINE_FFMPEG,
                mode=MODE_TRANSCODE,
                reason=(
                    "Automático: análise indeterminada; a usar FFmpeg "
                    "(sem incompatibilidade conhecida)."
                ),
                eligibilities=tuple(eligibilities),
            )
        # Também: se FFmpeg elegível ficou de fora por outro motivo — já coberto.
        # Se Gst indeterminado e FFmpeg disponível sem incompatibilidade:
        if (
            ffmpeg_available
            and ff is not None
            and ff.analysis != ANALYSIS_INCOMPATIBLE
            and any(e.analysis == ANALYSIS_INDETERMINATE for e in eligibilities)
        ):
            return EngineSelection(
                preference=pref,
                engine=ENGINE_FFMPEG,
                mode=MODE_TRANSCODE,
                reason=(
                    "Automático: determinação incompleta; a usar FFmpeg "
                    "(sem incompatibilidade conhecida)."
                ),
                eligibilities=tuple(eligibilities),
            )
        details = "; ".join(f"{e.engine}: {e.reason}" for e in eligibilities)
        raise ValueError("Nenhum motor elegível para a configuração pedida. " + details)

    last = normalize_engine_preference(last_successful) if last_successful else None
    if last and last != ENGINE_AUTOMATIC:
        for item in eligible:
            if item.engine == last:
                return _pick(
                    item.engine,
                    f"Automático: último motor com envio confirmado ({last}).",
                )

    # Sem histórico: FFmpeg primeiro
    for engine in (ENGINE_FFMPEG, ENGINE_GSTREAMER):
        for item in eligible:
            if item.engine == engine:
                return _pick(
                    item.engine,
                    f"Automático: ordem fixa sem histórico ({engine}).",
                )

    chosen = eligible[0]
    return _pick(chosen.engine, f"Automático: {chosen.engine}.")


def resolve_engine_for_session(
    *,
    effective: Optional[EffectiveConfig] = None,
    send_quality: str,
    audio_mode: str = "silent",
    contingency_on: bool = False,
    mp4_path: str = "",
    mp4_ok: Optional[bool] = None,
    input_args: Optional[Sequence[str]] = None,
    ffmpeg_path: Optional[str] = None,
    ffprobe_path: Optional[str] = None,
    data_dir: Optional[Path] = None,
    skip_probe: bool = False,
    probe_override: Optional[SourceProbeSummary] = None,
) -> EngineSelection:
    cfg = effective or load_effective_config(data_dir)
    quality = normalize_send_quality(send_quality)
    # Gst manual: qualidade da fonte (presets antigos não bloqueiam após UI).
    if (
        normalize_engine_preference(cfg.engine_preference) == ENGINE_GSTREAMER
        and quality != SEND_QUALITY_SOURCE
    ):
        quality = SEND_QUALITY_SOURCE

    ffmpeg_cap = detect_ffmpeg_capability(ffmpeg_path)
    # Em testes/dev, se FFMPEG env aponta para nome simples, marcar disponível.
    if not ffmpeg_cap.available and ffmpeg_path and Path(ffmpeg_path).name:
        if os.environ.get("BWB_FFMPEG_TEST_AVAILABLE") or (
            ffmpeg_path in {"ffmpeg", "ffmpeg.exe"}
        ):
            ffmpeg_cap = EngineCapability(
                engine=ENGINE_FFMPEG,
                available=True,
                mode=MODE_TRANSCODE,
                reason="FFmpeg (ambiente de teste/PATH).",
            )

    gst_cap = detect_gstreamer_capability()
    fingerprint = config_fingerprint(
        input_hint="|".join(input_args or []),
        send_quality=quality,
        audio_mode=audio_mode,
        contingency_on=contingency_on,
        demo_path=mp4_path or "",
        ffmpeg_path=ffmpeg_path or "",
        gst_available=gst_cap.available,
    )

    if probe_override is not None:
        probe = probe_override
    elif skip_probe:
        probe = SourceProbeSummary(
            analysis=ANALYSIS_INDETERMINATE,
            reason="Sondagem omitida.",
            config_fingerprint=fingerprint,
        )
    else:
        cached = load_compat_cache(data_dir)
        if cached and cached.is_fresh(fingerprint):
            probe = SourceProbeSummary(
                **{
                    **{
                        "video_codec": None,
                        "width": None,
                        "height": None,
                        "fps": None,
                        "audio_codec": None,
                        "audio_channels": None,
                        "audio_rate": None,
                        "is_h264": None,
                        "gop_known": False,
                        "bitrate_known": False,
                        "analysis": ANALYSIS_INDETERMINATE,
                        "reason": "",
                        "config_fingerprint": fingerprint,
                    },
                    **cached.probe,
                }
            )
        else:
            probe = probe_source_from_ffprobe(
                ffprobe=ffprobe_path or "ffprobe",
                input_args=input_args or [],
            )
            save_compat_cache(
                CompatCache(
                    fingerprint=fingerprint,
                    saved_at=time.time(),
                    probe={
                        k: v
                        for k, v in asdict(probe).items()
                        if k != "config_fingerprint"
                    },
                ),
                data_dir,
            )

    if contingency_on and mp4_ok is None and mp4_path:
        # Validação mínima: ficheiro existe (codec detalhado fica para sondagem).
        mp4_ok = Path(mp4_path).is_file()

    eligibilities = evaluate_eligibility(
        preference=cfg.engine_preference,
        send_quality=quality,
        contingency_on=contingency_on,
        mp4_ok=mp4_ok,
        ffmpeg_cap=ffmpeg_cap,
        gst_cap=gst_cap,
        probe=probe,
    )
    selection = select_engine(
        preference=cfg.engine_preference,
        eligibilities=eligibilities,
        last_successful=cfg.last_successful_engine,
        ffmpeg_available=ffmpeg_cap.available,
    )
    return EngineSelection(
        preference=selection.preference,
        engine=selection.engine,
        mode=selection.mode,
        reason=selection.reason,
        probe=probe,
        eligibilities=selection.eligibilities,
    )
