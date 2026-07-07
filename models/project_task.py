# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ProjectTask(models.Model):
    _inherit = 'project.task'

    # blocked / is_critical_path viven en project_improve (genéricos, sin
    # motor de scheduling); acá solo se le agrega el cómputo de
    # is_critical_path a partir del schedule TJ3.
    is_critical_path = fields.Boolean(
        string='Camino crítico', compute='_compute_scheduled', store=True,
    )
    tj_dependency_type = fields.Selection(
        [('FS', 'Finish→Start'), ('SS', 'Start→Start'), ('FF', 'Finish→Finish')],
        string='Tipo de dependencia TJ',
        default='FS',
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
