# -*- coding: utf-8 -*-
import re
from datetime import datetime, time, timedelta
from html import unescape

from odoo import _, api, fields, models

_TAG_RE = re.compile(r'<[^>]+>')
_SPACE_RE = re.compile(r'\s+')


def _html_to_text(html_value, max_len=280):
    if not html_value:
        return ''
    text = unescape(_TAG_RE.sub(' ', html_value))
    text = _SPACE_RE.sub(' ', text).strip()
    if len(text) > max_len:
        text = text[:max_len].rstrip() + '…'
    return text


class InsightUserSession(models.Model):
    _name = 'insight.user.session'
    _description = 'Active Task Session (Systray)'

    user_id = fields.Many2one(
        'res.users', required=True, default=lambda self: self.env.user, index=True,
    )
    project_id = fields.Many2one('project.project')
    task_id = fields.Many2one('project.task')
    start_datetime = fields.Datetime(default=fields.Datetime.now)
    state = fields.Selection(
        [('active', 'Trabajando'), ('break', 'Descanso')],
        default='break', required=True,
    )
    intent_note = fields.Text(
        string='Qué se va a hacer',
        help='Lo que el usuario dijo que iba a hacer en task_id al empezar '
             'este período; se combina con la nota de cierre en el parte de '
             'horas cuando se deja la tarea.',
    )

    _sql_constraints = [
        ('user_uniq', 'unique(user_id)', 'Cada usuario tiene una única sesión activa.'),
    ]

    @api.model
    def _get_or_create_for_user(self):
        session = self.search([('user_id', '=', self.env.uid)], limit=1)
        if not session:
            session = self.create({})
        return session

    @api.model
    def get_systray_state(self):
        return self._get_or_create_for_user().get_systray_data()

    @api.model
    def action_switch_task(self, task_id, outcome_note=None, outcome_kanban_state=None, intent_note=None):
        session = self._get_or_create_for_user()
        session.switch_task(
            task_id, outcome_note=outcome_note,
            outcome_kanban_state=outcome_kanban_state, intent_note=intent_note,
        )
        return session.get_systray_data()

    @api.model
    def action_take_break(self, outcome_note=None, outcome_kanban_state=None):
        session = self._get_or_create_for_user()
        session.take_break(outcome_note=outcome_note, outcome_kanban_state=outcome_kanban_state)
        return session.get_systray_data()

    def switch_task(self, task_id, outcome_note=None, outcome_kanban_state=None, intent_note=None):
        """Cierra el período activo (si existe, con su nota/estado de cierre)
        y abre uno nuevo en task_id (con la nota de intención)."""
        self.ensure_one()
        task = self.env['project.task'].browse(task_id)
        if self.user_id not in task.user_ids:
            task.write({'user_ids': [(4, self.user_id.id)]})
        self._close_active_period(outcome_note, outcome_kanban_state)
        # Retomar una tarea activamente la "desbloquea" visualmente; el
        # motivo del bloqueo queda igual en el parte de horas / chatter.
        task.kanban_state = 'normal'
        self.write({
            'project_id': task.project_id.id,
            'task_id': task.id,
            'start_datetime': fields.Datetime.now(),
            'state': 'active',
            'intent_note': intent_note or False,
        })
        self._notify_systray()

    def take_break(self, outcome_note=None, outcome_kanban_state=None):
        """Cierra el período activo (si existe) y pasa a estado Descanso."""
        self.ensure_one()
        self._close_active_period(outcome_note, outcome_kanban_state)
        self.write({
            'project_id': False,
            'task_id': False,
            'start_datetime': fields.Datetime.now(),
            'state': 'break',
            'intent_note': False,
        })
        self._notify_systray()

    def _notify_systray(self):
        """Empuja el nuevo estado por el bus para que el widget del systray
        del propio usuario se refresque sin recargar la página."""
        self.ensure_one()
        self.env['bus.bus']._sendone(
            self.user_id.partner_id, 'insight_project.session_updated', self.get_systray_data()
        )

    def _close_active_period(self, outcome_note=None, outcome_kanban_state=None):
        """Si el período actual estaba activo, aplica el estado kanban
        elegido a la tarea que se deja y registra un account.analytic.line
        combinando la intención de inicio con el resultado de cierre."""
        self.ensure_one()
        if self.state != 'active' or not self.task_id or not self.start_datetime:
            return
        if outcome_kanban_state:
            self.task_id.kanban_state = outcome_kanban_state
        employee = self.env['hr.employee'].search(
            [('user_id', '=', self.user_id.id)], limit=1
        )
        if not employee:
            return
        duration = (fields.Datetime.now() - self.start_datetime).total_seconds() / 3600.0
        if duration <= 0:
            return
        self.env['account.analytic.line'].sudo().create({
            'name': self._compose_analytic_name(outcome_note),
            'project_id': self.project_id.id,
            'task_id': self.task_id.id,
            'employee_id': employee.id,
            'unit_amount': duration,
            'date': self.start_datetime.date(),
        })

    def _compose_analytic_name(self, outcome_note):
        self.ensure_one()
        if not self.intent_note and not outcome_note:
            return self.task_id.name or _('Trabajo registrado')
        parts = []
        if self.intent_note:
            parts.append(_('Se quiso hacer: %s.') % self.intent_note)
        if outcome_note:
            parts.append(_('Se logró: %s.') % outcome_note)
        return ' '.join(parts)

    def get_systray_data(self):
        """Estado actual + tareas próximas a vencer para el widget del systray."""
        self.ensure_one()
        return {
            'state': self.state,
            'project_id': self.project_id.id,
            'project_name': self.project_id.name,
            'task_id': self.task_id.id,
            'task_name': self.task_id.name,
            'start_datetime': fields.Datetime.to_string(self.start_datetime) if self.start_datetime else False,
            'is_critical_path': bool(self.task_id.is_critical_path) if self.task_id else False,
            'task_description': _html_to_text(self.task_id.description) if self.task_id else '',
            'tasks': self._get_week_tasks(),
        }

    def _get_week_tasks(self):
        """Tareas propias vigentes esta semana (lunes → domingo); si no hay
        ninguna, las vigentes la próxima semana completa.
        Usado por el dropdown combinado (hint + lista) del systray."""
        self.ensure_one()
        today = fields.Date.context_today(self)
        this_monday = today - timedelta(days=today.weekday())
        this_sunday = this_monday + timedelta(days=6)
        tasks = self._search_week_tasks(this_monday, this_sunday)
        if not tasks:
            next_monday = this_monday + timedelta(days=7)
            next_sunday = next_monday + timedelta(days=6)
            tasks = self._search_week_tasks(next_monday, next_sunday)
        return tasks

    def _search_week_tasks(self, date_from, date_to):
        """Tareas vigentes: no terminadas y cuyo rango de ejecución
        (start_scheduled → end_scheduled) se superpone con [date_from, date_to],
        no solo las que vencen dentro de ese rango."""
        self.ensure_one()
        tasks = self.env['project.task'].search([
            ('user_ids', '=', self.user_id.id),
            ('state', 'not in', ['1_done', '1_canceled']),
            ('start_scheduled', '!=', False),
            ('end_scheduled', '!=', False),
            ('start_scheduled', '<=', datetime.combine(date_to, time.max)),
            ('end_scheduled', '>=', datetime.combine(date_from, time.min)),
        ]).sorted(key=lambda t: t.end_scheduled)
        return [{
            'id': t.id,
            'name': t.name,
            'project_id': t.project_id.id,
            'project_name': t.project_id.name,
            'is_critical_path': bool(t.is_critical_path),
            'end_scheduled': fields.Datetime.to_string(t.end_scheduled),
        } for t in tasks]
