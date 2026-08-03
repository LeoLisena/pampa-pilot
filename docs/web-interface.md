# Interfaz web de PampaPilot

## Alcance de la primera versión

La interfaz reemplaza la navegación manual de `media/` y `sessions/` para el
flujo habitual. Permite:

- ver el proyecto, BPM, origen, letra, secciones y stems descubiertos;
- crear una canción cargando stems, MIDI, referencia y letra;
- configurar LM Studio sin escribir el token en archivos;
- conversar con el Productor IA usando contexto estructurado del proyecto;
- recibir propuestas que siempre requieren aprobación.

En esta versión las propuestas del LLM son deliberadamente **no ejecutables**.
El botón Aplicar informa que falta el mapeo determinista y no modifica REAPER.
La siguiente capa traducirá propuestas admitidas a herramientas tipadas del
motor, volverá a leer el estado de REAPER y ofrecerá undo/A-B.

## Arranque

```powershell
.\scripts\run-web.ps1
```

Luego abrir `http://127.0.0.1:8765`.

Para acceder desde otro equipo de la misma red:

```powershell
.\scripts\run-web.ps1 -ServeOnLocalNetwork
```

El modo LAN usa HTTP sin cifrado. Debe utilizarse sólo en una red privada y con
autenticación de LM Studio habilitada. Antes de una distribución pública se
agregará autenticación propia de PampaPilot y HTTPS mediante un proxy local.

## Cerebro local

En **Configuración** se definen:

- URL de LM Studio, por ejemplo `http://192.168.1.19:1234`;
- identificador del modelo, por ejemplo `google/gemma-4-31b`;
- seguridad con token (predeterminada) o servidor sin autenticación;
- token, que se conserva sólo en memoria hasta cerrar PampaPilot.

El adaptador usa `/v1/models` y `/v1/chat/completions`. El LLM recibe un system
prompt versionado, contexto sin rutas locales, letra, secciones e inventario de
medios. Los WAV permanecen en el motor y no se envían al modelo conversacional.
