# Interfaz de efectos nativos

PampaPilot no expone parámetros VST arbitrarios. Cada efecto permitido tiene un
adaptador tipado que recibe unidades musicales, usa GUID estables y vuelve a leer
el estado que REAPER conservó.

`discover_fx_parameter_domain` es la excepción de sólo lectura usada durante el
desarrollo de adaptadores: muestrea cómo el propio plugin formatea un parámetro
sin cambiar su valor actual ni habilitar escritura arbitraria.

## Identidad común

Toda mutación requiere:

- `project_ref`: identidad de la instancia y ruta del proyecto activo;
- `track_guid`: identidad estable de la pista;
- `fx_guid`: identidad estable de la instancia del efecto.

`add_stock_fx` permite actualmente `reacomp`, `reaeq`, `reagate`, `reaxcomp`,
`reaverbate`, `readelay`, `reatune`, `reafir` y `waveshaper`. Cada alta comprueba que
la cadena aumentó exactamente en un efecto y que éste quedó habilitado y online.

`add_instrument` separa los generadores de sonido de los efectos de audio. Su
primer adaptador permite `reasynth`; además de comprobar nombre, GUID y estado,
exige que REAPER lo reconozca como el instrumento de la pista. Rechaza la
operación si la pista ya tiene otro instrumento, para no crear cadenas ambiguas.
La interfaz queda preparada para incorporar otros VSTi mediante identificadores
permitidos, sin aceptar nombres arbitrarios provenientes del cerebro.

ReaSynth sirve para validar de punta a punta que un MIDI produce sonido. No se
considera una emulación de guitarra ni una decisión tímbrica de producción.

## ReaTune mediante presets

ReaTune no expone por la API estándar sus controles de tonalidad, escala, notas
permitidas, ataque o algoritmo. `configure_reatune_preset` evita depender de
chunks internos: recibe el GUID exacto de una instancia existente, acepta sólo
un nombre explícito, lo carga mediante la API de presets y vuelve a leerlo. El
prefijo `PampaPilot - ` es una convención recomendada, no una limitación. Un
preset inexistente o una lectura distinta rechaza la transacción y restaura el
estado anterior mediante undo.

## ReaFIR

El puente 0.19.0 permite agregar y retirar ReaFIR por GUID y descubrir dominios
formateados sin modificar el proyecto. La prueba en REAPER 7.78/x64 confirmó
que los parámetros públicos 0 y 1 corresponden a `Show analysis` y
`Reduce artifacts (less effective)`. El desplegable `Mode: EQ` y el perfil
espectral no forman parte de esos parámetros y pertenecen al estado privado del
plugin. Por eso PampaPilot todavía no acepta valores de modo o perfil: no
presentará una reducción de ruido como verificada mientras no pueda releerlos.

Esta estrategia adapta la operación genérica de presets observada en Total
REAPER MCP y Bonfire REAPER MCP, ambos bajo licencia MIT, pero mantiene la
validación, el allowlist y el contrato transaccional propios de PampaPilot.

La integración se validó en REAPER 7.78/x64 sobre `Vocals`: la instancia
ReaTune `{E3892131-7818-4612-AD5A-37BF75B49E54}` cargó el preset local
`pampapilota#`; la lectura posterior conservó exactamente el mismo nombre, GUID,
estado activo y online, con `state_verified: true`.

## Saturación con JS Multi Waveshaper

El puente 0.20.0 selecciona el JSFX stock `Multi Waveshaper`
porque, a diferencia de `Saturation [LOSER]`, posee salida independiente para
reducir la ventaja de volumen durante la comparación. El adaptador admite:

- Drive de 0 a 35 %;
- Muffle de 0 a 30 %;
- Output de -12 a 0 dB.

Mantiene fija la ruta estéreo, la curva Type 1, el sobremuestreo x2 y el
limitador interno desactivado. Verifica nombre, orden y lectura de los siete
parámetros públicos, además del GUID y el estado online.

`preview_saturation_proposal` produce recetas `audition_only`: 5 % de Drive
para stems de Suno, 12 % para grabaciones orgánicas y 7 % cuando el origen es
desconocido. Los ajustes de Output (-0,2, -0,6 y -0,3 dB respectivamente) son
puntos de partida estáticos, no mediciones de loudness. La propuesta declara
explícitamente `measured: false` y exige A/B con volumen igualado.

