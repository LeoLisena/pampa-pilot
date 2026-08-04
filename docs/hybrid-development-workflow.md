# Flujo híbrido de desarrollo

## Objetivo

Mantener la dinámica conversacional e iterativa usada durante el desarrollo de
PampaPilot, reduciendo consumo: Codex con un LLM local resuelve el trabajo diario
y Codex de mayor capacidad supervisa decisiones y cambios de alto impacto.

## Herramienta principal

La primera opción es Codex CLI conectado a LM Studio mediante su endpoint
compatible con Responses API. Cline y OpenCode quedan como clientes alternativos:
las reglas durables viven en `AGENTS.md` y no dependen de ninguno de ellos.

El modelo local recomendado para desarrollo es Qwen 3.6 35B A3B. Qwen 3 4B puede
encargarse de clasificación, formato o cambios mecánicos mínimos, pero no debe
usarse como programador autónomo ni recibir más permisos por ser más veloz.

Codex agrega instrucciones y definiciones de herramientas al contexto. Cargue
los modelos de desarrollo en LM Studio con **16K como mínimo y 32K recomendado**.
Una ventana de 4096 tokens no alcanza: la solicitud puede fallar antes de que el
modelo lea la tarea. Esta configuración es independiente de la longitud visible
del mensaje del usuario.

Para Codex, configure `Max Concurrent Predictions` en **1**: una tarea agentica
usa las herramientas secuencialmente y cuatro slots multiplican memoria/KV sin
beneficio. Como punto de partida para la RTX 3090:

- Qwen 4B: 32K, GPU offload completo, concurrencia 1;
- Qwen 35B A3B: 16K o 32K según VRAM disponible, concurrencia 1 y el mayor GPU
  offload que permanezca estable.

### Resultado del piloto local

Codex CLI ejecutó herramientas reales con ambos modelos. Qwen 4B, aun con 32K y
offload completo, falló una tarea mediana: no localizó correctamente un módulo,
inventó perfiles prohibidos, omitió tests y declaró éxito. El worktree impidió
que ese resultado afectara el proyecto. Qwen 35B comprendió mejor el código y
produjo un borrador razonable, aunque no completó la tarea con concurrencia 4.
Por eso el 35B sigue siendo el agente diario y el 4B queda limitado a trabajo
trivial de resultado inequívoco.

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
2. El trabajo cotidiano continúa en el worktree persistente `local-llm/daily`.
   No es necesario nombrar cada pedido ni recrear su entorno Python.
3. Las tareas riesgosas, experimentales o no relacionadas usan un worktree y
   una rama independientes.
4. El modelo local trabaja en `local-llm/<tarea>`.
5. Codex trabaja o revisa en `codex/<tarea>`.
6. La rama se valida antes de integrarse; una implementación incorrecta se
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

### Uso diario: un solo comando

Después de la instalación inicial, el punto de entrada habitual es:

```powershell
.\scripts\local-development.ps1
```

Al presionar Enter se abre `daily`: conserva código, conversación y un único
entorno Python entre pedidos, para trabajar de forma continua. La opción `N`
crea una tarea aislada sólo cuando conviene separar un experimento o cambio
riesgoso. Si es necesario prepara Python automáticamente. El token sólo se
mantiene durante la sesión. El historial de conversación se separa por rama:
`daily` no retoma accidentalmente una charla de un experimento aislado.

Cuando una tarea aislada ya fue integrada, se puede limpiar con:

```powershell
.\scripts\cleanup-agent-worktree.ps1 -Task "nombre-breve"
```

La limpieza se niega a borrar worktrees con cambios locales o commits que no
estén en `main`. `daily` también está protegido y no se elimina por accidente.

También puede iniciarse sin menú:

```powershell
.\scripts\local-development.ps1 `
    -Task "nombre-tarea" `
    -Objective "Resultado concreto y verificable" `
    -Model "autor/modelo"
```

Para descartar el historial conversacional y abrir una charla nueva sobre el
mismo worktree, agregue `-NewSession`. El código y el historial local no dependen
de la disponibilidad de Codex cloud.

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

## Comparar otros modelos sin Codex cloud

Cargue cada candidato en LM Studio con al menos 16K de contexto y una sola
predicción concurrente. Luego ejecute enteramente en local:

```powershell
.\scripts\test-local-codex-model.ps1 `
    -Model "identificador/mostrado-por-lm-studio" `
    -Mode smoke
```

`smoke` comprueba lectura del repositorio, terminal y un test real sin modificar
archivos. `-Mode reasoning` compara comprensión arquitectónica. Duración, salida
y código de retorno quedan en `.runtime/model-evaluations/`, fuera de Git. Si LM
Studio queda en `PROCESSING PROMPT 0%`, cancele con Ctrl+C, expulse el modelo y
revise contexto, memoria y concurrencia antes de reintentar.
