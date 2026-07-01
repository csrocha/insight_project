# -*- coding: utf-8 -*-
from odoo import fields, models


class InsightSessionMessageTemplate(models.Model):
    _name = 'insight.session.message.template'
    _description = 'Plantilla de mensaje de inicio/cierre de tarea (systray)'
    _order = 'direction, sequence, id'

    name = fields.Char(required=True, string='Texto')
    direction = fields.Selection([
        ('enter', 'Al entrar'),
        ('leave', 'Al salir'),
    ], required=True)
    requires_detail = fields.Boolean(
        string='Requiere detalle',
        help='Si está marcado, se espera que el usuario complete el texto '
             'libre además de elegir esta plantilla (ej. "Se bloqueó la '
             'tarea porque: ___").',
    )
    kanban_state = fields.Selection([
        ('normal', 'A la vista (normal)'),
        ('done', 'Lista para el siguiente paso'),
        ('blocked', 'Bloqueada'),
    ], string='Estado resultante de la tarea',
        help='Solo aplica a plantillas "Al salir": estado kanban que se '
             'asigna a la tarea que se deja al elegir esta plantilla.')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
