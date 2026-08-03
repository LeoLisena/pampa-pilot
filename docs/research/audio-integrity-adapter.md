# Adaptador de integridad de audio

## Alcance

El adaptador detecta riesgos técnicos y propone revisión. No declara que un
transiente sea un clic, que un silencio sea basura ni que una cola esté
truncada sin escucha. Tampoco modifica el WAV ni REAPER.

## Señales medidas

- Muestra inicial/final y RMS de los primeros/últimos 20 ms.
- Saltos entre muestras que exceden un umbral robusto y dependiente de fuente.
- Regiones internas bajo un umbral de silencio durante una duración mínima.
- Tres o más frames consecutivos en escala digital completa.
- Energía audible que alcanza el final del rango analizado.

Los hallazgos conservan tiempo relativo al archivo y SHA-256. Para una toma de
REAPER, el puente 0.22.0 entrega fuente, offset, playrate, duración y fades; el
motor limita el análisis al tramo realmente reproducido y conserva la posición
del ítem como contexto.

`loop source` puede estar activado por defecto aun cuando el ítem termina justo
al final del WAV. Ese caso se acepta. Si duración, offset y playrate hacen que
el rango cruce un ciclo real, el análisis se bloquea hasta implementar el mapeo
de repeticiones explícitamente.

## Política por fuente

En grabaciones orgánicas, impulsos y silencios largos solicitan revisión. En
stems de Suno se anotan sólo como observaciones porque pueden representar
transientes procesados o huecos normales del arreglo. Bordes duros y clipping
mantienen prioridad técnica en ambos casos.

Los fades sugeridos son siempre `automatic: false`. Una cola con energía se
deriva a revisión de la fuente o del borde del ítem: aplicar un fade puede
ocultar un clic, pero no reconstruye un decaimiento ausente.

## Validación offline con Mi Pequeño Sol

Los 12 stems de Suno se analizaron sin modificar archivos ni REAPER. Ninguno
presentó borde duro, cola activa al umbral de Suno ni clipping plano. Tres stems
mostraron transientes candidatos y ocho contenían silencios internos largos;
ambos tipos quedaron como observaciones, no como defectos ni reparaciones. Tres
stems no produjeron hallazgos.

## Validación en vivo con REAPER

El puente 0.22.0 releyó el ítem real de `Guitar`: `3 Guitar.wav`, offset 0,
playrate 1, 234,875583 s, fuente estéreo de 48 kHz, `loop source` activo sin
repetición efectiva y fades de entrada/salida de 10 ms. El motor verificó la
ruta y analizó exactamente de 0 a 234,875583 s.

El resultado fue `observations_only`: cinco saltos impulsivos quedaron como
posibles transientes procesados de Suno y no se propuso ninguna reparación.
REAPER confirmó `state_verified=true`; no se modificó el proyecto ni el WAV.
La escucha y calibración sobre voz, guitarra o cuerdas orgánicas reales sigue
pendiente.