La validación real sobre `Guitar` agregó `JS: Multi Waveshaper` con GUID
`{09B0CB79-B3BA-42DC-B784-35E89CC8ACAA}`. REAPER releyó Stereo, Type 1,
Drive 5,0 %, Muffle 0,0 %, Output -0,2 dB, Limiter Off, Oversample On, Wet 100 %
y estado activo/online. Después se retiró esa instancia exacta; Guitar volvió a
un único FX, el ReaFIR preexistente, con `state_verified: true` en cada paso.

## ReaComp

`configure_reacomp` controla threshold, ratio, attack, release, knee, RMS y las
opciones automáticas. La escala interna se calibra contra los valores formateados
por el propio plugin y después se relee completa.

## ReaEQ

`configure_reaeq_band` dirige una banda existente por `band_type` y
`band_index`. Admite los tipos nativos pasa-altos, low shelf, campana, notch,
high shelf, pasa-bajos y las dos variantes band-pass. Configura:

- frecuencia en Hz;
- ganancia en dB, convertida a la amplitud lineal que espera la API;
- Q;
- banda habilitada o deshabilitada.

El adaptador no cambia silenciosamente el tipo ni crea bandas. Si la banda
solicitada no existe, rechaza la operación. Agregar o transformar bandas será una
operación explícita posterior.

## ReaGate

`preview_reagate_proposal` analiza bloques de 50 ms y separa dos observaciones:
proporción de pasajes por debajo de −40 dBFS y nivel alto de esos pasajes. No los
denomina automáticamente ruido. Sólo propone un threshold cuando también existe
una separación suficiente respecto del programa activo.

El motor rechaza por defecto la puerta para stems de Suno. Para voz o guitarra
orgánicas puede devolver una hipótesis `audition_only` con threshold, histéresis,
attack, pre-open, hold, release, filtros del detector y RMS. La aplicación exige
el ID vigente aprobado y crea o reutiliza ReaGate mediante GUID.

`configure_reagate` permite el ajuste fino posterior y relee los 24 parámetros.
El umbral finito permitido comienza en -42 dB: REAPER 7.78 representa los
valores inferiores como `-inf`, por lo que el motor limita las propuestas a un
valor que pueda escribir y verificar de manera reproducible.

La integración fue validada en vivo con el puente 0.14.0 sobre la pista
`Guitar`: ReaGate confirmó threshold -36.1 dB, hysteresis -3.0 dB, attack 5 ms,
release 220 ms, pre-open 5 ms, hold 100 ms, detector 60 Hz-15 kHz y RMS 5 ms.
La instancia temporal se eliminó después por GUID y la pista confirmó
`fx_count: 0`.
Además fuerza desactivados Preview Filter, Send MIDI e Invert Wet. La retirada
de una prueba sólo acepta el GUID exacto de ReaGate y verifica que desapareció.

La prueba offline del stem `3 Guitar.wav` de Suno observó 30,04 % de bloques
quiet, −40,90 dBFS en esos pasajes y 16,55 dB de separación. Aun así devolvió
`not_recommended`, porque el origen procesado no justifica una puerta por rutina.

## De-esser con ReaXcomp

`preview_deesser_proposal` mide la energía de 5 a 10 kHz por ventanas, su nivel
RMS y cuánto sobresalen los picos respecto de la mediana. Esa observación no se
etiqueta automáticamente como un defecto: brillo constante y sibilancia
intermitente producen decisiones distintas.

Para una voz orgánica con evidencia suficiente, el motor propone ReaXcomp en
modo `audition_only`. Las bandas 1 a 3 se configuran con ratio 1:1, ganancia 0 dB
y auto makeup desactivado; la banda 4 comienza en el crossover propuesto y es la
única que comprime. `configure_deesser` y `apply_deesser_proposal` releen los 51
parámetros y vinculan la instancia por GUID.

La voz de Suno `10 Vocals.wav` produjo ratio sibilante p95 0,598, banda p95
−28,68 dBFS y 8,67 dB de diferencia pico-mediana. El resultado fue igualmente
`not_recommended` por su origen ya procesado.

