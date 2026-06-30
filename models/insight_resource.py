# -*- coding: utf-8 -*-
from odoo import models, fields, api


class InsightResource(models.Model):
    _name = 'insight.resource'
    _description = 'Project Resource'
    _rec_name = 'partner_id'

    project_id = fields.Many2one('project.project', required=True, ondelete='cascade')
    partner_id = fields.Many2one('res.partner', required=True)
    source = fields.Selection(
        [('hr', 'Empleado RRHH'), ('manual', 'Manual')],
        compute='_compute_source', store=True,
    )
    shift_ids = fields.One2many('insight.resource.shift', 'resource_id', string='Turnos')
    vacation_ids = fields.One2many('insight.resource.vacation', 'resource_id', string='Vacaciones')
    base_efficiency = fields.Float(default=1.0)
    daily_max_hours = fields.Float()

    @api.depends('partner_id')
    def _compute_source(self):
        for rec in self:
            if not rec.partner_id:
                rec.source = 'manual'
                continue
            has_employee = bool(
                self.env['hr.employee'].search_count(
                    [('address_home_id', '=', rec.partner_id.id)]
                )
            )
            rec.source = 'hr' if has_employee else 'manual'


class InsightResourceShift(models.Model):
    _name = 'insight.resource.shift'
    _description = 'Resource Work Shift'

    resource_id = fields.Many2one('insight.resource', required=True, ondelete='cascade')
    day_of_week = fields.Selection([
        ('mon', 'Lunes'), ('tue', 'Martes'), ('wed', 'Miércoles'),
        ('thu', 'Jueves'), ('fri', 'Viernes'), ('sat', 'Sábado'), ('sun', 'Domingo'),
    ])
    hour_from = fields.Float()
    hour_to = fields.Float()


class InsightResourceVacation(models.Model):
    _name = 'insight.resource.vacation'
    _description = 'Resource Vacation Period'

    resource_id = fields.Many2one('insight.resource', required=True, ondelete='cascade')
    name = fields.Char()
    date_from = fields.Date(required=True)
    date_to = fields.Date(required=True)
