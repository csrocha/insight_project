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
    cost = fields.Float(help='Costo TJ3 de la tarea (columna "cost" del taskreport).')
    is_critical_path = fields.Boolean()
    bsi = fields.Char()
    complete = fields.Float(
        help='Avance (0-100) tal como quedó en el .tjp exportado (columna '
             '"Completion" del taskreport) — no lo calcula TJ3, es un espejo '
             'de project.task.progress al momento del export; TJ3 no lo usa '
             'para nada del cálculo, solo se re-importa para pintarlo en el '
             'reporte de Gantt propio (ver project.project.'
             '_tj_gantt_schedule_payload / report_gantt_report.render_gantt_svg).',
    )
    resource_ids = fields.Many2many(
        'res.users', string='Recursos asignados',
        help='Recurso(s) que TJ3 realmente asignó a la tarea en este '
             'escenario tras resolver el pool de candidatos (columna '
             '"resources" del taskreport).',
    )
