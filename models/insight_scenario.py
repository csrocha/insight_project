# -*- coding: utf-8 -*-
from odoo import models, fields


class InsightScenario(models.Model):
    _name = 'insight.scenario'
    _description = 'Planning Scenario'
    _order = 'project_id, is_baseline desc, name'

    name = fields.Char(required=True)
    project_id = fields.Many2one('project.project', required=True, ondelete='cascade')
    is_baseline = fields.Boolean()
    efficiency_ids = fields.One2many('insight.scenario.efficiency', 'scenario_id')
    schedule_ids = fields.One2many('insight.task.schedule', 'scenario_id')

    # Agregados calculados por project.project._apply_selection_strategy() luego
    # de cada corrida del schedule — no son fields computados porque dependen de
    # una normalización conjunta entre todos los escenarios del proyecto (ver
    # scenario_selection_strategy='weighted_score'), no de este registro solo.
    total_cost = fields.Float(
        readonly=True,
        help='Suma del costo TJ3 de las tareas raíz del proyecto en este '
             'escenario (TJ3 ya acumula el costo de las subtareas en el padre).',
    )
    computed_end_date = fields.Datetime(
        readonly=True,
        help='Fin calculado del proyecto en este escenario (máximo end_scheduled).',
    )
    peak_resources = fields.Integer(
        readonly=True,
        help='Pico de recursos distintos trabajando en simultáneo en este escenario.',
    )
    selection_score = fields.Float(
        readonly=True,
        help='Score normalizado usado por la estrategia "Score ponderado" para '
             'comparar este escenario contra los demás (menor = mejor). Solo '
             'tiene sentido cuando esa estrategia está activa.',
    )


class InsightScenarioEfficiency(models.Model):
    _name = 'insight.scenario.efficiency'
    _description = 'Scenario Resource Efficiency Override'

    scenario_id = fields.Many2one('insight.scenario', required=True, ondelete='cascade')
    user_id = fields.Many2one('res.users', required=True)
    efficiency = fields.Float(default=1.0)
