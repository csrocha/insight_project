# -*- coding: utf-8 -*-
from collections import defaultdict

from odoo import api, models, fields


class InsightScenario(models.Model):
    _name = 'insight.scenario'
    _description = 'Planning Scenario'
    _order = 'project_id, is_baseline desc, name'

    name = fields.Char(required=True)
    project_id = fields.Many2one('project.project', required=True, ondelete='cascade')
    is_baseline = fields.Boolean()
    efficiency_ids = fields.One2many('insight.scenario.efficiency', 'scenario_id')
    schedule_ids = fields.One2many('insight.task.schedule', 'scenario_id')
    cost_budget_ids = fields.Many2many(
        'insight.cost.budget', string='Costos extra',
        domain="[('project_id', '=', project_id)]",
        help='Costos de infraestructura/SaaS del catálogo del proyecto que aplican '
             'a este escenario.',
    )

    # Agregados calculados por project.project._apply_selection_strategy() luego
    # de cada corrida del schedule — no son fields computados porque dependen de
    # una normalización conjunta entre todos los escenarios del proyecto (ver
    # scenario_selection_strategy='automatic'), no de este registro solo.
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

    # extra_cost/grand_total_cost sí son fields computados: a diferencia de
    # total_cost (que depende de la corrida de TJ3), dependen solo de datos ya
    # guardados en Odoo (schedule_ids, cost_budget_ids), así que pueden
    # recalcularse solos apenas el usuario cambia la selección de costos extra.
    extra_cost = fields.Float(
        compute='_compute_extra_cost', store=True, readonly=True,
        help='Suma de los costos de infraestructura/SaaS seleccionados, '
             'prorrateados según el uso real del skill asociado en este escenario.',
    )
    grand_total_cost = fields.Float(
        compute='_compute_extra_cost', store=True, readonly=True,
        help='total_cost (TJ3, mano de obra) + extra_cost (infra/SaaS).',
    )

    def _cost_budget_contributions(self):
        """Yields (insight.cost.budget, monto en moneda de la compañía) por
        cada costo seleccionado que tuvo uso real en este escenario. Se
        expone como método propio (no inline en _compute_extra_cost) para que
        otros módulos (ej. insight_project_purchase) puedan derivar sus
        propios agregados —como "cuánto de este costo ya está comprado"— sin
        duplicar la lógica de prorrateo."""
        self.ensure_one()
        company_currency = self.env.company.currency_id
        today = fields.Date.context_today(self)
        for budget in self.cost_budget_ids:
            matching = self.schedule_ids.filtered(
                lambda s: (budget.skill_ids & s.task_id.required_skill_ids)
                and s.start_scheduled and s.end_scheduled
            )
            if not matching:
                continue
            rate = budget.currency_id._convert(
                budget.amount, company_currency,
                self.project_id.company_id or self.env.company, today,
            )
            if budget.periodicity == 'one_time':
                yield budget, rate
                continue
            daily_rate = {
                'hourly': rate * 24,
                'monthly': rate / 30.0,
                'annual': rate / 365.0,
            }[budget.periodicity]
            if budget.individual:
                days_by_user = defaultdict(float)
                for sched in matching:
                    days = max(
                        (sched.end_scheduled - sched.start_scheduled).total_seconds() / 86400.0,
                        0.0,
                    )
                    skilled_users = sched.resource_ids.filtered(
                        lambda u: budget.skill_ids & u.employee_id.skill_ids
                    )
                    for user in skilled_users:
                        days_by_user[user.id] += days
                yield budget, sum(daily_rate * days for days in days_by_user.values())
            else:
                start = min(matching.mapped('start_scheduled'))
                end = max(matching.mapped('end_scheduled'))
                days = max((end - start).total_seconds() / 86400.0, 0.0)
                yield budget, daily_rate * days

    @api.depends(
        'cost_budget_ids.amount', 'cost_budget_ids.currency_id',
        'cost_budget_ids.periodicity', 'cost_budget_ids.individual',
        'cost_budget_ids.skill_ids', 'schedule_ids.task_id.required_skill_ids',
        'schedule_ids.resource_ids', 'schedule_ids.resource_ids.employee_id.skill_ids',
        'schedule_ids.start_scheduled', 'schedule_ids.end_scheduled', 'total_cost',
    )
    def _compute_extra_cost(self):
        for scenario in self:
            extra = sum(amount for _, amount in scenario._cost_budget_contributions())
            scenario.extra_cost = extra
            scenario.grand_total_cost = scenario.total_cost + extra


class InsightScenarioEfficiency(models.Model):
    _name = 'insight.scenario.efficiency'
    _description = 'Scenario Resource Efficiency Override'

    scenario_id = fields.Many2one('insight.scenario', required=True, ondelete='cascade')
    user_id = fields.Many2one('res.users', required=True)
    efficiency = fields.Float(default=1.0)
