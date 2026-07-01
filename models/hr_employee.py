# -*- coding: utf-8 -*-
from odoo import models, fields


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    tj_base_efficiency = fields.Float(
        string='Eficiencia base TJ',
        default=1.0,
        help='Multiplicador de eficiencia aplicado a este empleado en todos los '
             'planes TaskJuggler donde participe (equivalente a la línea '
             '"efficiency" de TJ3). 1.0 = sin ajuste.',
    )
