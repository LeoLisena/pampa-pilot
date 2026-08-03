# Propuestas de procesamiento

`propose_track_processing` conecta por primera vez el análisis objetivo con la
base de conocimiento musical. Recibe un WAV, su rol y el origen de los stems;
devuelve una hipótesis de cadena, pero nunca modifica REAPER ni escribe archivos.

## Contrato

Toda propuesta incluye:

- hash e identidad del audio analizado;
- observaciones de señal separadas de las decisiones;
- reglas YAML exactas, con ruta, confianza y fecha de revisión;
- procesadores ordenados y parámetros iniciales;
- evidencia y limitaciones de cada paso;
- `execute: false` y aprobación del usuario obligatoria;
- plan de verificación de estado, señal y percepción.

La primera versión admite `lead_vocal`, `backing_vocals`, `bass` y `drums`. Los
perfiles de compresión proceden de `knowledge/mixing/reacomp-starting-points.yaml`.
Las voces reciben además una hipótesis de pasa-altos tomada de
`knowledge/mixing/eq-starting-points.yaml`.

## Límite deliberado

Las métricas actuales son de banda ancha. Pueden contextualizar el pico, RMS,
LUFS y factor de cresta, pero no demuestran que haya graves indeseados ni que la
compresión mejore la interpretación. Por eso todos los pasos se marcan
`audition_only`. En stems provenientes de Suno se agrega una advertencia expresa:
pueden venir procesados y no deben recibir EQ o compresión por rutina.

El techo teórico de reducción de picos sólo estima el efecto de threshold y
ratio sobre el pico observado. No sustituye la medición real del gain reduction
ni una comparación con bypass a volumen igualado.

## Prueba real: Mi Pequeño Sol

El stem `10 Vocals.wav`, identificado por SHA-256, produjo la propuesta
`039154a7c6626d7f8ebb0d05`. Las observaciones principales fueron −17,18 LUFS,
pico de −3,05 dBFS y factor de cresta de 19,82 dB. El plan devolvió:

- ReaEQ: pasa-altos a 80 Hz, Q 0,71;
- ReaComp: threshold −10 dB, ratio 1,5:1, attack 15 ms, release 120 ms,
  knee 3 dB y RMS 5 ms, sin automatismos.

La pista `Vocals` ya contenía esos dos FX por las pruebas supervisadas previas.
El puente volvió a leer nombres, GUID, estado online y todos los valores, que
coincidieron exactamente con la propuesta. Esto constituye verificación de
estado; la reducción real de ganancia y la mejora perceptual continúan sin
verificar.

## Aplicación aprobada

`apply_processing_proposal` vuelve a analizar el mismo WAV y recalcula el plan.
Sólo continúa si `approved_proposal_id` coincide exactamente, de modo que un
cambio de audio, reglas o parámetros invalida una aprobación anterior.

Cada procesador debe vincularse explícitamente:

- con `fx_guid`, reutiliza esa instancia y verifica su identidad;
- sin `fx_guid`, crea una instancia nueva, pero rechaza hacerlo si ya existe un
  FX del mismo tipo para evitar duplicados silenciosos.

ReaEQ y ReaComp se configuran dentro de una única transacción de REAPER. Si
falla cualquier alta, identidad, parámetro o lectura posterior, el puente
revierte la cadena completa. La aprobación autoriza valores concretos, pero no
implica verificación de señal ni aprobación perceptual.

### Validación real de la aplicación

La propuesta `039154a7c6626d7f8ebb0d05` fue aprobada explícitamente y aplicada a
`Vocals` mediante el puente 0.8.0. La transacción reutilizó los GUID existentes
de ReaEQ y ReaComp, mantuvo `fx_count = 2` y volvió a leer de forma independiente:

- ReaEQ: 80,0 Hz, ganancia 0,0 dB y Q 0,71;
- ReaComp: −10,0 dB, 1,500:1, 15,0 ms, 120 ms, RMS 5,0 ms, knee 3,0 dB y
  ambos automatismos desactivados.

