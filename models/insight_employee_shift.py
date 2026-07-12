# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class InsightEmployeeShift(models.Model):
    _name = 'insight.employee.shift'
    _description = 'Cambio temporal de disponibilidad TJ3 (shift)'
    _order = 'date_from'

    employee_id = fields.Many2one(
        'hr.employee', string='Empleado', required=True, ondelete='cascade', index=True,
    )
    name = fields.Char(
        string='Motivo',
        help='Ej. "Sprint crunch Q3", "Dedicación reducida julio" — solo '
             'para referencia, no se exporta a TJ3.',
    )
    date_from = fields.Date(string='Desde', required=True)
    date_to = fields.Date(string='Hasta', required=True)
    calendar_id = fields.Many2one(
        'resource.calendar', string='Calendario alternativo', required=True,
        help='Calendario a usar en TJ3 durante esta ventana en vez del '
             'calendario habitual del empleado (resource_calendar_id) — no '
             'lo modifica en Odoo, es un override que solo aplica al .tjp '
             'exportado (equivalente al bloque `shift` de TJ3).',
    )

    @api.constrains('date_from', 'date_to')
    def _check_date_range(self):
        for shift in self:
            if shift.date_from > shift.date_to:
                raise ValidationError(_('"Desde" no puede ser posterior a "Hasta".'))

    @api.constrains('employee_id', 'date_from', 'date_to')
    def _check_no_overlap(self):
        """TJ3 no acepta ventanas de `shift` superpuestas para el mismo
        recurso — se valida acá para fallar con un mensaje claro en vez de
        que el microservicio lo rechace con un error críptico."""
        for shift in self:
            overlapping = self.search([
                ('id', '!=', shift.id),
                ('employee_id', '=', shift.employee_id.id),
                ('date_from', '<=', shift.date_to),
                ('date_to', '>=', shift.date_from),
            ])
            if overlapping:
                raise ValidationError(_(
                    'Ya existe otro cambio temporal de disponibilidad para '
                    '%(employee)s que se superpone con este rango (%(other)s '
                    '- %(other_to)s).'
                ) % {
                    'employee': shift.employee_id.name,
                    'other': overlapping[0].date_from,
                    'other_to': overlapping[0].date_to,
                })
