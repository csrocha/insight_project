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
            # project.project.write() descarta silenciosamente un `date` sin
            # `date_start` (par tratado como rango) — hay que escribir ambos
            # a la vez si el proyecto todavía no tiene fecha de inicio.
            vals = {'date': self.suggested_horizon}
            if not self.project_id.date_start:
                vals['date_start'] = fields.Date.today()
            self.project_id.write(vals)
        return {'type': 'ir.actions.act_window_close'}

    def action_modify_project(self):
        return {'type': 'ir.actions.act_window_close'}