La integración se validó en vivo con el puente 0.15.0 sobre `Vocals`. REAPER
confirmó ratio 1:1, threshold 0 dB y auto makeup desactivado en las bandas 1 a
3; en la banda 4 confirmó crossover 5200 Hz, threshold −28 dB, ratio 3:1, knee
3 dB, attack 1 ms, release 79 ms (cuantización interna del pedido de 80 ms), RMS
0 ms y estado activo. La instancia temporal se retiró por GUID y la pista volvió
a sus dos FX originales.

## Resonancia dinámica amplia con ReaXcomp

El puente 0.23.0 reutiliza la estructura verificada de ReaXcomp para controlar
una sola prominencia espectral variable. El motor mide el p90 del STFT dentro
del rango del rol, lo compara con una curva espectral suavizada y comprueba que
la energía de la banda cambie en el tiempo. Devuelve como máximo una propuesta
`audition_only`, ligada al SHA-256 del WAV.

La banda 2 queda delimitada por dos crossovers alrededor del candidato. Bandas
1, 3 y 4 se fijan en ganancia 0 dB, ratio 1:1, threshold 0 dB, makeup apagado,
auto-release apagado, detector feedback apagado y estado activo. La banda 2
usa los valores propuestos; el plugin queda normal, 100 % wet y sin delta.

Para Suno se exige mayor prominencia y variación, con ratio 1,25:1, ataque 20
ms, release 180 ms y umbral p92. Una fuente orgánica parte de ratio 1,6:1 y
umbral p82. Fuente desconocida se bloquea. Esto es control multibanda amplio,
no un EQ dinámico quirúrgico; toda propuesta requiere escucha A/B.

El stem `3 Guitar.wav` produjo un candidato centrado en 234,375 Hz, banda
165,7-331,5 Hz, prominencia 16,12 dB y variación 10,76 dB. Para Suno propuso
threshold -30,7 dB y ratio 1,25:1.

La validación en vivo 0.23.0 creó una ReaXcomp temporal con GUID
`{0C9852A6-365D-41A8-A788-160091DF6CA1}`. Una lectura independiente confirmó
los 51 parámetros: crossover inferior 165,7 Hz; crossover superior 332,4 Hz
(cuantización interna del pedido 331,5); threshold -30,7 dB; ratio 1,25:1;
knee 4 dB; attack/RMS 20 ms; release 180 ms; makeup, auto-release y feedback
apagados; Wet 100 %, bypass y delta normales. Las bandas transparentes quedaron
en 0 dB y 1:1. La transacción se deshizo y Guitar volvió a su único ReaFIR
original, con volumen -7 dB y el resto del estado intacto.

## Buses de ambiente

Los buses separan la señal directa del retorno: `create_effect_bus` crea una
pista cuyo nombre comienza por `BUS`, volumen 0 dB, paneo central, salida al
master y un único ReaVerbate o ReaDelay configurado 100 % wet (`Dry = -inf`).
`configure_ambience_fx` permite ajustar posteriormente la instancia exacta.

`create_bus_send` crea exclusivamente routing estéreo post-fader. Verifica los
GUID de origen y destino, nivel, paneo, polaridad normal, canales 1/2 y MIDI
deshabilitado. `remove_bus_send` revierte sólo esa conexión y
`remove_effect_bus` exige un bus vacío con un único FX permitido.

Las propuestas son artísticas, no correcciones inferidas del WAV. Para fuentes
orgánicas ofrecen puntos de partida por rol; el delay convierte fracciones de
beat a milisegundos usando el BPM. Los stems de Suno reciben una variante de
audición más sutil: menor nivel de envío, menos feedback y retornos más oscuros
y acotados, siempre sujetos a aprobación.

La validación real 0.16.0 creó temporalmente dos buses. `BUS Vocal Reverb`
confirmó Wet 0 dB, Dry `-inf`, room 32, dampening 65, width 0,85, predelay 25 ms,
filtros 220 Hz-8,5 kHz y envío desde `Vocals` a -24 dB. `BUS Guitar Delay`
confirmó 352,9 ms a 85 BPM, componente musical 0, feedback -25 dB, filtros
200 Hz-6 kHz, width 0,8 y envío desde `Guitar` a -28 dB. Ambos routings fueron
post-fader, estéreo, sin MIDI y `state_verified: true`. En cada prueba se
retiraron envío y bus; el proyecto volvió a 14 pistas.

## Edición de ítems y automatización

