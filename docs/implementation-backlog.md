# Backlog de implementación de PampaPilot

Este archivo es la lista única de funcionalidades terminadas, próximas y
pendientes. Una función no se considera completa sólo porque REAPER acepte el
comando: debe tener contrato tipado, identificación por GUID, lectura posterior,
transacción undo, pruebas y documentación. La evaluación perceptual siempre se
registra por separado.

## Procesadores ya implementados

| Procesador | Uso | Estado técnico | Validación perceptual |
|---|---|---|---|
| ReaEQ | filtros y balance tonal | implementado y verificado | por canción |
| ReaComp | control dinámico | implementado y verificado | por canción |
| ReaGate | limpieza supervisada | implementado y verificado | por canción |
| ReaXcomp | de-esser | implementado y verificado | por canción |
| ReaVerbate | reverb en bus | implementado y verificado | por canción |
| ReaDelay | delay musical en bus | implementado y verificado | por canción |
| ReaLimit | limitador de master | implementado y verificado | por entrega |
| ReaTune | carga de preset por nombre | implementado y verificado | pendiente |

## Próximo procesador: ReaFIR

Objetivo: reducción de ruido conservadora para voces, guitarras y cuerdas
orgánicas. No se aplicará automáticamente a stems de Suno ni por el solo hecho
de detectar pasajes silenciosos.

- [x] Descubrir y documentar los parámetros públicos que expone ReaFIR y
      confirmar que modo y perfil permanecen en estado privado.
- [x] Implementar alta y retirada por GUID.
- [x] Añadir descubrimiento de dominios formateados de sólo lectura.
- [ ] Implementar perfil de ruido con captura explícita de un tramo aprobado.
- [ ] Aplicar reducción en modo subtract con intensidad limitada.
- [ ] Verificar modo, mezcla, estado y perfil cargado.
- [ ] Comparar nivel y espectro antes/después sin confundir silencio con ruido.
- [ ] Añadir propuesta diferenciada para fuente orgánica, Suno y desconocida.
- [ ] Validar en una copia de voz o guitarra orgánica y escuchar artefactos.

## ReaTune: segunda etapa pendiente

La primera etapa ya puede agregar ReaTune, aplicar un preset local por nombre y
confirmar que REAPER conservó exactamente ese preset. La prueba real utilizó
`pampapilota#` sobre `Vocals` con `state_verified: true`.

REAPER guardó el preset en `%APPDATA%\REAPER\presets\vst-reatune.ini` como un
bloque hexadecimal opaco de 198 bytes. El bloque contiene el estado interno y
el nombre, pero un solo ejemplo no permite asignar con seguridad cada byte a
tonalidad, escala, notas permitidas, ataque o algoritmo.

- [ ] Automatizar capturas diferenciales: cambiar un control por vez y guardar
      un preset temporal por variante.
- [ ] Comparar los bloques y mapear tonalidad, escala, ataque, algoritmo y rango.
- [ ] Comprobar que el formato es estable entre reinicios y versiones de REAPER.
- [ ] Crear un generador seguro de presets con copia de respaldo y escritura
      atómica; nunca sobrescribir presets del usuario.
- [ ] Enumerar presets locales y mantener un catálogo con fuente, intensidad,
      tonalidad, escala, versión validada y escucha humana.
- [ ] Crear perfiles `Suno Subtle`, `Organic Natural` y `Organic Tight`.
- [ ] Inferir tonalidad primero desde MIDI y usar análisis de audio sólo como
      evidencia secundaria con nivel de confianza explícito.
- [ ] Validar perceptualmente corrección, vibrato, consonantes y transiciones.

Referencias de diseño para carga genérica de presets:

- [Total REAPER MCP](https://github.com/shiehn/total-reaper-mcp)
- [Bonfire REAPER MCP](https://github.com/bonfire-systems/reaper-mcp)

## Procesadores siguientes

### Saturación

- [ ] Descubrir qué saturadores stock/JS están instalados y elegir uno estable.
- [ ] Adaptador tipado para drive, mezcla y salida.
- [ ] Compensación de nivel para no confundir más volumen con mejor sonido.
- [ ] Perfiles sutiles para Suno y más amplios para pistas orgánicas.

### ReaPitch

- [ ] Transposición y formantes verificables por GUID.
- [ ] Doblajes y armonías como operaciones explícitas, nunca como sustituto de
      corrección vocal transparente.
- [ ] Conservar siempre la señal original o una ruta seca.

### ReaVerb de convolución

- [ ] Bus 100 % wet con respuesta impulsional permitida y ruta validada.
- [ ] Allowlist de carpetas de impulsos y verificación de archivo cargado.
- [ ] Predelay, filtros y nivel de envío dependientes de la fuente.

### Modulación y doblaje

- [ ] Chorus/doubler para voces, guitarras y cuerdas.
- [ ] Control de mezcla, ancho y compatibilidad mono.
- [ ] Evitar modulación rutinaria en stems de Suno ya procesados.

## Mezcla y edición pendientes

- [ ] Escritura segura de envolventes de volumen y paneo; la inspección ya está.
- [ ] Validación real de fades automáticos por GUID; el adaptador ya está.
- [ ] Automatización de volumen vocal por frases antes de comprimir en exceso.
- [ ] Sidechain verificable para ducking de bajo/bombo y voz/instrumentación.
- [ ] Procesamiento paralelo con buses y compensación de nivel.
- [ ] Alineación temporal y de fase entre micrófonos o tomas relacionadas.
- [ ] Detección de clics, cortes, silencios anómalos y colas truncadas.
- [ ] Encadenado de tratamientos por rol con orden explícito de FX.
- [ ] Comparación A/B con loudness igualado y restauración exacta del estado.

## Análisis y decisiones de productor pendientes

- [ ] Clasificación fiable de fuente: Suno, grabación orgánica o desconocida.
- [ ] Detección de tonalidad y acordes combinando MIDI y audio.
- [ ] Análisis de estructura: intro, estrofa, estribillo, puente y final.
- [ ] Evaluación de balance espectral y dinámica frente a referencia, con
      recomendaciones y no cambios automáticos ciegos.
- [ ] Registro de cada decisión, evidencia, confianza y posibilidad de rechazo.
- [ ] Flujo de escucha humana: aceptar, ajustar, deshacer o guardar como receta.

## Entrega profesional pendiente

- [x] Render WAV nuevo y control técnico básico de master.
- [x] Limitador supervisado y verificado.
- [ ] Perfiles de entrega por plataforma sin perseguir un único LUFS universal.
- [ ] Verificación final de principio/final, silencios, clipping, true peak,
      sample rate, profundidad de bits, canales y metadatos.
- [ ] Generación de informe de entrega y archivo reproducible de la sesión.

## Criterio de priorización

1. Funciones correctivas y medibles para grabaciones orgánicas.
2. Operaciones reversibles que ahorran trabajo repetitivo.
3. Decisiones artísticas como propuestas de audición, no como verdades.
4. Automatización autónoma sólo después de validación técnica y humana.
