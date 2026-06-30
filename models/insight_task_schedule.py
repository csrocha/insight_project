# -*- coding: utf-8 -*-
from odoo import models, fields


class InsightTaskSchedule(models.Model):
    _name = 'insight.task.schedule'
    _description = 'Task Schedule Result (TJ3 output)'
    _rec_name = 'bsi'

    task_id = fields.Many2one('project.task', required=True, ondelete='cascade')
    scenario_id = fields.Many2one('insight.scenario', required=True, ondelete='cascade')
    start_scheduled = fields.Datetime()
    end_scheduled = fields.Datetime()
    effort_days = fields.Float()
    duration_days = fields.Float()
    is_critical_path = fields.Boolean()
    bsi = fields.Char()
