# Interfaz de efectos nativos

PampaPilot no expone parámetros VST arbitrarios. Cada efecto permitido tiene un
adaptador tipado que recibe unidades musicales, usa GUID estables y vuelve a leer
el estado que REAPER conservó.

## Identidad común

Toda mutación requiere:

- `project_ref`: identidad de la instancia y ruta del proyecto activo;
- `track_guid`: identidad estable de la pista;
- `fx_guid`: identidad estable de la instancia del efecto.

`add_stock_fx` permite actualmente `reacomp`, `reaeq` y `reagate`. Cada alta comprueba que
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
