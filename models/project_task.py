# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ProjectTask(models.Model):
    _inherit = 'project.task'

    is_milestone = fields.Boolean(string='Hito')
    alternative_assignee_id = fields.Many2one(
        'res.partner', string='Asignado alternativo',
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
    is_critical_path = fields.Boolean(
        string='Camino crítico', compute='_compute_scheduled', store=True,
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
