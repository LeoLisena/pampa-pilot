# Evaluación del adaptador de saturación

## Candidatos instalados

La instalación de REAPER 7.78 incluye, entre otros, `Saturation [LOSER]`,
`ReaLoud [Stillwell]`, `Multi Waveshaper` y varios clippers.
La primera alternativa sólo expone Amount; ReaLoud sólo expone Mix. Ninguna de
las dos permite compensar la salida dentro de la misma instancia.

Se eligió `JS: Multi Waveshaper` (identificador `Liteon/waveshapermulti`) porque
expone siete controles
simples: Processing, Waveshaper, Drive, Muffle, Output, Limiter y Oversample x2.
Su archivo instalado declara licencia GPL. PampaPilot no copia ni modifica el
código DSP: carga el JSFX que ya distribuye REAPER y controla únicamente su API.

## Contrato inicial

PampaPilot deja fijos estéreo, Type 1, limitador apagado y sobremuestreo x2. El
cerebro sólo puede solicitar Drive 0-35 %, Muffle 0-30 % y Output -12-0 dB. La
restricción evita distorsión extrema, suma mono accidental y clipping oculto.

Los perfiles iniciales son deliberadamente moderados:

| Fuente | Drive | Muffle | Output |
|---|---:|---:|---:|
| Suno | 5 % | 0 % | -0,2 dB |
| Orgánica | 12 % | 2 % | -0,6 dB |
| Desconocida | 7 % | 1 % | -0,3 dB |

Output es una estimación conservadora, no una compensación medida. La etapa
siguiente debe renderizar antes/después, calcular loudness sobre el mismo tramo
y ajustar Output sin perseguir diferencias por debajo de la resolución del
plugin. La aceptación tímbrica continúa siendo una decisión de escucha humana.

## Validación en vivo

`EnumInstalledFX` confirmó el nombre de catálogo `JS: Multi Waveshaper` y el
identificador `Liteon/waveshapermulti`; el nombre descriptivo del archivo fuente
no era aceptado por `TrackFX_AddByName`, por lo que el adaptador usa el valor
enumerado por REAPER.

La prueba sobre Guitar agregó una instancia con GUID
`{09B0CB79-B3BA-42DC-B784-35E89CC8ACAA}` y confirmó diez parámetros totales:
los siete sliders del JSFX más Bypass, Wet y Delta. El perfil Suno fue releyéndose
como Stereo, Type 1, Drive 5,0, Muffle 0,0, Output -0,2, Limiter Off y Oversample
On. La retirada por el mismo GUID dejó nuevamente sólo el ReaFIR preexistente.
No se reprodujo audio, por lo que la verificación fue de estado y no perceptual.
