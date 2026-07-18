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

### ~~2. Gaps del wizard de import de `.tjp` externos~~ — RESUELTO

Resuelto (2026-07-14): `insight_import_wizard.py` ahora parsea el `.tjp`
fuente con un parser real (`models/tjp_parser.py`, consciente de llaves y
strings — no un regex heurístico) en vez del CSV que devuelve TJ3, que
nunca tuvo columna de dependencias ni de notas. `depend_on_ids`,
`resource_pool_ids`, `description` (de `note`) y `task_ids` de milestones ya
no se pierden al importar. De paso se encontró y arregló un bug real de
export (`_tjp_task_abs_path` emitía siempre un solo `!`, TJ3 rechazaba
dependencias entre tareas anidadas — confirmado contra el binario real
tj3-ms v3.8.4), y se agregó reimportar (reemplaza tareas/milestones
existentes, solo permitido con el proyecto en estado `draft`). Ver
CHANGELOG.md y memoria `project_insight_tjp_import_gaps` (actualizarla si
se retoma este tema, ya no refleja el estado actual).

---

## De la conversación de hoy

### ~~3. Scheduling de portfolio (multi-proyecto) para aprovechar recursos compartidos~~ — RESUELTO

Resuelto en v17.0.9.7.5 (2026-07-14): campo `state` (draft/evaluación/
progreso/finalizado) en `project_improve`; `_generate_tjp()`/
`_tj_project_users()` multi-proyecto sin caso especial para N=1;
write-back asimétrico (evaluación → solo el proyecto activo; progreso →
todos los incluidos, cada uno contra su propio escenario baseline);
cron diario para recalcular los proyectos "en progreso" juntos; reporte
de impacto (`knowledge.asset`) cuando una evaluación afecta a proyectos
en progreso, en vez del mensaje de chatter que preveía el diseño
original. Ver CHANGELOG.md [17.0.9.7.5] para el detalle completo y los
2 bugs reales encontrados durante la implementación. Memoria
`project_portfolio_scheduling_states` actualizada con el estado final.

---

## De la conversación de hoy (2026-07-10)

### ~~4. Derivar `tj_daily_rate` de `hr.contract.wage` en vez de campo manual~~ — RESUELTO

Resuelto en v17.0.9.7.12 (2026-07-18): `tj_daily_rate` pasó de campo
manual a `compute='_compute_tj_daily_rate', store=True, readonly=True` —
`contract_id.wage / 30.0` (mismo divisor que ya usa `insight.cost.budget`
para costos extra, `insight_scenario.py`), `0.0` sin contrato activo (sin
fallback manual — decisión explícita del usuario). Bruto tal cual, sin
factor de carga social propio (no hay costeo de aportes patronales
disponible sin `hr_payroll`, que no está instalado). Nueva dependencia
`hr_contract` agregada al manifest — liviana, solo depende de `hr` (ya
instalado), no arrastra `hr_payroll`. Ver CHANGELOG.md [17.0.9.7.12].

---

## Del backlog de ecosistema (2026-07-13)

Ítems recibidos como propuesta de "nivel profesional superior" para todo el
ecosistema (`insight_project`, `project_improve`, `insight_project_purchase`,
`work_item_*`, `knowledge_asset`, `odoo_ai_core`). Los que tocan otro módulo
están en el `BACKLOG.md` de ese módulo; acá solo lo que es de
`insight_project`. Visión completa (con los ítems de módulos nuevos que
todavía no existen — riesgos, EVM/ventas, portal, IA) en la memoria
`project_ecosystem_roadmap`.

### ~~5. Prioridad entre proyectos como desempate de recursos~~ — RESUELTO

Resuelto en v17.0.9.7.10 (2026-07-17): `resource_priority` (`project_improve`)
ahora se traduce al atributo nativo `priority` de TJ3
(`_tjp_task_priority_line`) — sin configurar (default 10) no cambia nada;
con un valor distinto, escala alrededor del 500 implícito de TJ3, con techo
en 799 para nunca igualar la estrella de tarea (`_TJP_HIGH_PRIORITY = 800`).
No hizo falta arbitrar nada en Python: en una corrida combinada
(`_tj_portfolio_recordset`), dos proyectos con distinta prioridad compitiendo
por el mismo recurso quedan desempatados por el propio motor de TJ3. Ver
CHANGELOG.md [17.0.9.7.10] y `docs/modules/insight_project.md`.

### ~~6. Lock/freeze de un escenario al marcarlo baseline~~ — RESUELTO

Resuelto en v17.0.9.7.10 (2026-07-17): `action_start()` (evaluación→progreso)
congela el escenario baseline vigente como una versión nueva de un
`knowledge.asset` (categoría `insight_project.baseline_snapshot`) —
inmutable gracias a `knowledge.asset.version.write()` (patrón ya existente,
no reimplementado). No se tocó `insight.task.schedule` (sigue siendo la
corrida "viva"): el freeze vive aparte, específicamente para no congelarse
solo en `action_start` y no en cada `write()` de `is_baseline` (que
`_apply_selection_strategy` reafirma en cada corrida, incluido el cron
nocturno — congelar ahí hubiera regenerado el "punto fijo" todas las
noches).

