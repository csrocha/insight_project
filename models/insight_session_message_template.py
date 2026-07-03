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
    sets_blocked = fields.Boolean(
        string='Marca la tarea como bloqueada',
        help='Solo aplica a plantillas "Al salir": si está marcado, al '
             'elegir esta plantilla la tarea que se deja queda con '
             'blocked=True. No hay opción de "desbloquear" aquí porque '
             'retomar una tarea activamente ya la desbloquea.')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
