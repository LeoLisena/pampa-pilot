# Interfaz de efectos nativos

PampaPilot no expone parámetros VST arbitrarios. Cada efecto permitido tiene un
adaptador tipado que recibe unidades musicales, usa GUID estables y vuelve a leer
el estado que REAPER conservó.

## Identidad común

Toda mutación requiere:

- `project_ref`: identidad de la instancia y ruta del proyecto activo;
- `track_guid`: identidad estable de la pista;
- `fx_guid`: identidad estable de la instancia del efecto.

`add_stock_fx` permite actualmente `reacomp`, `reaeq`, `reagate`, `reaxcomp`,
`reaverbate` y `readelay`. Cada alta comprueba que
la cadena aumentó exactamente en un efecto y que éste quedó habilitado y online.

`add_instrument` separa los generadores de sonido de los efectos de audio. Su
primer adaptador permite `reasynth`; además de comprobar nombre, GUID y estado,
exige que REAPER lo reconozca como el instrumento de la pista. Rechaza la
operación si la pista ya tiene otro instrumento, para no crear cadenas ambiguas.
La interfaz queda preparada para incorporar otros VSTi mediante identificadores
permitidos, sin aceptar nombres arbitrarios provenientes del cerebro.

ReaSynth sirve para validar de punta a punta que un MIDI produce sonido. No se
considera una emulación de guitarra ni una decisión tímbrica de producción.

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
