# Insight Project — TaskJuggler Integration

Odoo 17 addon that integrates TaskJuggler 3 scheduling into Odoo projects.

## Features

- Schedule Odoo projects via a TaskJuggler 3 microservice
- Multiple planning scenarios per project (baseline, alternative)
- Resource availability from HR employees or manual shifts/vacations
- Schedule results stored in Odoo (`insight.task.schedule`)
- Critical path flag propagated to `project.task`
- TJ3 microservice URL configurable via Settings

## Flujo de tareas

El flujo de una tarea se compone de tres dimensiones independientes, ninguna
de las cuales reemplaza a las demás:

- **Etapa (`stage_id`)**: dónde se encuentra la tarea dentro del proceso de
  trabajo (kanban stage).
- **Estado (`state`)**: la situación del trabajo realizado sobre la tarea.
- **Bloqueada (`blocked`)**: si existe un impedimento que impide continuar
  el trabajo.

### Etapas (`stage_id`)

- **Requiere refinado** — la tarea fue creada pero aún no reúne la
  información necesaria para ser planificada (puede faltar descripción,
  criterios de aceptación, responsable, estimación, prioridad o
  dependencias). No debe ser considerada por el planificador.
- **Backlog** — la tarea está completamente definida y lista para ser
  priorizada/asignada cuando existan recursos disponibles. Es la etapa
  asignada por defecto a las tareas importadas desde TaskJuggler que ya
  tienen esfuerzo/recursos (ver `insight_import_wizard.py`).
- **En progreso** — existe al menos un responsable trabajando activamente
  sobre la tarea.
- **En revisión** — el desarrollo terminó y la tarea está siendo revisada
  (técnica, funcional, QA o de usuario).
- **Completada** — la tarea fue aceptada y finalizada; no requiere trabajo
  adicional.
- **Cancelada** — la tarea deja de formar parte del proyecto (cambio de
  alcance, duplicación, decisión del cliente, pérdida de prioridad).

Las transiciones entre "En progreso"/"En revisión"/"Completada"/"Cancelada"
se hacen manualmente desde el kanban de tareas; la importación de
TaskJuggler solo asigna Requiere refinado/Backlog/Completada según el
heurístico de esfuerzo/recursos/porcentaje completado.

### Estados (`state`, nativo de `project.task`)

- **`01_in_progress`** — el trabajo continúa normalmente; estado por
  defecto para las tareas activas.
- **`02_changes_requested`** — durante la revisión se solicitaron
  modificaciones; la tarea vuelve a trabajo activo para corregir.
- **`03_approved`** — la revisión fue aprobada; la tarea queda lista para
  pasar a la etapa Completada.
- **`04_waiting_normal`** / estados cerrados (`done`/`canceled`) — la tarea
  está en espera, finalizada o cancelada.

### Campo `blocked`

`fields.Boolean` en `project.task`. Indica que la tarea no puede continuar
temporalmente debido a un impedimento:

- no modifica la etapa ni el estado;
- puede ocurrir en cualquier etapa/estado activo;
- puede activarse y desactivarse en cualquier momento;
- **no almacena el motivo** — el motivo se registra como comentario en el
  chatter de la tarea o en el parte de horas (`account.analytic.line`), no
  en este campo.

En el systray de sesión (`insight.user.session`):

- Al **entrar** a una tarea (`switch_task`), `blocked` se resetea a
  `False` — retomar una tarea activamente la desbloquea, y la nota de
  intención capturada ("¿qué se va a hacer?") cumple el rol de comentario
  de desbloqueo.
- Al **salir** de una tarea (`_close_active_period`), `blocked` solo se
  fija a `True` si la plantilla de cierre elegida tiene
  `sets_blocked=True` (plantilla seed: "Se bloqueó la tarea porque:",
  con detalle obligatorio). Ninguna otra plantilla de salida toca este
  campo.

## Installation

```bash
git submodule add -b develop https://github.com/csrocha/insight_project addons/insight_project
```

Depends: `project`, `hr_holidays`

## License

OPL-1 — Cristian S. Rocha <csrocha@gmail.com>
