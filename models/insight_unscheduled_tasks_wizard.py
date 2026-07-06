# -*- coding: utf-8 -*-
from odoo import fields, models


class InsightUnscheduledTasksWizard(models.TransientModel):
    _name = 'insight.unscheduled.tasks.wizard'
    _description = 'Aviso de tareas que no entran en el horizonte de planificación'

    project_id = fields.Many2one('project.project', required=True)
    message = fields.Text(readonly=True)
    suggested_horizon = fields.Date(readonly=True)

    def action_extend_horizon(self):
        self.ensure_one()
        if self.suggested_horizon:
            self.project_id.tj_end_date = self.suggested_horizon
        return {'type': 'ir.actions.act_window_close'}

    def action_modify_project(self):
        return {'type': 'ir.actions.act_window_close'}
