# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class InsightSessionSwitchWizard(models.TransientModel):
    _name = 'insight.session.switch.wizard'
    _description = 'Cambiar de tarea / tomar descanso (systray) con notas'

    mode = fields.Selection([
        ('switch', 'Cambiar de tarea'),
        ('break', 'Tomar descanso'),
    ], default='switch', required=True)

    current_task_id = fields.Many2one(
        'project.task', string='Tarea actual', readonly=True,
        default=lambda self: self._default_session().task_id.id,
    )
    previous_intent_note = fields.Text(
        string='Dijiste que ibas a hacer', readonly=True,
        default=lambda self: self._default_session().intent_note,
    )
    outcome_template_id = fields.Many2one(
        'insight.session.message.template', string='Plantilla de cierre',
        domain=[('direction', '=', 'leave')],
    )
    outcome_text = fields.Text(string='¿Qué se logró?')

    target_task_id = fields.Many2one('project.task', string='Tarea a iniciar')
    new_task_name = fields.Char(string='O el nombre de una tarea nueva')
    new_task_project_id = fields.Many2one(
        'project.project', string='Proyecto de la tarea nueva',
        default=lambda self: self._default_session().project_id.id,
    )
    intent_template_id = fields.Many2one(
        'insight.session.message.template', string='Plantilla de inicio',
        domain=[('direction', '=', 'enter')],
    )
    intent_text = fields.Text(string='¿Qué se va a hacer?')

    def _default_session(self):
        return self.env['insight.user.session']._get_or_create_for_user()

    @api.onchange('outcome_template_id')
    def _onchange_outcome_template_id(self):
        if self.outcome_template_id:
            self.outcome_text = self.outcome_template_id.name

    @api.onchange('intent_template_id')
    def _onchange_intent_template_id(self):
        if self.intent_template_id:
            self.intent_text = self.intent_template_id.name

    def action_confirm(self):
        self.ensure_one()
        session = self._default_session()
        outcome_note = False
        if self.current_task_id:
            outcome_note = (self.outcome_text or '').strip() or False
        outcome_blocked = self.outcome_template_id.sets_blocked or False

        if self.mode == 'break':
            session.take_break(outcome_note=outcome_note, outcome_blocked=outcome_blocked)
            return {'type': 'ir.actions.act_window_close'}

        target = self.target_task_id
        if not target:
            if not self.new_task_name:
                raise UserError(_('Elija una tarea existente o indique el nombre de una nueva.'))
            project = self.new_task_project_id or self.current_task_id.project_id
            if not project:
                raise UserError(_('Indique el proyecto de la tarea nueva.'))
            target = self.env['project.task'].create({
                'name': self.new_task_name,
                'project_id': project.id,
            })

        intent_note = (self.intent_text or '').strip() or False
        session.switch_task(
            target.id, outcome_note=outcome_note,
            outcome_blocked=outcome_blocked, intent_note=intent_note,
        )
        return {'type': 'ir.actions.act_window_close'}
