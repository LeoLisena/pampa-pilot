# MVP: primera rebanada vertical

El MVP no intenta producir una canción. Demuestra que una instrucción puede
atravesar toda la arquitectura, modificar REAPER y ser validada sin depender de
la interfaz gráfica.

## Recorrido de aceptación

Sobre un proyecto de prueba desechable:

1. `health_check` devuelve versión de REAPER, versión del puente e identidad del
   proyecto.
2. `get_project_state` devuelve pistas con GUID, nombre y estado básico.
3. `create_track` crea una pista con un nombre único y devuelve su GUID.
4. `get_track_state` vuelve a encontrarla por GUID.
5. `set_track_pan` cambia el paneo dentro de un modo soportado y verifica por
   lectura el valor, el modo, la ley de paneo y el estado de automatización. La
   primera versión admite modo heredado del proyecto, clásico y balance.
6. `add_stock_fx` agrega un efecto nativo permitido y devuelve GUID, nombre,
   bypass y estado offline.
7. `set_stock_fx_parameter` usa un adaptador específico y verifica tanto el valor
   normalizado como la representación formateada por REAPER.
8. `undo_transaction` restaura el estado anterior y lo comprueba.
9. `import_audio` crea pista, ítem y toma desde un WAV permitido; fija el audio a
   tiempo absoluto y verifica ruta, duración, canales y sample rate.
10. `set_project_tempo` cambia BPM y comprueba que posición, duración y playrate
    de los ítems existentes no hayan variado.
11. `save_project_as` crea un `.rpp` nuevo dentro de una raíz local permitida y
    devuelve la identidad nueva del proyecto.
12. `import_audio_batch` valida todos los WAV antes de escribir y crea el lote
    completo dentro de una sola transacción reversible.

## Criterios de éxito

- Ninguna acción depende del número visible de pista.
- Repetir una solicitud con el mismo UUID no duplica la mutación.
- Una solicitud vencida no se ejecuta.
- Los errores de pista o plug-in inexistente son estructurados y no dejan una
  transacción abierta.
- El resultado distingue `accepted`, `state_verified`, `signal_verified` y
  `perceptually_evaluated`.
- El cambio es visible en REAPER mientras la aplicación está abierta.

## Siguiente rebanada

Después de aprobar este recorrido: analizar señal, organizar grupos y preparar
una mezcla estática supervisada. Luego se agregará un render de prueba y
comparación de archivo. La limpieza de MIDI vendrá después con fixtures que
contengan notas duplicadas, eventos fuera de rango, canales inconsistentes y
silencios anómalos.
