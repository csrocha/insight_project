# CHANGELOG

Formato basado en [Keep a Changelog](https://keepachangelog.com/es/1.1.0/).
Versionado: `17.0.MAYOR.MENOR.PARCHE`.

Cada entrada de version incluye el **prompt** que motivo los cambios
y las **discusiones de diseno** relevantes que influyeron en las decisiones,
para trazabilidad completa del razonamiento de agentes de IA.

---

## [17.0.9.7.14] - 2026-07-21

### Prompt

> Upgrade de `insight_project` en prod falló con
> `psycopg2.errors.UndefinedColumn: column "scenario_selection_strategy"
> does not exist` dentro de `migrations/17.0.9.5.0/pre-migrate.py`.

### Corregido

- **`pre-migrate.py` de 17.0.9.5.0 asumía que `scenario_selection_strategy`
  ya existía en la base**, porque en un upgrade incremental (versión por
  versión) así es: el campo se creó en v17.0.9.4.0 y esta migración solo
  reescribe sus valores. Pero en un upgrade que salta varias versiones de
  una sola vez, Odoo corre **todos** los `pre-migrate` de las versiones
  intermedias antes de ejecutar un único `_auto_init()` final -- si la
  base venía de antes de 17.0.9.4.0, la columna todavía no existe en el
  momento en que corre este script.
- Se agrega el mismo guard de `information_schema.columns` que el propio
  script ya usaba más abajo para la migración de `skill_id` -> `skill_ids`
  (líneas originales 45-49): si la columna no existe, no hay nada que
  reescribir y se saltea el bloque en vez de fallar.

## [17.0.9.7.13] - 2026-07-19

### Prompt

> Épica 7 del roadmap de ecosistema: reportes de proyecto en el website
> (vía `fop_odoo_project_report`, reusando `fop_odoo_report`).

### Agregado

- Bridge QWeb del reporte de desviación (`report/
  report_deviation_report_*.xml` + `models/report_deviation_report.py`),
  mismo patrón exacto que el bridge de costo ya existente
  (`report_cost_report.py`): `ir.actions.report` con `model='knowledge.
  asset'` y `asset_category='insight_project.deviation_report'`, un
  `AbstractModel` que lee `asset.latest_version().payload`, y una
  plantilla HTML standalone con el detalle de tareas (delta de fecha/
  costo) y el resumen CPI/SPI.

### Discusión de diseño

- No hizo falta tocar `_compute_and_save_deviation_report` — el payload
  ya existía (desde la Épica 2), solo faltaba un lector.
- El bridge de costo (ya existente) y el de Gantt son la referencia
  exacta que se calcó — mismo criterio de "reusar antes de reinventar"
  que ya se venía aplicando en este ecosistema.

## [17.0.9.7.12] - 2026-07-18

### Prompt

> "Tomemoslo" — ítem 4 del `BACKLOG.md` ("dime que punto es el
> funcionalmente más importante" → se eligió por ser el único de los
> pendientes que compromete la exactitud de algo ya construido: costo de
> mano de obra, del que dependen los reportes de costo, CPI/SPI y
> `margin`/`secured_margin` de `insight_project_sale`).

### Discusión de diseño

- Tres decisiones de política/alcance resueltas con el usuario antes de
  tocar código:
  1. **Divisor mensual→diario**: fijo `/30`, no calendario laboral real —
     mismo criterio que ya usa `insight.cost.budget` para costos extra
     (`insight_scenario.py:_cost_budget_contributions`, `amount/30` para
     `periodicity='monthly'`). Se prefirió consistencia interna sobre
     precisión de calendario (que hubiera requerido
     `resource_calendar_id.get_work_duration_data()` y definir una
     ventana de referencia, sin precedente en el código).
  2. **Bruto vs. cargado**: bruto tal cual (`contract_id.wage`), sin
     factor de carga social propio — confirmado que sin `hr_payroll`
     (no instalado, ni siquiera `hr_contract` lo requiere como
     dependencia) no existe ningún costo con aportes patronales
     calculado en ningún lado del código; inventar un factor de carga
     hubiera sido una política de costeo nueva sin pedido explícito.
  3. **Sin contrato activo**: `0.0` (no participa del costeo), sin
     fallback manual editable — mismo comportamiento que el default
     anterior del campo manual, más simple que mirror-ear el patrón
     `compute + readonly=False` de `hr_contract.resource_calendar_id`
     (que sí permite override manual) porque acá ninguna rama de la
     decisión necesitaba edición manual.
- Con las 3 decisiones resueltas hacia "siempre compute, nunca edición
  manual" en ambas ramas (con/sin contrato), el campo se implementó como
  `compute + store=True + readonly=True` — a diferencia del patrón
  `readonly=False` de `hr_contract` (pensado para permitir override), acá
  no hace falta esa complejidad.
- `hr_contract` no era dependencia de `insight_project` (confirmado
  contra `ir_module_module` de la base `fop`, sesión previa) — se agregó
  al manifest. Confirmado que es una dependencia liviana y autocontenida:
  `hr_contract/__manifest__.py` solo depende de `hr` (ya instalado
  transitivamente vía `hr_holidays`/`hr_attendance`/`hr_timesheet`), no
  arrastra `hr_payroll` ni ningún módulo de nómina real.
- Único punto de lectura de `tj_daily_rate` en todo el addon:
  `_tjp_resource_block` (`project_project.py`, línea `rate {rate:.2f}`) —
  el cambio es de impacto acotado, no toca ningún cálculo de costo de
  tarea (`insight.task.schedule.cost` sigue viniendo tal cual del
  taskreport de TJ3, que ya hizo la cuenta rate×días con el `rate` nuevo).

### Modificado

- `hr.employee.tj_daily_rate` (`models/hr_employee.py`): de campo manual
  a `compute='_compute_tj_daily_rate', store=True, readonly=True`,
  derivado de `contract_id.wage / 30.0` (0.0 sin contrato).
- `__manifest__.py`: nueva dependencia `hr_contract`.
- Tests: `tests/test_hr_employee.py` nuevo (deriva de wage, recomputa al
  cambiar wage, sin contrato → 0, `_tjp_resource_block` refleja el valor
  computado).

---

## [17.0.9.7.11] - 2026-07-17

### Prompt

> "Pasemos a la épica 4 y 5" — Épica 4 (gestión de riesgos) y Épica 5
> (Earned Value/rentabilidad) del backlog de ecosistema (memoria
> `project_ecosystem_roadmap`). Esta entrada cubre solo la parte de
> `insight_project` (hook de extensión para riesgos + EVM); los módulos
> nuevos (`insight_project_risk`/`insight_project_sale`) versionan aparte.

### Discusión de diseño

- **Buffer de riesgo — por qué un wrapper de tarea y no un ajuste en
  Python.** El requisito (confirmado con el usuario) es que el buffer
  mueva fechas reales de sucesoras, no solo un número en un reporte — eso
  descarta el patrón de `insight.cost.budget` (ajuste puro en
  `_compute_extra_cost`, nunca toca el `.tjp`). TJ3 no tiene un atributo
  nativo "duración extra sin costo" sobre una tarea `effort`-driven, así
  que la tarea con riesgo abierto deja de ser una hoja plana y pasa a ser
  un wrapper con dos hijos sintéticos: `_work` (el trabajo real, sin
  cambios) y `_risk{n}` (pura `duration` de calendario, sin `allocate` —
  no consume recurso ni infla costo). TJ3 ya rolea automáticamente
  fechas/costo de un padre real desde sus hijos (mismo mecanismo que ya
  usa cualquier tarea con subtareas reales) — por eso **ninguna otra
  tarea necesita cambiar su `depends`**: quien ya dependía de la tarea
  sigue apuntando al mismo id, solo que ahora ese id es un padre cuyo fin
  incluye el buffer. Se evaluó y descartó una alternativa con una tarea
  sintética *hermana* + redirección de las dependencias de cada sucesora
  hacia ella — mucho más invasivo (tocaría la resolución de dependencias,
  ya delicada por las reglas de orden `depends`/`precedes` y el límite de
  una sola arista FF por tarea) para el mismo resultado.
- **Validado contra el binario real** (tj3-ms v3.8.4, 2026-07-17, mismo
  criterio que otras veces en este addon — ver memoria
  `feedback_tj3_empirical_testing`): un `.tjp` de prueba con el wrapper
  (`t5` → `t5.t5_work` + `t5.t5_risk1`) más una tarea sucesora dependiendo
  de `t5` corrió la sucesora después del buffer completo (viernes fin de
  work+buffer → lunes hábil siguiente), no solo después del trabajo real.
  Confirma también que `_parse_task_id_from_tj_id` ya ignora en silencio
  los ids sintéticos (`t5.t5_work` → intenta `int('5_work')`, falla,
  `None`) sin necesitar ningún cambio — la fila que `insight.task.schedule`
  termina usando es la del padre (`t5`), con las fechas ya empujadas.
- Riesgos `closed`/`materialized` (a definir en el módulo satélite) no
  deberían seguir aportando buffer hacia adelante — ese criterio de
  filtrado vive en `insight_project_risk`, acá solo el hook vacío por
  defecto (`_tj_task_risk_buffers`, cero cambio de comportamiento sin el
  módulo instalado).
- Dos o más riesgos abiertos en la misma tarea se **encadenan** (risk2
  depende de risk1, no de work) para que sumen días — en paralelo (ambos
  dependiendo de `work`) solo aportarían el mayor de los dos, subestimando
  la exposición combinada.
- **CPI/SPI vive acá, no en `insight_project_sale`.** Earned Value
  Management es costo/avance puro — no necesita ingresos, solo el
  baseline congelado (Épica 2, v17.0.9.7.10) + `complete`. Se agregó como
  campos extra al mismo payload que ya arma
  `_compute_and_save_deviation_report` (`planned_value`/`earned_value`/
  `actual_cost`/`cost_performance_index`/`schedule_performance_index`),
  en vez de crear un reporte nuevo o depender de `insight_project_sale` —
  cada módulo aporta solo lo que realmente necesita (EVM acá,
  rentabilidad allá). Cálculo restringido a tareas raíz (mismo criterio
  que `_tj_scenario_root_cost`, para no contar doble el costo que TJ3 ya
  acumula de subtareas en el padre); los índices son `None` (no `0`/error)
  cuando `planned_value`/`actual_cost` son 0 — un índice sin sentido
  todavía no es lo mismo que un mal desempeño.

### Agregado

- `project.project._tj_task_risk_buffers` (hook, `[]` por defecto),
  `_tjp_leaf_body_lines`, `_tjp_risk_buffer_wrapper_lines`.
- `project.project._tj_scenario_evm`, wireado a
  `_compute_and_save_deviation_report`.
- Tests: `test_tjp_export.py` (wrapper con 1 y 2+ riesgos, texto exacto
  pinneado contra lo validado en tj3-ms), `test_tjp_schedule_import.py`
  (parser ignora ids sintéticos), `test_baseline_deviation.py` (PV/EV/AC/
  CPI/SPI, con y sin avance/vencimiento todavía).

---

## [17.0.9.7.10] - 2026-07-17

### Prompt

> "Si, avanza con la Épica 1/2. Logremos terminar esas dos, con los cambios
> que se propusieron y los fix necesarios." — Épica 1 (prioridad entre
> proyectos como desempate de recursos) y Épica 2 (lock/freeze de baseline +
> reporte de desviación) del backlog de ecosistema (memoria
> `project_ecosystem_roadmap`, `BACKLOG.md` ítems 5/6/7).

