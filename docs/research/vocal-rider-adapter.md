# Adaptador de vocal rider

## Objetivo

Nivelar diferencias amplias entre regiones de una voz antes de pedir más trabajo
al compresor, conservando intención, respiraciones y finales. No sustituye la
automatización fina por palabra ni la escucha del productor.

## Análisis

El motor convierte el WAV a mono para medir RMS en bloques de 50 ms. El umbral
de actividad se calcula como p90 menos 20 dB, limitado entre -45 y -30 dBFS. Los
bloques activos separados por no más de 200 ms forman regiones de al menos 250
ms. La referencia es la mediana RMS de esas regiones, no un LUFS objetivo.

Para una toma orgánica se aplica el 60 % de la diferencia con límite ±3 dB. Las
diferencias menores a 0,25 dB se ignoran. Cada corrección genera una entrada de
80 ms y una salida de 120 ms; los puntos usan tiempos relativos al archivo.

## Decisión por fuente

- `organic_multitrack`: propuesta `audition_only` aplicable.
- `suno_stems`: `not_recommended`, sin puntos internos; usar primero balance
  estático del stem.
- `unknown`: `classify_source_first`, sin puntos.

Esta distinción surgió de la prueba real con `10 Vocals.wav`: aun con umbral
adaptativo, la señal procesada formó regiones continuas muy largas. Aplicarlas
como si fueran frases sería una falsa precisión.

## Contrato REAPER

La acción recibe GUID de pista/ítem, ruta y SHA-256 del WAV, ID de propuesta y
`source_kind=organic_multitrack`, además de un máximo de 512 puntos lineales
entre -6 y +6 dB. Rechaza fuentes distintas,
MIDI, tiempos fuera del tramo reproducido, puntos duplicados o cualquier
automatización previa dentro del ítem. Mapea offset/playrate, inserta dentro de
una transacción undo y relee cada punto antes de confirmar `state_verified`.

## Validación en vivo

Con REAPER 7.78/x64 y el puente 0.21.0 se generó un WAV temporal de 3 s con tres
frases sintéticas a distintos niveles. El análisis orgánico produjo ocho puntos
para dos regiones, con correcciones de +3 y -3 dB. Tras aplicarlos, una consulta
independiente de la envolvente devolvió exactamente los ocho tiempos y valores,
con forma lineal y tensión cero.

La automatización y la importación se deshicieron como dos transacciones propias
en orden inverso. El proyecto quedó nuevamente en 14 pistas y 85 BPM; luego se
eliminaron el WAV y el directorio temporal. La validación demuestra escritura,
lectura y reversibilidad, pero aún falta ajustar el modelo mediante escucha de
una voz orgánica real.
