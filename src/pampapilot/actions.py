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
            "discover_project_fx",
            False,
            VerificationLevel.STATE,
            "Descubre instancias FX por GUID y parámetros acotados.",
        ),
        ActionSpec(
            "discover_installed_fx",
            False,
            VerificationLevel.STATE,
            "Enumera nombres exactos de FX instalados sin modificar el proyecto.",
        ),
        ActionSpec(
            "get_render_settings",
            False,
            VerificationLevel.STATE,
            "Lee ajustes de render y cadena del master sin abrir ni modificar el diálogo.",
        ),
        ActionSpec(
            "get_master_track_state",
            False,
            VerificationLevel.STATE,
            "Lee identidad, estado y FX de la pista master.",
        ),
        ActionSpec(
            "render_master_candidate",
            True,
            VerificationLevel.STATE,
            "Renderiza un WAV nuevo mediante ajustes explícitos y devuelve un recibo.",
        ),
        ActionSpec(
            "restore_render_settings",
            True,
            VerificationLevel.STATE,
            "Restaura un snapshot verificado después de renderizar un candidato.",
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
            "remove_track_fx",
            True,
            VerificationLevel.STATE,
            "Quita una instancia FX permitida exacta mediante GUID.",
        ),
        ActionSpec(
            "create_effect_bus",
            True,
            VerificationLevel.STATE,
            "Crea un bus ReaVerbate o ReaDelay 100 % wet y verifica su estado.",
        ),
        ActionSpec(
            "configure_ambience_fx",
            True,
            VerificationLevel.STATE,
            "Configura el FX exacto de un bus de ambiente mediante GUID.",
        ),
        ActionSpec(
            "create_bus_send",
            True,
            VerificationLevel.STATE,
            "Crea un envío post-fader sin MIDI y verifica origen, destino y nivel.",
        ),
        ActionSpec(
            "remove_bus_send",
            True,
            VerificationLevel.STATE,
            "Quita un envío exacto identificado por los GUID de sus pistas.",
        ),
        ActionSpec(
            "remove_effect_bus",
            True,
            VerificationLevel.STATE,
            "Quita un bus vacío permitido y sus recepciones después de verificarlo.",
        ),
        ActionSpec(
            "add_master_stock_fx",
            True,
            VerificationLevel.STATE,
            "Agrega ReaLimit al master y devuelve parámetros e identidad verificables.",
        ),
        ActionSpec(
            "remove_master_fx",
            True,
            VerificationLevel.STATE,
            "Quita una instancia ReaLimit exacta del master mediante su GUID.",
        ),
        ActionSpec(
            "apply_mastering_limiter",
            True,
            VerificationLevel.STATE,
            "Aplica una propuesta aprobada de ReaLimit al master en una transacción.",
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
            "configure_reagate",
            True,
            VerificationLevel.STATE,
            "Configura ReaGate en unidades musicales y relee todos sus parámetros.",
        ),
        ActionSpec(
            "apply_reagate_proposal",
            True,
            VerificationLevel.STATE,
            "Aplica una propuesta ReaGate aprobada y vigente, creando o reutilizando por GUID.",
        ),
        ActionSpec(
            "configure_deesser",
            True,
            VerificationLevel.STATE,
            "Configura ReaXcomp como de-esser de cuatro bandas y verifica sus parámetros.",
        ),
        ActionSpec(
            "apply_deesser_proposal",
            True,
            VerificationLevel.STATE,
            "Aplica una propuesta de-esser aprobada y vigente mediante GUID.",
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
