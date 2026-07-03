# CHANGELOG

Formato basado en [Keep a Changelog](https://keepachangelog.com/es/1.1.0/).
Versionado: `17.0.MAYOR.MENOR.PARCHE`.

Cada entrada de version incluye el **prompt** que motivo los cambios
y las **discusiones de diseno** relevantes que influyeron en las decisiones,
para trazabilidad completa del razonamiento de agentes de IA.

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
