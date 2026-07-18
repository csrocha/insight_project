# -*- coding: utf-8 -*-
from odoo import api, models, fields


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    tj_base_efficiency = fields.Float(
        string='Eficiencia base TJ',
        default=1.0,
        help='Multiplicador de eficiencia aplicado a este empleado en todos los '
             'planes TaskJuggler donde participe (equivalente a la línea '
             '"efficiency" de TJ3). 1.0 = sin ajuste.',
    )
    tj_daily_rate = fields.Float(
        string='Tarifa diaria TJ',
        compute='_compute_tj_daily_rate', store=True, readonly=True,
        help='Costo diario de este empleado (moneda de la compañía), equivalente '
             'a la línea "rate" de TJ3. Derivado de hr.contract.wage (salario '
             'bruto mensual) / 30 — mismo divisor que ya usa insight.cost.budget '
             'para costos extra (ver insight_scenario.py). Bruto tal cual, sin '
             'factor de carga social propio (no hay costeo de aportes '
             'patronales disponible sin hr_payroll). Sin contrato activo, 0 = '
             'no participa del cálculo de costo.',
    )

    @api.depends('contract_id.wage')
    def _compute_tj_daily_rate(self):
        for employee in self:
            employee.tj_daily_rate = (employee.contract_id.wage / 30.0) if employee.contract_id else 0.0
    tj_daily_max_hours = fields.Float(
        string='Máximo diario TJ (h)',
        default=0.0,
        help='Tope de horas por día que TJ3 puede asignarle a este empleado en '
             'los planes donde participe (equivalente a "dailymax" dentro del '
             'bloque "limits" de TJ3). Distinto del calendario laboral: sirve '
             'para reflejar que solo una parte de su jornada está disponible '
             'para este proyecto (el resto va a otros compromisos que TJ3 no '
             've). 0 = sin tope, usa toda la disponibilidad del calendario.',
    )
    tj_weekly_max_hours = fields.Float(
        string='Máximo semanal TJ (h)',
        default=0.0,
        help='Tope de horas por semana que TJ3 puede asignarle a este empleado '
             '("weeklymax" del bloque "limits" de TJ3). 0 = sin tope.',
    )
    tj_shift_ids = fields.One2many(
        'insight.employee.shift', 'employee_id',
        string='Cambios temporales de disponibilidad (TJ)',
        help='Ventanas puntuales (ej. sprint con horas extra, dedicación '
             'reducida temporal) donde este empleado usa un calendario '
             'distinto del habitual — sin tocar resource_calendar_id, solo '
             'para el .tjp exportado (equivalente al bloque "shift" de TJ3).',
    )
