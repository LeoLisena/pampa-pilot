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

## Decisiones iniciales

- Windows y REAPER 7 como primera plataforma.
- Python 3.12+ para MCP, análisis de audio/MIDI y orquestación.
- Lua/ReaScript para el adaptador que vive dentro de REAPER.
- MCP oficial v2, con el servidor local conectado por `stdio` al principio.
- Intercambio local por archivos atómicos y versionados entre Python y Lua.
- Efectos nativos de REAPER en el primer MVP.
- Un solo componente puede escribir en el proyecto; los especialistas sólo
  recomiendan acciones.

La arquitectura y sus límites están en [docs/architecture.md](docs/architecture.md).
El primer recorrido verificable está en [docs/mvp.md](docs/mvp.md).

## Pruebas locales

Por ahora no requieren dependencias externas:

```powershell
.\.venv\Scripts\python.exe -m pytest -v
```

El servidor local se inicia por `stdio` con:

```powershell
.\.venv\Scripts\python.exe -m pampapilot.mcp_server
```

No imprime nada mientras espera un cliente MCP; ese silencio es normal.

Para conectarlo a Codex, copie `.codex/config.toml.example` como
`.codex/config.toml`, reemplace las rutas absolutas y reinicie Codex. El archivo
real es local y no se versiona.
