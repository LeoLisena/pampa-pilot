"""Catálogo mínimo de acciones que el puente podrá aceptar."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class VerificationLevel(StrEnum):
    ACCEPTED = "accepted"
    STATE = "state_verified"
    SIGNAL = "signal_verified"
    PERCEPTUAL = "perceptually_evaluated"


@dataclass(frozen=True, slots=True)
class ActionSpec:
    name: str
    mutates_project: bool
    minimum_verification: VerificationLevel
    description: str


ACTION_SPECS: dict[str, ActionSpec] = {
    spec.name: spec
    for spec in (
        ActionSpec(
            "health_check",
            False,
            VerificationLevel.STATE,
            "Devuelve versiones e identidad del proyecto activo.",
        ),
        ActionSpec(
            "get_project_state",
            False,
            VerificationLevel.STATE,
            "Lee el estado estructural mínimo del proyecto.",
        ),
        ActionSpec(
            "get_render_settings",
            False,
            VerificationLevel.STATE,
            "Lee ajustes de render y cadena del master sin abrir ni modificar el diálogo.",
        ),
        ActionSpec(
            "create_track",
            True,
            VerificationLevel.STATE,
            "Crea una pista y devuelve su GUID estable.",
        ),
        ActionSpec(
            "get_track_state",
            False,
            VerificationLevel.STATE,
            "Localiza una pista por GUID y lee su estado.",
        ),
        ActionSpec(
            "set_track_pan",
            True,
            VerificationLevel.STATE,
            "Ajusta paneo con comprobación de modo, ley y automatización.",
        ),
        ActionSpec(
            "set_track_volume",
            True,
            VerificationLevel.STATE,
            "Ajusta volumen en dB y verifica la ganancia lineal leída de REAPER.",
        ),
        ActionSpec(
            "set_track_mute",
            True,
            VerificationLevel.STATE,
            "Activa o desactiva mute y verifica el estado leído de REAPER.",
        ),
        ActionSpec(
            "set_track_solo",
            True,
            VerificationLevel.STATE,
            "Activa o desactiva solo y verifica el estado leído de REAPER.",
        ),
        ActionSpec(
            "apply_track_mix_batch",
            True,
            VerificationLevel.STATE,
            "Aplica volumen, paneo y mute a varias pistas en una transacción.",
        ),
        ActionSpec(
            "import_audio",
            True,
            VerificationLevel.STATE,
            "Importa un archivo permitido en una pista nueva y verifica el ítem.",
        ),
        ActionSpec(
            "import_audio_batch",
            True,
            VerificationLevel.STATE,
            "Importa varios WAV como una única transacción verificable.",
        ),
        ActionSpec(
            "import_midi",
            True,
            VerificationLevel.STATE,
            "Materializa notas MIDI validadas en una pista y relee todos los eventos.",
        ),
        ActionSpec(
            "import_midi_batch",
            True,
            VerificationLevel.STATE,
            "Materializa varios MIDI como una única transacción verificable.",
        ),
        ActionSpec(
            "set_project_tempo",
            True,
            VerificationLevel.STATE,
            "Ajusta el tempo global y comprueba que no cambie el timing del audio.",
        ),
        ActionSpec(
            "save_project_as",
            True,
            VerificationLevel.STATE,
            "Guarda el proyecto activo con una ruta nueva permitida y la verifica.",
        ),
        ActionSpec(
            "add_stock_fx",
            True,
            VerificationLevel.STATE,
            "Agrega un efecto nativo permitido y devuelve su identidad.",
        ),
        ActionSpec(
            "add_instrument",
            True,
            VerificationLevel.STATE,
            "Agrega un instrumento virtual permitido y verifica su identidad y rol.",
        ),
        ActionSpec(
            "apply_processing_chain",
            True,
            VerificationLevel.STATE,
            "Aplica una propuesta aprobada como una única transacción verificable.",
        ),
        ActionSpec(
            "prepare_mix_listening",
            True,
            VerificationLevel.STATE,
            "Quita solos y mutea pistas extra como una transacción aprobada.",
        ),
        ActionSpec(
            "configure_reacomp",
            True,
            VerificationLevel.STATE,
            "Configura ReaComp en unidades musicales mediante un adaptador explícito.",
        ),
        ActionSpec(
            "configure_reaeq_band",
            True,
            VerificationLevel.STATE,
            "Configura una banda de ReaEQ en unidades musicales y relee su estado.",
        ),
        ActionSpec(
            "undo_transaction",
            True,
            VerificationLevel.STATE,
            "Revierte la última transacción propia y comprueba el resultado.",
        ),
    )
}


def require_action(name: str) -> ActionSpec:
    """Devuelve una acción permitida o rechaza el nombre sin ejecutarlo."""

    try:
        return ACTION_SPECS[name]
    except KeyError as exc:
        raise LookupError(f"acción no permitida: {name}") from exc
