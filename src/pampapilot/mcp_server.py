"""Servidor MCP v2 para controlar REAPER mediante el puente local."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from .bridge_client import BridgeClient
from .media_discovery import (
    discover_song_media as discover_song_media_files,
    resolve_input_file,
    resolve_output_directory,
)
from .midi_cleanup import (
    CleanupConfig,
    analyze_midi_file,
    preview_cleanup,
    run_cleanup,
)
from .midi_import import build_midi_import_payload
from .processing_proposal import propose_track_processing as build_track_processing_proposal
from .song_preparation import (
    SongPreparationConfig,
    build_song_manifest,
    prepare_song as write_prepared_song,
)


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
    title="Proponer procesamiento de una pista",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
def propose_track_processing(
    file_path: Annotated[str, Field(min_length=1, max_length=4096)],
    role: Literal["lead_vocal", "backing_vocals", "bass", "drums"],
    source_kind: Literal[
        "suno_stems", "organic_multitrack", "unknown"
    ] = "unknown",
) -> dict[str, Any]:
    """Analiza un WAV y propone una cadena auditable sin modificar REAPER."""

    audio_path = resolve_input_file(file_path, suffixes={".wav"})
    return build_track_processing_proposal(audio_path, role, source_kind)


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
    fx_type: Literal["reacomp", "reaeq"],
) -> dict[str, Any]:
    """Agrega ReaComp o ReaEQ y verifica identidad, GUID y estado."""

    return _call(
        "add_stock_fx",
        {"project_ref": project_ref, "track_guid": track_guid, "fx_type": fx_type},
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
