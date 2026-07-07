# -*- coding: utf-8 -*-
from odoo import fields, models


class ProjectMilestone(models.Model):
    _inherit = 'project.milestone'

    tj_scheduled_date = fields.Date(
        string='Fecha estimada (TJ3)', readonly=True, copy=False,
        help='Fecha en la que TaskJuggler agenda este hito según el último '
             'schedule del escenario baseline. No pisa "deadline" (la fecha '
             'objetivo, editable a mano por el usuario).',
    )