Desde el puente 0.22.0, `get_track_items` devuelve GUID, posición, duración,
fades y también la toma activa: archivo fuente, tipo, longitud, canales, sample
rate, offset, playrate y preservación de tono.
`configure_item_fades` modifica únicamente el ítem exacto, valida duración,
formas y curvaturas, y relee todos los campos. La operación es idempotente y
queda dentro de una transacción undo.

`preview_audio_integrity` analiza un WAV completo. La variante
`preview_project_item_audio_integrity` obtiene primero los datos anteriores de
REAPER, verifica que la ruta coincida y analiza únicamente el rango de fuente
reproducido por el ítem. Ambas son de sólo lectura y ligan el resultado al
SHA-256 del archivo.

El detector busca límites alejados de cero, energía en los últimos 20 ms,
saltos impulsivos aislados, silencios internos prolongados y clipping plano.
Para Suno, silencios y transientes se registran sólo como observaciones; para
audio orgánico se recomienda revisión. Un fade sugerido nunca es automático y
una cola activa se informa como riesgo, porque un fade no recupera audio que
falte.

`inspect_track_volume_envelope` sólo consulta la envolvente `<VOLENV>` si ya
existe; nunca la crea ni modifica. La escritura se mantiene como una acción
separada y explícita.

## Vocal rider por regiones

El puente 0.21.0 incorpora `apply_vocal_rider_envelope`. La propuesta offline
analiza bloques de 50 ms, calcula un umbral de actividad relativo al p90 y usa
la mediana RMS de las regiones como referencia interna. Para voz orgánica mueve
cada región sólo un 60 % hacia esa mediana, con un máximo de ±3 dB y rampas de
80/120 ms. No busca un nivel absoluto ni altera el WAV.

La aplicación exige `proposal_id`, SHA-256, ruta del WAV permitido, GUID de
pista e ítem, `source_kind=organic_multitrack` y puntos estrictamente ordenados. Verifica que la toma activa use
ese mismo archivo, transforma tiempos de fuente considerando offset y playrate,
y rechaza cualquier punto fuera del tramo reproducido. Nunca sobrescribe una
envolvente que ya tenga puntos dentro del ítem. Si debe crearla, usa la acción
nativa de REAPER y restaura la selección de pistas. Finalmente relee tiempo,
ganancia, forma y tensión de cada punto; toda la operación es deshacible.

Para `suno_stems`, el resultado es `not_recommended` y no contiene puntos: la
voz ya procesada puede conservar señal residual que una segmentación simple
confundiría con frase. Para fuente desconocida exige clasificar primero.

La prueba offline de `10 Vocals.wav` observó umbral adaptativo -39,37 dBFS y 12
regiones, pero generó cero puntos por ser Suno. REAPER confirmó además que la
pista `Vocals` tiene un único ítem de 234,875 s y una envolvente presente sin
puntos; esas consultas fueron de sólo lectura.

La escritura se validó en vivo con el puente 0.21.0 sobre una pista temporal de
3 s y un WAV sintético que simulaba tres frases orgánicas a niveles distintos.
El analizador propuso ocho puntos para dos correcciones limitadas a +3 y -3 dB.
REAPER releyó exactamente los ocho tiempos, ganancias, formas y tensiones desde
la envolvente. Después se deshicieron, en orden, la automatización y la
importación: el proyecto volvió a 14 pistas y 85 BPM. El WAV y su carpeta
temporal se eliminaron; ningún stem real fue modificado. Esta prueba verifica
estado, no sonido ni calidad perceptual sobre una voz humana.

## Prueba real 0.5.1

En REAPER 7.78/x64 se agregó ReaEQ a `Vocals` y se configuró la primera banda
pasa-altos existente con:

```text
frequency = 80.0 Hz
gain = 0.0 dB
Q = 0.71
enabled = true
```

La lectura posterior devolvió exactamente esos valores, el mismo GUID de FX y
estado habilitado/online. La sesión no se guardó, por lo que esta prueba sigue
siendo descartable.

## Casos de uso siguientes

1. Corte de graves en voz mediante pasa-altos.
2. Atenuación de resonancia mediante campana.
3. Ajuste tonal amplio mediante low/high shelf.
4. Creación explícita de notch o pasa-bajos cuando el caso lo requiera.

Fuentes: [API oficial de ReaScript](https://www.reaper.fm/sdk/reascript/reascripthelp.html)
y [guía oficial de ReaEffects](https://www.reaper.fm/guides/ReaEffectsGuide.pdf).
