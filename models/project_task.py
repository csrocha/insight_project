# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ProjectTask(models.Model):
    _inherit = 'project.task'

    # blocked / is_critical_path viven en project_improve (genéricos, sin
    # motor de scheduling); acá solo se le agrega el cómputo de
    # is_critical_path a partir del schedule TJ3.
    is_critical_path = fields.Boolean(
        string='Camino crítico', compute='_compute_scheduled', store=True,
    )
    tj_dependency_type = fields.Selection(
        [('FS', 'Finish→Start'), ('SS', 'Start→Start')],
        string='Tipo de dependencia TJ',
        default='FS',
        help='Default aplicado a todos los bloqueantes de depend_on_ids que '
             'no tengan su propio override en dependency_type_ids — la '
             'mayoría de las tareas tiene un solo tipo de dependencia, así '
             'que alcanza con este campo. No incluye Finish→Finish a '
             'propósito: FF es un caso puntual entre dos tareas específicas '
             '(no un "default" razonable para todos los bloqueantes de una '
             'tarea), así que solo está disponible como override en "Tipo '
             'de dependencia por bloqueante".',
    )
    dependency_type_ids = fields.One2many(
        'insight.task.dependency', 'task_id',
        string='Tipo de dependencia por bloqueante',
        help='Override de tj_dependency_type para bloqueantes puntuales — '
             'sin ningún override acá, todos los bloqueantes de '
             'depend_on_ids usan tj_dependency_type por igual. Es también '
             'el único lugar donde se puede elegir Finish→Finish.',
    )
    tj_persistent_allocation = fields.Boolean(
        string='Persistir recurso asignado (TJ)',
        help='Con más de un candidato posible (alternativas), TJ3 puede '
             'cambiar de persona entre segmentos no contiguos de la misma '
             'tarea (después de cada corte donde nadie estaba disponible). '
             'Marcar esto fuerza que, una vez elegida una persona de la '
             'lista, siga siendo esa hasta el final de la tarea '
             '(equivalente a la línea "persistent" de TJ3). Sin '
             'alternativas no tiene efecto.',
    )
    start_scheduled = fields.Datetime(
        string='Inicio planificado', compute='_compute_scheduled', store=True,
    )
    end_scheduled = fields.Datetime(
        string='Fin planificado', compute='_compute_scheduled', store=True,
    )
    bsi = fields.Char(
        string='BSI', compute='_compute_scheduled', store=True,
    )

    def _tj_dependency_type_for(self, dep):
        """Tipo de dependencia TJ3 efectivo hacia el bloqueante `dep`: el
        override puntual en dependency_type_ids si existe para esa arista,
        si no tj_dependency_type (el default de la tarea)."""
        self.ensure_one()
        override = self.dependency_type_ids.filtered(lambda d: d.depends_on_id == dep)
        return override.dependency_type if override else self.tj_dependency_type

    @api.depends('project_id.scenario_ids', 'project_id.scenario_ids.schedule_ids')
    def _compute_scheduled(self):
        for task in self:
            baseline = task.project_id.scenario_ids.filtered('is_baseline')[:1]
            if not baseline:
                task.start_scheduled = False
                task.end_scheduled = False
                task.is_critical_path = False
                task.bsi = False
                continue
            schedule = self.env['insight.task.schedule'].search([
                ('task_id', '=', task.id),
                ('scenario_id', '=', baseline.id),
            ], limit=1)
            task.start_scheduled = schedule.start_scheduled
            task.end_scheduled = schedule.end_scheduled
            task.is_critical_path = schedule.is_critical_path
            task.bsi = schedule.bsi

    @api.model
    def _cron_flag_changes_requested(self):
        """Pasa a 'Cambios solicitados' las tareas cuyo plan quedó invalidado
        por la realidad: se venció la fecha de fin planificada (end_scheduled,
        calculada por el motor CPM), o -si son camino crítico- se agotaron
        las horas asignadas. En una tarea sin holgura, agotar el presupuesto
        de horas también corre el cronograma aguas abajo; si no es crítica,
        el exceso de horas queda solo como alerta visual en el chip del
        systray, sin forzar un replanificado."""
        open_states = ('01_in_progress', '03_approved', '04_waiting_normal')
        overdue = self.search([
            ('state', 'in', open_states),
            ('end_scheduled', '!=', False),
            ('end_scheduled', '<', fields.Datetime.now()),
        ])
        over_budget = self.search([
            ('state', 'in', open_states),
            ('is_critical_path', '=', True),
            ('allocated_hours', '>', 0),
            ('remaining_hours', '<=', 0),
        ])
        (overdue | over_budget).write({'state': '02_changes_requested'})

    def action_reschedule_project(self):
        """Botón de replanificado en kanban/tree de tareas: actúa sobre el
        proyecto contenedor (el schedule TJ3 es por proyecto, no por tarea),
        no sobre las tareas seleccionadas. Se apoya en `default_project_id`
        (fijado por project.act_project_project_2_project_task_all) en vez de
        `active_model`/`active_id`: el botón de vista (MultiRecordViewButton)
        pisa `active_model` con el resModel de la propia lista ('project.task'),
        así que ese chequeo nunca es cierto acá."""
        ctx = self.env.context
        project_id = ctx.get('default_project_id')
        if not project_id and ctx.get('active_model') == 'project.project':
            project_id = ctx.get('active_id')
        project = self.env['project.project'].browse(project_id) if project_id else self.env['project.project']
        if not project.exists():
            project = self.mapped('project_id')[:1]
        if not project:
            raise UserError(_('Abra esta vista desde un proyecto para poder replanificarlo.'))
        return project.action_run_schedule()
