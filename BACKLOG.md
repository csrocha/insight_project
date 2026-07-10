# BACKLOG

Ideas y mejoras propuestas para `insight_project` que todavía no se
implementaron. A diferencia del `CHANGELOG.md` (que registra lo que ya se
hizo, con su prompt y discusión de diseño), este archivo junta lo que
falta, para no perderlo entre chats.

Fuentes usadas para armar esta primera versión: `CHANGELOG.md` (secciones
"Discusión de diseño" que mencionan algo descartado o pospuesto), la
memoria de sesiones anteriores, y la conversación de hoy (2026-07-09).
**No tengo acceso a otras sesiones de chat fuera de eso** — si hay
propuestas de otras conversaciones que no llegaron a ninguno de esos dos
lugares, avisá y las agrego.

---

## Recuperadas de conversaciones anteriores

### 1. Dependencia Finish→Finish (FF) real

Hoy `tj_dependency_type='FF'` falla explícito en el export
(`_tjp_task_block`, `project_project.py`) en vez de exportar algo que TJ3
ignore en silencio. Pero un FF genuino es posible: un hito sintético que
dependa de ambas tareas, combinado con `scheduling alap` en la tarea
dependiente (para que el motor la calcule hacia atrás en vez de hacia
adelante). Se descartó implementarlo de una porque `alap` cambia el modo
de planificación de *toda* la tarea, no solo la arista FF puntual, y
puede interactuar de forma no obvia con sus otras dependencias FS/SS.
Queda como cambio dedicado, con sus propios tests de esa interacción.

_Fuente: CHANGELOG.md [17.0.9.6.0], sección "Discusión de diseño"._

### 2. Gaps del wizard de import de `.tjp` externos

En `insight_import_wizard.py` (importar un `.tjp` de afuera de Odoo, no el
roundtrip de reschedule):

- **`depends` se ignora por completo al importar** — las dependencias
  declaradas en el archivo externo se pierden en silencio; no quedan
  registradas en `project.task.depend_on_ids`.
- **`note` se pierde end-to-end** — ni el `taskreport` inyectado ni
  `_parse_csv_preview` lo leen; ese texto nunca llega a Odoo.
- **Milestones importados quedan con `task_ids` vacío** (consecuencia del
  fix "los milestones son milestones, no son tareas"): como ya no se crea
  un `project.task` para el milestone, `_tjp_milestone_block` (lado
  export) nunca los va a re-emitir en un reschedule futuro — su guard
  `if not dep_tasks: return []` los omite. Si se quiere que un milestone
  importado sobreviva al roundtrip export→TJ3→import, hace falta resolver
  el gap de `depends` (arriba) y linkear el milestone a esas tareas reales
  en el import, en vez de dejarlo sin `task_ids`.

_Fuente: memoria de sesión (`project_insight_tjp_import_gaps`), confirmado
reproduciendo contra un `.tjp` de producción real y el microservicio
`tj3-ms`._

---

## De la conversación de hoy

### 3. Scheduling de portfolio (multi-proyecto) para aprovechar recursos compartidos

Hoy `action_run_schedule()` agenda un proyecto a la vez: un `.tjp` con un
solo `project`, un pool de recursos y una ventana de fechas. Si una
persona ya está comprometida en el Proyecto A, el Proyecto B lo agenda
como si estuviera libre — no hay noción de carga real compartida entre
proyectos.

Idea: introducir una etapa de proyecto (campo nuevo, no existe hoy en
`project.project` — ni en Odoo core ni en `insight_project`/
`project_improve` hay nada tipo draft/running):

- **Draft**: comportamiento actual, `action_run_schedule()` agenda solo
  ese proyecto. Sirve para evaluar y presupuestar proyectos individuales
  antes de aceptarlos.
- **Running/integrado**: una vez aceptado, el reschedule pasa a incluir
  a **todos** los proyectos en este estado en un único `.tjp` (un solo
  `project`, un pool de recursos compartido armado a partir de
  `_tj_project_users()` de cada proyecto involucrado), para que
  `select minallocated` y el análisis de picos de concurrencia reflejen
  la carga real entre proyectos.

Punto abierto (de gobernanza, no técnico): en modo portfolio, replanificar
un proyecto deja de ser una acción aislada de su dueño — puede mover
fechas o la asignación de recursos de otros proyectos "running". Falta
decidir quién dispara ese reschedule combinado (¿cron nocturno? ¿botón
manual con aviso a los demás project managers?) antes de construirlo.

---

## De la conversación de hoy (2026-07-10)

### 4. Derivar `tj_daily_rate` de `hr.contract.wage` en vez de campo manual

Hoy `hr.employee.tj_daily_rate` (`hr_employee.py`) es un campo manual sin
ninguna vista que lo autocalcule. El usuario preguntó si no podía salir
del contrato de trabajo del empleado — la respuesta es que el dato
existe (`hr.contract.wage`, salario bruto mensual, vía
`hr.employee.contract_id` que ya resuelve cuál es el contrato vigente),
pero hay 3 fricciones que hacen que no sea un cambio chico:

- **Dependencia nueva**: `hr_contract` está desinstalado hoy en la base
  `fop` (confirmado contra `ir_module_module`) y no es dependencia de
  `insight_project` — instalarlo es una decisión de alcance, no solo de
  código.
- **Conversión de unidad**: `wage` es mensual, `tj_daily_rate` es diario
  — hace falta decidir el divisor (¿22 días fijos? ¿los días laborables
  reales del calendario del empleado ese mes?) y si se usa bruto o un
  costo cargado (con aportes patronales), lo cual es una política de
  costeo que hoy no está resuelta en ningún lado del código.
- **Contrato ausente**: qué hacer si el empleado no tiene contrato activo
  (¿0? ¿mantener el campo manual como fallback?).

_Fuente: pregunta del usuario en la sesión del ítem "limits" (2026-07-10),
sin implementar todavía — queda para validar la política de costeo antes
de tocar código._

---

## Seguimiento operativo (no es una mejora de producto, pero quedó pendiente de hoy)

- Correr un reschedule real sobre el proyecto de "Eje V" (y en general
  sobre `fop`) para que el fix de `_parse_tj_resource_ids` (formato real
  de TJ3 `"Nombre (uID)"` en la columna `resources`) backfillee
  `user_ids` en las tareas que quedaron sin responsable asignado.

---

## Ideas propias, sin validar todavía con el usuario

Detectadas leyendo el export (`_generate_tjp`/`_tjp_task_block`/
`_tjp_reports`) mientras se investigaba el bug de hoy — no vinieron de
ninguna conversación previa, quedan acá para discutir si valen la pena:

- El `taskreport` del reschedule por proyecto
  (`_tjp_reports`) no incluye la columna `complete` (el wizard de import
  externo sí la usa). Sin ella, no hay forma de traer de vuelta el
  % de avance que calcula TJ3 — el único mecanismo de "task vencida"
  hoy es el heurístico de `_cron_flag_changes_requested`
  (fecha vencida u horas agotadas en camino crítico).
