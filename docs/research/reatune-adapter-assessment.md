# Evaluación del adaptador ReaTune

En REAPER 7.78/x64, una instancia nueva de ReaTune expuso sólo tres parámetros
VST automatizables: `Bypass`, `Wet` y `Delta`. Tonalidad, escala, notas
permitidas, ataque y algoritmo permanecen en el estado interno del plugin.

La guía oficial confirma que esos controles existen en la interfaz de ReaTune,
pero la API estándar de parámetros no permite escribirlos ni releerlos. Por lo
tanto PampaPilot no escribe directamente esos controles: manipular chunks
binarios o coordenadas de pantalla sería frágil y dependiente de versión,
idioma, resolución y estado de la ventana. La automatización se realiza mediante
presets completos guardados en ReaTune.

La alternativa elegida para el puente 0.18.0 es aplicar presets ReaTune propios,
previamente validados e identificados por nombre. El adaptador recomienda el
prefijo `PampaPilot - `, localiza la instancia por GUID y confirma el preset con
`TrackFX_GetPreset` después de cargarlo con `TrackFX_SetPreset`.

La búsqueda en proyectos relacionados no encontró un adaptador específico de
tonalidad o escala. Sí encontró dos implementaciones genéricas de carga por
nombre, usadas como referencia de diseño:

- [Total REAPER MCP](https://github.com/shiehn/total-reaper-mcp/blob/main/server/tools/fx.py)
- [Bonfire REAPER MCP](https://github.com/bonfire-systems/reaper-mcp/blob/main/src/reaper_mcp/fx_tools.py)

Validación real: REAPER 7.78/x64 aplicó `pampapilota#` a una instancia ReaTune
identificada por GUID y `TrackFX_GetPreset` devolvió exactamente el mismo nombre.
Esto verifica el control de estado del preset, no la calidad perceptual de la
afinación, que continúa requiriendo escucha.

El preset local quedó almacenado en `presets/vst-reatune.ini` como un bloque
hexadecimal de 198 bytes que incluye el nombre del preset. Esto demuestra que el
estado no expuesto está serializado, pero un único bloque no permite atribuir
bytes concretos a tonalidad, escala o ataque. La segunda etapa usará capturas
diferenciales automatizadas y copias de respaldo antes de generar presets.

Alternativas futuras adicionales:

1. integrar un plugin de afinación que exponga tonalidad, escala y velocidad;
2. implementar edición de pitch offline con un motor especializado y conservar
   el original.

Fuente: [guía oficial de ReaEffects](https://www.reaper.fm/guides/ReaEffectsGuide.pdf).
