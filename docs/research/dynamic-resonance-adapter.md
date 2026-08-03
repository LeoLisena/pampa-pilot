# Control dinámico de resonancias con ReaXcomp

## Decisión de arquitectura

La instalación local contiene ReaXcomp, ReaEQ y ReaFIR, pero no TDR Nova ni
FabFilter Pro-Q. ReaXcomp fue elegido porque es stock, portable y expone 51
parámetros verificables. Puede controlar una banda amplia; no pretende ofrecer
la precisión de un EQ dinámico dedicado.

## Propuesta

El análisis calcula un STFT, obtiene el espectro p90 y busca una prominencia
dentro del rango del rol respecto de una curva suavizada. Después filtra esa
banda y exige variación entre los bloques p50 y p90: una elevación fija sin
dinámica no justifica compresión. Se propone como máximo una banda de una
octava aproximada.

- `organic_multitrack`: prominencia mínima 5,5 dB, variación 3 dB, ratio 1,6 y
  threshold p82.
- `suno_stems`: prominencia mínima 8 dB, variación 5 dB, ratio 1,25 y threshold
  p92.
- `unknown`: sólo informa y exige clasificar la fuente.

La detección no distingue por sí sola una resonancia molesta de una nota o un
armónico musical. Por eso el resultado es `audition_only`, nunca ejecución
automática.

## Contrato de REAPER

Bandas 1, 3 y 4 quedan activas pero transparentes. La banda 2 recibe threshold,
ratio, knee, ataque, release y RMS. Makeup, auto-release y feedback se apagan;
bypass y delta se desactivan y Wet se fija en 100 %. La aplicación puede crear
una instancia nueva o reutilizar un GUID exacto, evita duplicados y relee los
51 parámetros dentro de una transacción undo.

## Evidencia inicial

`3 Guitar.wav` de Suno produjo centro 234,375 Hz, crossovers 165,7 y 331,5 Hz,
prominencia 16,12 dB, variación 10,76 dB, threshold -30,7 dB y ratio 1,25. Es
una hipótesis plausible de cuerpo/embarramiento y todavía requiere aplicación
reversible y escucha.

## Validación en vivo

El puente 0.23.0 creó una ReaXcomp temporal en Guitar y devolvió
`state_verified=true`. REAPER representó los crossovers como 165,7 y 332,4 Hz;
el segundo cuantizó el pedido 331,5 dentro de la tolerancia declarada. Threshold,
ratio, knee, ataque, release, RMS, estados de las cuatro bandas, Wet, bypass y
delta coincidieron en una segunda lectura independiente de los 51 parámetros.

La transacción se deshizo. Guitar volvió a un único FX, el ReaFIR preexistente
con el mismo GUID; no se guardó el proyecto ni se modificó el WAV. La calidad
perceptual de la hipótesis en 234 Hz continúa deliberadamente sin afirmar.
