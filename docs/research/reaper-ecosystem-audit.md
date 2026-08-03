# Auditoría del ecosistema de automatización de REAPER

Revisión realizada el 3 de agosto de 2026. Los repositorios se clonaron bajo
`.runtime/research/`, fuera de Git, y se inspeccionaron en los siguientes
commits:

- Reaper Daemon `cd60ab3280a3553eae24f46d1bf9ea8d18373b3c` (MIT);
- Total REAPER MCP `80b95e972c9f107f80a73f2f239dea0d418ee23b` (MIT);
- SWS `1eac4cba4d3f6f845c82689949f9afdfb5f35d25` (licencia permisiva tipo MIT,
  con componentes de terceros documentados por el proyecto).

Esta fase adopta ideas arquitectónicas, no fragmentos copiados. La
implementación de PampaPilot se escribió sobre su puente existente y la API
ReaScript. Si en el futuro se incorpora código sustancial de terceros, deberá
registrarse el archivo, commit, licencia, modificaciones y aviso de copyright.

## Hallazgos adoptados

Reaper Daemon confirma el valor de descubrir el estado real antes de actuar:
enumera FX instalados, expone GUID como identidad estable, limita listas de
parámetros y distingue la lectura de una mutación. También demuestra que los
nombres e índices son útiles para presentación, pero no suficientes como
identidad cuando una cadena puede cambiar.

Total REAPER MCP sirve como catálogo de cobertura ReaScript y prueba que el
puente Lua con IPC de archivos es portátil. PampaPilot no replica su superficie
de cientos de herramientas: conserva una lista pequeña, semántica y verificable
para reducir ambigüedad del LLM.

SWS es adecuado como capacidad opcional futura para medición EBU R128,
snapshots y acciones avanzadas. No pasa a ser una dependencia obligatoria: el
nucleo debe seguir funcionando en una instalación limpia de REAPER.

## Decisiones de PampaPilot 0.13

- `discover_installed_fx` obtiene nombres exactos mediante `EnumInstalledFX` y
  permite búsqueda y límite de resultados.
- `discover_project_fx` inspecciona master y pistas, filtra por nombre, devuelve
  GUID de pista y FX, y opcionalmente parámetros con identidad, valor
  normalizado y presentación de REAPER.
- Cualquier filtro por texto es sólo descubrimiento. Las futuras mutaciones
  deberán exigir GUID y releer el parámetro modificado.
- Los parámetros se limitan explícitamente para evitar respuestas gigantes y
  consumo innecesario de contexto.
- Esta fase no agrega sockets, `python-reapy`, binarios ni SWS.

## Próximas extensiones

1. buses verificados de ReaVerb/ReaDelay con envíos por GUID;
2. captura corta antes/después con el mismo rango para verificar cambios de
   señal sin confundirlos con calidad perceptual;
3. automatización de parámetros como capacidad separada y explícita.

ReaGate quedó implementado en 0.14.0 y el de-esser ReaXcomp en 0.15.0, ambos
con propuesta source-aware, aprobación por ID, mutación por GUID y relectura.

## Validación real de 0.13.0

La implementación se probó contra REAPER 7.78 en el proyecto activo de 14
pistas. `discover_installed_fx` encontró 27 coincidencias para `Rea`, incluidos
ReaGate, ReaXcomp, ReaFIR, ReaDelay, ReaVerb, ReaVerbate, ReaPitch y ReaTune.
`discover_project_fx` identificó cuatro instancias activas en tres pistas:
ReaComp y ReaEQ en voz, y dos ReaSynth en pistas MIDI. La consulta detallada de
ReaComp devolvió su GUID estable y los 24 parámetros, entre ellos threshold
-10.0 dB, ratio 1.5:1, attack 15 ms y release 120 ms. Las tres respuestas fueron
de sólo lectura y REAPER marcó `state_verified: true`.

## Validación real de 0.15.0

ReaXcomp expuso 51 parámetros distribuidos en cuatro bandas. En `Vocals`, el
adaptador dejó las bandas 1 a 3 en 1:1 y configuró sólo la banda 4 desde 5200 Hz,
threshold -28 dB, ratio 3:1, knee 3 dB, attack 1 ms y release observado 79 ms.
La relectura devolvió `state_verified: true`; la instancia temporal se eliminó
por GUID y la pista regresó a sus dos FX originales.

## Fuentes

- https://github.com/wretcher207/reaper-daemon
- https://github.com/shiehn/total-reaper-mcp
- https://github.com/reaper-oss/sws
- https://www.reaper.fm/sdk/reascript/reascripthelp.html
