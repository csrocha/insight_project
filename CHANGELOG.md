# CHANGELOG

Formato basado en [Keep a Changelog](https://keepachangelog.com/es/1.1.0/).
Versionado: `17.0.MAYOR.MENOR.PARCHE`.

Cada entrada de version incluye el **prompt** que motivo los cambios
y las **discusiones de diseno** relevantes que influyeron en las decisiones,
para trazabilidad completa del razonamiento de agentes de IA.

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
