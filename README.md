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
Desde el puente 0.7.0 se separan además instrumentos de efectos: `add_instrument` admite
inicialmente ReaSynth y comprueba que REAPER lo registre realmente como VSTi de
la pista, sin acoplar la interfaz a nombres arbitrarios de plugins.
El puente 0.12.2 aplica una propuesta aprobada completa en una sola transacción,
reutiliza FX mediante GUID explícitos y rechaza duplicaciones implícitas.
La acción persistente publica `on` en la columna `State` de REAPER mientras el
puente está activo y limpia el indicador al terminar.
También lee de forma no destructiva los ajustes de render y la cadena FX del
master para vincularlos con el control técnico del archivo final.
También genera propuestas conservadoras de ReaLimit desde el análisis del
archivo, exige el ID exacto aprobado, aplica parámetros en unidades legibles,
vuelve a leerlos y conserva una transacción de deshacer segura.
El mismo puente puede renderizar un candidato WAV de 24 bits a un destino nuevo
dentro de `sessions/`, verificar que REAPER lo creó y enlazar inmediatamente
su identidad SHA-256 con el análisis técnico del archivo.
El puente 0.15.0 descubre FX instalados y usados, y agrega un flujo supervisado
de ReaGate. Mide pasajes silenciosos sin clasificarlos automáticamente como
ruido, rechaza la puerta por rutina en stems de Suno y exige aprobación por ID
antes de crear o configurar una instancia identificada por GUID.
También analiza picos sibilantes de voces orgánicas y propone un de-esser con
ReaXcomp que comprime únicamente la banda superior. Los stems vocales de Suno
se diagnostican, pero no reciben este procesamiento automáticamente.
El puente 0.16.0 incorpora buses 100 % wet de ReaVerbate y ReaDelay, con envíos
post-fader identificados por GUID. Los retardos musicales se convierten a
milisegundos usando el BPM vigente y cada routing desactiva el transporte MIDI.
Suno usa perfiles de ambiente deliberadamente más sutiles que las fuentes
orgánicas, pero no queda excluido de la audición.
El puente 0.17.0 agrega edición verificable de fades por GUID e inspección de
envolventes de volumen. El puente 0.18.0 incorpora ReaTune mediante presets
propios: identifica la instancia por GUID, carga un nombre exacto y comprueba
que REAPER lo conservó, sin depender de parámetros internos no expuestos.
El puente 0.19.0 habilita el alta y retirada verificable de ReaFIR y el
descubrimiento de dominios públicos sin escribirlos. La reducción de ruido no
se habilita todavía: el modo Subtract y el perfil son estado privado del plugin.
El puente 0.20.0 incorpora saturación mediante `JS: Multi Waveshaper`: controla
Drive, Muffle y Output, fija estéreo y sobremuestreo x2, desactiva el limitador
interno y diferencia puntos de partida para Suno, fuentes orgánicas y desconocidas.
El puente 0.21.0 agrega vocal riding por regiones para voces orgánicas: liga la
propuesta al WAV y al ítem exactos, escribe sólo sobre una envolvente libre y
relee cada punto. Los stems vocales de Suno se analizan pero no se automatizan.
El puente 0.22.0 amplía la lectura de ítems con fuente, offset y playrate. El
motor puede así revisar límites duros, impulsos, silencios internos, clipping y
colas activas exactamente en el tramo usado por REAPER. Sólo propone revisión;
no corta ni repara audio automáticamente.
El puente 0.23.0 incorpora control dinámico de una resonancia amplia con
ReaXcomp: propone una única banda de audición, mantiene las otras tres
transparentes y usa un perfil especialmente suave para Suno.
El puente 0.24.0 puede aplicar una cadena FX correctiva completa y ordenada en
una única transacción: Gate, EQ, resonancia, compresión, de-esser y saturación.
El plan cruza los FX existentes, conserva los ajenos y bloquea ambigüedades.
El puente 0.25.0 agrega la preparación A/B: renderiza el mix antes y después de
la cadena, restaura los ajustes de render tras cada archivo y crea copias WAV
igualadas por LUFS mediante atenuación. La decisión sonora sigue siendo humana.
El puente 0.27.0 interpreta letras estructuradas y muestra regiones reversibles.
El motor 0.2 fusiona downbeats/modelo especialista, análisis por compás de todos
los stems, consenso por rol y repetición musical; esas métricas quedan separadas
para reutilizarlas en otras decisiones de productor.
El puente 0.28.1 agrega carga atómica de presets ReaTune y acepta volumen, paneo,
mute o solo como campos independientes dentro de una misma operación. La web
traduce órdenes simples o complejas del chat a
un catálogo tipado, exige aprobación según una política configurable, verifica
el estado y permite deshacer el plan completo. El texto libre del LLM nunca se
ejecuta directamente.
El puente 0.29.1 agrega materialización de canciones desde la web: crea o abre
un RPP propio en una pestaña de REAPER, configura el BPM e importa únicamente
los WAV cuyas rutas todavía no están presentes. La pantalla principal permite
crear borradores vacíos, agregar o quitar stems y definir su orden antes de
importar; las sincronizaciones posteriores evitan duplicar fuentes.

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
El estado completo de filtros y funciones pendientes se mantiene en
[docs/implementation-backlog.md](docs/implementation-backlog.md).
El primer recorrido verificable está en [docs/mvp.md](docs/mvp.md).
La limpieza reutilizable de MIDI contra un stem está en
[docs/midi-cleanup.md](docs/midi-cleanup.md).
La gatera y el manifiesto de sesión están en
[docs/song-preparation.md](docs/song-preparation.md).
La materialización MIDI verificable está en
[docs/midi-import.md](docs/midi-import.md).
La estrategia híbrida de procesamiento por stem está en
[docs/song-processing-strategy.md](docs/song-processing-strategy.md).
El diagnóstico ahora enlaza cada problema observado con el siguiente analizador
o filtro candidato, conservando una política especialmente cauta para Suno.
La compatibilidad mono se verifica por bloques y bandas antes de sugerir cambios
de ancho; una correlación negativa aislada no autoriza procesamiento. Véase
[docs/mono-compatibility.md](docs/mono-compatibility.md).
El análisis temporal reutilizable está en
[docs/timeline-analysis.md](docs/timeline-analysis.md) y su aplicación a
secciones en [docs/song-structure.md](docs/song-structure.md).