### Discusión de diseño

- **Épica 1 — TJ3 ya resuelve contención, no hacía falta arbitrar en
  Python.** La única palanca real sin reescribir el motor de scheduling es
  el atributo nativo `priority` de TJ3 (1-1000, default implícito 500), que
  ya se usaba para la estrella de tarea (`_TJP_HIGH_PRIORITY = 800`, desde
  v17.0.9.6.3). Se extendió el mismo mecanismo: `resource_priority`
  (`project_improve`, default 10 = "neutral") se escala alrededor del 500
  implícito, con techo en 799 para que ningún proyecto por sí solo pueda
  igualar/superar la estrella de una tarea puntual. Sin configurar
  (`resource_priority == 10`), no se emite ninguna línea — cero cambio de
  comportamiento para proyectos que nunca tocaron el campo. En una corrida
  combinada (`_tj_portfolio_recordset`), dos proyectos con distinta
  prioridad compitiendo por el mismo `res.users` ahora emiten valores
  `priority` distintos — es TJ3 quien desempata con su propio motor, igual
  que ya hacía con la estrella.
- **Épica 2 — el freeze NO puede engancharse a cualquier `write()` de
  `is_baseline`.** `_apply_selection_strategy` reafirma `is_baseline=True`
  en el ganador en **cada** corrida de schedule (incluida la del cron
  nocturno de portfolio) — enganchar el freeze ahí regeneraría el "punto
  fijo" todas las noches, contradiciendo el propósito mismo de comparar
  "cómo se aprobó" contra "cómo está ahora". El único punto de aprobación
  deliberado y poco frecuente que ya existe es `action_start()`
  (`project_improve`, transición evaluación→progreso) — coincide
  exactamente con el ciclo reevaluar→iniciar ya usado para re-baselinear a
  mitad de proyecto (v17.0.9.7.5), así que no hizo falta ningún camino
  adicional para ese caso.
- El freeze se implementó **reusando `knowledge_asset`** en vez de un
  modelo nuevo: un asset por escenario (categoría
  `insight_project.baseline_snapshot`), una versión nueva por cada
  `action_start()` — la inmutabilidad ya la da gratis
  `knowledge.asset.version.write()` (bloquea todo salvo `state`, sin
  reimplementar el patrón `MUTABLE_FIELDS`) y el historial de aprobaciones
  sale gratis vía `asset.version_ids`, mismo beneficio que ya tienen los
  reportes de costo/Gantt.
- El reporte de desviación (`_compute_and_save_deviation_report`) compara
  tarea por tarea el payload congelado contra `insight.task.schedule`
  actual (delta de fecha fin y costo, más `complete` — el único dato de
  avance real disponible). Exige el proyecto en estado "En progreso"
  (según lo indicado por el usuario: antes de eso no hay avance real
  contra el cual medir desviación, solo proyección) y un snapshot ya
  congelado; ninguno de los dos casos rompe silenciosamente, explotan con
  `UserError` explicando qué falta.
- Al calcular el total de costo (congelado y actual) se evitó confiar en
  `scenario.total_cost`/`grand_total_cost`: ese campo solo se actualiza
  cuando corre `_apply_selection_strategy`, no automáticamente al cambiar
  `schedule_ids` — mismo motivo por el que los reportes de costo
  (`_tj_cost_by_phase_and_skill`/`_cost_by_department`) tampoco confían en
  él. Se agregó `_tj_scenario_root_cost(scenario)` (suma de costo de tareas
  raíz, mismo criterio que `total_cost`) calculado fresco desde
  `schedule_ids` en ambos lados de la comparación.
- **Unificación del botón de reportes** (pedido explícito del usuario):
  `insight.scenario.action_generate_cost_reports` → `action_generate_reports`
  (rename directo, sin shim — nadie más lo llamaba fuera de las vistas).
  Corre costo+Gantt siempre (sin cambios de comportamiento) y desviación
  solo si el proyecto está en progreso. `cost_report_count` →
  `report_count`, ampliado a costo+desviación (el Gantt sigue sin contar
  ahí, es por-proyecto no por-escenario). El cron nocturno
  (`_cron_run_portfolio_schedule`) ahora regenera los tres reportes de cada
  proyecto en progreso tras un recálculo exitoso — un proyecto que falle no
  bloquea a los demás, mismo criterio de aislamiento que ya usaba el resto
  del cron. Draft/evaluación no requirieron cambios: ya eran manuales y por
  proyecto/portfolio respectivamente (el reporte de impacto de evaluación
  es un mecanismo aparte, ya existente).

### Agregado

- `project.project._tjp_task_priority_line`/`_TJP_NEUTRAL_RESOURCE_PRIORITY`/
  `_TJP_PRIORITY_SCALE`: desempate de `resource_priority` vía `priority` TJ3.
- `project.project.action_start` (override de `project_improve`):
  congela el baseline vigente al pasar a "En progreso".
- `project.project._freeze_baseline_snapshot`/
  `_get_or_create_baseline_snapshot_asset`/`_tj_scenario_root_cost`.
- `project.project._compute_and_save_deviation_report`/
  `_get_or_create_deviation_asset`.
- Categorías de `knowledge.asset` nuevas: `insight_project.baseline_snapshot`,
  `insight_project.deviation_report` (sumada a `report_asset_ids`).
- Tests: `test_tjp_export.py` (prioridad cross-proyecto, techo en 799,
  estrella siempre gana) y `tests/test_baseline_deviation.py` nuevo (freeze,
  inmutabilidad, cálculo de deltas, gates de estado/snapshot, botón
  unificado, cron).

### Modificado

- `insight.scenario.action_generate_cost_reports` → `action_generate_reports`;
  `cost_report_count`/`_compute_cost_report_count` →
  `report_count`/`_compute_report_count`.
- `project.project.action_generate_cost_reports` (wrapper) →
  `action_generate_reports`.
- `views/insight_scenario_views.xml`/`views/project_project_views.xml`:
  botones/campo renombrados.
- `_cron_run_portfolio_schedule`: regenera reportes tras el recálculo.
- `docs/modules/insight_project.md`: documentadas ambas épicas y las
  categorías de asset nuevas.

---

## [17.0.9.7.9] - 2026-07-16

### Modificado

- `AGENTS.md`: referencia a la sección del AGENTS.md raíz de `fop-odoo` corregida
  (Sección 17 -> Sección 10), tras la reestructuración de ese documento.

---

## [17.0.9.7.8] - 2026-07-16

### Prompt

> (Cambios ya presentes en el working tree al iniciar esta sesión de
> `/ship`, reconstruidos a partir del diff — no se dispone del prompt
> original que los motivó.) Migrar el Gantt del proyecto del controller
> HTTP ad-hoc (`/insight_project/gantt/<id>`, SVG generado en vivo en cada
> request) al mismo patrón ya usado por los reportes de costo:
> `knowledge.asset` persistido + `ir.actions.report`/QWeb.

### Discusión de diseño

- El Gantt vivía como un `http.Controller` propio que llamaba
  `project._render_gantt_svg()` en cada request, sin persistir nada; los
  reportes de costo ya habían migrado antes (v17.0.9.7.2) a
  `knowledge.asset` + `ir.actions.report`. Se aplicó el mismo patrón acá
  para que ambos reportes compartan mecanismo de generación, versionado y
  visualización — `controllers/` quedó vacío y se eliminó junto con su
  `from . import controllers`.
- Se separó el payload (JSON: tareas, milestones, dependencias — ver
  `project.project._tj_gantt_schedule_payload`) del renderer puro
  (`report_gantt_report.render_gantt_svg`, sin acceso a ORM, testeable con
  un dict a mano). El renderer es un solo asset por **proyecto**, no por
  escenario como los reportes de costo, porque el Gantt siempre superpuso
  todos los escenarios en un mismo gráfico.
- `insight.scenario.action_generate_cost_reports` ("Actualizar reportes")
  ahora también regenera el Gantt del proyecto en el mismo disparo, para
  que un solo botón deje ambos reportes al día sin importar desde qué
  escenario se lo invoque.
- Aprovechando la migración a un SVG persistido (ya no generado por
  request), se sumó interactividad que el controller viejo no tenía:
  leyenda de escenarios clickeable (`gantt-legend-item`) que oculta/muestra
  sus barras y flechas de dependencia sin regenerar el reporte, y el
  dibujo de las flechas de dependencia entre tareas (conector en escuadra
  o en "S" según haya espacio entre el fin de la tarea bloqueante y el
  inicio de la dependiente).
- El `<script>` embebido busca su propio `<svg>` por `id` (hash
  determinístico del payload) en vez de `document.currentScript`: ese
  mecanismo es del modelo de scripts de HTML y no está garantizado para un
  `<script>` dentro de un `<svg>` — de fallar, el script aborta sin
  conectar ningún listener y sin pisar otros Gantt embebidos en la misma
  página de reporte.

### Añadido

- `models/report_gantt_report.py`: renderer puro `render_gantt_svg(payload)`
  + modelo abstracto `report.insight_project.report_gantt_report_svg` que
  alimenta el QWeb.
- `report/report_gantt_report_actions.xml`, `report/report_gantt_report_templates.xml`:
  `ir.actions.report` + template QWeb del Gantt, análogos a los ya
  existentes para el reporte de costo.
- `models/project_project.py`: `_tj_gantt_schedule_payload`,
  `_get_or_create_gantt_asset`, `_compute_and_save_gantt_report`.

### Cambiado

- `models/project_project.py`: `action_view_gantt` deja de devolver una
  `ir.actions.act_url` al controller propio y ahora abre el
  `knowledge.asset` de categoría `insight_project.gantt_report` vía
  `action_open_category_report()`; `_compute_report_asset_ids` incluye
  también los assets de Gantt (por proyecto), no solo los de costo (por
  escenario).
- `models/insight_scenario.py`: `action_generate_cost_reports` regenera
  también el Gantt del proyecto.
- `tests/test_gantt.py`: reescrito para cubrir el payload, la persistencia
  del asset, el renderer puro (incluyendo toggle de leyenda y flechas de
  dependencia) y el `report.*` model.

