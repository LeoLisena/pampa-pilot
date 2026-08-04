# Flujo híbrido de desarrollo

## Objetivo

Mantener la dinámica conversacional e iterativa usada durante el desarrollo de
PampaPilot, reduciendo consumo: Codex con un LLM local resuelve el trabajo diario
y Codex de mayor capacidad supervisa decisiones y cambios de alto impacto.

## Herramienta principal

La primera opción es Codex CLI conectado a LM Studio mediante su endpoint
compatible con Responses API. Cline y OpenCode quedan como clientes alternativos:
las reglas durables viven en `AGENTS.md` y no dependen de ninguno de ellos.

El modelo local recomendado para el piloto es el Qwen 35B ya disponible. Un
modelo rápido puede encargarse de documentación o cambios mecánicos, pero no debe
recibir más permisos por ser más veloz.

Codex agrega instrucciones y definiciones de herramientas al contexto. Cargue
los modelos de desarrollo en LM Studio con **16K como mínimo y 32K recomendado**.
Una ventana de 4096 tokens no alcanza: la solicitud puede fallar antes de que el
modelo lea la tarea. Esta configuración es independiente de la longitud visible
del mensaje del usuario.

## Responsabilidades

### Modelo local

- desarrollo cotidiano con libertad para razonar y proponer un enfoque mejor;
- implementaciones pequeñas y medianas bien delimitadas;
- tests y documentación;
- schemas que sigan un patrón existente;
- correcciones localizadas y tareas repetitivas;
- exploración y prototipos de ideas mayores dentro de su worktree;
- validación automática y explicación del diff.

### Codex supervisor

- arquitectura y contratos entre componentes;
- bridge Lua, IPC, procesos, concurrencia y seguridad;
- bugs difíciles y refactors delicados;
- revisión de ramas `local-llm/*`;
- validación final antes de integrar cambios importantes.

## Aislamiento Git

1. `main` representa la versión estable.
2. Cada tarea usa un worktree y una rama independientes.
3. El modelo local trabaja en `local-llm/<tarea>`.
4. Codex trabaja o revisa en `codex/<tarea>`.
5. La rama se valida antes de integrarse; una implementación incorrecta se
   descarta eliminando su worktree y rama, nunca restaurando destructivamente
   `main`.

Crear una tarea local:

```powershell
.\scripts\new-agent-worktree.ps1 `
    -Task "nombre-breve" `
    -Agent local-llm `
    -Objective "Descripción concreta y verificable" `
    -Start
```

Con `-Start`, el comando crea el worktree, escribe un brief local no versionado,
prepara su entorno e inicia Codex con Qwen. Sin `-Start`, sólo muestra los comandos
que deben ejecutarse. No hace commits ni push automáticamente. Cada rama mantiene
su propio entorno `.venv-pampapilot` y el sandbox no necesita acceder al entorno
de `main`.

Al terminar, el supervisor puede obtener un resumen y ejecutar la validación sin
integrar nada:

```powershell
.\scripts\review-agent-worktree.ps1 `
    -WorkingDirectory "C:\ruta\al\worktree"
```

El script rechaza ramas que no sean `local-llm/*`. La revisión automática no
reemplaza la lectura semántica del diff por Codex ni una prueba manual en REAPER.

## Libertad del agente local

El protocolo no debe reducir al LLM a ejecutar una lista cerrada de instrucciones
de desarrollo. Qwen puede inspeccionar el repositorio completo, razonar sobre el
problema, cuestionar la solución sugerida, comparar alternativas y hacer cambios
de soporte que mejoren el resultado. El objetivo y los tests definen el resultado;
no prescriben cada paso.

Los límites estrictos protegen el entorno estable, las credenciales y las acciones
reales en REAPER. Una idea ambiciosa puede desarrollarse como prototipo en una
rama `local-llm/*`; simplemente necesita revisión de Codex antes de integrarse.

## Uso de Codex con LM Studio

Instalar la copia local verificada de Codex CLI:

```powershell
.\scripts\install-codex-cli.ps1
```

En la misma PC:

```powershell
$env:LM_STUDIO_BASE_URL = "http://127.0.0.1:1234/v1"
.\scripts\start-local-codex.ps1
```

Con LM Studio en la PC de la RTX 3090:

```powershell
$env:LM_STUDIO_BASE_URL = "http://IP-PRIVADA-O-TAILSCALE:1234/v1"
.\scripts\start-local-codex.ps1
```

Si LM Studio requiere autenticación, el lanzador solicita el token de manera
segura cuando `LM_STUDIO_API_KEY` no existe y PampaPilot tampoco tiene uno
guardado con DPAPI. Sólo vive en el proceso actual y no
se escribe en Git. Un proxy efímero limitado a `127.0.0.1` agrega la cabecera al
modo OSS de Codex y termina junto con la sesión. En una red local sin
autenticación se puede usar
`-NoAuthentication`, pero no se recomienda para una interfaz expuesta en LAN.
Las sesiones y ajustes del agente local viven en `.runtime/codex-local-home`,
separados del Codex de escritorio y de sus plugins personales.

## Validación

El contrato mínimo de finalización es:

```powershell
.\scripts\validate.ps1
```

Incluye comprobaciones de whitespace, compilación de Python y la suite completa.
Las pruebas offline no sustituyen una prueba manual en REAPER ni una escucha.

## Trabajo remoto

La app móvil de ChatGPT puede controlar el host de la app de escritorio y
continuar las conversaciones de Codex alojadas allí. Una sesión independiente
de Codex CLI con Qwen local no aparece automáticamente en la app móvil.

Para operar el agente local desde fuera se usará una red privada como Tailscale
y, según la necesidad, terminal remota o una interfaz web. Nunca se publica LM
Studio ni Codex app-server directamente en Internet. Codex, Cline u OpenCode
pueden compartir el mismo repositorio, ramas y `AGENTS.md`.

## Continuidad de contexto

GitHub transporta código y revisiones, no el historial completo de una charla.
La continuidad durable debe quedar en:

- `AGENTS.md`: reglas y límites;
- `docs/architecture.md`: arquitectura;
- `docs/implementation-backlog.md`: estado funcional y pendientes;
- documentación de cada función y decisiones relevantes;
- commits y pull requests pequeños con explicación verificable.

## Criterio de integración

Un cambio local puede proponerse para integración cuando su alcance sigue siendo
el solicitado, el diff es comprensible, las validaciones pasan y no toca un área
de revisión obligatoria. El usuario decide si se integra; el agente nunca hace
merge automático a `main`.