La automatización opcional por secciones se previsualiza antes de tocar REAPER.
Los stems de Suno reciben movimientos de media intensidad (normalmente décimas de
dB), las pistas orgánicas admiten un margen algo mayor y ninguna propuesta se
activa por defecto. La aplicación exige el identificador exacto de la propuesta,
no sobrescribe envolventes existentes y relee todos los puntos escritos. Véase
[docs/section-volume-automation.md](docs/section-volume-automation.md).
El fine-tuning lingüístico y su backend automático GPU/CPU están en
[docs/vocal-lyric-alignment.md](docs/vocal-lyric-alignment.md).
El control offline del master para distribución está en
[docs/master-delivery-qc.md](docs/master-delivery-qc.md).
El limitador de mastering supervisado está en
[docs/mastering-proposals.md](docs/mastering-proposals.md).
El render con procedencia verificable está en
[docs/rendered-master-candidates.md](docs/rendered-master-candidates.md).
Las propuestas auditables de procesamiento están en
[docs/processing-proposals.md](docs/processing-proposals.md).
El diagnóstico híbrido de stems está en
[docs/song-diagnosis.md](docs/song-diagnosis.md).
El cruce con el estado real de REAPER está en
[docs/production-plan.md](docs/production-plan.md).
El detector conservador de clics, silencios y bordes está en
[docs/research/audio-integrity-adapter.md](docs/research/audio-integrity-adapter.md).
La orquestación de una cadena por pista está en
[docs/research/producer-chain.md](docs/research/producer-chain.md).

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

### Interfaz web

La primera interfaz de PampaPilot se inicia con:

```powershell
.\scripts\run-web.ps1
```

Abra `http://127.0.0.1:8765`. Desde **Nueva canción** se cargan título, BPM,
origen, letra, stems, MIDI y referencia sin manipular la estructura interna de
carpetas. La configuración del cerebro admite LM Studio con token requerido de
forma predeterminada y un modo sin autenticación para una red confiable.
El botón **Modo compacto** abre la misma interfaz como ventana web always-on-top
abajo a la derecha, conserva la canción activa y permite operar el chat mientras
REAPER permanece visible.

Para abrir la interfaz desde otro equipo de la LAN use
`.\scripts\run-web.ps1 -ServeOnLocalNetwork`. Consulte
[`docs/web-interface.md`](docs/web-interface.md) para límites de seguridad y
alcance de la versión actual.

## Pruebas locales

```powershell
.\.venv-pampapilot\Scripts\python.exe -m pytest -v
```

El servidor local se inicia por `stdio` con:

```powershell
.\scripts\run-mcp.ps1
```

No imprime nada mientras espera un cliente MCP; ese silencio es normal.
El lanzador toma `ipc_root` de `reaper/bridge_config.local.json`, de modo que
Python y Lua conservan el mismo transporte local después de un reinicio.

La evaluación de proyectos relacionados, commits revisados, licencias y
decisiones de implementación se conserva en
[`docs/research/reaper-ecosystem-audit.md`](docs/research/reaper-ecosystem-audit.md).

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

`propose_track_processing` analiza un stem y consulta reglas YAML versionadas
para devolver cadenas tentativas de ReaEQ/ReaComp. Nunca aplica el plan: separa
observaciones, conocimiento, parámetros y verificaciones pendientes, y exige
aprobación del usuario. En stems de Suno advierte expresamente que el audio puede
venir procesado y que no debe comprimirse ni ecualizarse por rutina.
`apply_processing_proposal` exige el ID exacto aprobado, vincula cada procesador
a un GUID existente o a una creación explícita y aplica toda la cadena como una
sola transacción reversible.

## Preparación de canción

`preview_song_preparation` y `prepare_song` convierten una entrega de stems en
un manifiesto validado. Detectan formatos, duración, duplicados, roles, nombres
de pista y correspondencias MIDI/WAV; opcionalmente calculan métricas completas
de señal. El resultado incluye un plan de importación deliberadamente marcado
con `execute: false`:

```powershell
.\.venv-pampapilot\Scripts\python.exe .\scripts\prepare_song.py `
  "Mi Pequeño Sol" 85 --analysis-level signal
```

El manifiesto queda en `sessions/<canción>/song-manifest.json`. Para fuentes de
Suno conserva niveles relativos y nunca normaliza stems individualmente.

## MIDI dentro de REAPER

`import_midi` e `import_midi_batch` crean ítems sin abrir el diálogo de
importación, no modifican el tempo y vuelven a leer cada nota desde REAPER. La
primera versión conserva notas y cambios de programa, y rechaza archivos con
otros eventos para no perder expresión silenciosamente. Las pistas quedan
muteadas por defecto y cada lote es una única transacción reversible.

La instalación local de desarrollo usa un cargador pequeño para ejecutar
siempre el Lua versionado del repositorio:

```powershell
.\scripts\install-reaper-bridge.ps1
```
