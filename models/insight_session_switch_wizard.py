# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError


class WorkItemSessionSwitchWizard(models.TransientModel):
    _inherit = 'work.item.session.switch.wizard'

    new_task_name = fields.Char(string='O el nombre de una tarea nueva')
    new_task_project_id = fields.Many2one(
        'project.project', string='Proyecto de la tarea nueva',
        default=lambda self: self._default_new_task_project(),
    )

    def _default_new_task_project(self):
        ref = self._default_session().work_item_ref
        return ref.project_id.id if ref and ref._name == 'project.task' else False

    def action_confirm(self):
        if self.mode == 'switch' and not self.target_ref and self.new_task_name:
            project = self.new_task_project_id
            if not project:
                raise UserError(_('Indique el proyecto de la tarea nueva.'))
            task = self.env['project.task'].create({
                'name': self.new_task_name,
                'project_id': project.id,
            })
            self.target_ref = f'project.task,{task.id}'
        return super().action_confirm()
