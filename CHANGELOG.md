# CHANGELOG

Formato basado en [Keep a Changelog](https://keepachangelog.com/es/1.1.0/).
Versionado: `17.0.MAYOR.MENOR.PARCHE`.

Cada entrada de version incluye el **prompt** que motivo los cambios
y las **discusiones de diseno** relevantes que influyeron en las decisiones,
para trazabilidad completa del razonamiento de agentes de IA.

---

## [17.0.9.6.3] - 2026-07-09

### Prompt

> "Sigamos con el backlog de TJ3" (ítem 1 del backlog priorizado por
> impacto en la calidad del cálculo: `priority`).

### Discusión de diseño

- `project.task.priority` de Odoo core es binario (`'0'` Low / `'1'`
  High, la estrella nativa) — no la escala granular que en un principio
  se especuló en la memoria de sesión ("¿probablemente ya tiene un campo
  de prioridad mapeable 1:1?"). TJ3 en cambio espera un entero 1-1000
  (default implícito 500) para desempatar contención de recursos entre
  tareas competidoras.
- Con una fuente binaria, no tiene sentido inventar una escala granular
  del lado Odoo: se mapea Low → sin línea (coincide con el default
  implícito de TJ3) y High → `priority 800`, constante fija
  (`_TJP_HIGH_PRIORITY`) que garantiza ganar contención frente a
  cualquier tarea en el default.
- La línea se emite en cualquier profundidad de tarea (no solo hojas),
  porque en TJ3 `priority` es un atributo de tarea normal, no exclusivo
  de tareas con `effort`/`allocate`.

### Agregado

- `_tjp_task_block` (`project_project.py`) emite `priority 800` para
  tareas con `priority='1'` (Important); tareas Low no emiten nada.
- Tests en `test_tjp_export.py`: alta prioridad emite la línea, baja la
  omite, y se aplica igual en tareas anidadas.
- `BACKLOG.md`: se remueve el ítem de `priority` (ya resuelto).

---

## [17.0.9.6.2] - 2026-07-09

### Prompt

> "No entiendo que pasa. insight_project genera la siguiente exportación
> pero no completa la tarea. Mira el caso explícito de la tarea 'Eje V:
> Migración de Datos Históricos'." → "El import no actualiza el task en
> Odoo" → "Pon foco en los usuarios que tienen que completar la tarea."

### Discusión de diseño

- Se reprodujo `tj3 3.8.4` real (contenedor `tj3-ms`) contra un `.tjp`
  mínimo con `allocate`: la columna `resources` del `taskreport` CSV
  **siempre** viene como `"Nombre Completo (u12)"`, nunca como el token
  crudo `"u12"` que `_parse_tj_resource_ids` esperaba.
- Confirmado contra la base real `fop`: de 363 registros
  `insight.task.schedule` existentes, ninguno tenía `resource_ids`
  poblado — el parser fallaba el `int()` sobre el string completo,
  devolvía `[]` en silencio, y `_sync_gantt_dates` nunca llegaba a
  escribir `user_ids`. El bug es sistémico (todos los proyectos), no
  específico de "Eje V" — esa tarea solo lo hacía visible porque además
  nunca tuvo `user_ids` asignado a mano.
- `insight_import_wizard.py` (`_parse_csv_preview`) ya resolvía este
  mismo formato correctamente vía regex — la inconsistencia entre los
  dos caminos de import (wizard de `.tjp` externo vs. reschedule por
  proyecto) es lo que dejó pasar el bug sin que ningún test lo
  detectara: los fixtures de test usaban el formato viejo (`"u12"`
  bare), no el real de TJ3.

### Corregido

- `_parse_tj_resource_ids` (`project_project.py`) ahora extrae el id con
  `\(u(\d+)\)`, alineado con el formato real de TJ3 y con el parser ya
  correcto de `insight_import_wizard.py`.
- Fixtures de `test_tjp_schedule_import.py` y `test_scenario_selection.py`
  actualizados al formato real (`"Nombre (uID)"`) — antes daban falsos
  positivos al no ejercitar la columna `resources` como la devuelve TJ3.

### Agregado

- `BACKLOG.md`: mejoras pendientes recuperadas de `CHANGELOG.md` (FF vía
  hito sintético + `alap`), de memoria de sesión (gaps de `depends`/
  `note`/milestones en el wizard de import externo) y de la discusión de
  hoy (scheduling de portfolio multi-proyecto para compartir recursos
  entre proyectos "running").

---

## [17.0.9.6.1] - 2026-07-09

### Prompt

> "Quiero que el botón de Rescheduling aparezca también en las tareas, al
> lado de activar tarea. Esto para que el project manager pueda modificar
> una tarea y ver el resultado de su modificación en la tarea misma."

### Discusión de diseño

- `action_reschedule_project` ya existía en `project.task` y ya se
  mostraba en los headers de kanban/tree (multi-registro), pero no en el
  form de una tarea individual. El "▶ Activar tarea" de `work_item_task`
  sí vive en el header del form (`project.view_task_form2`).
- No fue necesario tocar Python: el método ya cae en el fallback
  `self.mapped('project_id')[:1]` cuando el contexto no trae
  `default_project_id`/`active_model` (el caso de un botón de form sobre
  un único registro), así que desde la tarea resuelve el proyecto
  contenedor igual que desde kanban/tree y corre `action_run_schedule()`
  sobre él.
- `insight_project` no depende de `work_item_task` (ni viceversa), así
  que no hay garantía de orden exacto entre "Replanificar" y "▶ Activar
  tarea" dentro del header — ambos quedan agregados vía
  `position="inside"` sobre el mismo `//header`.

### Agregado

- Botón "Replanificar" en el header del form de `project.task`
  (`views/project_task_views.xml`), junto al de "▶ Activar tarea".

---

## [17.0.9.6.0] - 2026-07-09

### Prompt

> "Quiero que me presentes el pseudo algoritmo de construcción de TJP de
> insight_project [...] y si estamos usando todas las características que
> tenemos para explotar al máximo el TJ3 [...] Hagamos un plan para
> aprovechar cada una de estas característica [...] Empecemos con
> Dependencias siempre FS, como has dicho es casi trivial."

### Discusión de diseño

- `project.task.tj_dependency_type` (FS/SS/FF) ya existía en el modelo y
  ya se mostraba en el form de tarea, pero `_tjp_task_block` lo ignoraba
  por completo: siempre emitía `depends !path` sin modificador. Elegir
  SS o FF en el form no tenía ningún efecto en el schedule — peor que no
  tener el campo.
- Investigando la sintaxis real de TJ3: `depends` solo puede anclar el
  **inicio** de la tarea dependiente contra el inicio (`{ onstart }`,
  Start→Start) o el fin (sin modificador, Finish→Start) de su
  predecesora. No existe una forma nativa de anclar el **fin** de la
  tarea dependiente contra nada — Finish→Finish no es un constraint
  directo de `depends`.
- Sí existe un truco real (no cosmético) para lograr un FF genuino: un
  hito sintético que depende de ambas tareas combinado con
  `scheduling alap` en la tarea dependiente, para que el motor la
  calcule hacia atrás en vez de hacia adelante. Se descartó implementarlo
  en este cambio porque `alap` cambia el modo de planificación de *toda*
  la tarea (no solo la arista FF puntual) y puede interactuar de forma no
  obvia con sus otras dependencias FS/SS — queda como un plan futuro
  dedicado, con sus propios tests de esa interacción.
- Mientras tanto, elegir FF debe fallar alto y claro en el export en vez
  de exportar un `.tjp` que ignora la elección en silencio (mismo estilo
  que el `UserError` ya existente en `_tjp_resource_id`).

### Agregado

- `_tjp_task_block` ahora emite `depends !path { onstart }` para
  dependencias `tj_dependency_type='SS'` (antes: sin efecto, igual que
  FS).

### Arreglado

- Elegir `tj_dependency_type='FF'` en una tarea ahora levanta un
  `UserError` explícito al exportar/replanificar en vez de exportar un
  `.tjp` que trata la dependencia como FS en silencio.

### Tests

- `test_dependency_ss_emits_onstart_modifier`,
  `test_dependency_multiple_blockers_share_task_type` (el tipo se aplica
  por tarea, no por arista) y `test_dependency_ff_raises_user_error` en
  `tests/test_tjp_export.py`.

---

## [17.0.9.5.1] - 2026-07-08

### Prompt

> "Acabo de ver cómo el siguiente milestone no apareció como milestone en
> Odoo, sino como tarea. [...] Veo que el problema está en la importación.
> [...] Quiero que hagas un nuevo test para reproducir este error. [...]
> Veo que el test no es contra la base de datos. Quiero que pruebes la
> importación completa, hasta que llegue la instancia en la base de datos
> y luego recuperes las tareas y no deberían estar los milestones. Y
> deberías encontrar en project.milestones los milestones de Tj3. [...]
> Si, exacto. Los milestones son milestones, no son tareas."

### Discusión de diseño

- La sospecha inicial (el heurístico `_find_milestone_task_ids`, regex sin
  brace-matching real) resultó no ser el problema: se reprodujo contra el
  `.tjp` real de producción (152 tareas, escenarios `plan/withia/noai`,
  dependencias cruzadas entre ejes) corriendo el pipeline completo
  —`action_analyze` contra el microservicio TJ3 real (`tj3-ms`) y
  `action_import` contra una base de datos real— y la detección/matching
  funcionaba correctamente en el 100% de los 31 milestones del archivo.
- El problema real era de diseño en `action_import`: toda fila del CSV
  creaba siempre un `project.task`, y si `is_milestone` era `True`
  *además* creaba un `project.milestone` y lo enlazaba vía
  `task.milestone_id`. Un milestone terminaba siendo tarea y milestone a
  la vez — visible como tarea regular en cualquier vista de Tareas.
- Confirmado con el usuario: un milestone del `.tjp` debe crear
  únicamente un `project.milestone`, nunca un `project.task`. Se agregó
  un `continue` temprano en el loop de `action_import` para las filas
  `is_milestone` (no se registran en `bsi_task_id`, así que ninguna
  subtarea puede terminar parentada bajo un milestone).
- Efecto secundario documentado (no resuelto en esta versión): como el
  milestone ya no tiene ningún `project.task` propio,
  `project.milestone.task_ids` queda siempre vacío para milestones
  importados por este wizard, y `_tjp_milestone_block` (lado export) no
  los va a re-emitir en un `.tjp` regenerado (corta temprano si
  `task_ids` está vacío). Para que sobrevivan a un reschedule habría que
  parsear `depends` en el import (gap ya conocido, tampoco resuelto acá)
  y enlazar el milestone a esas tareas reales.

### Arreglado

- `insight_import_wizard.py` (`action_import`): una fila `is_milestone`
  crea solo un `project.milestone`; ya no crea también un `project.task`
  con el mismo nombre enlazado vía `milestone_id`.

### Tests

- `tests/test_import_wizard.py`: `test_milestone_flagged_row_creates_milestone_not_task`,
  `test_milestone_row_does_not_break_sibling_bsi_hierarchy` (nuevo — un
  milestone entre dos hermanos no debe romper el `parent_id` de los que
  vienen después) y `test_full_pipeline_milestone_nested_under_eje_creates_only_milestone`
  (reproducción end-to-end con la forma real del `.tjp` de producción:
  `depends` antes de `milestone`, `note` final, anidado bajo un "eje" con
  4 tareas hermanas).

---

## [17.0.9.5.0] - 2026-07-08

### Prompt

> "¿La descalificación es binaria (si falta cualquier recurso comprometido sin
> comprar, el escenario queda fuera de la comparación) o hay margen para
> 'parcialmente viable'? El escenario se ejecuta igual, porque el
> administrador del proyecto tiene que conocer 'que se está perdiendo'. [...]
> ¿Esto conserva scenario_selection_strategy='manual' intacto [...] o la
> compra confirmada siempre pisa la selección manual? Si es manual es
> manual. [...] La pregunta es... vale la pena las estrategias parciales si
> tenemos el ponderado? [...] menor costo es decir que costo pondera 1, y el
> resto cero. [...] Y que las estrategias sean solo manual o automático.
> ¿Estoy correcto?"

Esta versión es el prerrequisito ("Parte A") de una funcionalidad más grande
—vincular `insight.cost.budget` a compras reales (`purchase.order`)— que se
va a implementar en un módulo nuevo (`insight_project_purchase`, depende de
`insight_project` + `purchase`, sin que `insight_project` sume esa
dependencia). Ver plan completo en la conversación que originó este cambio.

### Discusión de diseño

- `min_cost`/`min_duration`/`min_resources` son matemáticamente
  `weighted_score` con un peso en 1 y el resto en 0: la normalización
  min-max de `_weighted_scenario_scores` es monótona, así que el orden
  resultante de comparar por un solo eje ponderado es idéntico a comparar
  por ese valor crudo. Confirmado con el usuario, se colapsó
  `scenario_selection_strategy` a solo `manual`/`automatic`. `_scenario_metrics`
  (el `if strategy == ...` que despachaba a cada estrategia) quedó sin razón
  de ser — `_apply_selection_strategy` ya corta temprano si `strategy ==
  'manual'`, así que lo único que podía llegar ahí era `weighted_score`. Se
  eliminó el método y `_apply_selection_strategy` llama directo a
  `_weighted_scenario_scores`.
- Migración (`migrations/17.0.9.5.0/pre-migrate.py`, mismo patrón SQL crudo
  que las migraciones anteriores del addon): cada proyecto con
  `min_cost`/`min_duration`/`min_resources` se reescribe a `automatic` +
  los 3 pesos correspondientes (1/0/0, 0/1/0, 0/0/1) para preservar el
  comportamiento exacto; `weighted_score` pasa a `automatic` sin tocar
  pesos (ya eran explícitos).
- De paso, para la Parte B: `insight.cost.budget.skill_id` (Many2one) pasa a
  `skill_ids` (Many2many, relación explícita
  `insight_cost_budget_hr_skill_rel` en vez de autogenerada, para que la
  migración la pueda referenciar sin ambigüedad). Semántica confirmada con
  el usuario: "alguno" (OR) — el costo se considera usado si la tarea
  requiere al menos uno de los skills de la línea, no todos. La migración
  copia cada `skill_id` no nulo a la nueva tabla de relación y dropea la
  columna vieja.
- Se extrajo `insight.scenario._cost_budget_contributions()` (generador de
  `(budget, monto)`) desde adentro de `_compute_extra_cost`, sin cambiar su
  comportamiento — es pura preparación para que el módulo nuevo pueda sumar
  solo los costos con compra confirmada (`secured_extra_cost`) sin duplicar
  la lógica de prorrateo por skill/individual/periodicidad.
- `tests/test_scenario_selection.py`: las asignaciones directas de
  `min_cost`/`min_duration`/`min_resources` pasan a
  `.write({'scenario_selection_strategy': 'automatic', 'scenario_weight_...': ...})`
  con los pesos equivalentes explícitos; `weighted_score` se renombra a
  `automatic` sin otro cambio (esos tests ya traían pesos explícitos).

### Cambiado

- `scenario_selection_strategy`: de 5 opciones a 2
  (`manual`/`automatic`). `automatic` reemplaza a `weighted_score` y a los
  antiguos `min_cost`/`min_duration`/`min_resources` (poniendo el peso
  correspondiente en 1 y el resto en 0).
- `insight.cost.budget.skill_id` (Many2one) → `skill_ids` (Many2many),
  semántica "alguno" en el matching contra `required_skill_ids`.
- `_compute_extra_cost` se apoya ahora en `_cost_budget_contributions()`
  (mismo resultado, lógica reutilizable).

### Eliminado

- `project.project._scenario_metrics` (indirección sin uso tras colapsar
  las estrategias).

---

## [17.0.9.4.3] - 2026-07-08

### Prompt

> "Quiero que pienses en un plan para agregar costos extras para los
> escenarios. Quiero agregar costos de infrainstructura, costos de un
> servicio o SaaS. Esto debería usar un producto, que usando presupuestos
> puedan ayudar a calcular los costos. Por ejemplo, averiguo cuanto sale
> QuestionPro y el presupuesto es anual por X, quiero tener eso en cuenta.
> Entonces, lo que podríamos asignar directamente una lista de presupuestos
> e indicar si el presupuesto es mensual, anual, por hora, etc. Evalua la
> funcionalidad usando los presupuestos de Odoo."

Aclaración clave de seguimiento que definió el algoritmo:

> "La periodicidad debería ser parte de una relación entre escenario --
> [skills, individual, periodisidad] --> presupuesto. Algo muy sensillo.
> Entonces cuando vuelva el presupuesto de tj3 hay que ver cuanto tiempo se
> usa durante el proyecto: usa skill para identificar las tareas que
> requieren ese producto. Si es individual, por cada uno de los empleados
> que tenga el skill le corresponde pagar un presupuesto, sino es un único
> presupuesto para todos durante el período de uso. La suma de todos los
> costos de productos se suma al costo total."

### Discusión de diseño

- Se evaluó reutilizar `account_budget` de Odoo (`crossovered.budget`/
  `crossovered.budget.lines`) y se descartó: es Enterprise-only, no tiene
  periodicidad automática (cada línea es un rango de fechas manual con
  monto fijo) y no se vincula a productos (solo a cuentas analíticas/
  contables). Se optó por un modelo propio muy simple en su lugar.
- Nuevo modelo `insight.cost.budget`: catálogo de costos extra por
  `project.project` (no por escenario) con `product_id` (`product.product`,
  agrega dependencia del módulo `product`), `skill_id` (`hr.skill` — el
  mismo mecanismo que `project_improve` ya usa en
  `project.task.required_skill_ids`/`resource_pool_ids` para asignar
  tareas), `individual` (bool), `periodicity` (hora/mes/año/único) y
  `amount`+`currency_id`. Cada escenario elige cuáles aplican vía
  `insight.scenario.cost_budget_ids` (M2M con domain por proyecto).
- Algoritmo de cálculo (`insight.scenario._compute_extra_cost`): para cada
  costo seleccionado, se filtran las filas de `schedule_ids` cuya
  `task_id.required_skill_ids` contenga el skill del costo. Si no hay
  ninguna, el costo no aporta nada (nunca se "usó"). Periodicidad `one_time`
  suma el monto completo una sola vez sin proratear. Para el resto se
  calcula una tasa diaria (`amount/365` anual, `amount/30` mensual,
  `amount*24` por hora) y se prorratea:
  - `individual=True`: se agrupa por empleado usando
    `insight.task.schedule.resource_ids` (la asignación **real** que
    devolvió TJ3, no `resource_pool_ids` que es solo el pool de candidatos
    previo al schedule), sumando los días de sus tareas que matchean, y se
    cobra la tasa diaria una vez por cada empleado calificado.
  - `individual=False`: se toma la ventana compartida (mín `start_scheduled`,
    máx `end_scheduled` entre todas las filas que matchean) y se prorratea
    una sola vez, sin duplicar por empleado (ej. un servidor compartido).
- Chequeo defensivo agregado a pedido explícito del usuario durante la
  revisión del plan: `project.task.resource_pool_ids` es
  `store=True, readonly=False` (editable a mano), así que en el caso
  `individual` se revalida `budget.skill_id in user.employee_id.skill_ids`
  antes de cobrarle a un empleado — cubre el caso borde de que alguien
  fuerce en el pool a un empleado sin el skill y TJ3 termine asignándolo.
- `extra_cost`/`grand_total_cost` se implementaron como `compute(store=True)`
  declarativos (no imperativos como `total_cost`, que lo escribe
  `_compute_scenario_aggregates` después de cada corrida de TJ3) porque solo
  dependen de datos ya guardados (`schedule_ids`, `cost_budget_ids`): se
  recalculan solos apenas el usuario cambia la selección de costos, sin
  tener que re-correr el schedule.
- `grand_total_cost = total_cost + extra_cost` pasó a ser el valor que usan
  `_scenario_metrics`, `_weighted_scenario_scores` y
  `_post_selection_message` (antes leían `total_cost` a secas), para que los
  costos extra realmente influyan en qué escenario gana la selección
  automática (`scenario_selection_strategy`). `total_cost` no se tocó: sigue
  mostrando el costo laboral puro de TJ3 para transparencia.
- Conversión de moneda explícita (`currency_id._convert(...)`) al sumar cada
  costo: `total_cost`/`extra_cost` son floats en moneda de la compañía sin
  campo de moneda propio, y los costos de SaaS típicos (QuestionPro, AWS)
  suelen cargarse en USD mientras la contabilidad puede estar en otra
  moneda.
- Verificación: instalación limpia del módulo en una base de datos
  descartable (`odoo -i insight_project --stop-after-init`, sin errores) y
  una prueba funcional vía `odoo shell` con proyecto/tareas/empleados/
  schedule sintéticos que confirmó los cuatro casos (individual=20.0,
  compartido=14.0, único=500.0, combinado=534.0), incluido que un empleado
  sin el skill forzado a mano en el pool queda correctamente excluido del
  cobro individual.

### Agregado

- Modelo `insight.cost.budget` (catálogo de costos extra de infraestructura/
  SaaS por proyecto).
- `project.project.cost_budget_ids` (catálogo embebido en la pestaña
  TaskJuggler) e `insight.scenario.cost_budget_ids` (selección por
  escenario).
- `insight.scenario.extra_cost` y `grand_total_cost` (computados,
  `store=True`).
- Vista `views/insight_cost_budget_views.xml` y accesos en
  `ir.model.access.csv`.

### Cambiado

- `_scenario_metrics`, `_weighted_scenario_scores` y
  `_post_selection_message` comparan/muestran `grand_total_cost` en vez de
  `total_cost`.
- `depends` del manifest: se agregó `product`.

---

## [17.0.9.4.2] - 2026-07-08

### Prompt

> "Tenemos problemas con los mensajes del chatter que estan mal
> rendereados. Aparecen tags html en el mensaje."

### Discusión de diseño

- `mail.thread.message_post(body=...)` en esta versión de Odoo escapa el
  `body` cuando es un `str` plano (lo dice su propio docstring: "str
  content will be escaped, Markup for html body"). Los mensajes que se
  arman concatenando líneas con `'<br/>'.join(...)` o
  `texto.replace('\n', '<br/>')` (el aviso de escenarios sin planificar de
  `_call_tj_microservice`, y el nuevo resumen de selección de escenario de
  `17.0.9.4.0`) quedaban con el `<br/>` escapado y visible como texto
  literal en vez de un salto de línea real.
- Fix: envolver el resultado con `markupsafe.Markup('<br/>').join(lines)`
  en vez de `'<br/>'.join(lines)`. `Markup.join()` no solo evita el
  doble-escapado del separador — también escapa automáticamente cada
  línea que sea un `str` plano, así que de paso resuelve un riesgo de XSS
  si un nombre de escenario/tarea (texto libre del usuario) contuviera
  `<`, `>` o `&`.
- No se tocó el `message_post` de `_check_horizon_overrun`: es una sola
  línea sin HTML, el bug no lo afecta.

### Corregido

- `_call_tj_microservice`/`_post_selection_message`: mensajes de chatter
  multilínea ahora usan `Markup('<br/>').join(...)` en vez de concatenar
  `<br/>` como texto plano.

---

## [17.0.9.4.1] - 2026-07-07

### Prompt

> "En el módulo insight_project y project_improve en los escenarios se
> puede cambiar por usuario su eficiencia. El problema está en que ahora
> no hay usuarios para elegir sino que son res.partners y eso no es
> compatible con los recursos seleccionables. Hay que usar siempre
> usuarios."

### Discusión de diseño

- `insight.scenario.efficiency.partner_id` (`res.partner`) quedó de la
  implementación original de escenarios (`17.0.9.4.0`) mientras que los
  recursos seleccionables del proyecto (`project.project.candidate_user_ids`,
  `project.task.resource_pool_ids`, `task.user_ids`) siempre fueron
  `res.users`. El picker de la línea de eficiencia por escenario ofrecía
  cualquier contacto del sistema en vez de un recurso válido, y
  `_tjp_scenario_supplement` dependía de un round-trip partner→user
  (`_tjp_resource_id` ya resuelve `res.users` a partir de un `partner_id`
  para todo el resto del export TJP) que no aportaba nada salvo el bug.
- Se optó por el cambio mínimo consistente con el resto del archivo:
  renombrar el campo a `user_id` (`res.users`) y en el único call site
  (`_tjp_scenario_supplement`) pasar `eff.user_id.partner_id.id` a
  `_tjp_resource_id`, en vez de generalizar esa función para aceptar un
  usuario directamente — todos los demás call sites
  (`_tjp_resource_block`, `_tjp_bookings`, `_tjp_allocate`) ya siguen ese
  mismo patrón de partir de un `res.users` en mano y pasar su
  `partner_id.id`.
- Sin domain en el picker de `user_id`: se decidió no restringirlo a los
  candidatos/recursos del proyecto por ahora, para no acoplar el picker de
  eficiencias a `_tj_project_users()` en esta pasada.
- Migración de datos en `migrations/17.0.9.4.1/pre-migrate.py`: puebla
  `user_id` buscando el `res.users` cuyo `partner_id` coincida con el
  `partner_id` viejo, y elimina (con warning en el log) las filas
  huérfanas cuyo contacto no tiene usuario Odoo asociado, ya que
  `user_id` es `required=True` y no hay forma válida de migrarlas.

### Corregido

- `insight.scenario.efficiency`: el recurso de la línea de eficiencia por
  escenario ahora es `user_id` (`res.users`) en vez de `partner_id`
  (`res.partner`), consistente con el resto de los campos de recursos
  seleccionables del proyecto.

---

## [17.0.9.4.0] - 2026-07-07

### Prompt

> "Quiero aprovechar los escenarios de tjp3. Debemos elegir el escenario que
> sea más eficiente, en dinero, tiempo u otra estrategia, y esto tiene que
> ocurrir luego de ejecutar el scheduler. Entonces el proyecto tiene que
> tener una estrategia de selección del mejor escenario. [...] ¿Tiene
> sentido una opción multiobjetivo? [...] ¿taskjuggler puede calcular bien
> esas variables? ¿Y qué otras variables podemos usar?"
>
> Alcance confirmado por el usuario: implementar todo junto (incluida la
> estrategia ponderada/multiobjetivo desde el arranque), medir "uso de
> recursos" como pico de concurrencia (no headcount ni horas-persona), y
> aplicar la selección automáticamente al final de cada corrida de schedule
> — dejando la decisión y el motivo en el chatter del proyecto.

### Discusión de diseño

- Verificado contra el manual oficial de TJ3: `insight.scenario` solo variaba
  entre sí por eficiencia de recursos (`supplement resource ... efficiency`).
  TJ3 permite en realidad overridear cualquier atributo scenario-specific
  (esfuerzo, allocate, prioridad, etc.) — es una limitación autoimpuesta del
  addon, no de TJ3 — pero no hizo falta tocar eso: alcanza con comparar los
  resultados que TJ3 ya calcula por escenario.
- No existía ningún dato de costo en el addon. `tj_allocation_selection` ya
  ofrecía la opción `mincost` pero era letra muerta: nunca se emitía ninguna
  tarifa a TJ3. Según el manual, `rate` en un recurso es el **costo diario**
  (no horario); para que la columna de reporte `cost` calcule algo hace falta
  además declarar un `account` de costo y asignar `chargeset` a las tareas
  (se declaró una sola vez en cada tarea raíz — se hereda a las subtareas) y
  un `currency` a nivel proyecto.
- "Uso de recursos" se definió como **pico de concurrencia** (máxima
  cantidad de recursos distintos trabajando en simultáneo en algún momento
  del proyecto), no headcount total ni horas-persona acumuladas — más fiel a
  "cuánta gente necesito disponible a la vez". Se calcula 100% en Odoo
  (sweep-line sobre `insight.task.schedule`), sin pedirle nada nuevo a TJ3,
  y **solo sobre tareas hoja**: las filas de tareas padre en el reporte son
  un rollup de TJ3, incluirlas duplicaría/infllaría la concurrencia real.
- El costo total del escenario se suma solo desde las **tareas raíz** del
  proyecto (no las hoja): TJ3 ya acumula el costo de las subtareas en el
  padre, así que sumar cada subárbol raíz una vez evita contar dos veces sin
  tener que filtrar por profundidad.
- Filtro de "cumple la fecha pactada" (`project.date`) antes de aplicar
  cualquier estrategia (salvo la manual): si ningún escenario la cumple, se
  ignora el filtro para no bloquear la selección, y se dice explícitamente
  en el chatter — nunca falla silenciosamente ni deja el proyecto sin
  baseline.
- Empate: se conserva el `is_baseline` actual si está entre los empatados,
  para no barajar el Gantt nativo sin necesidad cuando el resultado es
  indistinto.
- La estrategia ponderada normaliza costo/duración/pico de recursos con
  min-max (0=mejor, 1=peor) entre los escenarios candidatos — no z-score,
  para no depender de una distribución con más de 2-3 escenarios — y guarda
  `selection_score` por escenario para que la UI explique el resultado sin
  tener que leer el chatter.
- `is_baseline` se reutiliza tal cual como "el escenario elegido" (ya
  decidía qué sincroniza con el Gantt nativo) en vez de agregar un campo
  `is_selected` separado — evita dos fuentes de verdad para la misma
  pregunta.

### Agregado

- `hr.employee.tj_daily_rate`: tarifa diaria por empleado (equivalente a
  `rate` de TJ3), expuesta en el form de empleado.
- `insight.task.schedule.cost`: costo TJ3 de la tarea (columna `cost` del
  taskreport).
- `insight.scenario`: agregados `total_cost`, `computed_end_date`,
  `peak_resources`, `selection_score`, recalculados en cada corrida.
- `project.project.scenario_selection_strategy` (manual / menor costo /
  menor duración / menor pico de recursos / score ponderado) +
  `scenario_weight_cost/duration/resources` para la estrategia ponderada.
- `_apply_selection_strategy`: recalcula agregados, aplica el filtro de
  fecha pactada, decide el escenario ganador y postea el resultado y el
  motivo en el chatter del proyecto. Se invoca desde `_import_all_schedules`,
  antes de `_sync_gantt_dates` (el Gantt nativo siempre refleja al escenario
  que terminó ganando).
- `_tjp_cost_account`/`chargeset`/`rate`/`currency` en el generador `.tjp`,
  columna `cost` en `_tjp_reports`, y `_parse_tj_cost` para importarla de
  vuelta.

---

## [17.0.9.3.0] - 2026-07-07

### Prompt

> "Has el plan para implementarla. Con esto el blocked no tiene sentido
> pasarlo al scheduler, porque va a estirar solo la tarea."
>
> (contexto previo: "¿tenemos en las tareas una registración de horas
> acumuladas? [...] deberíamos fijar cuando empezó la tarea, y debería
> decirnos cuánto falta para terminar. El scheduler nos debería ayudar a
> extender el fin de la tarea con esa información. No es así?")

### Discusión de diseño

- Cada reschedule regeneraba el `.tjp` usando siempre `task.allocated_hours`
  completo — sin ningún mecanismo que le dijera a TJ3 "esto ya se hizo".
  Verificado contra el manual oficial de TJ3 (taskjuggler.org) cuál es el
  mecanismo idiomático: **`booking`** a nivel de tarea. Con al menos un
  booking, TJ3 activa automáticamente "projection mode" (el keyword
  `projection` está deprecado) y resta ese trabajo del `effort` total al
  planificar lo que falta, extendiendo el fin real de la tarea.
- Alternativas descartadas, todas verificadas en el manual: `effortdone`/
  `effortleft` ("no ha sido completamente probado, puede dar resultados
  incorrectos"), `complete` (puramente cosmético, "has no impact on the
  scheduler"), `depends !now` (inválido — `depends` solo acepta IDs de
  tarea, `now` es un atributo de `project{}`), `minstart`/`maxstart` (no
  afectan el cálculo, solo validación post-hoc).
- **Decisión explícita**: con `booking` implementado, el campo `blocked` de
  Odoo (impedimento ad-hoc, vive en `project_improve`) no se exporta a TJ3.
  Si una tarea bloqueada deja de recibir bookings, el `effort` restante no
  avanza y el scheduler la estira por sí solo — no hace falta una señal
  explícita de "bloqueado". `blocked` sigue siendo puramente informativo/UI.
- Para que "proteger el pasado" tenga sentido en cada corrida sucesiva, `now`
  no podía seguir pinneado a `self.date_start` (fijo): se separa en
  `_tjp_now_date()` = `max(fields.Date.today(), date_start)` — nunca antes
  del inicio del proyecto, pero avanza con cada reschedule real.
- `_tj_project_users` debía incluir también a quien imputó timesheets en una
  tarea sin estar en `resource_pool_ids`/`user_ids` — si no, su `booking`
  referenciaría un recurso (`uX`) nunca declarado y TJ3 fallaría al parsear
  el archivo. Esto solo afecta qué bloques `resource {}` se declaran; no lo
  convierte en candidato de asignación futura (`_tjp_allocate` sigue leyendo
  solo `resource_pool_ids`/`user_ids`).
- Este trabajo se construyó sobre el refactor de milestones en curso en el
  mismo archivo (`_tjp_milestone_block`, `is_milestone` → `project.milestone`
  nativo) sin revertir nada de eso.

### Agregado

- `_tjp_bookings`: agrupa `task.timesheet_ids` por `(usuario, día)` y emite
  `booking uX <fecha> +Nh` (shorthand `interval4` de fecha+duración,
  verificado en el manual TJ3) para cada grupo con `date <= now_date`.
  Llamado desde `_tjp_task_block` junto con `effort`/`allocate`.
- `_tjp_now_date`: fecha de referencia real para `now`, desacoplada del
  `start` fijo del header.
- `hr_timesheet` agregado a `depends` (antes solo transitivo vía
  `project_timesheet_holidays`; ahora se usa directamente `timesheet_ids`).

### Cambiado

- `_tjp_project_header`/`_generate_tjp`/`_tjp_task_block`: threading de
  `now_date` para que header y bookings usen la misma referencia de "hoy".
- `_tj_project_users`: suma `task.timesheet_ids.mapped('user_id')` al pool
  de usuarios con bloque `resource{}` declarado.

---

## [17.0.9.2.2] - 2026-07-07

### Prompt

> Seguimiento de la verificación contra Odoo real de v17.0.9.2.1: 2 de los
> 3 tests de `TestTjpMilestoneBlock`/`TestTjpTaskBlock` fallaban con
> `UserError: No se encontró un usuario Odoo para el contacto "OdooBot"`
> porque las tareas de esos fixtures se creaban sin `user_ids` explícito,
> heredando un default que arrastraba a `_tjp_allocate`/`_tjp_resource_id`
> a un recurso sin correspondencia limpia.

### Arreglado

- `TestTjpMilestoneBlock._task`: default `user_ids=[(6, 0, [])]` para que
  las tareas del fixture no arrastren un usuario implícito al pool de
  recursos.
- `test_three_level_nesting_indentation`, `test_dependency_renders_absolute_path`
  y `test_reports_one_per_scenario` se reubican en `TestTjpTaskBlock`
  (donde `self.u1`/`self.u2`/`self.u3` están definidos), en vez de
  `TestTjpMilestoneBlock`.

---

## [17.0.9.2.1] - 2026-07-07

### Prompt

> "En la vista de Form de Proyecto aparece todas las propiedades de
> insight_project y project_improve. Deberíamos separar las cosas: Lo de
> project_improve debería ir en Settings, y mejor si acomodamos con
> temática en las secciones TASK MANAGEMENT y TIME MANAGEMENT."
>
> Sobre no duplicar las fechas del proyecto: "project.tj_now ==
> project.date_start y project.tj_end_date == project.date: No es
> necesario tj_now y tj_end_date, usemos las variables que ya vienen en
> project."
>
> Sobre `candidate_user_ids`: "se merece su propia hoja. Esa hoja sería
> 'Candidatos' o 'Recursos' o 'Equipo de asignado'."
>
> Sobre los skills de tarea: "Falta que aparezcan los skills requeridos
> en la vista de tareas. Habría que agregarlos en una página dentro del
> formulario. Los skills pertenecen a project_improve."
>
> Sobre no pisar la fecha pactada: "Pusimos que no sobreescribas el fin
> del proyecto, pero si la fecha es superior a la fecha pactada hay que
> avisar en el chatter de que el proyecto va a durar más que lo que está
> planificado. Que requiere revisión."

### Discusión de diseño

- Todo lo que se veía en la pestaña "TaskJuggler" del form de Proyecto lo
  inyectaba un único archivo (`views/project_project_views.xml`),
  incluyendo `candidate_user_ids` — que en realidad es un campo de
  `project_improve`, usado por su propio cómputo de `resource_pool_ids`
  independientemente de si TaskJuggler está habilitado, de ahí que
  estuviera escondido detrás de `invisible="not is_tj_enabled"` sin
  motivo real. El mismo patrón se repetía en la vista de Tarea con
  `required_skill_ids`/`resource_pool_ids` dentro del grupo "Staffing" de
  la pestaña "Schedule".
- Se evaluó mover esos campos a Settings > Task Management / Time
  Management (grupos nativos de `project.edit_project`), pero se
  descartó: no son "ajustes" tipo toggle, son datos de trabajo diario —
  mejor una pestaña propia en `project_improve`, separada por completo de
  `insight_project` (ver su CHANGELOG).
- `date_start`/`date` (nativos de `project.project`, con constraint SQL
  `date >= date_start`) ya cubrían exactamente lo que `tj_now`/
  `tj_end_date` duplicaban, y ya son visibles/editables en el form
  principal vía el daterange "Planned Date" — se eliminan los campos
  propios y todo el código de scheduling pasa a leerlos directamente.
- El horizonte auto-calculado (deadline de tarea más lejana + buffer, o
  +2 años desde `date_start`) nunca debe pisar la fecha pactada (`date`).
  Comparar el resultado de `_tjp_project_end_date` contra `self.date` es
  un chequeo autorreferencial que nunca dispara, porque esa función ya
  devuelve `self.date` como override cuando está seteada — se separó un
  `_tjp_derived_horizon` (ignora `date`, solo deriva de las tareas) para
  que `_check_horizon_overrun` compare contra algo distinto de su propio
  input. Si lo excede, postea un chatter + agenda una actividad al
  Project Manager, sin escribir nunca en `self.date`.
- Bug real encontrado al verificar contra una instancia real de Odoo:
  `project.project.write()` descarta silenciosamente un `date` sin
  `date_start` cuando el proyecto nunca tuvo uno (los trata como un
  rango) — rompía el wizard "extender horizonte" y podía romper el
  import de un `.tjp` externo con solo una de las dos fechas parseada.
  Se corrigió escribiendo ambos campos juntos cuando `date_start`
  todavía no existe.
- Migración de datos en `migrations/17.0.9.2.1/pre-migrate.py`: copia
  `tj_now` → `date_start` y `tj_end_date` → `date` (solo donde el campo
  nativo todavía esté vacío) antes de que el ORM dropee las columnas
  viejas al actualizar, para no perder overrides ya cargados en
  proyectos existentes.

### Quitado

- `project.project.tj_now`, `project.project.tj_end_date`: duplicaban
  `date_start`/`date`, nativos de `project.project`.
- Los campos `candidate_user_ids` de la pestaña "TaskJuggler" del form de
  Proyecto, y el grupo "Staffing" (`required_skill_ids`/
  `resource_pool_ids`) de la pestaña "Schedule" del form de Tarea — ahora
  tienen vista propia en `project_improve` (ver su CHANGELOG).

### Cambiado

- `insight_import_wizard.py` e `insight_unscheduled_tasks_wizard.py`
  escriben `date_start`/`date` en vez de `tj_now`/`tj_end_date`.

### Agregado

- `project.project._check_horizon_overrun()`: avisa por chatter +
  actividad cuando el horizonte de scheduling calculado supera la fecha
  de vencimiento pactada, sin sobreescribirla.
- `migrations/17.0.9.2.1/pre-migrate.py`: preserva los valores de
  `tj_now`/`tj_end_date` ya cargados, copiándolos a `date_start`/`date`
  antes del drop de columnas.

---

## [17.0.9.2.0] - 2026-07-07

### Prompt

> "Veo que algo hicimos mal en la importación y exportación de tjp,
> específicamente en el tema milestone. Estamos agregando milestone en el
> proyecto como tasks, pero son tasks? Por favor revisa una mejor
> implementación de la que estamos teniendo ahora sin usar el
> is_milestone, sino usando las características propias del addon
> project."

### Discusión de diseño

- `_tjp_task_block` forzaba un hito a ser una tarea real con
  `is_milestone=True`, suprimiendo su `effort`/`duration` aunque tuviera
  horas asignadas — el hack vivía enteramente en el export, y nada en el
  import (ni el CSV de schedule, ni el wizard de `.tjp` externo) leía la
  keyword `milestone` de vuelta: el roundtrip perdía el hito.
- Se decidió que cada `project.milestone` (nativo de `project`, ver
  CHANGELOG de `project_improve`) se exporte como su **propia tarea TJP
  sintética** de 0 esfuerzo (`task m{id} "..." { milestone; depends
  !t{task1}, ... }`), con `depends` hacia las tareas reales enlazadas vía
  `milestone_id` (`milestone.task_ids`). Las tareas reales dejan de tener
  ninguna rama especial en `_tjp_task_block`: siempre emiten su propio
  effort/duration, estén o no ligadas a un hito. Esto resuelve el
  desajuste de fondo entre cómo TJ3 entiende "milestone" (propiedad de
  una tarea puntual) y cómo lo entiende Odoo (un hito de proyecto al que
  varias tareas reales pueden apuntar).
- IDs sintéticos con prefijo `m` (`_tjp_milestone_id`) en vez de `t`: el
  parser existente `_parse_task_id_from_tj_id` ya descarta silenciosamente
  cualquier id que no empiece con `t` (falla el `int()` y cae al
  `except`), así que agregar filas `m{id}` al CSV de schedule no rompe el
  import de tareas existente — solo hacía falta un parser hermano
  (`_parse_milestone_id_from_tj_id`) para leerlas aparte.
- La fecha que TJ3 calcula para un hito se guarda en un campo nuevo,
  `project.milestone.tj_scheduled_date` (solo lectura, solo se sincroniza
  desde el escenario baseline, mismo criterio que `_sync_gantt_dates` usa
  para tareas) — no pisa `deadline`, que es la fecha objetivo editable
  por el usuario, no la calculada por el schedule.
- El wizard de import de `.tjp` externos (`insight_import_wizard.py`)
  tampoco reconstruía milestones antes de este cambio; se aprovechó para
  agregarle detección best-effort de la keyword `milestone` por bloque de
  tarea en el texto fuente (`_find_milestone_task_ids`, sin parser real de
  llaves — asume que los atributos de una tarea van antes de cualquier
  subtarea anidada, igual que nuestro propio exporter) y crear/enlazar un
  `project.milestone` por cada tarea detectada así al importar.

### Cambiado

- `_tjp_task_block`: ya no suprime `effort`/`duration` de una tarea real
  por `is_milestone` (campo removido de `project_improve`, ver su
  CHANGELOG). Una tarea enlazada a un hito vía `milestone_id` sigue
  emitiendo su propio bloque normalmente.
- `views/project_task_views.xml`: quitado el checkbox manual de
  `is_milestone`; el campo nativo `milestone_id` ya aparece en el form
  estándar de `project.task` cuando el proyecto tiene `allow_milestones`
  activo.

### Agregado

- `_tjp_milestone_id` / `_tjp_milestone_block`: exportan cada
  `project.milestone` del proyecto como tarea TJP sintética separada.
- `_parse_milestone_id_from_tj_id` y el manejo de filas `m{id}` en
  `_import_scenario_csv`: sincronizan `project.milestone.tj_scheduled_date`
  desde el escenario baseline.
- `models/project_milestone.py`: extiende `project.milestone` con
  `tj_scheduled_date`.
- `insight_import_wizard.py`: `_find_milestone_task_ids` detecta hitos en
  un `.tjp` externo y `action_import` los enlaza a un `project.milestone`
  nuevo en vez de crearlos como tareas sin distinción.

---

## [17.0.9.1.2] - 2026-07-06

### Prompt

> "Estoy viendo un comportamiento no deseado de insight_project. No estamos
> aprovechando a TaskJuggler para asignar la persona óptima a cada tarea,
> sino que el resultado son todas los recursos disponible. Entonces, cuando
> se exporta en tjp hay que dejar disponible todos los recursos
> potenciales, y cuando taskjuggler quede asignado uno (o varios, segun
> conf) ese tiene que ser la persona asignada. Lo que no tenemos son las
> personas que pueden ser elegidas para esa tarea en el lugar de las
> personas asignadas [...] deberían tener una lista de personas disponibles
> para atender esas tareas y usar esa lista para enviar al taskjuggler."
>
> Sobre dónde debía reflejarse la asignación real que devuelve TJ3: "No
> cambiar la semántica de project.task.user_ids sino agregar un nuevo
> campo, que puede ser computado usando los skills, que tenga el pool de
> empleados que puede ser asignado (project.task.resource_pool_ids?)" — y,
> aun así, "Se escribe en project.task.user_ids" una vez corrido el
> schedule.
>
> Sobre el criterio de selección de TJ3: "Agrega un campo a project donde
> podamos seleccionar el criterio de asignación."
>
> Sobre dónde debía vivir la lógica de skills/pool: "Deberíamos pasar todo
> lo de skills que no es propio de tj3 en project_improve."

### Discusión de diseño

- El bug de fondo no era que se declararan "todos los recursos del
  sistema" como candidatos — `_tjp_allocate` ya estaba escribiendo solo
  los `user_ids` de la tarea — sino que, con más de un asignado, emitía
  una lista plana `allocate u1, u2, u3`. En sintaxis TJ3 eso significa
  "los tres trabajan la tarea en simultáneo", no "elegí uno de estos
  tres": TaskJuggler nunca llegaba a optimizar nada. Esto estaba incluso
  fijado como comportamiento "intencional" en
  `test_leaf_task_with_multiple_resources_allocates_all`.
- El pool de candidatos por skills y la restricción por roster del
  proyecto (`project.candidate_user_ids`) no son un concepto de
  TaskJuggler — son staffing genérico, útil incluso sin TJ3 — así que
  `required_skill_ids`/`resource_pool_ids` (en `project.task`) y
  `candidate_user_ids` (en `project.project`) se agregaron en
  `project_improve`, no acá. `insight_project` solo consume
  `task.resource_pool_ids` al generar el `.tjp` y agrega lo específico de
  TJ3: el criterio `select` configurable (`tj_allocation_selection`) y el
  round-trip de la asignación real.
- Para que TJ3 elija un solo recurso entre varios candidatos hace falta la
  sintaxis `allocate primario { alternative candidato2, candidato3;
  select <criterio> }`, no una lista plana — de ahí la reescritura de
  `_tjp_allocate`. `_tj_project_users()` también pasó a declarar el pool
  efectivo de cada tarea (`resource_pool_ids or user_ids`), porque un
  candidato que no esté en `user_ids` igual necesita su propio bloque
  `resource` en el `.tjp`.
- El `taskreport` ya pedía la columna `resources` en el CSV pero se
  ignoraba al importar — quedaba la mitad del round-trip sin cerrar. Se
  agregó `resource_ids` a `insight.task.schedule`, se parsea esa columna
  en `_import_scenario_csv`, y `_sync_gantt_dates` la vuelca a
  `task.user_ids` — pero **solo** para el escenario baseline (mismo
  alcance que ya tenía esa función para fechas), para no pisar
  `user_ids` con el resultado de un escenario alternativo.
- Al testear el guard de "no tocar `user_ids` en escenarios no-baseline"
  apareció que `project.task.user_ids` no arranca vacío por defecto (hay
  un asignado por defecto preexistente, no relacionado a este cambio) —
  el test se ajustó para comparar contra el valor previo en vez de asumir
  `False`.
- Suite corrida contra Odoo real en el contenedor Docker del proyecto
  (`odoo-test`, DB `fop`) — 83 tests en `insight_project` (+ 6 nuevos en
  `project_improve`), todos en verde.

### Cambiado

- `_tjp_allocate(task)`: usa `task.resource_pool_ids or task.user_ids`
  como pool de candidatos y emite un bloque `allocate primario {
  alternative ...; select ... }` en vez de una lista plana cuando hay más
  de un candidato.
- `_tj_project_users()`: declara el pool efectivo de cada tarea
  (`resource_pool_ids or user_ids`), no solo `user_ids`.
- `_sync_gantt_dates()`: además de `date_deadline`/`planned_date_begin`,
  ahora también escribe `task.user_ids` a partir de `resource_ids` del
  schedule baseline.

### Agregado

- `project.project.tj_allocation_selection`: criterio configurable
  (`minallocated`, `minloaded`, `maxloaded`, `mincost`, `order`,
  `random`) para el atributo `select` de TJ3.
- `insight.task.schedule.resource_ids`: recurso(s) que TJ3 realmente
  asignó a la tarea en cada escenario, parseado desde la columna
  `resources` del `taskreport`.
- Vistas: criterio de selección y `candidate_user_ids` en la pestaña
  TaskJuggler del proyecto; `required_skill_ids`/`resource_pool_ids` en
  la pestaña Schedule de la tarea (campos definidos en `project_improve`).

---

## [17.0.9.1.1] - 2026-07-06

### Prompt

> "Para project_insight necesitamos tests unitarios para la importación y
> exportación de TJP, para la ejecución del Scheduler, y para generar el
> Gantt. Dejo un archivo para usar como test. Nota, la llamada a tj3 debe
> estar mockeada. La idea es fijar estas funcionalidades para no perderlas
> en el futuro y asegurar que la interface se mantiene. Y asegurar un
> espacio donde probar errores de interface y más."
>
> Luego, al notar en paralelo el agregado de `UnscheduledTasksError`:
> "Notar que empezaste a armar los tests se agregó una nueva excepción:
> UnscheduledTasksError, por favor, no pierdas esa funcionalidad y agregala
> a los tests si tiene sentido."

### Discusión de diseño

- Se usó un `.tjp` real exportado por el usuario (`IT_plan.tjp`, proyecto
  interno) solo como **referencia** para diseñar los fixtures — no se
  commiteó el archivo ni su contenido, para no dejar el roadmap interno
  real en el repo. Los fixtures sintéticos reproducen sus casos límite más
  representativos: tareas hoja sin esfuerzo/hijos (renderizan como bloque
  `{ }` vacío, usadas como hitos/resúmenes), `allocate` con múltiples
  recursos en una tarea, un recurso sin `hr.employee` vinculado (bloque de
  recurso vacío), y un escenario raíz con alternativas anidadas.
- `_generate_tjp`/`_tj_project_users` dependen de `project.task.user_ids`
  del proyecto completo (no solo de la tarea bajo test); toda tarea creada
  sin asignar explícitamente `user_ids: [(6, 0, [])]` termina con un
  asignado por defecto y puede disparar `UserError` de recurso huérfano en
  tests que no lo esperaban — hay que limpiarlo explícitamente.
- `_sync_gantt_dates` escribe `date_deadline` vía `write()`, que en esta
  instalación pasa por el `write()` de `project_enterprise` (no es
  dependencia de `insight_project`, pero está instalado en la misma BD):
  ese código "ajusta" la fecha al calendario laboral del proyecto/empresa,
  así que el test no puede esperar igualdad exacta con la fecha del CSV —
  se usa una tolerancia de ±3 días.
- Hallazgo de testing en Odoo: `TransactionCase.assertRaises()` envuelve su
  bloque en un savepoint y hace rollback al capturar la excepción esperada,
  lo que **descarta también los efectos de DB previos al raise** (ej. el
  `message_post` del chatter en `_call_tj_microservice` antes de lanzar
  `UnscheduledTasksError`). El test que verifica ese mensaje usa
  `try/except` plano en su lugar; queda documentado inline para no
  repetir la investigación.
- `UnscheduledTasksError` (agregada en paralelo en 17.0.9.1.0) quedó
  cubierta: tipo específico + atributo `n_unscheduled` + mensaje posteado
  al chatter desde `_call_tj_microservice`, y la bifurcación de
  `action_run_schedule(interactive=...)` (wizard vs. `UserError` plano)
  más las dos acciones del wizard (`action_extend_horizon`,
  `action_modify_project`).
- Suite corrida contra Odoo real en el contenedor Docker del proyecto
  (`odoo-test`, DB `fop`) — 77 tests, todos en verde.

### Agregado

- `tests/test_tjp_export.py`: generación del `.tjp` (header, escenarios
  anidados, bloques de recurso con calendario/leaves, jerarquía de tareas,
  `allocate` multi-recurso, dependencias, taskreports) y
  `action_export_tjp`; incluye el caso de error de interfaz "recurso TJ3
  sin usuario Odoo asociado".
- `tests/test_tjp_schedule_import.py`: parseo del CSV que devuelve tj3
  (`_import_scenario_csv`, `_import_all_schedules`, `_sync_gantt_dates`) y
  los helpers de parseo de fecha/duración/criticidad.
- `tests/test_scheduler.py`: `action_run_schedule` con el microservicio
  tj3 siempre mockeado — guards, contrato HTTP de
  `_call_tj_microservice`, y todo el flujo de `UnscheduledTasksError`.
- `tests/test_gantt.py`: `_render_gantt_svg` (placeholder vacío,
  etiquetas, leyenda de escenarios, marcador de camino crítico, marcador
  "Hoy") y el guard de `action_view_gantt`.

---

## [17.0.9.1.0] - 2026-07-06

### Prompt

> "En el mensaje que sale cuando el horizonte de planificación queda corto
> me gustaría que cambie el título de "Invalid Operation" a "Operation
> requires attention". Y que tenga dos botones: "Extender horizonte de
> planificación", "Modificar proyecto". El primero solo modifica el
> horizonte de planificación al valor recomendado, y el segundo no hace
> cambios. Importante, tiene que haber un mensaje en el chatter con ese
> mismo mensaje siempre. El mensaje en una ventana solo aparece en modo
> interactivo."

### Discusión de diseño

- Un `UserError` no permite personalizar título ni agregar botones — se
  reemplaza por un wizard (`insight.unscheduled.tasks.wizard`) abierto
  como `ir.actions.act_window` con `target=new`, cuyo `name` de acción es
  el título del diálogo ("La operación requiere atención").
- **El mensaje al chatter se sigue posteando siempre, sin importar el modo**
  (`_call_tj_microservice` no cambió en ese aspecto). Lo único condicionado
  por `interactive` es si además se abre el wizard o se deja propagar como
  `UserError` plano (para llamadores no interactivos, ej. futuros crons).
- Para no romper el contrato existente ("`_call_tj_microservice` lanza
  `UserError` para el caso de tareas sin agendar", ya cubierto por
  `tests/test_scheduler.py`, todavía sin commitear — hay otra sesión
  escribiendo tests unitarios en paralelo), se introduce
  `UnscheduledTasksError(UserError)`: sigue siendo un `UserError` para
  quien llame a `_call_tj_microservice` directamente, pero
  `action_run_schedule` la distingue por tipo para decidir si mostrar el
  wizard.
- Botón "Extender horizonte de planificación" solo visible si hay una
  estimación calculable (`_tjp_suggest_horizon`); "Modificar proyecto" no
  aplica ningún cambio, solo cierra el wizard.
- Verificado el comportamiento (chatter + tipo de excepción) directo por
  shell de Odoo, sin pasar por la suite de tests en paralelo.

### Agregado

- `models/insight_unscheduled_tasks_wizard.py`,
  `views/insight_unscheduled_tasks_wizard_views.xml`:
  `insight.unscheduled.tasks.wizard`.
- `action_run_schedule(interactive=True)`: nuevo parámetro.

---

## [17.0.9.0.2] - 2026-07-04

### Prompt

Siguiente error al ejecutar el schedule tras el fix de fechas:

> "Error del microservicio TJ3: 422 [...] project.tjp:28: Error:
> Unexpected token 'vacation' found. Expecting one of 'project', 'annual',
> 'special', 'sick', 'unpaid', 'holiday', 'unemployed' / leaves vacation"

### Discusión de diseño

- Otro bug preexistente sin relación con las sesiones anteriores:
  `_tjp_hr_schedule` generaba `leaves vacation ...`, pero `vacation` no es
  un token válido de la sintaxis TJ3 — los tipos válidos son `annual`,
  `special`, `sick`, `unpaid`, `holiday`, `unemployed`. `annual` es el
  equivalente correcto para licencias/vacaciones validadas de `hr.leave`.

### Arreglado

- `_tjp_hr_schedule`: `leaves vacation` → `leaves annual`.

---

## [17.0.9.0.1] - 2026-07-04

### Prompt

Primer schedule real ejecutado end-to-end tras importar un TJP:

> "Pude importar un tjp. Cuando quise ejecutar un scheduler falló con: [...]
> TypeError: can't compare datetime.datetime to datetime.date"

### Discusión de diseño

- Bug preexistente, sin relación con los cambios de sesiones anteriores:
  `_tjp_project_end_date` comparaba `task.date_deadline` (campo
  `Datetime` nativo de `project`) contra `start`/`tj_end_date` (campos
  `Date`). Nunca se había disparado porque hacía falta una tarea con
  `date_deadline` real combinada con un intento de schedule — el primer
  TJP importado con deadlines fue lo que lo expuso.

### Arreglado

- `_tjp_project_end_date`: normaliza `task.date_deadline` a `.date()`
  antes de comparar/guardar como `latest`.

---

## [17.0.9.0.0] - 2026-07-04

### Prompt

Continuación de la sesión de 17.0.8.0.0, al terminar de armar
`work_item_task_tj3` (el glue module con `insight_project`):

> "Ya se porque me hace tanto ruido work_item_task_tj3. insight_project
> Implementa blocked y decoración de camino critico y si no usamos
> insight_project esas funcionalidades no tienen sentido en
> work_item_task. Para mi hay que sacar blocked y camino critico de
> insight_project y trasladarlo a un módulo más básico (project_improve)
> porque no es algo exclusivo de tj3."

### Discusión de diseño

- **`blocked`, `is_critical_path` e `is_milestone` no son conceptos
  exclusivos de TaskJuggler** — son vocabulario genérico de gestión de
  tareas. Vivían en `insight_project` solo por herencia histórica (ahí
  nació el systray, antes del split en varios addons). Se mudan al nuevo
  addon base `project_improve` (depende solo de `project`).
- **`is_milestone` también se mueve**, con una razón concreta más allá de
  "es genérico": permite marcar tareas de duración cero pensadas para
  disparar comunicaciones a usuarios/clientes ("etapa terminada",
  "documento listo") desde addons futuros que no tengan por qué depender
  de TaskJuggler. `insight_project` se enfoca en optimización de tareas y
  asignación de recursos, no en esto.
- **`is_critical_path` sigue necesitando el cómputo de `insight_project`**:
  `project_improve` lo declara como campo plano (sin `compute`, queda en
  `False` sin un motor de scheduling); acá se le agrega
  `compute='_compute_scheduled', store=True` encima, igual que antes.
- **Esto vuelve innecesario `work_item_task_tj3`** (el glue module creado
  en la sesión anterior): al ser campos compartidos (lectura), no hay
  ningún método sobreescrito en común entre `insight_project` y
  `work_item_task` que necesite un glue module para resolver el orden de
  carga — cada uno depende de `project_improve` de forma independiente y
  listo. Se repositorio queda en GitHub sin uso; no se borró.
- **Se descubrió de paso que `state`/`02_changes_requested` (usado para el
  ❗ "revisión pendiente") es nativo de `project`**, no algo que
  `insight_project` haya definido — solo lo usa su cron. Esto simplifica
  aún más: `work_item_task` puede decorar con ❗ sin depender de nada
  extra.

### Quitado

- Campos `blocked`, `is_milestone` de `models/project_task.py`: migrados a
  `project_improve`.
- `is_critical_path` deja de declararse desde cero: ahora extiende (con
  `compute`) el campo plano que ya declaró `project_improve`.

### Cambiado

- `depends`: se agrega `project_improve`.

---

## [17.0.8.0.0] - 2026-07-04

### Prompt

Continuación directa de la sesión de 17.0.7.0.0. Al armar una matriz de
funcionalidades × módulo para el ecosistema Work Item Systray completo
(incluyendo un addon nuevo para usar el timer nativo de Odoo Enterprise),
surgió la pregunta:

> "insight_project podría no depender work_item_task, porque necesitaría?"

### Discusión de diseño

- **Se revierte por completo la dependencia con `work_item_task`** que se
  había introducido en 17.0.7.0.0: `insight_project` vuelve a ser
  TaskJuggler puro, sin saber nada del Work Item Systray.
- **Motivo del cambio de opinión**: mantener la decoración TJ3 (⚡/❗/
  `blocked`) adentro de `insight_project` no era arquitectónicamente malo
  per se (la dirección de la dependencia — lo específico depende de lo
  general — es la misma que `work_item_helpdesk → helpdesk`). Pero surgió
  un módulo hermano nuevo, `work_item_enterprise_task` (usa el `timer.timer`
  nativo de Odoo Enterprise en vez de escribir la `account.analytic.line`
  a mano), que también cuelga de `work_item_task`. Para que la decoración
  TJ3 y el timer Enterprise puedan convivir instalados a la vez sin
  depender uno del otro ni competir por el orden de carga, la decoración
  se extrae a un **glue module** dedicado, `work_item_task_tj3`
  (`depends: ['insight_project', 'work_item_task']`) — el mismo patrón que
  `sale_stock`/`sale_timesheet` en el propio Odoo.
- **Riesgo concreto que motivó la extracción** (no solo preferencia
  estética): si dos addons independientes sobreescriben el mismo método
  (`_work_item_close`) sobre el mismo modelo sin un edge de dependencia
  explícito entre ellos, el orden de combinación de clases de Odoo no está
  garantizado — podría aplicarse la decoración correctamente hoy por
  casualidad de orden, y dejar de aplicarse mañana sin ningún error ni
  log, con otra instalación que reordene los módulos. El glue module, al
  depender de ambos padres, elimina esa ambigüedad.
- **También se revierte** todo lo que se había migrado a `insight_project`
  en la sesión anterior y que en realidad era genérico a `project.task`,
  no específico de TaskJuggler: el wizard de "crear tarea nueva al vuelo"
  desde el switch, el botón "▶ Activar tarea" en form/kanban/tree, el
  check-out de asistencia cerrando la sesión activa, y las plantillas de
  mensaje seed. Todo eso pasa a `work_item_task`, que es su lugar natural.

### Quitado

- `models/insight_session_switch_wizard.py`, `models/hr_attendance.py`,
  `security/insight_user_session_security.xml`,
  `views/insight_session_message_template_views.xml`,
  `views/insight_session_switch_wizard_views.xml`,
  `data/insight_session_message_templates.xml`: migrados a
  `work_item_task`.
- `_work_item_label`/`_work_item_candidates`/`_work_item_close` de
  `models/project_task.py`: migrados a `work_item_task_tj3`.
- Botones "▶ Activar tarea" de `views/project_task_views.xml`: migrados a
  `work_item_task` (ese botón no tiene nada de específico a TaskJuggler).

### Cambiado

- `depends`: se quita `work_item_task`. Vuelve a ser
  `['project', 'hr_holidays', 'hr_attendance', 'project_timesheet_holidays']`,
  igual que antes de 17.0.7.0.0.
- `security/ir.model.access.csv`: se quitan las filas de acceso a modelos
  de `work_item_systray` (ya no aplica, sin la dependencia).

---

## [17.0.7.0.0] - 2026-07-03

### Prompt

> "Me gustaría que los tickets también aparezcan en la lista de tareas en
> el dropdown [...]. El timer debe ir para adelante. Y el cambio de tarea a
> ticket, y de ticket a tarea, debería ser natural [...] No debería
> depender de helpdesk."

### Discusión de diseño

- **Systray partido en 3 addons con un contrato de mixin**, no en un solo
  addon con `if model == ...`: se crea `work_item_systray` (base genérica:
  sesión, cronómetro que por defecto siempre cuenta hacia adelante, wizard
  de cambio) que define `work.item.mixin` — cualquier modelo lo implementa
  (`_work_item_label`, `_work_item_close`, `_work_item_candidates`) para
  volverse elegible como work item. `work.item.session` descubre en
  runtime, vía el registry de Odoo, qué modelos lo implementan; ningún
  proveedor toca `work.item.session` directamente.
- **`insight_project` deja de ser el dueño del systray**: se descubrió que
  `allocated_hours` (core `project`) y `remaining_hours` (`hr_timesheet`)
  no son específicos de TaskJuggler, así que la implementación genérica de
  `project.task` como work item (candidatos, cierre → parte de horas,
  cuenta regresiva) se extrajo a un addon nuevo, `work_item_task`. Este
  addon queda como una capa fina encima: solo decora con ⚡ camino crítico
  / ❗ revisión pendiente (`_work_item_label`/`_work_item_candidates` con
  `super()`) y aplica `blocked = True` al cerrar si corresponde.
- **`work_item_helpdesk`** (nuevo, fuera de este addon) implementa el mismo
  mixin sobre `helpdesk.ticket`: candidatos = mis tickets abiertos, cierre
  = mensaje en el chatter del ticket + parte de horas opcional si
  `helpdesk_timesheet` está instalado (detectado por la presencia del
  campo `account.analytic.line.helpdesk_ticket_id`, sin declarar esa
  dependencia). El cronómetro nunca cuenta regresiva para tickets porque
  ese addon no aporta `allocated_hours`/`remaining_hours` — el
  comportamiento ascendente es el default del base, no algo que haya que
  pedir.
- **Se descartó reusar el systray nativo de `mail`** (`ActivityMenu` /
  `res.users.systray_get_activities()`): es de recordatorios con
  vencimiento que aparecen y desaparecen solos; la idea acá es la opuesta,
  encasillar activamente al usuario en un work item hasta que decida
  cambiar.
- **Migración de datos**: `insight.user.session` e
  `insight.session.message.template` ya tenían datos reales bajo
  `insight_project`. Se migran con
  `migrations/17.0.7.0.0/pre-migrate.py`: rename de tabla, `task_id`
  (Many2one) → `work_item_ref` (Reference), y reasignación de los
  `ir_model_data` (módulo + nombre del xmlid) de modelo/campos que
  sobreviven hacia `work_item_systray`, para que la próxima actualización
  no los borre por "ya no declarados". `insight.session.switch.wizard`
  (transient, sin datos que preservar) no se migra.

### Agregado

- `models/project_task.py`: `_work_item_label`/`_work_item_candidates`/
  `_work_item_close` decorando el contrato de `work_item_task` con
  ⚡/❗/`blocked`.
- `migrations/17.0.7.0.0/pre-migrate.py`.

### Quitado

- `models/insight_user_session.py`, `models/insight_session_message_template.py`,
  `static/src/components/insight_systray/` (JS/XML/SCSS del widget): todo
  migrado a `work_item_systray`.
- `action_switch_to_session` de `project.task`: ahora la aporta
  `work_item_task` (misma tarea, mismo comportamiento).

### Cambiado

- `depends`: se agrega `work_item_task` (que a su vez depende de
  `work_item_systray` + `project` + `hr_timesheet`).
- `models/insight_session_switch_wizard.py`: pasa de definir el modelo
  completo a `_inherit = 'work.item.session.switch.wizard'`, agregando
  solo `new_task_name`/`new_task_project_id` (crear tarea al vuelo).
- `models/hr_attendance.py`: busca sesiones en `work.item.session` en vez
  de `insight.user.session` al hacer check-out.
- `security/`: la regla "ve todas las sesiones" y las filas de acceso de
  manager de proyecto pasan a apuntar a los modelos ahora dueños de
  `work_item_systray` (`work_item_systray.model_work_item_session`, etc.).

---

## [17.0.6.0.3] - 2026-07-03

### Prompt

Release que consolida trabajo de sesión previa (bloqueo de tareas, nuevas
etapas de kanban, cron de revisión vencida, cronómetro de horas restantes
en el systray) junto con el pedido puntual de esta sesión:

> "En la lista de mensajes de insight_project para dejar mensajes al dejar
> una tarea agregá 'Continuo mañana'."

### Discusión de diseño

- **`kanban_state` reemplazado por `blocked` (boolean) en `project.task`**:
  el estado kanban nativo de Odoo (`normal`/`done`/`blocked`) mezclaba
  semántica visual con la de impedimento real. Se separa en un campo propio
  que no reemplaza `stage_id` ni `state`, puede coexistir con cualquier
  etapa/estado activo, y no almacena el motivo (queda en el chatter o en el
  parte de horas). Se resetea a `False` al retomar activamente una tarea;
  solo se fija a `True` desde una plantilla de cierre con `sets_blocked`.
- **Etapas de tarea ampliadas**: "Planificada" → "Pendientes"/"Backlog", y
  se agregan "En progreso", "En revisión" y "Cancelada" para reflejar el
  flujo real de trabajo (documentado en el README). El importador TJP
  registra todas las etapas en el proyecto importado, aunque solo asigne
  automáticamente Requiere refinado/Backlog/Completada.
- **Cron de "cambios solicitados"**: tareas activas cuya `end_scheduled`
  (CPM) ya venció, o que son camino crítico y agotaron `remaining_hours`,
  pasan a `02_changes_requested` para alertar que el plan quedó invalidado
  por la realidad.
- **Cronómetro del systray con horas restantes**: cuando la tarea tiene
  horas asignadas, el chip de tiempo pasa de cronómetro ascendente a cuenta
  regresiva contra el presupuesto, con clases de color fijas
  (`neutral`/`ok`/`warning`/`critical`/`overtime`) sin parpadeo.
- **Nueva plantilla de cierre "Continuo mañana."**: agregada a
  `insight_session_message_templates.xml` junto a las demás opciones de
  "Al dejar una tarea" (secuencia 70), sin `requires_detail` ni
  `sets_blocked`.

### Agregado

- Campo `blocked` en `project.task`.
- Cron `_cron_flag_changes_requested`.
- Etapas `task_type_progress`, `task_type_review`, `task_type_cancelled`.
- Plantilla `msg_leave_continue_tomorrow` ("Continuo mañana.").
- Sección "Flujo de tareas" en el README documentando etapa/estado/bloqueo.
- Colores de alerta del cronómetro y flag `needs_review` en el systray.

### Cambiado

- `insight_session_message_template`: `kanban_state` (selection) →
  `sets_blocked` (boolean).
- `insight_user_session`/`insight_session_switch_wizard`: parámetros
  `outcome_kanban_state` renombrados a `outcome_blocked` en toda la cadena
  de llamadas.
- `insight_import_wizard`: variable interna `stage_planned` renombrada a
  `stage_backlog`; registra las 6 etapas en el proyecto importado.
- Wizard de cambio de tarea: grupos "Tarea que dejás"/"Tarea que iniciás"
  simplificados (sin subgrupo anidado), diálogo en tamaño extra-large.

---

## [17.0.6.0.2] - 2026-07-02

### Prompt

> "Quiero que revises el HTML del systray del botón de tareas... Quiero que
> el botón de tareas tenga la misma estructura de HTML [que el de chat]...
> saques el botón o ícono de proyecto... coloca el botón de descanso dentro
> del dropdown como la primera opción" → "el botón... no ocupa el 100% del
> espacio asignado. Quisiera que sí ocupe todo el espacio" → "Encontré el
> problema. El botón se le está aplicando una transformación por la
> siguiente regla de CSS: `.o_main_navbar .o_menu_systray .badge { ...
> transform: translate(-0.6em, -30%); }`"

### Discusión de diseño

- **Estructura del systray alineada con el patrón nativo de Odoo**: el
  chip de proyecto, el dropdown de tareas, el chip de tiempo y el botón de
  descanso vivían como hermanos dentro de un `<div class="o_insight_systray
  d-flex ...">`. El systray de chat (`o-mail-DiscussSystray-class`) en
  cambio usa el propio `<Dropdown class="...">` como raíz. Se replicó ese
  patrón: el componente `Dropdown` de `insight_systray.xml` ahora es el
  elemento raíz (con `class="'o_insight_systray'"`, aplicado por el prop
  `class` del componente al `div.o-dropdown.dropdown` externo, igual que
  hace `useDiscussSystray()`), sin wrapper adicional.
- **Chip de proyecto eliminado, botón de descanso movido dentro del
  dropdown**: por pedido explícito, solo queda visible el botón de tarea.
  "Descanso" pasó de ser un `<button>` suelto con solo el ícono de pausa a
  ser el primer `DropdownItem` del menú, con texto explícito ("Descanso") e
  ícono. El chip de tiempo transcurrido (⏱) se conservó dentro del propio
  toggler junto al chip de tarea, para no perder esa información visible
  sin abrir el dropdown.
- **El chip no llenaba la altura del botón del systray**: la base de
  entradas del navbar (`%-main-navbar-entry-base` en
  `navbar.variables.scss`) fija `align-items: center` en el
  `button.dropdown-toggle`, centrando los chips en vez de estirarlos.
  Se sobreescribió a `align-items: stretch` solo dentro de
  `.o_insight_systray > .dropdown-toggle` para que el fondo de color llene
  el alto completo de la entrada, sin tocar el navbar global.
- **Causa real de la desalineación — colisión con `.o_menu_systray
  .badge`**: los chips usaban la clase `badge` de Bootstrap solo para
  heredar `text-bg-danger`/`text-bg-light`, pero esa clase también matchea
  la regla global `.o_main_navbar .o_menu_systray .badge`, pensada para el
  puntito de notificación que flota sobre un ícono (`margin-right: -.5em`,
  `transform: translate(-0.6em, -30%)`). Aplicado a un chip de ancho
  completo, ese `transform` lo desplazaba fuera de su caja. Se quitó
  `badge` de ambos chips (`o_insight_chip`, `o_insight_chip-task`),
  dejando solo `text-bg-*` (utilidad de Bootstrap 5 independiente de
  `.badge`), y se agregó `border-radius: 0.375rem` a `.o_insight_chip` en
  `insight_systray.scss` para no perder la única propiedad visual que sí
  aportaba `.badge` y que no teníamos ya cubierta.

### Corregido

- `insight_systray.xml`: `Dropdown` como raíz del template (sin `<div>`
  envolvente), chip de proyecto eliminado, "Descanso" como primer
  `DropdownItem` con texto explícito.
- `insight_systray.scss`: `align-items: stretch` en el toggler y
  `border-radius` en `.o_insight_chip` para compensar la pérdida de
  `.badge`; se quitó `badge` de los chips para evitar la colisión con el
  selector global de notificaciones del navbar.

---

## [17.0.6.0.1] - 2026-07-01

### Prompt

> "En la exportación el archivo generado es... Error: Unknown scenario plan" →
> "Ahora el error del taskjuggler... Error in scenario plan: Some tasks did not
> fit into the project time frame" → "Estoy viendo que el gantt de Odoo no
> presenta las tareas en los tiempos asignados" → "No se muestran las tareas
> que corresponden en el systray... hay que listar las tareas vigentes" →
> "Me lo imagino como un wizard, con dos entradas de texto. Y que permita
> seleccionar textos genéricos o templates... Refina esta idea" → "Podés
> completar con todas las tareas."

### Discusión de diseño

- **Escenarios TJ3 como hermanos del `project {}`**: causa raíz del
  `Unknown scenario plan`. TJ3 solo admite un escenario raíz; los alternos
  deben anidarse dentro de él para heredarlo. `_tjp_project_header` ahora
  anida los escenarios no-baseline dentro del primero (ordenado por
  `is_baseline desc` vía `_order` de `insight.scenario`).
- **`Some tasks did not fit into the project time frame`**: confirmado
  corriendo `tj3` local — no era un bug de sintaxis sino sobreasignación real
  (845 días-persona contra ~521 días laborables disponibles en la ventana de
  2 años, todo en un único recurso). Se resuelve dando visibilidad y control,
  no ocultando el error: nuevo campo `tj_end_date` (horizonte editable) que
  `_tjp_project_end_date` prioriza sobre el fallback de 2 años; y
  `_call_tj_microservice` detecta el patrón `"N tasks could not be scheduled"`
  en el stderr de TJ3 para levantar un `UserError` con una estimación propia
  de horizonte (`_tjp_suggest_horizon`, aclarando explícitamente que es una
  estimación nuestra, no un valor que calcule TaskJuggler) y postearlo al
  chatter del proyecto.
- **`resource.calendar.hours_per_week` no existe en esta versión de Odoo**:
  `_tjp_suggest_horizon` sumaba mal las horas semanales; se corrigió a
  agregarlas desde `attendance_ids` (mismo patrón que `_tjp_calendar_hours`).
- **Gantt de Enterprise vacío pese a tener `start_scheduled`/`end_scheduled`**:
  `project_enterprise` lee `planned_date_begin`/`date_deadline`, no los
  campos custom del módulo. Se agrega `_sync_gantt_dates()` que copia el
  escenario baseline a esos campos tras cada schedule/importación.
  `planned_date_begin` es Enterprise-only y este módulo no depende de
  Enterprise (`depends` sin `project_enterprise`) — se escribe solo si el
  campo existe en el modelo, para no romper instalaciones Community-only.
- **Import de `.tjp` no recuperaba la fecha base ni el horizonte**: se
  parsean `now` y el rango `start - end` del header `project` importado y se
  asignan a `tj_now`/`tj_end_date` en `action_import`.
- **Systray listaba por fecha de fin, no por vigencia**: una tarea que
  empezaba esta semana y terminaba la próxima quedaba invisible (su fin no
  caía en el rango buscado). `_search_week_tasks` ahora filtra por
  superposición de intervalo (`start_scheduled <= fin_semana` y
  `end_scheduled >= inicio_semana`, con el inicio de semana real —lunes—, no
  "hoy") en vez de solo `end_scheduled` dentro del rango.
- **Fase 2b — notas de inicio/cierre de tarea**: en vez de un mensaje
  genérico fijo (`task.name`) en el parte de horas, se captura qué se
  planeaba hacer al entrar y qué se logró al salir. Catálogo de templates
  como modelo (`insight.session.message.template`), no hardcodeado, para que
  se puedan agregar/editar sin tocar código. Los templates "al salir" pueden
  fijar el `kanban_state` resultante de la tarea que se deja (`blocked` para
  "se bloqueó porque:", `done` para "se terminó"/"necesita revisión",
  `normal` para el resto) usando el campo nativo de Odoo en lugar de inventar
  un estado nuevo. Al *entrar* a cualquier tarea se resetea a `normal`
  (retomarla activamente la "desbloquea"; el motivo queda igual en el parte
  de horas). El intent capturado al entrar y el outcome capturado al salir
  se componen en una sola línea: "Se quiso hacer: X. Se logró: Y.".

### Corregido

- `project_project.py`: anidado de escenarios TJ3 (`scenario plan "Plan" {
  scenario noai ... }`), en vez de declaraciones hermanas.
- `project_project.py`: `_tjp_suggest_horizon` usa `attendance_ids` en vez del
  campo inexistente `hours_per_week`.
- `insight_import_wizard.py`: se captura `now`/rango de fechas del `.tjp`
  importado y se asigna a `tj_now`/`tj_end_date`.
- `insight_user_session.py`: `_search_week_tasks` filtra tareas vigentes por
  superposición de rango con la semana (lunes-domingo), no solo por
  `end_scheduled`.

### Añadido

- `project.project`: campo `tj_end_date` ("Horizonte de planificación"),
  `_sync_gantt_dates()`, `_tj_unscheduled_message()`, `_tjp_suggest_horizon()`.
- `insight.session.message.template`: catálogo de mensajes de inicio/cierre
  de tarea, con `direction`, `requires_detail`, `kanban_state`; seed de datos
  con 5 templates de entrada y 6 de salida.
- `insight.session.switch.wizard`: wizard de cambio de tarea/descanso con
  selección de template + texto libre para intención y resultado, y creación
  de tarea nueva inline.
- `insight_user_session.py`: campo `intent_note`; `switch_task`/`take_break`
  aceptan `outcome_note`, `outcome_kanban_state`, `intent_note`.
- Systray: entrada "➕ Nueva tarea" en el dropdown; `onSelectTask`/
  `onTakeBreak`/`onNewTask` abren el wizard en vez de llamar el RPC directo.

---

## [17.0.6.0.0] - 2026-07-01

### Prompt

> Ya que solo usamos los recursos que son users, ¿por qué no dejamos de usar el
> modelo insight.resource, y como id de TaskJuggler solo usamos el xmlid? Lo
> pregunto porque no busco recuperar el mismo archivo importado, sino que se
> pueda calcular bien el flujo de tareas.
>
> (Seguido de: "Ok, usar el u{user_id.id} en vez del xmlid", confirmación de
> que todo recurso siempre tiene `hr.employee` — interno o contratista/freelance
> vía `employee_type` — y que la eficiencia por skill no es viable en
> TaskJuggler, por lo que se conserva una eficiencia base pero a nivel
> `hr.employee`, no por proyecto.)

### Discusión de diseño

- **Causa raíz del bug original**: `insight.resource` exigía un registro manual
  por proyecto+partner antes de poder asignar un usuario a una tarea.
  `_tjp_allocate()` solo emitía `allocate` si ese registro existía; si se
  olvidaba, la tarea perdía `effort`/`allocate` y caía a `duration`, rompiendo
  el cálculo del schedule. Además, sin constraint de unicidad
  `(project_id, partner_id)`, filas duplicadas producían bloques `resource`
  duplicados en el `.tjp`, rechazados por TaskJuggler ("Resource X has already
  been defined").
- **xmlid como id TJ3**: descartado — los xmlids contienen un punto
  (`modulo.nombre`), inválido como identificador TJ3 (`[a-zA-Z_][a-zA-Z0-9_]*`),
  y la mayoría de los `res.users` creados desde la UI no tienen xmlid asignado
  (habría que crear uno bajo demanda, la misma contabilidad lateral que se
  quiere eliminar).
- **`f'u{user.id}'` como id TJ3**: elegido — estable, único, sin bookkeeping
  adicional, y consistente con el criterio ya usado para tareas
  (`_tjp_task_id` = `f't{task.id}'`).
- **Eliminar `insight.resource`**: el conjunto de recursos de un proyecto se
  deriva ahora de `task.user_ids` (helper `_tj_project_users`), sin paso de
  registro previo. Esto cierra la clase de bug completa: cualquier usuario
  asignado a una tarea automáticamente tiene un recurso TJ3 válido.
- **`daily_max_hours`**: eliminado sin reemplazo — no se usaba en la práctica y
  no tiene equivalente nativo en Odoo.
- **`base_efficiency` → `hr.employee.tj_base_efficiency`**: se conserva pero
  pasa de ser un override por proyecto a un único valor por empleado.
  TaskJuggler no soporta eficiencia por skill/asignación, solo un multiplicador
  plano por recurso, así que ese es el nivel de granularidad correcto. No se
  agrega vista en esta pasada (campo técnico, editable por shell/modo debug);
  se puede sumar una vista en `hr.view_employee_form` en una iteración futura
  si hace falta.
- **`_tjp_resource_id` con `UserError` en vez de fallback silencioso**: si una
  `insight.scenario.efficiency` apunta a un `partner_id` sin `res.users`
  asociado, antes se generaba un id "fantasma" slugificado silenciosamente;
  ahora se levanta un error claro en tiempo de generación, evitando un `.tjp`
  con una referencia a un recurso inexistente.
- **Migración de datos**: no se escribió script de migración (no existe
  `migrations/` en el addon, sin datos reales conocidos de
  `base_efficiency`/`daily_max_hours` cargados en producción).

### Eliminado

- `models/insight_resource.py`: modelos `insight.resource`,
  `insight.resource.shift`, `insight.resource.vacation`.
- Campo `resource_ids` en `project.project`.
- `views/insight_resource_views.xml`, acción y menú "Recursos TJ" en
  `views/menus.xml`, sección "Recursos" en la pestaña TaskJuggler del proyecto.
- 6 líneas de `security/ir.model.access.csv` para los modelos eliminados.
- Creación de `insight.resource` como efecto secundario de
  `InsightImportWizard.action_import`.
- Método `_tjp_manual_schedule` (ya no alcanzable — todo recurso es HR).
- Test `test_insight_resource_created_with_tj_id`.

### Añadido

- `models/hr_employee.py`: campo `tj_base_efficiency` (Float, default 1.0) en
  `hr.employee`.
- Helper `_tj_project_users()` en `project.project`.

### Cambiado

- `_generate_tjp`, `_tjp_resource_block`, `_tjp_hr_schedule`, `_tjp_allocate`,
  `_tjp_resource_id`: reescritos para resolver recursos directamente vía
  `res.users`/`hr.employee` en lugar de `insight.resource`.

---

## [17.0.2.0.0] - 2026-06-30

### Prompt

> Si, arranca con el paso 7.

### Discusion de diseno

- **IDs TJ3 con prefijo tipo (`p`, `res`, `t`)**: se descartan nombres sanitizados
  para evitar colisiones; `p{id}`, `res{partner_id}`, `t{task_id}` son únicos por
  construcción y permiten mapear de vuelta el CSV de TJ3 → Odoo sin tabla auxiliar.
- **`effort` vs `duration` para tareas sin recurso**: TJ3 requiere `allocate` para
  poder schedulear `effort`. Si la tarea tiene horas planificadas pero no tiene ningún
  recurso del proyecto asignado, se emite `duration` en lugar de `effort`. Esto hace
  el TJP válido y deja la tarea en el timeline aunque sin asignar.
- **`_tjp_task_abs_path` con `!`**: los paths relativos en `depends` fallan cuando la
  tarea dependida está en un subárbol distinto. Se usa el prefijo `!` (scope del
  proyecto) + ruta completa desde la raíz del proyecto para todos los depends.
- **`supplement resource` para eficiencias por escenario**: en lugar de incluir todas
  las eficiencias por escenario dentro del bloque `resource { }`, se usa
  `supplement resource resX { sc:efficiency N }` que es más legible y separa la
  definición del recurso de sus overrides por escenario.
- **`_tjp_calendar_hours` emite `off` para días no configurados**: TJ3 hereda el
  calendario global si no se especifica. Para evitar que un empleado trabaje sábados/
  domingos por herencia de calendario global, se emite `workinghours sat off` y
  `workinghours sun off` para todos los días sin attendances.
- **`_tjp_manual_schedule` con default Mon–Fri 9–17**: si un recurso manual no tiene
  turnos cargados, se asume la semana laboral estándar. Evita que TJ3 rechace el
  recurso por no tener horarios definidos.
- **`_generate_tjp` ordena por `sequence`**: las tareas se emiten en orden de
  `sequence` de Odoo para que el BSI generado por TJ3 sea estable entre corridas
  (mismo orden → mismo BSI), facilitando el matching en `_import_schedule_csv`.
- **`action_export_tjp` crea `ir.attachment`**: en lugar de retornar el contenido
  inline, crea un attachment temporal y retorna un `ir.actions.act_url`. Esto permite
  que Odoo gestione el download sin timeouts de RPC.

### Anadido

- `_tjp_project_header`: bloque `project { timezone, now, scenarios }` completo.
- `_tjp_project_end_date`: infiere el fin del proyecto desde `date_deadline` de
  tareas + buffer 33%; fallback a +2 años con `dateutil.relativedelta`.
- `_tjp_resource_block`: genera bloque completo con `efficiency`, `limits.dailymax`,
  y delega horarios a `_tjp_hr_schedule` o `_tjp_manual_schedule`.
- `_tjp_hr_schedule`: lee `resource.calendar.attendance_ids` y `hr.leave` (aprobadas)
  del empleado asociado al partner del recurso.
- `_tjp_calendar_hours`: convierte `resource.calendar.attendance_ids` → cláusulas
  `workinghours TJP`; emite `off` para días no configurados.
- `_tjp_manual_schedule`: convierte `insight.resource.shift/vacation` → TJP.
- `_tjp_scenario_supplement`: emite `supplement resource` con `sc_id:efficiency`.
- `_tjp_task_block` (recursivo): emite `task { milestone | effort/allocate, depends,
  subtareas }`.
- `_tjp_allocate`: mapea `task.user_ids` a IDs de recursos del proyecto; soporta
  `alternative_assignee_id`.
- `_tjp_reports`: emite `taskreport "DebugCSV"` con columnas para el CSV de TJ3.
- `action_export_tjp`: crea `ir.attachment` y retorna `act_url` para download.
- Helpers estáticos: `_tjp_resource_id`, `_tjp_task_id`, `_tjp_task_abs_path`,
  `_tjp_scenario_id`, `_float_to_hhmm`.

---

## [17.0.1.1.0] - 2026-06-30

### Prompt

> Si arranca con el siguiente paso

### Discusion de diseno

- **`get_values` para default de timeout**: `fields.Integer` con `config_parameter`
  devuelve `0` (falsy) cuando el parámetro no existe aún en `ir.config_parameter`.
  Se sobreescribe `get_values` para retornar `120` como default, evitando que el
  formulario muestre 0 en una instalación fresca.
- **Test de conexión lee de `ir.config_parameter` directamente**: el botón
  `action_test_tj_connection` no lee `self.tj_microservice_url` porque en
  `res.config.settings` (TransientModel) el valor del campo puede estar sin guardar
  si el usuario hace click sin guardar primero. Leer desde `ir.config_parameter.sudo()`
  garantiza que se testa la URL efectivamente almacenada.
- **`/health` como endpoint de test**: endpoint estándar para servicios HTTP. Si el
  microservicio no implementa `/health`, el test dará un error 404 pero al menos
  confirma conectividad. Alternativa: usar el endpoint `/` o `/docs` de FastAPI,
  pero `/health` es más explícito y fácil de agregar al microservicio.
- **Distinción de errores HTTP**: se capturan `ConnectionError`, `Timeout` e
  `HTTPError` por separado para dar mensajes de error más útiles al usuario.

### Modificado

- `models/res_config_settings.py`: override de `get_values` para default timeout 120;
  método `action_test_tj_connection` con health check al microservicio.
- `views/res_config_settings_views.xml`: botón "Probar conexión" inline junto al
  campo timeout.

---

## [17.0.1.0.0] - 2026-06-30

### Prompt

> Quiero implementar el módulo insight_project. Revisá la memoria del proyecto
> y el plan en C:\Users\csroc\.claude\plans\hagamos-un-plan-para-cosmic-bee.md
> y arranquemos con el Paso 0.

### Discusion de diseno

- **Repositorio personal `csrocha/insight_project`**: el módulo es de uso interno
  del proyecto fop-odoo pero no pertenece a la organización `observatoriopyme`,
  siguiendo el mismo patrón que `insight_graph` e `insight_graph_account_partner`.
- **`insight.task.schedule` en archivo propio**: aunque el plan original lo agrupaba
  con `insight_scenario.py`, se separó para que las dependencias entre modelos sean
  claras en el `__init__.py` (los modelos de `project_task.py` referencian
  `insight.task.schedule`, que a su vez referencia `insight.scenario`).
- **`source` computado via `hr.employee.address_home_id`**: el plan usaba
  `partner_id.employee_id` que no existe en Odoo 17 por defecto. Se usa
  `search_count([('address_home_id', '=', partner_id.id)])` que es el campo canónico
  de la relación partner→employee en Odoo 17.
- **Vistas con `invisible=` en lugar de `attrs`**: Odoo 17 usa la sintaxis nueva
  `invisible="not field"` en lugar de `attrs="{'invisible': [...]}"`.
- **Depend `hr_holidays`**: cubre transitivamente `hr` y `hr_attendance` que se
  necesitarán en fases posteriores.

### Anadido

- `__manifest__.py`: manifest inicial versión `17.0.1.0.0`, licencia OPL-1.
- `models/insight_scenario.py`: modelos `insight.scenario` e `insight.scenario.efficiency`.
- `models/insight_task_schedule.py`: modelo `insight.task.schedule` (resultado del scheduler TJ3).
- `models/insight_resource.py`: modelos `insight.resource`, `insight.resource.shift`,
  `insight.resource.vacation`.
- `models/project_project.py`: extensión de `project.project` con campos TJ y
  métodos stub (`_generate_tjp`, `action_run_schedule`, `action_export_tjp`).
- `models/project_task.py`: extensión de `project.task` con campos `is_milestone`,
  `bsi`, `start_scheduled`, `end_scheduled`, `is_critical_path`.
- `models/res_config_settings.py`: extensión de `res.config.settings` con URL y
  timeout del microservicio TJ3.
- `security/ir.model.access.csv`: accesos para todos los modelos nuevos.
- `views/`: vistas form/list para todos los modelos nuevos + herencias en
  `project.project` y `project.task`.