### Eliminado

- `controllers/main.py` (y el `from . import controllers` de `__init__.py`):
  la ruta `/insight_project/gantt/<id>` queda reemplazada por el reporte
  QWeb/`ir.actions.report`.
- `models/project_project.py`: `_render_gantt_svg` (renderer SVG en vivo),
  reemplazado por `report_gantt_report.render_gantt_svg` sobre el payload
  persistido.


## [17.0.9.7.7] - 2026-07-15

### Prompt

> "Algunos cambios estéticos: El budget de status moverlo del header al
> formulario..." / "Otro cambio estético, que los botones de importar
> TJP, Resheduling y Exportar TJP esté en el header y no dentro de
> Scheduler. Quitar el generar reportes de costos que ya no se usa más
> (confirmame en el código, que es lo mismo que resheduling)" →
> confirmado que NO es lo mismo (no vuelve a correr TJ3, solo lee
> `insight.task.schedule` ya persistido) → "Cambialo de lugar, pasalo a
> la pestaña 'Reportes'. Y que sea actualizar reportes." / "Unifica
> botón de Rescheduler. Me gusta el que tiene el ícono de la ruedita y
> dice Replanificar." / "Cuando termina actualizar reportes no actualiza
> la pantalla, y no se ven los reportes generados." / "Ojo! El botón de
> importar siempre tiene que estar visible si está en modo draft" /
> "No! [...] Por favor, habilitalo incluso [siempre visible]."

### Discusión de diseño

- Los botones `Ejecutar Schedule`/`Exportar TJP`/`Importar TJP...` vivían
  dentro de la pestaña "Scheduler" del notebook; se movieron al header
  del formulario (`xpath expr="//header"`), mismo lugar donde
  `project_improve` ya tenía los botones de workflow de `state`.
  `Ver Gantt` se dejó donde estaba (no se pidió moverlo).
- Se investigó si "Generar reportes de costos" es redundante con el
  rescheduling ("Replanificar") antes de tocarlo: confirmado en código
  que **no lo es** — `_compute_and_save_cost_reports` /
  `_tj_cost_by_phase_and_skill` calculan todo en Python puro sobre
  `scenario.schedule_ids` (el `insight.task.schedule` que dejó importado
  la última corrida de "Replanificar"), sin llamar nunca a
  `_call_tj_microservice`; de hecho valida `schedule_dirty` y tira
  `UserError` pidiendo replanificar primero si está desactualizado. Son
  dos pasos secuenciales, no duplicados. Se renombró a "Actualizar
  reportes" y se movió de la pestaña "Scheduler" a su propia pestaña
  "Reportes" (`insight_reports`), junto a la lista `report_asset_ids`
  que ya vivía ahí.
- Botón de reschedule unificado con el que ya existía en el header/
  kanban/tree de `project.task` (`action_reschedule_project`, que solo
  resuelve el proyecto contenedor y delega en `action_run_schedule()`):
  mismo label "Replanificar" + ícono `fa-refresh` en los dos lugares.
  Se actualizaron también los dos textos user-facing que todavía
  mencionaban el nombre viejo del botón ("Ejecutar Schedule"): el SVG
  placeholder del Gantt sin datos y el `UserError` de
  `_tj_cost_by_phase_and_skill` cuando el schedule está sucio.
- Bug encontrado al actualizar reportes: `_compute_and_save_cost_reports`
  devolvía solo un `display_notification`, que **no recarga el
  formulario** — `report_asset_ids` (computado, no-stored) quedaba con
  el valor viejo hasta refrescar la página a mano. Fix: se agregó
  `'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'}` dentro
  de los `params` de la notificación (patrón estándar del web client:
  muestra el mensaje y después recarga el registro actual sin salir de
  la pantalla). Beneficia tanto al botón del proyecto como al
  equivalente en `insight.scenario`, porque ambos comparten la función.
- El botón "Importar TJP..." pasó por dos iteraciones de visibilidad:
  primero `invisible="is_tj_enabled"` (solo si TJ3 no está habilitado),
  después `invisible="is_tj_enabled and state != 'draft'"` (también
  visible en `draft` aunque ya esté habilitado), y finalmente sin
  `invisible` — siempre visible. Se confirmó que
  `action_open_import_wizard` no tiene ninguna validación server-side
  que dependa de `is_tj_enabled` (solo abre el wizard, que al importar
  vuelve a setear `is_tj_enabled=True`, operación idempotente), así que
  no hay riesgo funcional en dejarlo siempre disponible.
- De una sesión previa sin commitear (no motivada por el prompt de esta
  entrada, pero parte del mismo diff a shippear): reimportar un `.tjp`
  borra todas las tareas/milestones existentes del proyecto — `'draft'`
  por sí solo no garantiza que no haya horas imputadas (nada impide
  cargar timesheets en un proyecto en borrador). Se agregó
  `_check_no_timesheets_logged` en `insight.import.wizard`, que valida
  *antes* de intentar el `unlink` y tira un `UserError` propio con las
  tareas afectadas, en vez de dejar que lo rechace a mitad de camino el
  guard nativo de `hr_timesheet`
  (`_unlink_except_contains_entries`) con un mensaje que no dice nada de
  reimportar.

### Cambiado

- `views/project_project_views.xml`: botones de header reordenados
  (Replanificar → Exportar TJP → Importar TJP, siempre visible este
  último); "Actualizar reportes" movido a la pestaña "Reportes".
- `models/project_project.py`: `'next': soft_reload` en la notificación
  de `_compute_and_save_cost_reports`; textos user-facing actualizados
  a "Replanificar"/"actualizar los reportes".
- `models/insight_import_wizard.py` /
  `tests/test_import_wizard.py`: `_check_no_timesheets_logged` +
  test `test_reimport_blocked_when_a_task_has_logged_timesheets`.

### Validación

- Pendiente `-u insight_project` + prueba manual en el navegador para
  los cambios de vista/header. Los tests de `test_import_wizard.py`
  cubren `_check_no_timesheets_logged` (no se corrió la suite completa
  en esta sesión antes de shippear).

---

## [17.0.9.7.6] - 2026-07-14

### Prompt

