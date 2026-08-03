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

## Preparación aprobada para escuchar

`apply_listening_preparation` vuelve a calcular el plan antes de escribir. Sólo
continúa si `approved_plan_id` coincide exactamente con el `plan_id` vigente;
un cambio en REAPER o en los audios invalida la aprobación.

La preparación se deriva del plan, no de parámetros libres. Únicamente puede:

- quitar el solo de pistas que el plan marque como `project.active_solo`;
- mutear pistas activas que marque como `project.unmanaged_track`.

Los GUID se resuelven antes de comenzar y todos los cambios se aplican en una
sola transacción deshacible. El puente relee cada pista y sólo informa
`state_verified` si los solos quedaron quitados y los mutes activados. No cambia
volumen, paneo, FX, ítems ni archivos, y no implica evaluación perceptual.

En la validación real, el plan vigente `7b90191800008172a82aa26e` fue
recalculado inmediatamente antes de escribir y conservó su identidad. La
transacción `c0cb4859-3c2d-4684-abee-6011402feb4f` quitó el solo de
`Guitar MIDI - Safe` y muteó tanto esa pista como
`Guitar MIDI - Reconstructed`. La lectura posterior confirmó `solo = 0` y
`muted = true` en ambas pistas; los demás parámetros quedaron fuera del alcance
de la operación.
