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


class InsightScenarioEfficiency(models.Model):
    _name = 'insight.scenario.efficiency'
    _description = 'Scenario Resource Efficiency Override'

    scenario_id = fields.Many2one('insight.scenario', required=True, ondelete='cascade')
    partner_id = fields.Many2one('res.partner', required=True)
    efficiency = fields.Float(default=1.0)