> Continuación del ítem 2 de `BACKLOG.md` ("Gaps del wizard de import de
> `.tjp` externos"): `depends`/`note` se perdían al importar un `.tjp`
> externo y los milestones importados quedaban con `task_ids` vacío,
> rompiendo el roundtrip export→TJ3→import. (Trabajo de una sesión
> previa a esta; no se dispone del prompt textual original — ver memoria
> `project_insight_tjp_import_gaps`.)

### Discusión de diseño

- Causa raíz de los tres gaps: `insight_import_wizard.py` construía la
  jerarquía de tareas parseando el **CSV que devuelve TJ3** (vía
  `_parse_csv_preview`, con un heurístico de regex aparte para detectar
  milestones), y ese CSV nunca tuvo columna de dependencias ni de notas
  — no era un problema de parsing sino de estar leyendo la fuente
  equivocada. Fix: `models/tjp_parser.py`, un parser real (tokenizer +
  descenso recursivo consciente de llaves/strings, no regex) que lee
  directamente el `.tjp` fuente y expone jerarquía, `depends`/`precedes`
  (con modificador `onstart`/`onend`), `allocate` (recurso primario +
  alternativas) y `note` por tarea. El CSV se sigue usando, pero solo
  para completar fechas/criticidad vía `_import_scenario_csv` — ya no
  para crear tareas.
- `_serialize_tree` aplana el árbol de `tjp_parser` en pre-orden (padre
  antes que hijos) y resuelve `depends`/`precedes` a su `full_id`
  destino ahí mismo, contra el árbol completo — así `action_import` solo
  necesita buscar ese `full_id` en el mapa de registros ya creados
  (`record_by_full_id`), sin reimplementar la resolución de rutas `!`.
- **Bug real de export encontrado y corregido de paso, confirmado contra
  el binario real (tj3-ms v3.8.4)**: `_tjp_task_abs_path` siempre emitía
  un solo `!` sin importar la profundidad de la tarea que declara el
  `depends`/`precedes`. TJ3 resuelve cada `!` subiendo un nivel *desde la
  tarea que declara la dependencia* (no desde la raíz del proyecto) —
  para cualquier tarea anidada dependiendo de una hermana, esto hacía
  que TJ3 rechazara el archivo (`Error: Task a.c has unknown depends
  a.a.b`, reproducido contra el binario real). Fix: `owner` (la tarea
  que declara la dependencia) determina cuántos `!` hacen falta
  (profundidad + 1); antes solo funcionaba por accidente cuando `owner`
  era de nivel raíz, el único caso testeado hasta ahora.
- Se agregó **reimportar**: `action_import` ahora borra las
  `project.task`/`project.milestone` existentes del proyecto antes de
  recrear desde el `.tjp` (no mergea contra un import anterior, para no
  duplicar si la estructura cambió entre corridas). Gateado a que el
  proyecto esté en `state == 'draft'` (`project_improve`,
  `_check_draft_state`) — en evaluación/progreso/finalizado se bloquea,
  para no arriesgar borrar timesheets o schedule ya comprometido.
- `note` ahora llena `project.task.description`; tareas importadas ya
  100% completas (`complete == 100` en el `.tjp`) se crean directamente
  con `state = '1_done'` — sin esto quedaban en "en progreso" (o
  "esperando" si algo dependía de ellas) pese a que su `stage_id` ya
  mostrara "Completada", porque `project.task._compute_state` no deriva
  de la etapa, solo alterna según dependencias abiertas y respeta un
  valor ya cerrado sin pisarlo.
- `BACKLOG.md` ítem 2 actualizado a resuelto.

### Tests

`tests/test_tjp_parser.py` (nuevo, tokenizer + parser: jerarquía,
`depends`/`precedes` con modificadores, `allocate` con alternativas,
milestones, notas con llaves adentro, comentarios). `test_import_wizard.py`
reescrito contra el nuevo pipeline basado en `tjp_parser`. Suite completa
de `insight_project` verificada en verde (236 tests) vía
`make test-local MODULE=insight_project`.

---

## [17.0.9.7.5] - 2026-07-14

### Prompt

> "Dentro del backlog hay una funcionalidad que quiero darle más
> prioridad, que corresponde a los estados de los proyectos en draft,
> evaluación y en progreso. Estamos listos para implementarla?" / "_generate_tjp
> debería ser aplicable a múltiples proyectos [...] En el caso que se
> ejecute contra solo un proyecto no debería ser un caso especial." /
> "Si el active_id tiene estado evaluación entonces solo se actualiza
> active_id, y si está en modo progreso se actualizan todos." / "El diff
> no es importante pero si el resultado de la ejecución en modo
> validación [...] hay que agregar un reporte nuevo que diga a qué fecha
> se moverán los otros proyectos [...] Es un reporte del tipo
> knowledge.asset." / "El message post no tienen ningún tratamiento
> especial. No es necesario."

### Discusión de diseño

- Auditoría previa (2026-07-13) confirmó que nada de esto existía:
  sin campo de estado en `project.project`, `_generate_tjp()`/
  `_tj_project_users()` estrictamente de un solo proyecto,
  `_apply_selection_strategy()` intra-proyecto. El diseño de 3 estados
  (draft/evaluación/progreso) discutido esa sesión quedó documentado en
  memoria (`project_portfolio_scheduling_states`) como referencia — este
  ciclo lo implementó, con ajustes reales respecto a esa versión.
- El usuario insistió en que la generación del `.tjp` no debía tener un
  caso especial para un solo proyecto: `_generate_tjp`/`_tj_project_users`
  pasan a operar siempre sobre un recordset (1 o N proyectos). La única
  pieza genuinamente asimétrica es el **write-back**: en evaluación solo
  se persiste el proyecto activo; en progreso se persiste todo el
  recordset combinado.
- Bug real encontrado y corregido durante la implementación: no se puede
  reusar el `insight.scenario` del proyecto activo para persistir filas
  de otro proyecto combinado — `insight.task.schedule` exige que
  `scenario_id.project_id == task_id.project_id`. Cada proyecto "en
  progreso" incluido en la corrida persiste contra su PROPIO escenario
  baseline, no el del proyecto activo.
- Segundo bug encontrado (vía la suite de tests, no por inspección): el
  `default=` de `max()` en Python se evalúa siempre, no perezosamente —
  `_tjp_project_header` llamaba un método `ensure_one()` sobre el
  recordset combinado completo dentro de ese `default`, rompiendo con
  "Expected singleton" en cualquier corrida de 2+ proyectos.
- `_tjp_scenario_id` se calificó con el id del proyecto dueño del
  escenario (antes derivaba solo del nombre) — dos proyectos con un
  escenario "Default" cada uno colisionaban al combinarse.
- El diseño original preveía un `message_post` de impacto cruzado en el
  chatter; se descartó a pedido del usuario a favor de un reporte
  estructurado versionado como `knowledge.asset`
  (`_tj_generate_evaluation_impact_report`), mismo patrón que los
  reportes de costo (`_get_or_create_cost_asset`/
  `_compute_and_save_cost_reports`) — delta de fecha por tarea/hito raíz,
  usuarios afectados, conteo de recursos antes/después. Solo se genera
  si hay un cambio real que reportar (evita ruido).
- Se agregó un 4to estado, "Finalizado" (`done`), y botones de transición
  de estado en el header del form (ver CHANGELOG de `project_improve`,
  que es donde vive el campo `state`) — se discutió un botón "Reabrir"
  desde Finalizado y se descartó a favor de la idea de "Clonar proyecto"
  con calibración histórica de esfuerzo (ver
  `insight_project/BACKLOG.md` ítem 8, memoria
  `project_clone_template_design`, no implementado todavía).

### Agregado

- `_tj_portfolio_recordset()`: recordset a combinar en una corrida =
  todos los proyectos `state='progress'` + el proyecto activo, sin
  importar su propio estado.
- `_cron_run_portfolio_schedule()` + `ir_cron_run_portfolio_schedule`
  (`data/insight_cron.xml`): recalcula diariamente todos los proyectos
  "en progreso" juntos.
- `_parse_scenario_csv_preview()`: parsea la respuesta de TJ3 sin
  persistir, usada para los proyectos combinados que no se tocan en modo
  evaluación (comparte parsing con `_import_scenario_csv` vía el nuevo
  helper `_parse_tj_schedule_csv`).
- `_tj_generate_evaluation_impact_report()` / `_tj_project_impact_summary()`
  / `_get_or_create_evaluation_impact_asset()`: reporte de impacto
  versionado como `knowledge.asset` (categoría
  `insight_project.evaluation_impact_report`) cuando la evaluación de un
  proyecto afecta a proyectos "en progreso".
- `tests/test_portfolio_scheduling.py`: recordset combinado, dedup de
  recursos compartidos en el `.tjp`, calificación de escenarios por
  proyecto, gateo de persistencia (evaluación vs. progreso), y el
  reporte de impacto.

### Cambiado

- `_generate_tjp(active_project=None)` / `_tj_project_users()` /
  `_tjp_project_header(..., active_project=None)`: multi-proyecto, sin
  caso especial para un solo proyecto. `active_project` determina la
  jerarquía de escenarios TJ3 y el header/etiqueta del archivo; el
  `start`/`end` del bloque `project` cubre a todos los proyectos
  combinados. `_tjp_task_block`/`_tjp_milestone_block`/dependencias FF
  dejan de comparar `project_id == self` (rompía con un recordset
  multi-proyecto) y comparan contra el proyecto dueño de cada tarea.
- `_import_all_schedules(csv_files, active_project=None)`: write-back
  asimétrico (ver discusión de diseño arriba).
- `action_run_schedule`: arma el recordset combinado, genera el `.tjp`
  sobre él, pero sigue llamando a `_call_tj_microservice` sobre `self`
  (el proyecto que disparó la corrida) para no spamear el chatter de
  proyectos ajenos ante un error.

### Validación

- `make test-local MODULE=insight_project` (DB de sesión aislada,
  clonada de `test_template` — no toca la DB compartida `fop`):
  199/199 tests, 0 fallos, 0 errores.

---

## [17.0.9.7.4] - 2026-07-13

### Prompt

> "No se puede unificar el cálculo de costos con Ejecutar schedule? Acaso
> no estamos haciendo lo mismo antes de calcular los costos? [...]
> Unifiquemos por favor." / "Quedo perplejo, porque cachear los costos?" /
> "Cómo van a existir varios reportes de tipo knowledge.asset me parece
> mas comodo que los reportes tengan sus propia hoja y salgan de
> 'Scheduler'."

### Discusión de diseño

- Primer intento (descartado tras la pregunta del usuario sobre el
  cache): declarar las cuentas TJ3 `by_phase`/`by_skill` en el MISMO
  .tjp del schedule + un `accountreport` por escenario, cacheando el
  resultado parseado en campos nuevos de `insight.scenario`. Se abandonó
  al notar que `insight.task.schedule` YA trae el `cost` de cada tarea
  (no solo hojas) desde el schedule normal — `insight.scenario.total_cost`
  ya es literalmente `sum(root_schedules.cost)` (ver
  `_compute_scenario_aggregates`), es decir que "costo por fase" ya es el
  `cost` de la tarea raíz sin declarar ninguna cuenta nueva.
- Diseño final: `_tj_cost_by_phase_and_skill` pasa a calcularse 100% en
  Python sobre `scenario.schedule_ids`, con el mismo criterio que
  `_cost_by_department` (ya existente): "por fase" toma el `cost` de la
  tarea raíz tal cual; "por skill" reparte el `cost` de cada tarea hoja
  en partes iguales entre sus `required_skill_ids`. Se elimina la
  segunda corrida de TJ3 que hacía `_generate_cost_report_tjp`, sin
  necesitar ningún cache intermedio: el dato persistente entre "Ejecutar
  Schedule" y "Generar reportes de costos" es `insight.task.schedule`,
  que ya existía.
- Beneficio adicional (no solo de performance): antes, si
  `tj_allocation_selection = 'random'`, cada corrida de TJ3 podía asignar
  recursos distintos a la misma tarea — el desglose de costo por
  fase/skill (segunda corrida) podía no coincidir con los recursos
  realmente asignados en el schedule importado (primera corrida). Al
  quedar todo derivado de la misma corrida, ese riesgo de inconsistencia
  desaparece.
- Se elimina como código muerto: `_generate_cost_report_tjp`,
  `_tjp_phase_skill_account_lines`, `_tjp_extra_chargeset_fn`,
  `_tjp_accountreports`, `_parse_accountreport_csv`, las constantes
  `_TJP_PHASE_ACCOUNT_ID`/`_TJP_SKILL_ACCOUNT_ID`/`_TJP_PHASE_REPORT_ID`/
  `_TJP_SKILL_REPORT_ID`, y el parámetro `extra_chargeset_fn` de
  `_tjp_task_block` (sin más llamadores tras lo anterior).
- `report_asset_ids` (la lista de reportes `knowledge.asset` del
  proyecto) se muda de un `<field>` embebido al fondo de la pestaña
  "Scheduler" a su propia pestaña "Reportes" en el notebook del
  proyecto — se anticipa que crezca (el Gantt vía este mismo mecanismo
  ya estaba anotado como próxima iteración desde v17.0.9.7.2) y no tiene
  sentido seguir agregando reportes al fondo de una pestaña que ya tiene
  Escenarios y Costos extra.

### Cambiado

- `models/project_project.py`: `_tj_cost_by_phase_and_skill` calcula fase
  y skill 100% en Python sobre `insight.task.schedule`, sin llamar a TJ3.
  `_generate_tjp` queda sin cambios (vuelve a ser exactamente el .tjp de
  antes de este ciclo). Removido todo lo relacionado a las cuentas
  TJ3 `by_phase`/`by_skill` (ver arriba).
- `views/project_project_views.xml`: nueva pestaña "Reportes"
  (`name="insight_reports"`), separada de "Scheduler"; `report_asset_ids`
  se mudó ahí.
- `tests/test_cost_reports.py`: `TestTjpPhaseSkillAccountLines`,
  `TestTjpExtraChargesetFn` y `TestParseAccountreportCsv` se eliminan
  (probaban código removido); nueva `TestCostByPhaseAndSkill` prueba
  `_tj_cost_by_phase_and_skill` sembrando `insight.task.schedule`
  directamente, mismo patrón que `TestCostByDepartment`.

### Validación

- `make test-local MODULE=insight_project`: 189/189 tests, 0 fallos.

## [17.0.9.7.3] - 2026-07-13

### Cambiado

- `views/res_config_settings_views.xml`: la sección "TaskJuggler" de
  Ajustes se cuelga ahora de `project.res_config_settings_view_form`
  (`//app[@name='project']`) en vez de `base.res_config_settings_view_form`,
  y usa los widgets nativos `<block>`/`<setting>` de la app de Ajustes en
  vez del `div.o_setting_box` armado a mano. Efecto: la configuración de
  TJ3 (`tj_microservice_url`, `tj_microservice_timeout` + botón "Probar
  conexión") ahora aparece dentro de la sección de Proyecto en Ajustes,
  con el mismo look & feel que el resto de las settings nativas de esa
  app, en vez de un bloque genérico suelto al final de Ajustes.
- Sin cambios de campos ni de lógica (`action_test_tj_connection` y los
  dos campos de configuración quedan igual) — es puramente de
  presentación/ubicación.

### Validación

- `make test-local MODULE=insight_project`: 193/193 tests, 0 fallos (sin
  tests unitarios propios de vistas de Ajustes; validado por carga
  limpia del módulo).

## [17.0.9.7.2] - 2026-07-13

### Prompt

> "Voy a necesitar cosas dinámicas [...] Yo al asset lo dejaría tal como
> está, no lo relacionaría con el render. Es el QWeb quien sabe como
> renderear [...] Me gusta la salida de asset_category en
> ir.actions.report; mas natural imposible. Probemos este aproach. Agrega
> asset_category en el addon de knowledge_asset. Luego agrega a
> insight_project el ir.action.report acorde a cada reporte generado, con
> un qweb que sea de tipo html. Y deja un botón en los reportes para
> acceder al reporte html. Por ahora solo en costos, vamos a probar ahí."

### Discusión de diseño

- Reemplaza el controller propio `/insight_project/cost_report/<id>`
  (SVG armado a mano con f-strings, sin QWeb) por el mecanismo genérico
  discutido con el usuario: `ir.actions.report` + el nuevo campo
  `asset_category` de `knowledge_asset` (ver su CHANGELOG v17.0.1.0.4).
  `insight_project` no escribe ningún controller propio — reusa el
  controller nativo de Odoo (`/report/<type>/<reportname>/<docids>`, ya
  con manejo de acceso vía el `ir.rule` del modelo, mismo criterio
  "todo o nada" que ya regía en el controller descartado).
- `report.insight_project.report_cost_report_html` (`_get_report_values`)
  hace el trabajo de armar filas/porcentajes de barra en Python — el
  QWeb (`report/report_cost_report_templates.xml`) solo itera y escapa
  (`t-esc`), sin lógica de negocio adentro. Mismo criterio que ya se
  usaba en el controller viejo, solo que ahora la "vista" es
  declarativa.
- `ir.actions.report` con `model='knowledge.asset'` y
  `asset_category='insight_project.cost_report'`: una sola acción sirve
  para las 3 dimensiones (fase/skill/departamento) porque comparten el
  mismo *schema* de payload (`title`/`currency`/`items`/`total`/
  `generated_at`) — no hace falta una acción por dimensión.
- Botón "Ver reporte" agregado directo en el `<tree>` embebido de
  `report_asset_ids` (pestaña Scheduler), llamando al método genérico
  `knowledge.asset.action_open_category_report()` — `insight_project` no
  necesita ningún método propio de apertura, solo declarar la acción con
  la categoría correcta.
- Primer caso de uso de este mecanismo (costos); el Gantt vía este mismo
  mecanismo queda para una iteración siguiente, una vez validado acá.

### Cambiado

- Se elimina `controllers/main.py::InsightProjectCostReport` y
  `_render_bar_chart` (reemplazados por `ir.actions.report` + QWeb).

### Agregado

- `report.insight_project.report_cost_report_html`
  (`models/report_cost_report.py`): prepara filas/porcentajes desde el
  payload de la última versión del asset.
- `report/report_cost_report_templates.xml`: template QWeb
  `insight_project.report_cost_report_html` (barras de costo, HTML puro,
  sin JS).
- `report/report_cost_report_actions.xml`:
  `action_report_cost_report_html` (`ir.actions.report`,
  `report_type='qweb-html'`, `asset_category='insight_project.cost_report'`).
- Botón "Ver reporte" en la lista de `report_asset_ids` (pestaña
  Scheduler).

### Validación

- `make test-local MODULE=insight_project`: 188/188 tests, 0 fallos.
- Verificado en shell: `asset.action_open_category_report()` devuelve una
  action `ir.actions.report` apuntando al template correcto;
  `ir.actions.report._render_qweb_html(...)` produce el HTML esperado
  (título, total, barras con porcentaje relativo correcto — 5000 vs 3000
  → 100%/60%).

## [17.0.9.7.1] - 2026-07-13

### Prompt

> "Podríamos dejar los knowledge.assets que sean reportes de un projecto
> en la hoja TaskJuggler, debajo de Costos Extras. Y podríamos cambiar el
> nombre de la hoja de Task Juggler a Scheduler, te parece?"

### Discusión de diseño

- Los reportes de costo (`knowledge.asset`, ver v17.0.9.7.0) se generan
  con `res_model='insight.scenario'`, no `'project.project'` — no había
  ninguna vista a nivel proyecto que los agregara a través de todos los
  escenarios. Se agregó `project.project.report_asset_ids` (Many2many
  `knowledge.asset`, computado, no almacenado — mismo patrón sin
  `@api.depends` que `insight.scenario.cost_report_count`, porque ninguno
  de los dos puede expresar su dependencia real vía el grafo de ORM) que
  busca los assets de categoría `_TJP_COST_REPORT_CATEGORY` cuyo
  `res_id` esté entre los escenarios del proyecto.
- Se embebió como lista de solo lectura (`create="0" delete="0"`) debajo
  de "Costos extra (infra/SaaS)", tal cual lo pidió el usuario — abrir un
  registro de la lista lleva a la vista propia de `knowledge.asset` (no
  se construyó una vista dedicada al reporte renderizado; eso ya existe
  vía el controller `/insight_project/cost_report/<id>`).
- Renombrado el label de la pestaña de "TaskJuggler" a "Scheduler" (el
  `name="tashjuggler"` interno del `<page>` se dejó igual a propósito —
  es solo la clave de persistencia de la pestaña activa en el navegador,
  cambiarlo no aporta nada y evita invalidar preferencias de UI ya
  guardadas).

### Agregado

- `project.project.report_asset_ids` + `_compute_report_asset_ids`:
  reportes de costo del proyecto, agregados a través de todos sus
  escenarios.
- Vista: sección "Reportes" debajo de "Costos extra (infra/SaaS)" en la
  pestaña Scheduler, listando `report_asset_ids`.

### Cambiado

- Label de la pestaña TaskJuggler → "Scheduler" en el form de
  `project.project` (`name` interno sin cambios).

### Validación

- `make test-local MODULE=insight_project`: 188/188 tests, 0 fallos.
- `get_views()` del form de `project.project` confirmado sin errores de
  arch tras el cambio de vista.

## [17.0.9.7.0] - 2026-07-13

### Prompt

> "Dame detalle de cuenta de única. Quiero intercambiar ideas antes de
> implementar." → tras discutir el diseño: "Me gustan esos reportes de
> costos, pero todavia no me lo imagino en la interface de Odoo [...]
> Creo que la mejor opción es que cada reporte termine en un JSON [...]
> Que existan tipos de reportes [...] tendríamos al menos tres botones
> tipo radio: Por eje/fase, Por categoría/skill, Por Departamento [...]
> Al activarlo guarda esos tres reportes. Te parece viable?" → al
> descubrirse que el usuario ya construía, en otra sesión en paralelo,
> un addon genérico `knowledge_asset` para exactamente este tipo de
> almacenamiento: "Pausar costos, foco 100% en Knowledge Assets ahora"
> → luego, al confirmar que ya estaba shippeado: "insight_project pasa
> a ser consumidor, no motor de reportes propio."

### Discusión de diseño

- Item #9 del backlog TJ3 ("cuenta de costo única") arrancó chico pero
  escaló a reportes de costo **históricos**, con 3 desgloses (fase,
  categoría/skill, departamento), navegables desde Odoo — se fusionó
  con el item #10 (reportes nativos) del mismo backlog.
- **Fase y categoría/skill** son atributos fijos de la tarea, conocidos
  *antes* de programar → se resuelven con **cuentas TJ3 reales**
  (`account`/`chargeset` anidados + un `accountreport` nuevo por
  dimensión), no en Python. **Departamento** depende de qué recurso
  termina asignado (solo se sabe *después* del schedule) → se calcula
  100% en Python sobre `insight.task.schedule` ya importado, sin volver
  a invocar TJ3 para esa dimensión.
- Sintaxis TJ3 validada empíricamente contra `tj3-ms` real antes de
  escribir el export (mismo método que toda la sesión, ver
  `feedback_tj3_empirical_testing` en memoria): cuentas anidadas se
  declaran con bloque (`account by_phase "Por fase" { account phase_5
  "..." }`), no con paths punteados (`by_phase.phase_5` es rechazado
  tanto al declarar como al referenciar en `chargeset`/`accountroot`);
  cada tarea puede tener múltiples `chargeset` simultáneos apuntando a
  cuentas top-level distintas sin pisarse; las columnas de período de
  un `accountreport` son **acumulativas a la fecha**, no incrementales
  — sumar todas las columnas duplicaría/triplicaría el costo real, hay
  que tomar solo la última.
- Multi-departamento en una tarea hoja (ej. un puesto por skill de un
  departamento y el usuario asignado de otro): el costo de esa tarea se
  reparte en **partes iguales** entre los departamentos representados,
  para que la suma de todos los departamentos siga dando el costo total
  real sin doble conteo.
- Disparo **explícito** (botón "Generar reportes de costos"), nunca
  automático en cada reschedule — el histórico debe quedar con
  checkpoints significativos, no una fila por cada ajuste menor.
  Bloqueado con `UserError` si `schedule_dirty` o si no hay escenario
  baseline.
- Almacenamiento vía `knowledge_asset` (addon nuevo, ya shippeado en
  paralelo por otra sesión, v17.0.1.0.0): un `knowledge.asset` por
  combinación (escenario, dimensión) — 3 en total por escenario, con
  `res_model='insight.scenario'`. Cada click en "Generar" hace
  get-or-create de esos 3 assets y les agrega una **versión nueva**
  (`create_version`) — el histórico sale gratis vía
  `asset.version_ids`, sin modelo propio en `insight_project`.
  Visibilidad `shared` + `shared_group_ids` incluyendo
  `project.group_project_manager`, para que todo el equipo de PM vea
  los reportes, no solo quien apretó el botón.
- Rendering vía un controller liviano propio
  (`/insight_project/cost_report/<id>`, mismo patrón que el SVG de
  Gantt existente) — `knowledge_asset` deliberadamente no rendariza
  nada, eso queda a cargo de cada consumidor.
- Descubierto **al pasar** (no buscado): `insight.task.schedule.cost`
  venía siendo 0 o gravemente incorrecto en todo reschedule real, por
  falta de `balance`/`currencyformat` en el `.tjp` — ver detalle en el
  fix de más abajo. Corregido en el mismo alcance porque el nuevo
  `taskreport` de costos dependía de que `cost` funcionara realmente.
- Limitación conocida, documentada y no parcheada (pertenece a
  `knowledge_asset`, de otra sesión): su regla `shared` solo otorga
  `perm_read=1` a usuarios no-owner en `shared_group_ids` — un segundo
  project manager que no generó el reporte puede **verlo** pero no
  volver a generarlo (`create_version`) sobre los mismos 3 assets; solo
  el owner original o miembros de `group_knowledge_asset_manager`
  pueden hacerlo. Si esto resulta molesto en el uso real, requiere un
  cambio en `knowledge_asset`, no en `insight_project`.

### Agregado

- `project.project._generate_cost_report_tjp(scenario)`: genera un
  `.tjp` acotado a un solo escenario, con cuentas anidadas `by_phase`/
  `by_skill` y sus `chargeset` correspondientes, y dos `accountreport`
  (`cost_by_phase`, `cost_by_skill`) en formato CSV.
- `project.project._tj_cost_by_phase_and_skill(scenario)`: invoca el
  microservicio TJ3 con el `.tjp` de arriba y parsea ambos CSV
  (`_parse_accountreport_csv`, tomando solo la última columna de
  período).
- `project.project._cost_by_department(scenario)`: cálculo 100% Python
  sobre `insight.task.schedule`, con reparto parejo entre departamentos
  múltiples de una misma tarea.
- `project.project._compute_and_save_cost_reports(scenario)` /
  `insight.scenario.action_generate_cost_reports()`: orquestan el
  cálculo de las 3 dimensiones y las versionan como `knowledge.asset`.
- Botón "Generar reportes de costos" y botón inteligente "Reportes" en
  `insight.scenario` (form) y en la pestaña TaskJuggler de
  `project.project`.
- Controller `/insight_project/cost_report/<int:asset_id>` (`auth=
  'user'`): renderiza el payload JSON de cada reporte como un gráfico
  de barras SVG inline, respetando el `ir.rule` propio de
  `knowledge.asset` (sin `sudo()`).
- `depends`: se agrega `knowledge_asset`.

### Corregido

- **`insight.task.schedule.cost` venía siendo 0 o incorrecto en todo
  reschedule real**: el `taskreport` nunca declaraba `balance`, así que
  la columna `cost` devolvía el string literal `"No 'balance' defined!"`
  (parseado como `0.0`); y sin `currencyformat`, un locale con coma
  decimal hacía que `_parse_tj_cost` confundiera separador de miles con
  decimal (error de 100x). Se agregó una cuenta `revenue` dummy (nunca
  imputada) + `balance cost revenue` en ambos `taskreport`, y
  `currencyformat "-" "" "" "." 2` en el header del proyecto. Validado
  end-to-end contra `tj3-ms` real: 5 días × $800/día → `4000.0`
  correctamente (antes: `"No 'balance' defined!"` → `0.0`, o con coma de
  locale → `30000.0`).

### Validación

- `make test-local MODULE=insight_project`: 188/188 tests, 0 fallos.
- End-to-end manual contra `tj3-ms` real (proyecto con 2 fases, 2
  skills, 2 departamentos, 2 usuarios): `.tjp` generado, corrido contra
  el binario real, CSV de `cost_by_phase`/`cost_by_skill` con totales
  correctos (5 días × $1000/día = $5000 por tarea, sin doble conteo).
  Pipeline completo (`action_generate_cost_reports` →
  `knowledge.asset`) validado en shell: 3 assets creados con payloads
  correctos; una segunda generación versiona los mismos 3 assets (no
  duplica); un usuario `project.group_project_manager` distinto del que
  generó el reporte puede leerlo (`shared_group_ids` funciona); el
  guard de `schedule_dirty` bloquea la generación con `UserError`.

## [17.0.9.6.12] - 2026-07-13

### Prompt

> "Me encontré con el siguiente error: Error del microservicio TJ3: 422
> Client Error [...] The interval duration must be a multiple of the
> specified timing resolution (60 min) [...] booking u2 2026-07-13
> +0.14h" → luego, tras el primer fix, un segundo error distinto en el
> mismo proyecto: "Resource u2 has no duty at 2026-07-10-00:00--0300" →
> "Pero es lo que trabajó. Si trabajó demás no debería descartarlo,
> quizás esa persona trabajó 10hs para trabajar menos la semana
> siguiente. No puede ser? Cómo aceptamos esos casos?" → finalmente,
> tras verificar el fix end-to-end: "Veamos un tema. Veo que los
> errores ninguno quedó asentado en el chatter!"

### Discusión de diseño

- `_tjp_bookings` volcaba la suma de `unit_amount` de los timesheets tal
  cual a un `booking +{hours}h`, sin truncar contra el
  `timingresolution` del proyecto (60 min, default *y máximo* de TJ3
  según su documentación oficial — bajarlo tiene costo real de memoria/
  performance en un horizonte de varios años, así que se descartó como
  solución). Un timesheet con minutos sueltos (ej. `0.14h`) rompía el
  parseo completo del `.tjp`.
- El truncamiento a hora entera se aplica sobre la suma ya agrupada por
  (usuario, día), no timesheet por timesheet — dos líneas de 0.6h
  (1.2h reales) deben truncar a `+1.00h`, no a `0h + 0h`.
- Descubierto un segundo bug relacionado al verificar el primero contra
  el binario real (`tj3-ms`): un `booking` cuyas horas logueadas superan
  la capacidad de calendario del recurso ese día (ej. 10h logueadas un
  viernes con calendario de 9h) obliga a TJ3 a derramar el excedente al
  próximo día hábil — si ese día cae en o después de `now` (típico
  cruzando un fin de semana), TJ3 rechaza todo el booking con "has no
  duty". Se descartó truncar/descartar el excedente (perdería horas
  realmente trabajadas, posible compensación de una semana con otra) a
  favor de `{ overtime 2 }`: atributo nativo de `booking` en TJ3 que
  permite cubrir la duración pedida con horas fuera de calendario
  (incluida licencia) en vez de derramar a otro día. Confirmado
  end-to-end contra `tj3-ms` real: el mismo `.tjp` que fallaba con "no
  duty" ahora responde `HTTP 200` con los 3 CSV de schedule.
- `_call_tj_microservice` solo asentaba en el chatter el caso puntual de
  "N tareas no entran en el horizonte" (`UnscheduledTasksError`) — los
  otros tres caminos de error (conexión caída, timeout, error genérico
  de scheduling — exactamente el tipo de error de este mismo fix) solo
  mostraban un `UserError` como popup momentáneo, sin dejar rastro. Se
  extendió el `message_post` a los tres caminos restantes vía un helper
  común (`_tj_post_error`).

### Corregido

- `_tjp_bookings` (`project_project.py`): trunca la suma de horas por
  (usuario, día) a la hora entera antes de emitir el `booking`, evitando
  duraciones no múltiplo del `timingresolution` de TJ3.
- `_tjp_bookings`: agrega `{ overtime 2 }` a cada `booking`, para que
  horas logueadas por encima de la capacidad de calendario del recurso
  ese día no fuercen un derrame a otro día que puede pisar `now` y
  romper el schedule completo.
- `_call_tj_microservice`: los errores de conexión, timeout, y error
  genérico del microservicio TJ3 ahora quedan asentados en el chatter
  del proyecto (antes solo el caso de "unscheduled tasks" lo hacía).

### Adenda (misma versión, trabajo concurrente de otra sesión)

Mientras se investigaba este fix, en otra sesión en paralelo (mismo
directorio de trabajo) se encontró y corrigió un bug no relacionado, que
terminó empaquetado en este mismo commit al compartir el working tree:

- **`insight.task.schedule.cost` venía siendo 0 en todo reschedule real**:
  el `taskreport` nunca declaraba `balance`, así que la columna `cost` de
  TJ3 devolvía el string literal `"No 'balance' defined!"` en vez de un
  número — `_parse_tj_cost` lo interpretaba silenciosamente como `0.0`.
  Además, sin un `currencyformat` explícito, TJ3 usa el separador
  decimal del locale del contenedor (coma, ej. `"300,00"`), que
  `_parse_tj_cost` habría leído como separador de miles (100 veces más
  grande) si el `balance` hubiera estado seteado con el locale por
  default.
- Fix: `_tjp_cost_account` declara una cuenta `revenue` dummy (nunca se
  le carga nada, solo existe porque `balance` exige dos cuentas de nivel
  superior); `_tjp_project_header` agrega
  `currencyformat "-" "" "" "." 2` (punto decimal, sin separador de
  miles); `_tjp_reports` agrega `balance cost revenue` a ambos
  taskreports. Validado contra el binario real: con el fix, una tarea de
  5 días a $800/día devuelve `4000.0` (número plano, sin comillas) en
  vez del string de error.
- Prerequisito real para el desglose de costos por departamento (item #9
  del backlog TJ3), que depende de que `sched.cost` sea correcto — y
  también corrige `insight.scenario.total_cost`/`grand_total_cost`
  (usados en la selección automática de escenario), que hasta ahora
  nunca reflejaban costo laboral real.

---

## [17.0.9.6.11] - 2026-07-12

### Prompt

> "Pasemos al shift. Pero describime el caso de uso." → confirmado el
> caso de uso (cambios temporales de disponibilidad de un recurso — ej.
> sprint con horas extra, o dedicación reducida puntual — sin tocar su
> calendario permanente en Odoo) → "No, me parece perfecto. Sigamos con eso."

### Discusión de diseño

- Confirmado en el gem (`shifts.resource`, `TjpSyntaxRules.rb`): un
  `shift` es una "mini-calendario" reusable, declarado una sola vez a
  nivel proyecto, que se le asigna a un recurso acotado a una ventana de
  fechas — durante esa ventana **reemplaza por completo** el calendario
  habitual del recurso. Distinto de `leaves` (que son ausencias, 0
  horas): un shift puede tener MÁS o MENOS horas que lo habitual.
- Se reusó el modelo `resource.calendar` de Odoo en vez de inventar un
  esquema propio de horarios: el "calendario alternativo" de un shift es
  cualquier `resource.calendar` existente, y `_tjp_calendar_hours`
  (ya usado para el calendario habitual del empleado) se reutiliza tal
  cual para volcar las horas del shift — cero código nuevo de parsing de
  horarios.
- Validado contra el binario real: una tarea de 20 días de esfuerzo
  termina antes (2026-07-27) con una ventana de horas extra (8-20h en
  vez de 9-18h) que sin ella (2026-07-29) — confirma que el shift
  realmente cambia el cálculo, no es solo cosmético.
- `insight.employee.shift` vive a nivel de `hr.employee` (no por
  proyecto), consistente con `tj_base_efficiency`/`tj_daily_rate`/
  `tj_daily_max_hours` — mismo precedente. Si en el futuro hace falta
  variar por proyecto, sería una extensión, no un rediseño.
- Los bloques `shift` deben declararse ANTES que los `resource` que los
  referencian (igual que `account`) — un solo bloque por
  `resource.calendar` distinto, reusado por id desde cualquier empleado
  que lo use en su ventana.
- Constraint de no-superposición (`insight.employee.shift`): TJ3 no
  acepta ventanas de shift solapadas para el mismo recurso — se valida
  en Odoo con un mensaje claro en vez de dejar que el microservicio lo
  rechace.

### Agregado

- Modelo `insight.employee.shift` (`employee_id`, `date_from`,
  `date_to`, `calendar_id`), con constraints de rango de fechas válido y
  no-superposición.
- `hr.employee.tj_shift_ids` (One2many), visible en una pestaña nueva
  "Disponibilidad TJ" del form de empleado.
- `_tjp_shift_declarations`/`_tjp_shift_id`/`_tjp_shift_assignments`
  (`project_project.py`).
- Tests: emisión de la ventana activa, exclusión de ventanas vencidas,
  contenido del bloque `shift` declarado, ausencia sin ningún shift,
  constraints del modelo (rango inválido, solapamiento, ventanas
  adyacentes permitidas).
- Validado end-to-end: proyecto real → `_generate_tjp()` → binario real
  → mismo resultado que la exploración aislada.

---

## [17.0.9.6.10] - 2026-07-11

### Prompt

> "Sabes porque realmente no avanzo en el punto Finish-Finish? Porque el
> tipo de dependencia lo tiene la tarea y no la tiene la relación entre
> tarea y tarea?" → resuelto el prerequisito (v17.0.9.6.9) → "Ah! Creo
> que para prevenir problemas de usabilidad es mejor sacar FF de la
> general y solo dejarlo en las aristas" → "Revisa todas las
> combinaciones posibles y así confirmamos funcionamiento. Luego
> implementa los tests [...] el objetivo es validar la construcción de
> tjp cumpliendo la semántica esperada para combinación de tareas, orden,
> tipos de tareas, comienzo, fin y esfuerzo." — con la aclaración
> explícita de que los tests del addon NO deben depender del servicio
> real de TJ3 (solo warning si no está disponible; en la práctica: la
> exploración empírica la hace el agente por su cuenta contra `tj3-ms`,
> y el addon solo pinnea el `.tjp` de texto ya validado).

### Discusión de diseño

- **FF ya no es una opción de `tj_dependency_type`** (el default de la
  tarea) — pasa a ser Selection `[FS, SS]` únicamente. Como default
  general no tenía sentido (¿"todos los bloqueantes de esta tarea son
  FF"? casi nunca es lo que alguien quiere), y ahora que FF sí funciona
  de verdad, dejarlo elegible ahí era una trampa de usabilidad. FF sigue
  disponible, pero solo como override puntual en
  `insight.task.dependency.dependency_type`. Migración
  (`migrations/17.0.9.6.10/pre-migrate.py`) lleva cualquier
  `tj_dependency_type='FF'` preexistente a `'FS'` (nunca fue funcional
  de todos modos, siempre fallaba al exportar).
- **La sintaxis real de FF se encontró por exploración empírica directa
  contra el binario `tj3` corriendo en `tj3-ms`** (no contra el addon):
  se armaron ~30 archivos `.tjp` de prueba variando tipo de dependencia,
  orden de declaración, duración relativa de las tareas (corta bloquea
  larga y viceversa), anidamiento, cadenas, y combinaciones con
  `mandatory`/recursos compartidos, revisando el schedule real devuelto
  en cada caso. El plan original del backlog (hito sintético + `alap`
  explícito) resultó **innecesario**: alcanza con
  `precedes {bloqueante} { onend }` declarado en la propia tarea
  dependiente — `precedes` ya fuerza `alap` por su cuenta.
- Dos reglas duras que la exploración reveló (ninguna deducible de la
  sintaxis o la documentación en prosa del gem, que en este punto es
  ambigua/imprecisa):
  1. **Orden de declaración**: si `precedes {onend}` se declara antes que
     los `depends` FS/SS de la misma tarea, TJ3 rechaza el archivo
     ("Tasks with on-end dependencies must be ALAP scheduled") — la
     última política declarada (ASAP/ALAP) gana. El export ahora
     siempre emite todos los `depends` antes que el `precedes`,
     independientemente del orden de `depend_on_ids` en Odoo.
  2. **Como máximo una arista FF por tarea**: con dos o más
     `precedes {onend}` en la misma tarea (probado con líneas separadas
     y con lista por comas — mismo resultado en ambas), TJ3 3.8.4 solo
     respeta la primera y **ignora la segunda en silencio**, sin error
     ni warning. Detectado comparando fechas resultantes contra lo
     esperado, no por ningún mensaje de TJ3. El export ahora falla loud
     (`UserError`) si detecta más de una arista FF por tarea.
- Se confirmó que **Start→Finish (SF) no es alcanzable** con ninguna
  combinación de `depends`/`precedes`: `depends` siempre ancla el INICIO
  de la tarea declarante (nunca su fin); `precedes` siempre se origina
  desde el FIN de la tarea declarante (nunca su inicio) — entre ambos
  cubren FS/SS/FF pero estructuralmente no hay forma de expresar "mi fin
  depende del inicio de otra tarea". Queda fuera de alcance, no por
  decisión de producto sino porque el motor no lo soporta.
- Validado además: cadenas de FF (A→B→C) y FF con tareas anidadas
  (subtareas) propagan correctamente; FF mezclado con FS o con SS en la
  misma tarea funciona sin corromper ninguna de las dos restricciones
  (verificado con fechas reales, incluyendo un caso de restricción
  imposible que falla limpio en vez de agendar algo incorrecto).
  Validación end-to-end final: proyecto Odoo real → `_generate_tjp()` →
  binario real de `tj3-ms` → el schedule resultante respeta
  simultáneamente una arista FS y una FF en la misma tarea.

### Agregado

- `_tjp_task_block` (`project_project.py`): aristas FF emiten
  `precedes {path} { onend }` (siempre después de los `depends`
  FS/SS); más de una arista FF por tarea falla con `UserError` explícito.
- `project.task.tj_dependency_type`: ya no acepta `'FF'` (solo `FS`/`SS`);
  FF sigue disponible vía `insight.task.dependency.dependency_type`.
- Migración `migrations/17.0.9.6.10/pre-migrate.py`.
- Tests en `test_tjp_export.py`: FF simple, FF mezclado con FS (orden de
  salida correcto), FF mezclado con SS, dos FF en la misma tarea (falla),
  FF ya no seleccionable como default de tarea.

---

## [17.0.9.6.9] - 2026-07-11

### Prompt

> "Sabes porque realmente no avanzo en el punto Finish-Finish? Porque el
> tipo de dependencia lo tiene la tarea y no la tiene la relación entre
> tarea y tarea?" → confirmado como el bloqueante real de FF; se acordó
> resolverlo como su propio ítem de backlog, antes de FF, en vez de
> mezclarlo con el truco de `alap`.

### Discusión de diseño

- `tj_dependency_type` vivía en `project.task` (la tarea dependiente),
  aplicado por igual a **todos** sus bloqueantes (`depend_on_ids`, un
  Many2many nativo de Odoo sin atributos propios por arista). Una tarea
  real casi nunca depende de una sola cosa, así que este diseño no podía
  ni describir "FF con este bloqueante, FS con aquel otro" — el problema
  era anterior a cualquier dificultad de `alap`/hito sintético.
- Se evaluó reemplazar `depend_on_ids` por un modelo propio, pero se
  descartó: ese campo nativo alimenta el Gantt/kanban/bloqueo de Odoo
  (flechas de dependencia, estado bloqueado, etc.) — tocarlo hubiera
  significado reimplementar UI que ya funciona bien. En cambio,
  `insight.task.dependency` es un **overlay opcional**: solo declara un
  tipo para las aristas que necesitan algo distinto del default de la
  tarea; sin overrides, el comportamiento es idéntico a antes (mismo
  patrón que `extra_skill_group_ids` en `project_improve`: la mecánica
  simple sigue siendo el camino por default, el overlay es la excepción).
- Se prefirió no sincronizar automáticamente el overlay con
  `depend_on_ids` (crear/borrar filas cuando cambia la dependencia
  nativa): en vez de eso, un `@api.constrains` valida que
  `depends_on_id` ya sea un bloqueante real de la tarea al guardar. Si
  luego se quita esa dependencia de `depend_on_ids`, el override queda
  huérfano pero inofensivo (el loop de export solo itera
  `depend_on_ids`, nunca al revés) — más simple que mantener sincronía
  bidireccional para un caso de uso que va a ser minoritario.
- El domain `[('id', 'in', parent.depend_on_ids)]` en la vista (para
  limitar qué bloqueante se puede elegir) rompió la carga de la vista:
  Odoo restringe `depend_on_ids` al grupo
  `project.group_project_task_dependencies` y no permite referenciarlo
  en el domain de un campo visible para cualquier usuario. Se sacó el
  domain — la validación queda solo del lado del constraint Python.

### Agregado

- Modelo `insight.task.dependency` (`task_id`, `depends_on_id`,
  `dependency_type`), con constraint de unicidad por arista y validación
  de que `depends_on_id` sea un bloqueante real.
- `project.task.dependency_type_ids` (One2many) + método
  `_tj_dependency_type_for(dep)` que resuelve el tipo efectivo (override
  si existe, si no `tj_dependency_type`).
- `_tjp_task_block` (`project_project.py`): el chequeo/emisión de FF/SS
  ahora es por arista, no por tarea.
- Vista: lista embebida en la pestaña "Schedule" de la tarea.
- Tests: override afecta solo su arista, FF en una arista con default FS
  en la tarea sigue fallando, constraint de bloqueante inexistente.

---

## [17.0.9.6.8] - 2026-07-10

### Prompt

> "Sigamos con el backlog de TJ3" (ítem "sin `complete`") → tras
> descubrir que `complete` no afecta el scheduling, se preguntó si valía
> la pena; el usuario eligió "Sumarlo a nuestro propio taskreport/Gantt"
> → pregunta intermedia: "las tareas que terminaron [...] no se mueven
> de fechas, ¿no?" — se confirmó que sí, pero por `booking`
> (`_tjp_bookings`), no por `complete`.

### Discusión de diseño

- Se confirmó en la doc del gem `taskjuggler` (atributo `complete`,
  `TjpSyntaxRules.rb`): *"The completion percentage has no impact on the
  scheduler. It's meant for documentation purposes only."* Por eso no
  alcanza con exportarlo y ya — hace falta re-importarlo y usarlo en
  algo propio para que tenga valor real, que es lo que el usuario pidió.
- El % de avance real ya existía en Odoo sin tocar nada: `project.task.progress`
  (de `hr_timesheet`, dependencia ya declarada) calcula horas imputadas
  sobre `allocated_hours`. Se exporta ese valor tal cual, en vez de dejar
  que TJ3 use su propio cálculo naive basado en `now` (que puede
  sobre/subestimar mucho si una tarea vencida no se cerró a tiempo).
- Validado contra el binario real `tj3`: la columna del taskreport se
  llama `"Completion"` (no `"complete"`) y el valor viene como string con
  `%` (ej. `"62%"`), no un número plano — ninguna de las dos cosas era
  obvia a partir de la sintaxis del atributo de entrada.
- `complete` puede superar 100 en Odoo (`overtime`), pero TJ3 rechaza el
  atributo fuera de `[0, 100]` — se clampea al exportar.
- Aclaración de alcance: `complete` no reemplaza ni interactúa con
  `booking` — una tarea con avance 100% ya queda "congelada" en el
  pasado por tener bookings que cubren todo su esfuerzo (mecanismo
  existente, sin relación con este cambio); `complete` es puramente la
  barra visual en nuestro propio Gantt SVG.

### Agregado

- `_tjp_task_block` emite `complete <task.progress>` (clampeado a 100) en
  toda tarea, no solo las hoja.
- `_tjp_reports`: columna `complete` agregada al `taskreport` CSV.
- `insight.task.schedule.complete` (Float, nuevo) + parser
  `_parse_tj_complete` (columna `Completion`, formato `"NN%"`).
- `_render_gantt_svg`: franja de avance sobre el borde inferior de cada
  barra cuando `complete > 0`.
- Tests: emisión con progreso real / clamp por overtime / cero sin
  horas; parseo de `Completion`; columna ausente default a 0; overlay
  presente/ausente en el SVG.

---

## [17.0.9.6.7] - 2026-07-10

### Prompt

> "Sigamos con el backlog de TJ3" (ítem "sin `persistent` en `allocate`").

### Discusión de diseño

- Confirmado en el mismo código fuente del gem `taskjuggler` usado para
  el ítem anterior: `persistent` es un atributo suelto dentro del bloque
  de una entrada de `allocate` (mismo nivel que `alternative`/`select`/
  `mandatory`) — "una vez elegido un recurso de la lista de
  alternativas, se usa para toda la tarea" en vez de poder cambiar en
  cada corte donde nadie estaba disponible.
- Validado contra el binario real `tj3`: una tarea con 2 candidatos
  alternativos y `persistent` mantuvo al mismo recurso durante toda la
  tarea (sin la línea, TJ3 podría alternar entre cortes).
- Solo tiene sentido con alternativas — sin ellas no hay "lista" entre
  la cual persistir. `_tjp_allocate_entry_lines` no emite la línea si el
  pool no tiene alternativas, aunque el flag esté prendido, para no
  ensuciar el `.tjp` con un atributo sin efecto.
- Es un flag por tarea (no por escenario ni por candidato individual):
  se guarda en `project.task.tj_persistent_allocation` — cambio chico,
  sin nuevo modelo, siguiendo el mismo patrón que `tj_dependency_type`.

### Agregado

- `project.task.tj_persistent_allocation` (Boolean, `project_task.py`),
  visible en el form de Tarea junto a `tj_dependency_type`.
- `_tjp_allocate`/`_tjp_allocate_entry_lines` (`project_project.py`):
  emiten `persistent` en cada entrada del `allocate` cuando el flag está
  activo y esa entrada tiene alternativas.
- Tests en `test_tjp_export.py`: emite con alternativas + flag, no emite
  sin alternativas aunque el flag esté prendido, no emite por default.

---

## [17.0.9.6.6] - 2026-07-10

### Prompt

> "Sigamos con el backlog de TJ3" (ítem "allocate con múltiples roles
> obligatorios por tarea") → tras confirmar semántica ("roles
> simultáneos, mismo esfuerzo") y descartar el concepto de "roles" en
> favor de generalizar el matching por skills ya existente (ver
> `project_improve` [17.0.1.1.2]).

### Discusión de diseño

- Se investigó la sintaxis real de `allocate` leyendo el código fuente
  del gem `taskjuggler` 3.8.4 que corre en `tj3-ms` (mismo patrón que el
  caso FF: no asumir, confirmar contra el motor real). Hallazgo clave:
  varias entradas `allocate a, b { mandatory }` dentro de un mismo
  `allocate` agendan una franja solo cuando **todos** los mandatorios
  están disponibles a la vez, y sus horas se acumulan contra el **mismo**
  `effort` de la tarea — el usuario confirmó que ese es exactamente el
  caso de uso que quería (trabajo conjunto tipo pair programming, no
  roles con distinta carga horaria dentro de la misma tarea).
- Se validó el `.tjp` generado contra el binario real `tj3` (no solo la
  gramática): un `allocate u1 { mandatory }, u2 { mandatory }` con
  `effort 2d` programó a ambos recursos el mismo día, confirmando el
  comportamiento esperado antes de dar por buena la sintaxis de salida.
- `_tjp_allocate` ahora arma una lista de "entradas" (candidato principal
  + alternativas + `select` + `mandatory` opcional) y las combina en un
  solo `allocate`. Se verificó explícitamente que el camino sin
  `extra_skill_group_ids` (el caso común, miles de tareas existentes)
  produce carácter por carácter la misma salida que antes — cero
  `mandatory`, cero cambio de formato.
- Si una tarea tiene puestos adicionales pero su pool principal
  (`resource_pool_ids`/`user_ids`) o alguno de los puestos extra queda
  sin candidatos, se falla alto (`UserError`) en vez de agendar una
  franja que nunca podría cubrirse (mandatory con cero candidatos
  bloquearía el schedule en silencio).

### Agregado

- `_tjp_allocate`/`_tjp_allocate_entry_lines` (`project_project.py`):
  soporte para `task.extra_skill_group_ids` (ver `project_improve`
  [17.0.1.1.2]) como entradas `mandatory` adicionales del mismo
  `allocate`.
- `_tj_project_users` incluye también los candidatos de cada puesto
  adicional (necesitan su propio bloque `resource`).
- Tests en `test_tjp_export.py`: segunda entrada mandatory, sin cambio de
  formato cuando no hay puestos extra, error si el pool principal o un
  puesto extra queda sin candidatos, candidatos de puestos extra
  incluidos en `_tj_project_users`.

---

## [17.0.9.6.5] - 2026-07-10

### Prompt

> "Agregalo al backlog, y continua con el siguiente punto del backlog
> TJ3" (ítem 3: feriados globales de empresa).

### Discusión de diseño

- Hasta ahora `_tjp_hr_schedule` solo exportaba ausencias individuales
  (`hr.leave`, con `employee_id` propio). Un feriado que aplica a toda la
  compañía (ej. 25 de mayo) no tiene ningún `hr.leave` asociado — cada
  empleado lo "sufre" a través de su calendario, pero nada en el export
  actual lo capturaba.
- Odoo core ya modela esto: `resource.calendar.leaves` con
  `resource_id` vacío es una ausencia general del calendario (no de un
  recurso puntual); `resource.calendar.global_leave_ids` es el
  one2many que expone exactamente ese subconjunto
  (`domain=[('resource_id', '=', False)]`) sobre `resource.calendar`.
  No hizo falta ningún modelo ni campo nuevo, solo leer un campo que ya
  existía.
- TJ3 ya tiene el token semánticamente correcto para esto: `leaves
  holiday` (distinto de `leaves annual`, que se sigue usando para
  ausencias individuales). Se comprobó en el comentario existente del
  código (línea con la lista completa de tipos válidos de TJ3) que
  `holiday` ya estaba contemplado ahí, solo sin uso.
- Se filtran los feriados con `date_to` anterior a `ref_date` (mismo
  criterio que ya usan los `hr.leave` individuales) para no acumular
  años de feriados pasados en cada `.tjp` generado.

### Agregado

- `_tjp_global_leaves` (`project_project.py`), llamado desde
  `_tjp_hr_schedule` junto al calendario del empleado: emite `leaves
  holiday <desde> - <hasta>` por cada `resource.calendar.leaves` sin
  `resource_id` del calendario del empleado.
- Tests en `test_tjp_export.py`: feriado dentro del horizonte se emite,
  feriado anterior a `date_start` del proyecto se excluye.
- `BACKLOG.md`: se agrega el ítem "derivar `tj_daily_rate` de
  `hr.contract.wage`" (pregunta del usuario de la sesión anterior, sin
  implementar — ver discusión de costeo/dependencia nueva en el propio
  archivo).

---

## [17.0.9.6.4] - 2026-07-10

### Prompt

> "Sigamos con el backlog de TJ3" (ítem 2 del backlog priorizado por
> impacto en la calidad del cálculo: `limits`).

### Discusión de diseño

- El gap real que motiva este ítem es que un recurso compartido entre
  proyectos concurrentes aparece con 100% de disponibilidad en cada
  `.tjp` por separado (cada proyecto se planifica de forma aislada, ver
  ítem 3 de `BACKLOG.md` — "scheduling de portfolio" — que sí resolvería
  esto de raíz componiendo todos los proyectos "running" en un solo
  `.tjp`). Mientras ese ítem más grande no se ataca, `limits` es un proxy
  manual: declarar explícitamente cuántas horas por día/semana puede
  dedicarle este empleado *a este proyecto puntual*, para que TJ3 no
  asuma que tiene toda su jornada libre.
- Sintaxis TJ3 real (`resource { limits { dailymax Xh; weeklymax Yh } }`):
  es un bloque anidado dentro de la declaración de `resource`, con
  sub-atributos independientes — a diferencia de `efficiency`/`rate` que
  son líneas sueltas. Ambos sub-atributos son opcionales entre sí.
- Se siguió el patrón ya existente de `tj_base_efficiency`/`tj_daily_rate`
  en `hr.employee`: dos campos nuevos (`tj_daily_max_hours`,
  `tj_weekly_max_hours`), 0.0 = sin tope (no emite esa línea). A
  diferencia de `tj_base_efficiency` (que quedó sin vista, solo
  accesible por código), estos dos sí se agregaron al form de empleado
  junto a `tj_daily_rate` — sin esto el campo queda inerte para
  cualquier usuario que no edite datos a mano.
- Quedó fuera de alcance (para no sobre-diseñar un cap "por proyecto"
  real): esto es un tope global del empleado que se exporta igual en
  cualquier `.tjp` donde participe, no una dedicación distinta por
  proyecto. Si en el futuro hace falta variar el tope por proyecto,
  el patrón de `insight.scenario.efficiency` (override por escenario)
  es el lugar natural para extenderlo.

### Agregado

- `hr.employee.tj_daily_max_hours` / `tj_weekly_max_hours` (`hr_employee.py`).
- `_tjp_resource_limits` (`project_project.py`), llamado desde
  `_tjp_resource_block`: emite el bloque `limits { dailymax ...;
  weeklymax ... }` solo con los sub-atributos que tengan valor.
- Campos visibles en el form de empleado (`hr_employee_views.xml`).
- Tests en `test_tjp_export.py`: ambos topes juntos, solo uno, y ninguno
  (bloque omitido).

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