### ~~7. Reporte de desviación baseline vs. real (+ publicación como knowledge.asset)~~ — RESUELTO

Resuelto en v17.0.9.7.10 (2026-07-17): `_compute_and_save_deviation_report`
compara el baseline congelado (ítem 6) contra `insight.task.schedule`
actual, tarea por tarea (delta de fecha fin y costo, más `complete`), y
publica el corte como `knowledge.asset` versionado (categoría
`insight_project.deviation_report`). Solo aplica con el proyecto en estado
"En progreso" (necesita avance real, no proyección). De paso se unificó el
botón "Generar reportes de costos" → "Generar reportes"
(`insight.scenario.action_generate_reports`), que ahora corre costo+Gantt
siempre y desviación cuando corresponde, y el cron nocturno
(`_cron_run_portfolio_schedule`) regenera los tres reportes de cada
proyecto en progreso tras cada recálculo.

_Fuente: backlog de ecosistema propuesto por el usuario (2026-07-13,
"Épica 1" ítem 2 y "Épica 2" completa). Ver `project_ecosystem_roadmap` en
memoria para el resto de las épicas (riesgos, EVM, portal, IA), que no
tienen todavía un módulo/archivo `BACKLOG.md` propio._

---

## De la conversación de hoy (2026-07-14)

### 8. Clonar proyecto + concepto de "proyecto template" (calibración histórica de esfuerzo)

Surgió al diseñar los botones de estado de portfolio scheduling (draft/
evaluación/progreso/finalizado, ver CHANGELOG — campo `state` +
`resource_priority` en `project_improve`, motor multi-proyecto en
`insight_project`). Se descartó agregar un botón "Reabrir" desde
Finalizado — en cambio, la idea es un botón **Clonar**:

- Crea un `project.project` nuevo en estado Draft, con la misma
  estructura de tareas, misma asignación de personal/skills
  (`user_ids`/`resource_pool_ids`/`extra_skill_group_ids`) que el
  proyecto origen — pero con `allocated_hours` de cada tarea ajustado a
  lo que **realmente** costó ejecutarla, no a lo planificado (ej. una
  tarea pensada en 100hs que terminó en 120hs se clona con 120hs).
- **Concepto de "proyecto template"**: el proyecto que dio origen a una
  cadena de clones. Un clon puede a su vez clonarse de nuevo, formando
  una cadena (template → clon 1 → clon 2 → ...). Lo que se calibra en
  cada clonación no es solo la última ejecución (la del padre
  inmediato), sino el estadístico agregado de **todas** las ejecuciones
  históricas de esa misma tarea a través de toda la cadena — así el
  estimado se afina con cada ciclo real completado, no solo con el más
  reciente.
- **Estadístico de calibración**: horas reales trabajadas (timesheets),
  no el `allocated_hours` original ni el `effort`/`duration` de TJ3.
  Se descartó calcular percentil 90 con recorte de outliers por
  complejidad — arrancar con la **mediana** (robusta a outliers sin
  necesitar lógica de recorte aparte, y más representativa de "cuánto
  tarda típicamente" que p90, que sobreestima sistemáticamente por
  pensarse como buffer de seguridad, no como estimación central).
  Revisar esta elección solo si la calibración en la práctica no da
  buenos resultados.
- **Manejo de `insight.scenario.efficiency` al clonar**: los recursos
  que ya participaron en ejecuciones previas de la tarea se clonan con
  `efficiency = 1` — el promedio calibrado de horas reales YA
  incorpora el rendimiento real de ese recurso, así que aplicar un
  efficiency extra encima duplicaría el ajuste. Los recursos nuevos
  (sin historia en esa tarea) no reciben ningún cálculo automático de
  efficiency ni de horas — queda a criterio manual del administrador
  del proyecto.

**Gaps de diseño que faltan resolver antes de codear** (no son
triviales, quedan para cuando se retome este ítem):
- Identidad de tarea a través de clones: hoy cada clon crearía
  `project.task` nuevos sin ningún vínculo al original — hace falta un
  campo tipo `source_task_id`/`template_task_id` (o un mecanismo
  equivalente) para poder agrupar "la misma tarea" a través de toda la
  cadena de clones y calcular el estadístico histórico.
- De qué fuente exacta salen las "horas reales" por tarea: hoy no hay
  ningún campo que ya calcule esto — probablemente `task.timesheet_ids`
  agregado, pero falta confirmar contra el código si alcanza o si hace
  falta otra fuente (ej. `insight.task.schedule` con `complete=100`).
- Remapeo de dependencias (`depend_on_ids`) entre las tareas nuevas del
  clon — las dependencias del original apuntan a los `project.task.id`
  viejos, no a los del clon.
- Qué proyectos de la cadena cuentan para el promedio histórico: ¿solo
  los que llegaron a estado Finalizado, o cualquiera con horas
  imputadas independientemente de su estado actual?

_Fuente: conversación del usuario sobre UI de estados de portfolio
scheduling (2026-07-14), explícitamente pospuesto ("no nos volvamos
locos" con el cálculo) — anotado para no perderlo, no implementado
todavía._

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
