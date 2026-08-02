# PampaPilot

Agente de producción musical con IA para controlar REAPER desde lenguaje natural
sin acoplar la automatización a un proveedor de IA específico.

> **PampaPilot — Your AI music production agent.**

El principio central es separar responsabilidades:

- el **cerebro** propone un plan;
- el **servidor MCP** expone operaciones musicales tipadas;
- el **puente de REAPER** ejecuta una lista permitida de acciones;
- el **verificador** vuelve a leer el estado y distingue ejecución de resultado;
- los analizadores pesados trabajan fuera del hilo de interfaz de REAPER.

## Estado

La etapa 0 y la primera integración están terminadas. En REAPER 7.78/x64 se
verificó el recorrido crear pista -> leer GUID -> ajustar paneo -> volver a leer
-> deshacer ambas transacciones. El proyecto terminó con su estructura inicial.
También se verificó en vivo la importación y lectura posterior de un WAV estéreo
de 48 kHz, el cambio de 120 a 85 BPM sin alterar el audio y el guardado de la
sesión con nombre propio. La primera sesión real contiene 12 stems importados y
guardados; el lote completo es una única transacción reversible. El puente
también aplica volumen, paneo y mute de varias pistas en una sola transacción. La
primera mezcla estática real fue releída desde REAPER y su suma se verificó sin
clipping antes de guardarla. El puente 0.5.1 agrega ReaComp y ReaEQ por GUID. El
compresor se configura en unidades musicales y ReaEQ permite controlar bandas
existentes por tipo e índice, con frecuencia, ganancia, Q y estado habilitado. Los
valores se vuelven a leer dentro de una única transacción reversible.

## Decisiones iniciales

- Windows y REAPER 7 como primera plataforma.
- Python 3.12.13 para MCP, análisis de audio/MIDI y orquestación.
- Lua/ReaScript para el adaptador que vive dentro de REAPER.
- MCP oficial v2, con el servidor local conectado por `stdio` al principio.
- Intercambio local por archivos atómicos y versionados entre Python y Lua.
- Efectos nativos de REAPER en el primer MVP.
- Un solo componente puede escribir en el proyecto; los especialistas sólo
  recomiendan acciones.

La arquitectura y sus límites están en [docs/architecture.md](docs/architecture.md).
El primer recorrido verificable está en [docs/mvp.md](docs/mvp.md).
La limpieza reutilizable de MIDI contra un stem está en
[docs/midi-cleanup.md](docs/midi-cleanup.md).

## Entorno Python reproducible

En Windows x64, un único comando descarga una copia verificada de `uv 0.12.1`,
instala Python 3.12.13 y sincroniza exactamente las dependencias del proyecto:

```powershell
.\scripts\bootstrap.ps1
```

Las herramientas, Python y el entorno se guardan localmente en `.tools/`,
`.runtime/` y `.venv-pampapilot/`; no se versionan. El repositorio sí conserva
`.python-version`, `pyproject.toml` y `uv.lock`, por lo que otra máquina puede
reconstruir el mismo entorno sin depender del Python instalado en Windows.

## Pruebas locales

```powershell
.\.venv-pampapilot\Scripts\python.exe -m pytest -v
```

El servidor local se inicia por `stdio` con:

```powershell
.\scripts\run-mcp.ps1
```

No imprime nada mientras espera un cliente MCP; ese silencio es normal.

Para conectarlo a Codex, copie `.codex/config.toml.example` como
`.codex/config.toml`, reemplace las rutas absolutas y reinicie Codex. El archivo
real es local y no se versiona.

El puente de REAPER usa además `reaper/bridge_config.local.json`, copiado desde
`reaper/bridge_config.example.json`. Sólo permite importar medios ubicados bajo
`allowed_media_roots` y guardar proyectos bajo `allowed_project_roots`; los stems
locales de `media/` y las sesiones de `sessions/` están excluidos de Git.

## Análisis offline de stems

El análisis objetivo se ejecuta fuera de REAPER para no bloquear su interfaz:

```powershell
.\.venv-pampapilot\Scripts\python.exe .\scripts\analyze_stems.py `
  "C:\RUTA\A\LOS\STEMS" "C:\RUTA\AL\REPORTE\stems.json"
```

El reporte incluye formato, duración, LUFS, picos, RMS, factor de cresta,
silencios, correlación estéreo, offset DC y posibles muestras saturadas. Estas
mediciones son observaciones; las decisiones musicales se toman en una etapa
posterior y siempre se verifican contra el estado de REAPER.

## Ingreso recomendado desde Suno

Cuando sea posible, cada canción debe llegar con la mezcla completa original de
Suno, todos sus stems sin renormalizar y el BPM confirmado. PampaPilot conserva
los niveles relativos de esa mezcla: no normaliza stems individualmente ni los
trata como grabaciones crudas. Primero reconstruye y compara la suma; después
busca artefactos de separación, duplicados, incompatibilidad mono o problemas
audibles concretos. EQ, compresión y rebalanceo sólo se aplican con una razón
verificable o una intención estética indicada por el usuario.

## Limpieza MIDI offline

El mismo motor admite cualquier par formado por un MIDI de interpretación y el
WAV del instrumento correspondiente. En modo `generic` no fija BPM, rango ni
instrumento. Los perfiles son optativos y todos los supuestos se pueden
reemplazar mediante configuración:

```powershell
.\.venv-pampapilot\Scripts\python.exe .\scripts\clean_midi.py `
  "C:\RUTA\instrumento.mid" "C:\RUTA\instrumento.wav" "C:\RUTA\salida"
```

El original se preserva y se generan una variante segura, otra reconstruida y
un reporte JSON auditable. La cuantización y la incorporación automática de
notas faltantes están desactivadas por defecto.

El servidor MCP expone además `discover_song_media`, `analyze_midi`,
`preview_midi_cleanup` y `clean_midi_files`. Las tres primeras operaciones son
de sólo lectura; la última conserva los originales y restringe sus salidas a
`sessions/`. De esta manera el agente puede descubrir, explicar y previsualizar
antes de generar archivos, sin que REAPER esté abierto.
