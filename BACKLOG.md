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

### ~~1. Dependencia Finish→Finish (FF) real~~ — RESUELTO

Resuelto en v17.0.9.6.9/.10 (2026-07-11): no hizo falta el hito
sintético+`alap` que se especulaba acá — `precedes {onend}` alcanza por
sí solo. Ver CHANGELOG.md [17.0.9.6.10] y memoria
`project_tj3_feature_backlog`.

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

**Nota (2026-07-13):** existe una versión más completa de este diseño (3
estados: draft/en evaluación/en progreso, con mensaje de impacto cruzado
en el chatter) documentada en la memoria `project_portfolio_scheduling_states`
— no implementada tampoco, es la referencia a usar si se retoma este ítem.
Si el multi-proyecto completo resulta demasiado grande para atacar de una,
el ítem 5 de abajo (prioridad entre proyectos como desempate) es un primer
paso más chico que no requiere agregar todos los proyectos a un único
`.tjp`.

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

## Del backlog de ecosistema (2026-07-13)

Ítems recibidos como propuesta de "nivel profesional superior" para todo el
ecosistema (`insight_project`, `project_improve`, `insight_project_purchase`,
`work_item_*`, `knowledge_asset`, `odoo_ai_core`). Los que tocan otro módulo
están en el `BACKLOG.md` de ese módulo; acá solo lo que es de
`insight_project`. Visión completa (con los ítems de módulos nuevos que
todavía no existen — riesgos, EVM/ventas, portal, IA) en la memoria
`project_ecosystem_roadmap`.

### 5. Prioridad entre proyectos como desempate de recursos

Hoy, en modo ejecución, todos los proyectos compiten por los mismos
candidatos sin ningún criterio de desempate — es la brecha de mayor
impacto detectada en la auditoría del ecosistema. Depende de un campo
nuevo en `project.project` (`resource_priority`, ver `project_improve/
BACKLOG.md`); acá el trabajo es usarlo en el punto donde
`_apply_selection_strategy()`/la resolución de `resource_pool_ids`
compartidos resuelve conflictos entre proyectos — hoy esa resolución es
estrictamente intra-proyecto (`project_project.py:1349-1387`, nunca mira
otros `project.project`). Criterio de aceptación: dado un empleado
candidato en dos proyectos con distinta prioridad, el de mayor prioridad
se queda con el recurso en el cálculo automático.

Es un primer paso más chico que el ítem 3 de arriba (portfolio completo):
no requiere unificar todos los proyectos en un solo `.tjp`, solo usar la
prioridad como criterio de desempate donde ya se resuelven pools
compartidos.

### 6. Lock/freeze de un escenario al marcarlo baseline

Hoy `is_baseline` (`insight_scenario.py`) es un booleano sin ninguna
protección: cada re-import/reschedule (`_import_scenario_csv`,
`project_project.py:1436-1442`) borra y recrea `schedule_ids` del mismo
escenario sin importar si es baseline o no — no hay forma de comparar
"cómo se aprobó el proyecto" contra "cómo está ahora" porque el baseline
se pisa solo. Idea: al marcar/aprobar un escenario como baseline, congelar
una copia inmutable de fechas/costos, mismo patrón que
`knowledge.asset.version.write()` (bloquea todo salvo `state`) — ya usado
en el módulo `knowledge_asset` que `insight_project` ya consume (ver
`_get_or_create_cost_asset`/`_compute_and_save_cost_reports`, v17.0.9.7.0).

### 7. Reporte de desviación baseline vs. real (+ publicación como knowledge.asset)

Depende del ítem 6 (necesita un baseline congelado contra qué comparar).
Generar automáticamente el delta (fechas, costo, avance) entre el
baseline y el estado actual del proyecto, sin depender de comparar dos
reportes a mano. Publicar cada corte de comparación como
`knowledge.asset` versionado — mismo patrón ya implementado para
`_compute_and_save_cost_reports`, pero acá con `category` propia (ej.
`insight_project.deviation_report`) en vez de reusar la de costos.

_Fuente: backlog de ecosistema propuesto por el usuario (2026-07-13,
"Épica 1" ítem 2 y "Épica 2" completa). Ver `project_ecosystem_roadmap` en
memoria para el resto de las épicas (riesgos, EVM, portal, IA), que no
tienen todavía un módulo/archivo `BACKLOG.md` propio._

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