La transacción `bf139559-ca3b-451b-b8b3-769319a9ddac` quedó disponible para
undo. `state_verified` fue verdadero; `signal_verified` y
`perceptually_evaluated` permanecieron falsos.

## Producer chain 0.24.0

`preview_project_track_producer_chain` combina los adaptadores especializados,
ordena sólo los candidatos vigentes y los cruza con la cadena real de REAPER.
El orden permitido es ReaGate, ReaEQ, resonancia ReaXcomp, ReaComp, de-esser
ReaXcomp y JS Multi Waveshaper. Una fuente Suno no recibe EQ o compresión por
rutina; únicamente entran tratamientos con evidencia propia y, opcionalmente,
saturación artística aprobada.

`apply_project_track_producer_chain` vuelve a calcular audio y estado de REAPER.
El `chain_id` cambia si cambia el WAV, una regla, un parámetro o un FX existente.
Hasta seis procesadores se crean o reutilizan en orden dentro de una única
transacción. Los FX ajenos se conservan; duplicados y ReaXcomp cuyo propósito
no pueda inferirse bloquean el plan.

Vocal rider y ambiente aparecen como etapas diferidas: el primero escribe una
envolvente y el segundo crea routing/buses. No se ocultan dentro de la cadena FX
porque requieren contratos y reversiones diferentes.

### Validación real 0.24.0

La cadena `cffa42fdf5eb81bc6db79bfd` de Guitar preservó el ReaFIR preexistente
en índice 0 y creó ReaXcomp en índice 1. La respuesta y una consulta posterior
independiente confirmaron GUID, 51 parámetros, estado online, orden y
`fx_count=2`. La única transacción se deshizo: Guitar volvió a un FX, el mismo
ReaFIR, fader -7 dB, paneo central y automatización Trim/Read. El proyecto quedó
en 14 pistas y 85 BPM. No se modificó ni renderizó el WAV.

## Comparación A/B 0.25.0

`apply_and_compare_project_track_producer_chain` ejecuta un flujo explícito:
render A del mix sin la propuesta, aplicación de la cadena aprobada como una
única transacción, render B y creación offline de dos copias igualadas por
loudness integrado. Los WAV originales A/B se conservan intactos.

El objetivo es el LUFS de la versión más silenciosa. Por eso el motor sólo
atenúa la más fuerte: no introduce clipping ni confunde una subida de volumen
con una mejora. Verifica que tasa, canales y duración coincidan y exige un error
de igualado no mayor a 0,1 LU. Esto valida la preparación técnica, no la calidad
musical; `perceptually_evaluated` permanece falso hasta una escucha humana.

Cada render restaura internamente directorio, patrón, formato, bounds, sample
rate, canales, tail, normalización y dither previos. La cadena queda como última
transacción PampaPilot, de modo que puede conservarse o deshacerse después de
la audición.

Antes de renderizar, el puente recorre las tomas de audio activas y rechaza el
flujo si REAPER informa sample rate o duración de fuente iguales a cero. Así un
estado `OFFLINE` no puede producir silencios que parezcan comparaciones válidas.

### Validación real 0.25.0

El flujo se ejecutó sobre Guitar en `Mi Pequeño Sol - MIDI Validation`: A sin la
propuesta midió -20,190 LUFS y B con la resonancia dinámica midió -20,218 LUFS.
El igualado atenuó A en 0,028 dB y dejó B sin ganancia; las dos copias resultaron
en -20,218 LUFS, con error 0,000 LU. REAPER restauró sus ajustes de render y la
transacción `46e9bf1b-3220-4060-b48c-65a9c1d5449f` se deshizo. Guitar volvió a
un único ReaFIR con el mismo GUID, -7 dB y paneo central. La escucha perceptual
continúa pendiente y los cuatro WAV quedaron bajo `sessions/Mi Pequeño Sol/renders/ab`.
