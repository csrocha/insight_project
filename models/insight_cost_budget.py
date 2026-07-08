# -*- coding: utf-8 -*-
from odoo import fields, models


class InsightCostBudget(models.Model):
    _name = 'insight.cost.budget'
    _description = 'Extra Cost Budget (infra/SaaS) per Project'

    project_id = fields.Many2one('project.project', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', required=True)
    skill_id = fields.Many2one(
        'hr.skill', required=True,
        help='Skill que identifica qué tareas usan este producto/servicio '
             '(project.task.required_skill_ids).',
    )
    individual = fields.Boolean(
        help='Si está marcado, el costo se paga por cada empleado asignado a una '
             'tarea que requiere el skill (ej. licencia nominal). Si no, es un '
             'único costo compartido durante todo el período de uso (ej. un servidor).',
    )
    periodicity = fields.Selection(
        [
            ('hourly', 'Por hora'),
            ('monthly', 'Mensual'),
            ('annual', 'Anual'),
            ('one_time', 'Único'),
        ],
        required=True, default='monthly',
    )
    amount = fields.Monetary(required=True)
    currency_id = fields.Many2one(
        'res.currency', required=True,
        default=lambda self: self.env.company.currency_id,
    )
    company_id = fields.Many2one(related='project_id.company_id', store=True)
    active = fields.Boolean(default=True)
