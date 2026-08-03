# Plan de producción contextual

`preview_production_plan` cruza el diagnóstico offline con el estado actual de
REAPER. Devuelve un plan ligado a `project_ref` y al contador de cambios, pero
nunca ejecuta acciones.

## Unión de identidad

Los stems se vinculan con las pistas mediante nombres canonizados y sólo cuando
la coincidencia es única. El resultado conserva los GUID; ninguna acción futura
podrá usar el índice visible. Las coincidencias ausentes o ambiguas bloquean esa
parte del plan.

## Estado que modifica la interpretación

El plan comprueba:

- volumen, paneo, mute y solo;
- cantidad, GUID, identidad y estado de los FX;
- pistas presentes en REAPER pero ausentes del manifiesto;
- problemas ya neutralizados porque una variante está muteada.

Un posible conflicto espectral no requiere acción si una de sus pistas está
muteada. En cambio, una pista extra activa o un solo impiden evaluar la mezcla
normal y reciben prioridad superior.

## Salida

Cada ítem incluye prioridad, estado, evidencia, pistas con GUID y recomendación.
Las relaciones espectrales conservan baja confianza. El `plan_id` cambia si se
modifican el audio, el diagnóstico o el estado de REAPER; por tanto, un plan
viejo no debe aplicarse sobre un proyecto distinto.

## Primera validación real

El plan `9cc888540ca2b73c519b635e` vinculó correctamente los 12 stems de
`Mi Pequeño Sol` con 12 de las 14 pistas de REAPER. Detectó:

- prioridad alta: `Guitar MIDI - Safe` permanece en solo y bloquea una escucha
  normal de la mezcla;
- prioridad media: las dos pistas MIDI de validación están activas pero no
  pertenecen al manifiesto de stems;
- prioridad media: correlación estéreo negativa en `Backing Vocals`;
- tres pares espectrales activos para revisión de baja confianza;
- cinco pares cuyo posible conflicto ya está neutralizado porque una variante
  de batería está muteada.

El plan no modificó REAPER. Tanto el diagnóstico de señal como la lectura del
estado fueron verificados; la evaluación perceptual permanece pendiente.
