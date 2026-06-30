# CHANGELOG

Formato basado en [Keep a Changelog](https://keepachangelog.com/es/1.1.0/).
Versionado: `17.0.MAYOR.MENOR.PARCHE`.

Cada entrada de version incluye el **prompt** que motivo los cambios
y las **discusiones de diseno** relevantes que influyeron en las decisiones,
para trazabilidad completa del razonamiento de agentes de IA.

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
