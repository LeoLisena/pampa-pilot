"""Servidor MCP v2 para controlar REAPER mediante el puente local."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Mapping

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from .bridge_client import BridgeClient
from .deesser_proposal import (
    build_deesser_application_payload,
    propose_deesser as build_deesser_proposal,
)
from .gate_proposal import (
    build_reagate_application_payload,
    propose_reagate as build_reagate_proposal,
)
from .media_discovery import (
    discover_song_media as discover_song_media_files,
    resolve_input_file,
    resolve_output_directory,
    resolve_output_file,
)
from .mastering_qc import (
    build_master_delivery_qc,
    build_project_master_delivery_qc,
)
from .mastering_proposal import (
    build_mastering_application_payload,
    build_mastering_proposal,
)
from .midi_cleanup import (
    CleanupConfig,
    analyze_midi_file,
    preview_cleanup,
    run_cleanup,
)
from .midi_import import build_midi_import_payload
from .processing_proposal import (
    build_processing_application_payload,
    propose_track_processing as build_track_processing_proposal,
)
from .production_plan import (
    build_listening_preparation_payload,
    build_production_plan,
)
from .render_workflow import build_rendered_master_candidate_report
from .song_preparation import (
    SongPreparationConfig,
    build_song_manifest,
    prepare_song as write_prepared_song,
)
from .song_diagnosis import diagnose_song as build_song_diagnosis
from .song_processing_strategy import build_song_processing_strategy


mcp = MCPServer(
    "PampaPilot",
    instructions=(
        "Controla únicamente el proyecto REAPER activo mediante acciones permitidas. "
        "Antes de mutar, llama health_check y conserva project_ref. Usa GUID, nunca "
        "índices observados previamente. Después de cada mutación inspecciona "
        "observations.state_verified. No afirmes verificación de señal o perceptual "
        "si sus indicadores son false. Las ediciones producen transacciones undo; "
        "save_project_as cambia la identidad del proyecto y devuelve un project_ref nuevo. "
        "Las herramientas MIDI offline no requieren REAPER: preview_midi_cleanup nunca "
        "escribe y clean_midi_files conserva los originales y sólo escribe en sessions/. "
        "preview_song_preparation planifica una sesión sin escribir; prepare_song sólo "
        "crea un manifiesto bajo sessions/ y nunca importa en REAPER."
    ),
)
_bridge = BridgeClient()


class AudioImportItem(BaseModel):
    file_path: Annotated[str, Field(min_length=1, max_length=4096)]
    track_name: Annotated[str, Field(min_length=1, max_length=128)]
    position_seconds: Annotated[float, Field(ge=0.0)] = 0.0


class TrackMixItem(BaseModel):
    track_guid: Annotated[str, Field(min_length=1, max_length=64)]
    volume_db: Annotated[float | None, Field(ge=-60.0, le=12.0)] = None
    pan: Annotated[float | None, Field(ge=-1.0, le=1.0)] = None
    muted: bool | None = None


class MidiCleanupOptions(BaseModel):
    bpm: Annotated[float | None, Field(ge=20.0, le=400.0)] = None
    profile: Literal["generic", "guitar", "bass", "piano", "drums"] = "generic"
    minimum_pitch: Annotated[int | None, Field(ge=0, le=127)] = None
    maximum_pitch: Annotated[int | None, Field(ge=0, le=127)] = None
    quantize: bool = False
    quantize_division: Annotated[int, Field(ge=1, le=64)] = 16
    quantize_tolerance_fraction: Annotated[float, Field(ge=0.0, le=0.5)] = 0.125
    propose_missing_notes: bool = True


class MidiImportItem(BaseModel):
    file_path: Annotated[str, Field(min_length=1, max_length=4096)]
    track_name: Annotated[str, Field(min_length=1, max_length=128)]
    position_quarter_notes: Annotated[float, Field(ge=0.0, le=1_000_000.0)] = 0.0
    muted: bool = True


class ProcessingFxBinding(BaseModel):
    processor: Literal["reaeq", "reacomp"]
    fx_guid: Annotated[str | None, Field(min_length=1, max_length=64)] = None


class StemSourceOverride(BaseModel):
    track_name: Annotated[str, Field(min_length=1, max_length=128)]
    source_kind: Literal["suno_stems", "organic_multitrack", "unknown"]


class RenderSettingsSnapshot(BaseModel):
    render_settings_flags: Annotated[float, Field(ge=0, le=1_048_575)]
    render_bounds_flag: Annotated[float, Field(ge=0, le=7)]
    render_channels: Annotated[float, Field(ge=1, le=64)]
    render_sample_rate_hz: Annotated[float, Field(ge=0, le=192_000)]
    render_start_seconds: Annotated[float, Field(ge=0, le=86_400)]
    render_end_seconds: Annotated[float, Field(ge=0, le=86_400)]
    render_tail_flags: Annotated[float, Field(ge=0, le=63)]
    render_tail_ms: Annotated[float, Field(ge=0, le=600_000)]
    render_add_to_project_flags: Annotated[float, Field(ge=0, le=3)]
    render_dither_flags: Annotated[float, Field(ge=0, le=31)]
    render_normalize_flags: Annotated[float, Field(ge=0, le=16_777_215)]
    render_directory: Annotated[str, Field(max_length=4096)]
    render_pattern: Annotated[str, Field(max_length=512)]
    render_format_configuration: Annotated[str, Field(max_length=512)]
    render_secondary_format_configuration: Annotated[str, Field(max_length=512)]


def _call(
    action: str,
    params: dict[str, Any] | None = None,
    *,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    return _bridge.call(action, params, timeout_seconds=timeout_seconds).to_dict()


def _midi_config(options: MidiCleanupOptions | None) -> CleanupConfig:
    options = options or MidiCleanupOptions()
    return CleanupConfig(
        bpm=options.bpm,
        profile=options.profile,
        minimum_pitch=options.minimum_pitch,
        maximum_pitch=options.maximum_pitch,
        quantize_division=options.quantize_division,
        quantize_tolerance_fraction=options.quantize_tolerance_fraction,
        enable_quantization=options.quantize,
        propose_missing_notes=options.propose_missing_notes,
    )


@mcp.tool(
    title="Descubrir medios de una canción",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
def discover_song_media(
    song_name: Annotated[str, Field(min_length=1, max_length=128)],
) -> dict[str, object]:
    """Encuentra stems, MIDI, referencia y pares sugeridos sin abrir REAPER."""

    return discover_song_media_files(song_name)


@mcp.tool(
    title="Analizar estructura MIDI",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
def analyze_midi(
    midi_path: Annotated[str, Field(min_length=1, max_length=4096)],
) -> dict[str, Any]:
    """Lee notas, tempo y defectos estructurales; no escribe archivos."""

    path = resolve_input_file(midi_path, suffixes={".mid", ".midi"})
    return analyze_midi_file(path)


@mcp.tool(
    title="Previsualizar control técnico de master",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
def preview_master_delivery_qc(
    file_path: Annotated[str, Field(min_length=1, max_length=4096)],
    profile: Literal["spotify_streaming"] = "spotify_streaming",
) -> dict[str, Any]:
    """Mide el archivo final y simula normalización; no modifica audio ni REAPER."""

    audio_path = resolve_input_file(file_path, suffixes={".wav", ".flac"})
    return build_master_delivery_qc(audio_path, profile_name=profile)


@mcp.tool(
    title="Previsualizar control de master vinculado a REAPER",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
def preview_project_master_delivery_qc(
    project_ref: str,
    file_path: Annotated[str, Field(min_length=1, max_length=4096)],
    profile: Literal["spotify_streaming"] = "spotify_streaming",
) -> dict[str, Any]:
    """Cruza ajustes de render verificados con mediciones del archivo final."""

    render_reply = _call("get_render_settings", {"project_ref": project_ref})
    audio_path = resolve_input_file(file_path, suffixes={".wav", ".flac"})
    file_report = build_master_delivery_qc(audio_path, profile_name=profile)
    return build_project_master_delivery_qc(render_reply["result"], file_report)


@mcp.tool(
    title="Renderizar y verificar candidato de master",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
def render_and_verify_master_candidate(
    project_ref: str,
    output_file: Annotated[str, Field(min_length=1, max_length=4096)],
    sample_rate_hz: Annotated[int, Field(ge=44100, le=192000)] = 48000,
    profile: Literal["spotify_streaming"] = "spotify_streaming",
) -> dict[str, Any]:
    """Renderiza un WAV único en REAPER, lo mide y vincula su procedencia."""

    output_path = resolve_output_file(
        output_file, suffixes={".wav"}, require_absent=True
    )
    render_reply = _call(
        "render_master_candidate",
        {
            "project_ref": project_ref,
            "output_file": str(output_path),
            "sample_rate_hz": sample_rate_hz,
        },
        timeout_seconds=900.0,
    )
    report: dict[str, Any] | None = None
    analysis_error: Exception | None = None
    try:
        rendered_path = resolve_input_file(output_path, suffixes={".wav"})
        file_report = build_master_delivery_qc(
            rendered_path, profile_name=profile
        )
        report = build_rendered_master_candidate_report(render_reply, file_report)
    except Exception as exc:
        analysis_error = exc
    snapshot = render_reply["result"].get("previous_render_settings")
    try:
        restore_reply = _call(
            "restore_render_settings",
            {
                "project_ref": project_ref,
                "output_file": str(output_path),
                "snapshot": snapshot,
            },
            timeout_seconds=30.0,
        )
    except Exception as exc:
        if report is not None:
            report["render_settings_restoration"] = {
                "state_verified": False,
                "error": {"type": type(exc).__name__, "message": str(exc)},
            }
            return report
        return {
            "schema_version": "0.1",
            "kind": "pampapilot_rendered_master_candidate_analysis_failed",
            "render_reply": render_reply,
            "error": {
                "type": type(analysis_error).__name__,
                "message": str(analysis_error),
            },
            "render_settings_restoration": {
                "state_verified": False,
                "error": {"type": type(exc).__name__, "message": str(exc)},
            },
            "verification": {
                "state_verified": True,
                "signal_verified": False,
                "perceptually_evaluated": False,
            },
        }
    if report is not None:
        report["render_settings_restoration"] = {
            "state_verified": restore_reply["observations"]["state_verified"],
            "request_id": restore_reply["request_id"],
        }
        return report
    return {
        "schema_version": "0.1",
        "kind": "pampapilot_rendered_master_candidate_analysis_failed",
        "render_reply": render_reply,
        "error": {
            "type": type(analysis_error).__name__,
            "message": str(analysis_error),
        },
        "render_settings_restoration": {
            "state_verified": restore_reply["observations"]["state_verified"],
            "request_id": restore_reply["request_id"],
        },
        "verification": {
            "state_verified": True,
            "signal_verified": False,
            "perceptually_evaluated": False,
        },
    }


@mcp.tool(
    title="Previsualizar propuesta de limitador del master",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
def preview_mastering_proposal(
    file_path: Annotated[str, Field(min_length=1, max_length=4096)],
    profile: Literal["spotify_streaming"] = "spotify_streaming",
) -> dict[str, Any]:
    """Propone ReaLimit sólo si el archivo medido necesita margen de pico."""

    audio_path = resolve_input_file(file_path, suffixes={".wav", ".flac"})
    file_report = build_master_delivery_qc(audio_path, profile_name=profile)
    return build_mastering_proposal(file_report)


@mcp.tool(
    title="Aplicar propuesta aprobada de limitador del master",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
def apply_mastering_proposal(
    project_ref: str,
    file_path: Annotated[str, Field(min_length=1, max_length=4096)],
    approved_proposal_id: Annotated[str, Field(pattern=r"^[0-9a-f]{24}$")],
    fx_guid: Annotated[str | None, Field(min_length=1, max_length=64)] = None,
    profile: Literal["spotify_streaming"] = "spotify_streaming",
) -> dict[str, Any]:
    """Recalcula y aplica exactamente una propuesta ReaLimit vigente."""

    audio_path = resolve_input_file(file_path, suffixes={".wav", ".flac"})
    file_report = build_master_delivery_qc(audio_path, profile_name=profile)
    proposal = build_mastering_proposal(file_report)
    payload = build_mastering_application_payload(
        proposal, approved_proposal_id, fx_guid
    )
    return _call(
        "apply_mastering_limiter",
        {"project_ref": project_ref, **payload},
        timeout_seconds=30.0,
    )


@mcp.tool(
    title="Proponer procesamiento de una pista",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
def propose_track_processing(
    file_path: Annotated[str, Field(min_length=1, max_length=4096)],
    role: Literal[
        "lead_vocal", "backing_vocals", "bass", "drums", "guitar", "strings"
    ],
    source_kind: Literal[
        "suno_stems", "organic_multitrack", "unknown"
    ] = "unknown",
) -> dict[str, Any]:
    """Analiza un WAV y propone una cadena auditable sin modificar REAPER."""

    audio_path = resolve_input_file(file_path, suffixes={".wav"})
    return build_track_processing_proposal(audio_path, role, source_kind)


@mcp.tool(
    title="Proponer limpieza conservadora con ReaGate",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
def preview_reagate_proposal(
    file_path: Annotated[str, Field(min_length=1, max_length=4096)],
    role: Literal["lead_vocal", "guitar"],
    source_kind: Literal[
        "suno_stems", "organic_multitrack", "unknown"
    ] = "unknown",
) -> dict[str, Any]:
    """Mide silencios y sólo propone puerta cuando existe separación suficiente."""

    audio_path = resolve_input_file(file_path, suffixes={".wav"})
    return build_reagate_proposal(audio_path, role, source_kind)


@mcp.tool(
    title="Aplicar propuesta aprobada de ReaGate",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
def apply_reagate_proposal(
    project_ref: str,
    track_guid: Annotated[str, Field(min_length=1, max_length=64)],
    file_path: Annotated[str, Field(min_length=1, max_length=4096)],
    role: Literal["lead_vocal", "guitar"],
    approved_proposal_id: Annotated[str, Field(pattern=r"^[0-9a-f]{24}$")],
    fx_guid: Annotated[str | None, Field(min_length=1, max_length=64)] = None,
    source_kind: Literal[
        "suno_stems", "organic_multitrack", "unknown"
    ] = "unknown",
) -> dict[str, Any]:
    """Recalcula la evidencia y aplica sólo la propuesta vigente aprobada."""

    audio_path = resolve_input_file(file_path, suffixes={".wav"})
    proposal = build_reagate_proposal(audio_path, role, source_kind)
    payload = build_reagate_application_payload(
        proposal, approved_proposal_id, fx_guid
    )
    return _call(
        "apply_reagate_proposal",
        {"project_ref": project_ref, "track_guid": track_guid, **payload},
        timeout_seconds=30.0,
    )


@mcp.tool(
    title="Previsualizar de-esser vocal con ReaXcomp",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
def preview_deesser_proposal(
    file_path: Annotated[str, Field(min_length=1, max_length=4096)],
    source_kind: Literal[
        "suno_stems", "organic_multitrack", "unknown"
    ] = "unknown",
) -> dict[str, Any]:
    """Mide picos de 5-10 kHz y propone sólo compresión de la banda superior."""

    audio_path = resolve_input_file(file_path, suffixes={".wav"})
    return build_deesser_proposal(audio_path, source_kind)


@mcp.tool(
    title="Aplicar propuesta aprobada de de-esser",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
def apply_deesser_proposal(
    project_ref: str,
    track_guid: Annotated[str, Field(min_length=1, max_length=64)],
    file_path: Annotated[str, Field(min_length=1, max_length=4096)],
    approved_proposal_id: Annotated[str, Field(pattern=r"^[0-9a-f]{24}$")],
    fx_guid: Annotated[str | None, Field(min_length=1, max_length=64)] = None,
    source_kind: Literal[
        "suno_stems", "organic_multitrack", "unknown"
    ] = "unknown",
) -> dict[str, Any]:
    """Recalcula y aplica sólo la propuesta de de-esser vigente aprobada."""

    audio_path = resolve_input_file(file_path, suffixes={".wav"})
    proposal = build_deesser_proposal(audio_path, source_kind)
    payload = build_deesser_application_payload(
        proposal, approved_proposal_id, fx_guid
    )
    return _call(
        "apply_deesser_proposal",
        {"project_ref": project_ref, "track_guid": track_guid, **payload},
        timeout_seconds=30.0,
    )


@mcp.tool(
    title="Aplicar propuesta de procesamiento aprobada",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
def apply_processing_proposal(
    project_ref: str,
    track_guid: Annotated[str, Field(min_length=1, max_length=64)],
    file_path: Annotated[str, Field(min_length=1, max_length=4096)],
    role: Literal[
        "lead_vocal", "backing_vocals", "bass", "drums", "guitar", "strings"
    ],
    approved_proposal_id: Annotated[
        str, Field(min_length=24, max_length=24, pattern=r"^[0-9a-f]{24}$")
    ],
    bindings: Annotated[list[ProcessingFxBinding], Field(min_length=1, max_length=2)],
    source_kind: Literal[
        "suno_stems", "organic_multitrack", "unknown"
    ] = "unknown",
) -> dict[str, Any]:
    """Recalcula y aplica sólo la propuesta cuyo ID aprobó el usuario."""

    audio_path = resolve_input_file(file_path, suffixes={".wav"})
    proposal = build_track_processing_proposal(audio_path, role, source_kind)
    application = build_processing_application_payload(
        proposal,
        approved_proposal_id,
        [binding.model_dump() for binding in bindings],
    )
    return _call(
        "apply_processing_chain",
        {
            "project_ref": project_ref,
            "track_guid": track_guid,
            **application,
        },
        timeout_seconds=30.0,
    )


@mcp.tool(
    title="Previsualizar limpieza MIDI",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
def preview_midi_cleanup(
    midi_path: Annotated[str, Field(min_length=1, max_length=4096)],
    audio_path: Annotated[str, Field(min_length=1, max_length=4096)],
    options: MidiCleanupOptions | None = None,
) -> dict[str, Any]:
    """Compara MIDI/WAV y devuelve el plan completo sin crear ni cambiar archivos."""

    midi = resolve_input_file(midi_path, suffixes={".mid", ".midi"})
    audio = resolve_input_file(audio_path, suffixes={".wav"})
    return preview_cleanup(midi, audio, config=_midi_config(options))


@mcp.tool(
    title="Generar variantes MIDI limpias",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
def clean_midi_files(
    midi_path: Annotated[str, Field(min_length=1, max_length=4096)],
    audio_path: Annotated[str, Field(min_length=1, max_length=4096)],
    output_directory: Annotated[str, Field(min_length=1, max_length=4096)],
    options: MidiCleanupOptions | None = None,
) -> dict[str, Any]:
    """Conserva originales y escribe variantes auditables solamente en sessions/."""

    midi = resolve_input_file(midi_path, suffixes={".mid", ".midi"})
    audio = resolve_input_file(audio_path, suffixes={".wav"})
    output = resolve_output_directory(output_directory)
    return run_cleanup(midi, audio, output, config=_midi_config(options))


def _song_config(
    bpm: float,
    numerator: int,
    denominator: int,
    source_kind: Literal["suno_stems", "organic_multitrack", "unknown"],
    analysis_level: Literal["metadata", "signal"],
) -> SongPreparationConfig:
    return SongPreparationConfig(
        bpm=bpm,
        numerator=numerator,
        denominator=denominator,
        source_kind=source_kind,
        analysis_level=analysis_level,
    )


@mcp.tool(
    title="Previsualizar preparación de canción",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
def preview_song_preparation(
    song_name: Annotated[str, Field(min_length=1, max_length=128)],
    bpm: Annotated[float, Field(ge=20.0, le=400.0)],
    numerator: Annotated[int, Field(ge=1, le=32)] = 4,
    denominator: Literal[1, 2, 4, 8, 16, 32] = 4,
    source_kind: Literal["suno_stems", "organic_multitrack", "unknown"] = "suno_stems",
    analysis_level: Literal["metadata", "signal"] = "metadata",
) -> dict[str, Any]:
    """Valida medios y devuelve un plan de sesión sin escribir ni abrir REAPER."""

    return build_song_manifest(
        song_name,
        _song_config(bpm, numerator, denominator, source_kind, analysis_level),
    )


@mcp.tool(
    title="Preparar manifiesto de canción",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
def prepare_song(
    song_name: Annotated[str, Field(min_length=1, max_length=128)],
    bpm: Annotated[float, Field(ge=20.0, le=400.0)],
    numerator: Annotated[int, Field(ge=1, le=32)] = 4,
    denominator: Literal[1, 2, 4, 8, 16, 32] = 4,
    source_kind: Literal["suno_stems", "organic_multitrack", "unknown"] = "suno_stems",
    analysis_level: Literal["metadata", "signal"] = "metadata",
) -> dict[str, Any]:
    """Escribe song-manifest.json bajo sessions/; no ejecuta el plan de REAPER."""

    return write_prepared_song(
        song_name,
        _song_config(bpm, numerator, denominator, source_kind, analysis_level),
    )


@mcp.tool(
    title="Diagnosticar mezcla completa por procedencia",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
def diagnose_song(
    song_name: Annotated[str, Field(min_length=1, max_length=128)],
    bpm: Annotated[float, Field(ge=20.0, le=400.0)],
    default_source_kind: Literal[
        "suno_stems", "organic_multitrack", "unknown"
    ] = "unknown",
    source_overrides: Annotated[
        list[StemSourceOverride] | None, Field(max_length=128)
    ] = None,
) -> dict[str, Any]:
    """Reanaliza stems y genera hallazgos; no escribe ni modifica REAPER."""

    return build_song_diagnosis(
        song_name,
        bpm,
        default_source_kind,
        [override.model_dump() for override in (source_overrides or [])],
    )


@mcp.tool(
    title="Previsualizar estrategia de procesamiento por stem",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
def preview_song_processing_strategy(
    song_name: Annotated[str, Field(min_length=1, max_length=128)],
    bpm: Annotated[float, Field(ge=20.0, le=400.0)],
    default_source_kind: Literal[
        "suno_stems", "organic_multitrack", "unknown"
    ] = "unknown",
    source_overrides: Annotated[
        list[StemSourceOverride] | None, Field(max_length=128)
    ] = None,
) -> dict[str, Any]:
    """Propone sólo audiciones respaldadas por diagnóstico; no modifica REAPER."""

    diagnosis = build_song_diagnosis(
        song_name,
        bpm,
        default_source_kind,
        [override.model_dump() for override in (source_overrides or [])],
    )
    return build_song_processing_strategy(diagnosis)


def _build_current_production_plan(
    project_ref: str,
    song_name: str,
    bpm: float,
    default_source_kind: str,
    source_overrides: list[dict[str, Any]],
) -> dict[str, Any]:
    diagnosis = build_song_diagnosis(
        song_name,
        bpm,
        default_source_kind,
        source_overrides,
    )
    project_reply = _call("get_project_state")
    project_state = project_reply["result"]
    if project_state["project_ref"] != project_ref:
        raise ValueError("the active REAPER project changed while building the plan")
    details: dict[str, Mapping[str, Any]] = {}
    for track in project_state["tracks"]:
        if track["fx_count"] > 0:
            reply = _call(
                "get_track_state",
                {"project_ref": project_ref, "track_guid": track["guid"]},
            )
            details[track["guid"]] = reply["result"]
    return build_production_plan(diagnosis, project_state, details)


@mcp.tool(
    title="Previsualizar plan de producción",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
def preview_production_plan(
    project_ref: str,
    song_name: Annotated[str, Field(min_length=1, max_length=128)],
    bpm: Annotated[float, Field(ge=20.0, le=400.0)],
    default_source_kind: Literal[
        "suno_stems", "organic_multitrack", "unknown"
    ] = "unknown",
    source_overrides: Annotated[
        list[StemSourceOverride] | None, Field(max_length=128)
    ] = None,
) -> dict[str, Any]:
    """Cruza diagnóstico de señal con pistas y FX actuales; no modifica REAPER."""

    return _build_current_production_plan(
        project_ref,
        song_name,
        bpm,
        default_source_kind,
        [override.model_dump() for override in (source_overrides or [])],
    )


@mcp.tool(
    title="Comprobar conexión con REAPER",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
def health_check() -> dict[str, Any]:
    """Comprueba el puente y devuelve REAPER, proyecto activo y versiones."""

    return _call("health_check")


@mcp.tool(
    title="Leer proyecto de REAPER",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
def get_project_state() -> dict[str, Any]:
    """Lee pistas y estado básico del proyecto activo, sin modificarlo."""

    return _call("get_project_state")


@mcp.tool(
    title="Descubrir FX usados en el proyecto",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
def discover_project_fx(
    project_ref: str,
    query: Annotated[str | None, Field(min_length=1, max_length=128)] = None,
    track_guid: Annotated[str | None, Field(min_length=1, max_length=64)] = None,
    include_parameters: bool = False,
    max_parameters: Annotated[int, Field(ge=1, le=1000)] = 128,
) -> dict[str, Any]:
    """Filtra FX existentes y devuelve identidades estables; nunca los modifica."""

    payload: dict[str, Any] = {
        "project_ref": project_ref,
        "include_parameters": include_parameters,
        "max_parameters": max_parameters,
    }
    if query is not None:
        payload["query"] = query
    if track_guid is not None:
        payload["track_guid"] = track_guid
    return _call("discover_project_fx", payload)


@mcp.tool(
    title="Descubrir FX instalados en REAPER",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
def discover_installed_fx(
    project_ref: str,
    query: Annotated[str | None, Field(min_length=1, max_length=128)] = None,
    limit: Annotated[int, Field(ge=1, le=500)] = 100,
) -> dict[str, Any]:
    """Enumera nombres exactos de plugins disponibles para evitar adivinarlos."""

    payload: dict[str, Any] = {"project_ref": project_ref, "limit": limit}
    if query is not None:
        payload["query"] = query
    return _call("discover_installed_fx", payload)


@mcp.tool(
    title="Leer ajustes de render y master",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
def get_render_settings(project_ref: str) -> dict[str, Any]:
    """Lee render, destinos y FX del master sin modificar ni abrir el diálogo."""

    return _call("get_render_settings", {"project_ref": project_ref})


@mcp.tool(
    title="Leer pista master",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
def get_master_track_state(project_ref: str) -> dict[str, Any]:
    """Lee estado, identidad y parámetros FX del master sin modificarlo."""

    return _call("get_master_track_state", {"project_ref": project_ref})


@mcp.tool(
    title="Leer pista por GUID",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
def get_track_state(project_ref: str, track_guid: str) -> dict[str, Any]:
    """Lee una pista por GUID y exige que el proyecto activo no haya cambiado."""

    return _call(
        "get_track_state",
        {"project_ref": project_ref, "track_guid": track_guid},
    )


@mcp.tool(
    title="Crear pista en REAPER",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
def create_track(
    project_ref: str,
    name: Annotated[str, Field(min_length=1, max_length=128)],
    index: Annotated[int | None, Field(ge=0)] = None,
) -> dict[str, Any]:
    """Crea una pista, verifica el nombre y devuelve GUID y transacción reversible."""

    params: dict[str, Any] = {"project_ref": project_ref, "name": name}
    if index is not None:
        params["index"] = index
    return _call("create_track", params)


@mcp.tool(
    title="Ajustar paneo de pista",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
def set_track_pan(
    project_ref: str,
    track_guid: str,
    pan: Annotated[float, Field(ge=-1.0, le=1.0)],
) -> dict[str, Any]:
    """Ajusta paneo -1..1 y lo verifica; no sobrescribe automatización activa."""

    return _call(
        "set_track_pan",
        {"project_ref": project_ref, "track_guid": track_guid, "pan": pan},
    )


@mcp.tool(
    title="Ajustar volumen de pista",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
def set_track_volume(
    project_ref: str,
    track_guid: str,
    volume_db: Annotated[float, Field(ge=-60.0, le=12.0)],
) -> dict[str, Any]:
    """Ajusta volumen -60..+12 dB y verifica la lectura posterior."""

    return _call(
        "set_track_volume",
        {
            "project_ref": project_ref,
            "track_guid": track_guid,
            "volume_db": volume_db,
        },
    )


@mcp.tool(
    title="Silenciar o activar pista",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
def set_track_mute(
    project_ref: str,
    track_guid: str,
    muted: bool,
) -> dict[str, Any]:
    """Cambia el mute de una pista y verifica la lectura posterior."""

    return _call(
        "set_track_mute",
        {"project_ref": project_ref, "track_guid": track_guid, "muted": muted},
    )


@mcp.tool(
    title="Activar o quitar solo de pista",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
def set_track_solo(
    project_ref: str,
    track_guid: str,
    soloed: bool,
) -> dict[str, Any]:
    """Cambia el solo de una pista y verifica la lectura posterior."""

    return _call(
        "set_track_solo",
        {"project_ref": project_ref, "track_guid": track_guid, "soloed": soloed},
    )


@mcp.tool(
    title="Aplicar preparación aprobada para escuchar la mezcla",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
def apply_listening_preparation(
    project_ref: str,
    song_name: Annotated[str, Field(min_length=1, max_length=128)],
    bpm: Annotated[float, Field(ge=20.0, le=400.0)],
    approved_plan_id: Annotated[str, Field(pattern=r"^[0-9a-f]{24}$")],
    default_source_kind: Literal[
        "suno_stems", "organic_multitrack", "unknown"
    ] = "unknown",
    source_overrides: Annotated[
        list[StemSourceOverride] | None, Field(max_length=128)
    ] = None,
) -> dict[str, Any]:
    """Recalcula el plan y aplica sólo su preparación si el ID aprobado sigue vigente."""

    plan = _build_current_production_plan(
        project_ref,
        song_name,
        bpm,
        default_source_kind,
        [override.model_dump() for override in (source_overrides or [])],
    )
    payload = build_listening_preparation_payload(plan, approved_plan_id)
    return _call(
        "prepare_mix_listening",
        {"project_ref": project_ref, **payload},
    )


@mcp.tool(
    title="Aplicar mezcla estática en lote",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
def apply_track_mix_batch(
    project_ref: str,
    items: Annotated[list[TrackMixItem], Field(min_length=1, max_length=64)],
) -> dict[str, Any]:
    """Aplica volumen, paneo y mute como una sola transacción verificable."""

    return _call(
        "apply_track_mix_batch",
        {
            "project_ref": project_ref,
            "items": [item.model_dump(exclude_none=True) for item in items],
        },
    )


@mcp.tool(
    title="Agregar efecto nativo permitido",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
def add_stock_fx(
    project_ref: str,
    track_guid: str,
    fx_type: Literal["reacomp", "reaeq", "reagate", "reaxcomp"],
) -> dict[str, Any]:
    """Agrega ReaComp, ReaEQ, ReaGate o ReaXcomp y verifica su estado."""

    return _call(
        "add_stock_fx",
        {"project_ref": project_ref, "track_guid": track_guid, "fx_type": fx_type},
    )


@mcp.tool(
    title="Quitar FX de dinámica permitido de una pista",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
def remove_track_fx(
    project_ref: str,
    track_guid: Annotated[str, Field(min_length=1, max_length=64)],
    fx_guid: Annotated[str, Field(min_length=1, max_length=64)],
) -> dict[str, Any]:
    """Quita exclusivamente la instancia ReaGate o ReaXcomp indicada por GUID."""

    return _call(
        "remove_track_fx",
        {"project_ref": project_ref, "track_guid": track_guid, "fx_guid": fx_guid},
    )


@mcp.tool(
    title="Agregar ReaLimit al master",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
def add_master_stock_fx(
    project_ref: str,
    fx_type: Literal["realimit"],
) -> dict[str, Any]:
    """Agrega un ReaLimit único al master y devuelve su GUID y parámetros."""

    return _call(
        "add_master_stock_fx",
        {"project_ref": project_ref, "fx_type": fx_type},
    )


@mcp.tool(
    title="Restaurar ajustes de render",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
def restore_candidate_render_settings(
    project_ref: str,
    output_file: Annotated[str, Field(min_length=1, max_length=4096)],
    snapshot: RenderSettingsSnapshot,
) -> dict[str, Any]:
    """Restaura el snapshot previo sólo si el destino actual aún coincide."""

    output_path = resolve_input_file(output_file, suffixes={".wav"})
    return _call(
        "restore_render_settings",
        {
            "project_ref": project_ref,
            "output_file": str(output_path),
            "snapshot": snapshot.model_dump(),
        },
        timeout_seconds=30.0,
    )


@mcp.tool(
    title="Quitar ReaLimit del master",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
def remove_master_fx(
    project_ref: str,
    fx_guid: Annotated[str, Field(min_length=1, max_length=64)],
) -> dict[str, Any]:
    """Quita exclusivamente la instancia ReaLimit identificada por GUID."""

    return _call(
        "remove_master_fx",
        {"project_ref": project_ref, "fx_guid": fx_guid},
    )


@mcp.tool(
    title="Agregar instrumento virtual permitido",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
def add_instrument(
    project_ref: str,
    track_guid: str,
    instrument_type: Literal["reasynth"],
) -> dict[str, Any]:
    """Agrega ReaSynth y verifica GUID, estado y reconocimiento como instrumento."""

    return _call(
        "add_instrument",
        {
            "project_ref": project_ref,
            "track_guid": track_guid,
            "instrument_type": instrument_type,
        },
    )


@mcp.tool(
    title="Configurar compresor ReaComp",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
def configure_reacomp(
    project_ref: str,
    track_guid: str,
    fx_guid: str,
    threshold_db: Annotated[float, Field(ge=-60.0, le=0.0)],
    ratio: Annotated[float, Field(ge=1.0, le=10.0)],
    attack_ms: Annotated[float, Field(ge=0.0, le=200.0)],
    release_ms: Annotated[float, Field(ge=5.0, le=1000.0)],
    knee_db: Annotated[float, Field(ge=0.0, le=12.0)],
    rms_ms: Annotated[float, Field(ge=0.0, le=100.0)] = 5.0,
    auto_makeup: bool = False,
    auto_release: bool = False,
) -> dict[str, Any]:
    """Configura un ReaComp identificado por GUID y verifica los valores mostrados."""

    return _call(
        "configure_reacomp",
        {
            "project_ref": project_ref,
            "track_guid": track_guid,
            "fx_guid": fx_guid,
            "threshold_db": threshold_db,
            "ratio": ratio,
            "attack_ms": attack_ms,
            "release_ms": release_ms,
            "knee_db": knee_db,
            "rms_ms": rms_ms,
            "auto_makeup": auto_makeup,
            "auto_release": auto_release,
        },
    )


@mcp.tool(
    title="Configurar puerta ReaGate",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
def configure_reagate(
    project_ref: str,
    track_guid: Annotated[str, Field(min_length=1, max_length=64)],
    fx_guid: Annotated[str, Field(min_length=1, max_length=64)],
    threshold_db: Annotated[float, Field(ge=-42.0, le=0.0)],
    hysteresis_db: Annotated[float, Field(ge=-12.0, le=0.0)],
    attack_ms: Annotated[float, Field(ge=0.0, le=200.0)],
    release_ms: Annotated[float, Field(ge=5.0, le=2000.0)],
    pre_open_ms: Annotated[float, Field(ge=0.0, le=100.0)],
    hold_ms: Annotated[float, Field(ge=0.0, le=1000.0)],
    highpass_hz: Annotated[float, Field(ge=0.0, le=5000.0)],
    lowpass_hz: Annotated[float, Field(ge=1000.0, le=20000.0)],
    rms_ms: Annotated[float, Field(ge=0.0, le=100.0)] = 5.0,
) -> dict[str, Any]:
    """Configura un ReaGate por GUID y verifica valores y modos seguros."""

    return _call(
        "configure_reagate",
        {
            "project_ref": project_ref,
            "track_guid": track_guid,
            "fx_guid": fx_guid,
            "threshold_db": threshold_db,
            "hysteresis_db": hysteresis_db,
            "attack_ms": attack_ms,
            "release_ms": release_ms,
            "pre_open_ms": pre_open_ms,
            "hold_ms": hold_ms,
            "highpass_hz": highpass_hz,
            "lowpass_hz": lowpass_hz,
            "rms_ms": rms_ms,
        },
    )


@mcp.tool(
    title="Configurar de-esser ReaXcomp",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
def configure_deesser(
    project_ref: str,
    track_guid: Annotated[str, Field(min_length=1, max_length=64)],
    fx_guid: Annotated[str, Field(min_length=1, max_length=64)],
    crossover_hz: Annotated[float, Field(ge=4000.0, le=10000.0)],
    threshold_db: Annotated[float, Field(ge=-60.0, le=0.0)],
    ratio: Annotated[float, Field(ge=1.0, le=10.0)],
    knee_db: Annotated[float, Field(ge=0.0, le=12.0)],
    attack_ms: Annotated[float, Field(ge=0.0, le=50.0)],
    release_ms: Annotated[float, Field(ge=5.0, le=500.0)],
    rms_ms: Annotated[float, Field(ge=0.0, le=50.0)] = 0.0,
) -> dict[str, Any]:
    """Configura la banda superior y deja transparentes las tres inferiores."""

    return _call(
        "configure_deesser",
        {
            "project_ref": project_ref,
            "track_guid": track_guid,
            "fx_guid": fx_guid,
            "crossover_hz": crossover_hz,
            "threshold_db": threshold_db,
            "ratio": ratio,
            "knee_db": knee_db,
            "attack_ms": attack_ms,
            "release_ms": release_ms,
            "rms_ms": rms_ms,
        },
    )


@mcp.tool(
    title="Configurar una banda de ReaEQ",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
def configure_reaeq_band(
    project_ref: str,
    track_guid: str,
    fx_guid: str,
    band_index: Annotated[int, Field(ge=0, le=7)],
    band_type: Literal[
        "high_pass",
        "low_shelf",
        "bell",
        "notch",
        "high_shelf",
        "low_pass",
        "band_pass",
        "parallel_band_pass",
    ],
    frequency_hz: Annotated[float, Field(ge=20.0, le=20000.0)],
    gain_db: Annotated[float, Field(ge=-24.0, le=24.0)] = 0.0,
    q: Annotated[float, Field(ge=0.1, le=10.0)] = 0.71,
    enabled: bool = True,
) -> dict[str, Any]:
    """Configura una banda existente por tipo e índice y devuelve su estado."""

    return _call(
        "configure_reaeq_band",
        {
            "project_ref": project_ref,
            "track_guid": track_guid,
            "fx_guid": fx_guid,
            "band_index": band_index,
            "band_type": band_type,
            "frequency_hz": frequency_hz,
            "gain_db": gain_db,
            "q": q,
            "enabled": enabled,
        },
    )


@mcp.tool(
    title="Importar audio en una pista nueva",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
def import_audio(
    project_ref: str,
    file_path: Annotated[str, Field(min_length=1, max_length=4096)],
    track_name: Annotated[str, Field(min_length=1, max_length=128)],
    position_seconds: Annotated[float, Field(ge=0.0)] = 0.0,
) -> dict[str, Any]:
    """Importa un WAV permitido, verifica pista/ítem/toma y devuelve sus GUID."""

    return _call(
        "import_audio",
        {
            "project_ref": project_ref,
            "file_path": file_path,
            "track_name": track_name,
            "position_seconds": position_seconds,
        },
    )


@mcp.tool(
    title="Importar lote de audio",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
def import_audio_batch(
    project_ref: str,
    items: Annotated[list[AudioImportItem], Field(min_length=1, max_length=64)],
) -> dict[str, Any]:
    """Importa un lote de WAV como una sola transacción con verificación."""

    return _call(
        "import_audio_batch",
        {
            "project_ref": project_ref,
            "items": [item.model_dump() for item in items],
        },
    )


@mcp.tool(
    title="Importar MIDI validado",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
def import_midi(
    project_ref: str,
    file_path: Annotated[str, Field(min_length=1, max_length=4096)],
    track_name: Annotated[str, Field(min_length=1, max_length=128)],
    expected_bpm: Annotated[float | None, Field(ge=20.0, le=400.0)] = None,
    position_quarter_notes: Annotated[float, Field(ge=0.0, le=1_000_000.0)] = 0.0,
    muted: bool = True,
) -> dict[str, Any]:
    """Crea una pista MIDI sin diálogos y verifica todas las notas releídas."""

    midi_path = resolve_input_file(file_path, suffixes={".mid", ".midi"})
    item = build_midi_import_payload(
        midi_path,
        track_name,
        position_quarter_notes=position_quarter_notes,
        muted=muted,
        expected_bpm=expected_bpm,
    )
    return _call(
        "import_midi",
        {"project_ref": project_ref, **item},
        timeout_seconds=15.0,
    )


@mcp.tool(
    title="Importar lote MIDI validado",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
def import_midi_batch(
    project_ref: str,
    items: Annotated[list[MidiImportItem], Field(min_length=1, max_length=8)],
    expected_bpm: Annotated[float | None, Field(ge=20.0, le=400.0)] = None,
) -> dict[str, Any]:
    """Crea hasta ocho pistas MIDI dentro de una única transacción reversible."""

    payloads = []
    for item in items:
        midi_path = resolve_input_file(item.file_path, suffixes={".mid", ".midi"})
        payloads.append(
            build_midi_import_payload(
                midi_path,
                item.track_name,
                position_quarter_notes=item.position_quarter_notes,
                muted=item.muted,
                expected_bpm=expected_bpm,
            )
        )
    return _call(
        "import_midi_batch",
        {"project_ref": project_ref, "items": payloads},
        timeout_seconds=30.0,
    )


@mcp.tool(
    title="Ajustar tempo del proyecto",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
def set_project_tempo(
    project_ref: str,
    bpm: Annotated[float, Field(ge=20.0, le=400.0)],
) -> dict[str, Any]:
    """Ajusta BPM y verifica que posiciones, duraciones y playrate no cambien."""

    return _call(
        "set_project_tempo",
        {"project_ref": project_ref, "bpm": bpm},
    )


@mcp.tool(
    title="Guardar proyecto con nombre nuevo",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
def save_project_as(
    project_ref: str,
    project_path: Annotated[str, Field(min_length=1, max_length=4096)],
) -> dict[str, Any]:
    """Guarda como RPP nuevo dentro de las raíces de sesiones permitidas."""

    return _call(
        "save_project_as",
        {"project_ref": project_ref, "project_path": project_path},
    )


@mcp.tool(
    title="Deshacer transacción propia",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
def undo_transaction(project_ref: str, transaction_request_id: str) -> dict[str, Any]:
    """Deshace sólo la última transacción propia si el historial sigue intacto."""

    return _call(
        "undo_transaction",
        {
            "project_ref": project_ref,
            "transaction_request_id": transaction_request_id,
        },
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
