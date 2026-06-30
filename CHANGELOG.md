# CHANGELOG

Formato basado en [Keep a Changelog](https://keepachangelog.com/es/1.1.0/).
Versionado: `17.0.MAYOR.MENOR.PARCHE`.

Cada entrada de version incluye el **prompt** que motivo los cambios
y las **discusiones de diseno** relevantes que influyeron en las decisiones,
para trazabilidad completa del razonamiento de agentes de IA.

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
