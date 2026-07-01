# -*- coding: utf-8 -*-
from odoo import models


class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    def write(self, vals):
        res = super().write(vals)
        if vals.get('check_out'):
            sessions = self.env['insight.user.session'].sudo().search([
                ('user_id', 'in', self.employee_id.user_id.ids),
                ('state', '=', 'active'),
            ])
            for session in sessions:
                session.take_break()
        return res
