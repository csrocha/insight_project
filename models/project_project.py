# -*- coding: utf-8 -*-
import base64
import csv
import io
import re
from collections import defaultdict
from datetime import datetime, timedelta

import pytz

from odoo import _, fields, models
from odoo.exceptions import UserError


class UnscheduledTasksError(UserError):
    """El microservicio TJ3 respondió que algunas tareas no entran en el
    horizonte de planificación actual. Es un UserError (quien llame a
    _call_tj_microservice directamente sigue viendo un UserError normal);
    action_run_schedule además la distingue por tipo para decidir si
    mostrar el wizard interactivo o dejarla propagar tal cual."""

    def __init__(self, n_unscheduled, message):
        self.n_unscheduled = n_unscheduled
        self.message = message
        super().__init__(message)


def _tz_get(self):
    return [(x, x) for x in sorted(pytz.all_timezones)]

# Odoo resource.calendar dayofweek → TJ3 day name
_DOW_TJ = {
    '0': 'mon', '1': 'tue', '2': 'wed',
    '3': 'thu', '4': 'fri', '5': 'sat', '6': 'sun',
}


class ProjectProject(models.Model):
    _inherit = 'project.project'

    tj_timezone = fields.Selection(
        _tz_get,
        string='Zona horaria TJ',
        default='America/Argentina/Buenos_Aires',
    )
    is_tj_enabled = fields.Boolean(string='Habilitar integración TaskJuggler')
    scenario_ids = fields.One2many('insight.scenario', 'project_id', string='Escenarios')
    schedule_dirty = fields.Boolean(string='Schedule desactualizado')
    last_scheduled = fields.Datetime(string='Último schedule', readonly=True)
    tj_allocation_selection = fields.Selection(
        [
            ('minallocated', 'Menor carga asignada'),
            ('minloaded', 'Menor carga relativa'),
            ('maxloaded', 'Mayor carga relativa'),
            ('mincost', 'Menor costo'),
            ('order', 'Orden de la lista'),
            ('random', 'Aleatorio'),
        ],
        string='Criterio de selección TJ3', default='minallocated',
        help='Criterio que usa TaskJuggler (atributo "select" de un bloque '
             'allocate) para elegir un recurso entre el candidato principal '
             'y sus alternativas cuando una tarea tiene más de un candidato.',
    )

    # ── Public actions ────────────────────────────────────────────────────────

    def action_export_tjp(self):
        self.ensure_one()
        if not self.is_tj_enabled:
            raise UserError(_('La integración TaskJuggler no está habilitada para este proyecto.'))
        tjp_content = self._generate_tjp()
        safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', self.name or 'project')
        filename = f'{safe_name}.tjp'
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'datas': base64.b64encode(tjp_content.encode('utf-8')),
            'res_model': 'project.project',
            'res_id': self.id,
            'type': 'binary',
        })
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}/{filename}?download=true',
            'target': 'self',
        }

    def action_run_schedule(self, interactive=True):
        self.ensure_one()
        if not self.is_tj_enabled:
            raise UserError(_('La integración TaskJuggler no está habilitada para este proyecto.'))
        if not self.scenario_ids:
            raise UserError(_('Defina al menos un escenario antes de ejecutar el schedule.'))

        ICP = self.env['ir.config_parameter'].sudo()
        url = ICP.get_param('insight_project.tj_microservice_url')
        if not url:
            raise UserError(_('Configure la URL del microservicio TJ3 en Ajustes → TaskJuggler.'))
        try:
            timeout = int(ICP.get_param('insight_project.tj_microservice_timeout') or 120)
        except (ValueError, TypeError):
            timeout = 120

        tjp_content = self._generate_tjp()
        try:
            response_data = self._call_tj_microservice(url.rstrip('/'), tjp_content, timeout)
        except UnscheduledTasksError as exc:
            # El chatter ya tiene el mensaje (se postea siempre, sin importar
            # el modo); la ventana con los dos botones es solo para uso
            # interactivo — un llamador no interactivo (cron, RPC) recibe el
            # UserError de siempre.
            if interactive:
                return self._action_unscheduled_tasks_wizard(exc.message)
            raise UserError(exc.message) from exc

        imported = self._import_all_schedules(response_data.get('csv_files', {}))
        self.write({
            'schedule_dirty': False,
            'last_scheduled': fields.Datetime.now(),
        })
        self._check_horizon_overrun()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Schedule completado'),
                'message': _('Schedule actualizado para %d escenario(s).') % imported,
                'type': 'success',
                'sticky': False,
            },
        }

    def _check_horizon_overrun(self):
        """Avisa (sin sobreescribir self.date) cuando el horizonte de
        scheduling calculado se extiende más allá de la fecha de vencimiento
        pactada del proyecto."""
        self.ensure_one()
        start = self.date_start or fields.Date.today()
        computed_end = self._tjp_derived_horizon(start)
        if self.date and computed_end > self.date:
            msg = _(
                'El schedule calculado se extiende hasta %(computed)s, más allá '
                'de la fecha de vencimiento pactada (%(agreed)s). Requiere revisión.'
            ) % {'computed': computed_end, 'agreed': self.date}
            self.message_post(body=msg)
            self.activity_schedule(
                'mail.mail_activity_data_todo',
                date_deadline=fields.Date.today(),
                summary=_('Revisar horizonte de planificación'),
                note=msg,
                user_id=self.user_id.id or self.env.user.id,
            )

    def _action_unscheduled_tasks_wizard(self, message):
        self.ensure_one()
        suggested = self._tjp_suggest_horizon(self.date_start or fields.Date.today())
        wizard = self.env['insight.unscheduled.tasks.wizard'].create({
            'project_id': self.id,
            'message': message,
            'suggested_horizon': suggested,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('La operación requiere atención'),
            'res_model': 'insight.unscheduled.tasks.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _call_tj_microservice(self, base_url, tjp_content, timeout, include_files=None):
        import requests
        payload = {'tjp_content': tjp_content, 'timeout': timeout}
        if include_files:
            payload['include_files'] = include_files
        try:
            resp = requests.post(
                f'{base_url}/schedule',
                json=payload,
                timeout=timeout + 15,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.ConnectionError:
            raise UserError(
                _('No se pudo conectar con el microservicio TJ3 en %s.') % base_url
            )
        except requests.exceptions.Timeout:
            raise UserError(_('Timeout esperando respuesta del microservicio TJ3.'))
        except requests.exceptions.HTTPError as e:
            detail = ''
            try:
                err = e.response.json().get('detail', {})
                if isinstance(err, dict):
                    detail = err.get('stderr', '') or err.get('error', '')
            except Exception:
                pass
            unscheduled = self._TJ_UNSCHEDULED_RE.search(detail)
            if unscheduled and self.id:
                n_unscheduled = int(unscheduled.group(1))
                message = self._tj_unscheduled_message(n_unscheduled)
                self.message_post(body=message.replace('\n', '<br/>'))
                raise UnscheduledTasksError(n_unscheduled, message)
            raise UserError(_('Error del microservicio TJ3: %s\n%s') % (str(e), detail))

    _TJ_UNSCHEDULED_RE = re.compile(r'(\d+)\s+tasks? could not be scheduled')

    def _tj_unscheduled_message(self, n_unscheduled):
        self.ensure_one()
        start = self.date_start or fields.Date.today()
        current_end = self._tjp_project_end_date(start)
        message = _(
            '%(n)d tarea(s) no entran en el horizonte de planificación actual '
            '(%(start)s → %(end)s): hay más esfuerzo asignado a los recursos '
            'del que pueden cubrir en ese plazo.'
        ) % {'n': n_unscheduled, 'start': start, 'end': current_end}
        suggested = self._tjp_suggest_horizon(start)
        if suggested and suggested > current_end:
            message += '\n' + _(
                'Estimación propia (TaskJuggler no calcula este valor): '
                'extienda el campo "Horizonte de planificación" hasta al '
                'menos %(date)s, o agregue más recursos a las tareas.'
            ) % {'date': suggested}
        else:
            message += '\n' + _(
                'Extienda el campo "Horizonte de planificación" o agregue '
                'más recursos a las tareas.'
            )
        return message

    def _tjp_suggest_horizon(self, start):
        """Estimación propia (no la calcula TJ3) de hasta cuándo extender el
        horizonte para que el esfuerzo del recurso más cargado entre."""
        self.ensure_one()
        worst_days = 0.0
        for user in self._tj_project_users():
            hours = sum(
                t.allocated_hours for t in self.task_ids
                if user in t.user_ids and not t.child_ids
            )
            if not hours:
                continue
            employee = self.env['hr.employee'].sudo().search(
                [('user_id', '=', user.id)], limit=1
            )
            calendar = employee.resource_calendar_id if employee else False
            weekly_hours = 0.0
            if calendar:
                weekly_hours = sum(
                    att.hour_to - att.hour_from for att in calendar.attendance_ids
                )
            weekly_hours = weekly_hours or 40.0
            worst_days = max(worst_days, (hours / weekly_hours) * 7)
        if not worst_days:
            return None
        buffer_days = max(worst_days * 0.15, 14)
        return start + timedelta(days=int(worst_days + buffer_days))

    def action_view_gantt(self):
        self.ensure_one()
        if not self.last_scheduled:
            raise UserError(_('Ejecute el schedule primero para generar el Gantt.'))
        return {
            'type': 'ir.actions.act_url',
            'url': f'/insight_project/gantt/{self.id}',
            'target': 'new',
        }

    def action_open_import_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'insight.import.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'active_id': self.id},
        }

    # ── TJP Generator ─────────────────────────────────────────────────────────

    def _generate_tjp(self):
        self.ensure_one()
        scenarios = self.scenario_ids  # snapshot once — both header and reports must agree
        lines = []
        lines += self._tjp_project_header(scenarios)
        for user in self._tj_project_users():
            lines += self._tjp_resource_block(user)
        for scenario in scenarios:
            lines += self._tjp_scenario_supplement(scenario)
        for task in self.task_ids.filtered(
            lambda t: not t.parent_id
        ).sorted('sequence'):
            lines += self._tjp_task_block(task, depth=0)
        for milestone in self.milestone_ids:
            lines += self._tjp_milestone_block(milestone)
        lines += self._tjp_reports(scenarios)
        return '\n'.join(lines)

    def _tjp_project_header(self, scenarios=None):
        if scenarios is None:
            scenarios = self.scenario_ids
        proj_id = f'p{self.id}'
        name = (self.name or 'Project').replace('"', "'")
        start = self.date_start or fields.Date.today()
        end = self._tjp_project_end_date(start)
        tz = self.tj_timezone or 'UTC'

        lines = [
            f'project {proj_id} "{name}" {start} - {end} {{',
            f'  timezone "{tz}"',
            f'  now {start}',
        ]
        if not scenarios:
            lines.append('  scenario plan "Plan"')
        else:
            # TJ3 allows only one top-level scenario; alternates must be
            # nested inside it (children inherit the baseline) or the
            # parser only keeps the last sibling declaration.
            root, *alternates = scenarios
            root_id = self._tjp_scenario_id(root)
            root_name = (root.name or 'Scenario').replace('"', "'")
            if alternates:
                lines.append(f'  scenario {root_id} "{root_name}" {{')
                for sc in alternates:
                    sc_id = self._tjp_scenario_id(sc)
                    sc_name = (sc.name or 'Scenario').replace('"', "'")
                    lines.append(f'    scenario {sc_id} "{sc_name}"')
                lines.append('  }')
            else:
                lines.append(f'  scenario {root_id} "{root_name}"')
        lines += ['}', '']
        return lines

    def _tjp_project_end_date(self, start):
        if self.date and self.date > start:
            return self.date
        return self._tjp_derived_horizon(start)

    def _tjp_derived_horizon(self, start):
        """Horizonte estimado a partir de las tareas, ignorando self.date —
        usado tanto como fallback de _tjp_project_end_date (cuando no hay
        fecha pactada) como para detectar, en _check_horizon_overrun, si el
        trabajo real excede la fecha pactada."""
        latest = None
        for task in self.task_ids:
            # date_deadline es Datetime (nativo de project); start/date
            # son Date — hay que normalizar antes de comparar.
            deadline = task.date_deadline.date() if task.date_deadline else False
            if deadline and (latest is None or deadline > latest):
                latest = deadline
        if latest and latest > start:
            buffer = max((latest - start).days // 3, 30)
            return latest + timedelta(days=buffer)
        try:
            from dateutil.relativedelta import relativedelta
            return start + relativedelta(years=2)
        except ImportError:
            return start + timedelta(days=730)

    def _tj_project_users(self):
        """res.users deduplicado a partir del pool de candidatos efectivo de
        cada tarea del proyecto (resource_pool_ids si está definido, si no
        user_ids). Cualquier candidato potencial de una tarea necesita su
        propio bloque `resource`, no solo quien termine asignado."""
        self.ensure_one()
        users = self.env['res.users']
        for task in self.task_ids:
            users |= task.resource_pool_ids or task.user_ids
        return users

    def _tjp_resource_block(self, user):
        res_id = self._tjp_resource_id(user.partner_id.id)
        res_name = (user.partner_id.name or user.name or 'Resource').replace('"', "'")
        employee = self.env['hr.employee'].sudo().search(
            [('user_id', '=', user.id)], limit=1
        )

        lines = [f'resource {res_id} "{res_name}" {{']

        if employee and employee.tj_base_efficiency and employee.tj_base_efficiency != 1.0:
            lines.append(f'  efficiency {employee.tj_base_efficiency:.2f}')

        lines += self._tjp_hr_schedule(employee)

        lines += ['}', '']
        return lines

    def _tjp_hr_schedule(self, employee):
        lines = []
        if not employee:
            return lines

        calendar = employee.resource_calendar_id
        if calendar:
            lines += self._tjp_calendar_hours(calendar)

        ref_date = self.date_start or fields.Date.today()
        leaves = self.env['hr.leave'].search([
            ('employee_id', '=', employee.id),
            ('state', '=', 'validate'),
            ('date_to', '>=', str(ref_date)),
        ], order='date_from')
        for leave in leaves:
            d_from = leave.date_from.date()
            d_to = leave.date_to.date()
            # TJ3 solo acepta estos tipos de leaves: annual, special, sick,
            # unpaid, holiday, unemployed. 'vacation' no es un token válido
            # de la sintaxis — 'annual' es el equivalente correcto.
            lines.append(f'  leaves annual {d_from} - {d_to}')

        return lines

    def _tjp_calendar_hours(self, calendar):
        day_slots = defaultdict(list)
        for att in calendar.attendance_ids:
            day_slots[att.dayofweek].append((att.hour_from, att.hour_to))

        lines = []
        for dow_str, tj_day in _DOW_TJ.items():
            if dow_str in day_slots:
                for h_from, h_to in sorted(day_slots[dow_str]):
                    lines.append(
                        f'  workinghours {tj_day}'
                        f' {self._float_to_hhmm(h_from)}'
                        f' - {self._float_to_hhmm(h_to)}'
                    )
            else:
                lines.append(f'  workinghours {tj_day} off')
        return lines

    def _tjp_scenario_supplement(self, scenario):
        """supplement resource blocks para eficiencias por escenario."""
        lines = []
        sc_id = self._tjp_scenario_id(scenario)
        for eff in scenario.efficiency_ids:
            res_id = self._tjp_resource_id(eff.partner_id.id)
            lines += [
                f'supplement resource {res_id} {{',
                f'  {sc_id}:efficiency {eff.efficiency:.2f}',
                '}',
                '',
            ]
        return lines

    def _tjp_task_block(self, task, depth=0):
        t_id = self._tjp_task_id(task)
        t_name = (task.name or 'Task').replace('"', "'")
        ind = '  ' * depth

        lines = [f'{ind}task {t_id} "{t_name}" {{']

        child_tasks = task.child_ids.filtered(
            lambda t: t.project_id == self
        ).sorted('sequence')

        if not child_tasks:
            # Leaf task: emit effort/duration and allocations
            if task.allocated_hours:
                allocate_lines = self._tjp_allocate(task)
                if allocate_lines:
                    effort_d = task.allocated_hours / 8.0
                    if effort_d < 0.125:
                        lines.append(f'{ind}  effort {task.allocated_hours:.2f}h')
                    else:
                        lines.append(f'{ind}  effort {effort_d:.2f}d')
                    for al in allocate_lines:
                        lines.append(f'{ind}  {al}')
                else:
                    # No resource assigned → use duration (TJ3 needs resource for effort)
                    duration_d = task.allocated_hours / 8.0
                    lines.append(f'{ind}  duration {duration_d:.2f}d')

        # Dependencies (FS only in v1; TJ3 default dependency type)
        for dep in task.depend_on_ids:
            if dep.project_id == self:
                dep_path = self._tjp_task_abs_path(dep)
                lines.append(f'{ind}  depends {dep_path}')

        # Subtasks (recursive)
        for child in child_tasks:
            lines += self._tjp_task_block(child, depth=depth + 1)

        lines.append(f'{ind}}}')
        lines.append('')
        return lines

    def _tjp_milestone_block(self, milestone):
        """Un project.milestone se exporta como su propia tarea TJP
        sintética de 0 esfuerzo (`milestone`), separada de las tareas
        reales, que depende de todas las tareas de este proyecto enlazadas
        a él (milestone.task_ids). Se omite si no tiene ninguna tarea
        enlazada en este proyecto: no hay contra qué anclarla en el
        schedule."""
        dep_tasks = milestone.task_ids.filtered(lambda t: t.project_id == self)
        if not dep_tasks:
            return []
        m_id = self._tjp_milestone_id(milestone)
        m_name = (milestone.name or 'Milestone').replace('"', "'")
        lines = [
            f'task {m_id} "{m_name}" {{',
            '  milestone',
        ]
        for dep in dep_tasks:
            lines.append(f'  depends {self._tjp_task_abs_path(dep)}')
        lines += ['}', '']
        return lines

    def _tjp_allocate(self, task):
        """Emite el pool de candidatos de la tarea (resource_pool_ids si está
        definido, si no user_ids) como un bloque `allocate primary { alternative
        ...; select ... }`, para que TJ3 elija a una sola persona del pool en
        vez de asignarlas todas en simultáneo."""
        pool = task.resource_pool_ids or task.user_ids
        if not pool:
            return []
        ids = [self._tjp_resource_id(u.partner_id.id) for u in pool]
        primary, *alternatives = ids
        if not alternatives:
            return [f'allocate {primary}']
        selection = task.project_id.tj_allocation_selection or 'minallocated'
        return [
            f'allocate {primary} {{',
            f'  alternative {", ".join(alternatives)}',
            f'  select {selection}',
            '}',
        ]

    def _tjp_reports(self, scenarios=None):
        """One taskreport per scenario so each CSV file maps to exactly one scenario."""
        if scenarios is None:
            scenarios = self.scenario_ids
        if not scenarios:
            return [
                'taskreport "schedule_plan" {',
                '  formats csv',
                '  columns id, bsi, name, start, end, effort, duration, resources, criticalness',
                '  scenarios plan',
                '}',
                '',
            ]
        lines = []
        for sc in scenarios:
            sc_id = self._tjp_scenario_id(sc)
            lines += [
                f'taskreport "schedule_{sc_id}" {{',
                '  formats csv',
                '  columns id, bsi, name, start, end, effort, duration, resources, criticalness',
                f'  scenarios {sc_id}',
                '}',
                '',
            ]
        return lines

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _tjp_resource_id(self, partner_id):
        user = self.env['res.users'].sudo().search(
            [('partner_id', '=', partner_id)], limit=1
        )
        if not user:
            partner = self.env['res.partner'].browse(partner_id)
            raise UserError(_(
                'No se encontró un usuario Odoo para el contacto "%s" (id %s). '
                'Todo recurso TJ3 debe corresponder a un usuario existente.'
            ) % (partner.name or '?', partner_id))
        return f'u{user.id}'

    @staticmethod
    def _tjp_task_id(task):
        return f't{task.id}'

    @staticmethod
    def _tjp_milestone_id(milestone):
        return f'm{milestone.id}'

    @staticmethod
    def _tjp_task_abs_path(task):
        """Absolute TJ3 path for a task: !t1.t5.t42 (from project scope)."""
        parts = []
        t = task
        project_id = task.project_id.id
        while t and t.project_id.id == project_id:
            parts.append(f't{t.id}')
            t = t.parent_id
        return '!' + '.'.join(reversed(parts))

    @staticmethod
    def _tjp_scenario_id(scenario):
        raw = re.sub(r'[^a-zA-Z0-9_]', '_', scenario.name or 'scenario')
        raw = re.sub(r'_+', '_', raw).strip('_') or 'scenario'
        if raw[0].isdigit():
            raw = 'sc_' + raw
        return raw.lower()[:24]

    @staticmethod
    def _float_to_hhmm(hours):
        h = int(hours)
        m = int(round((hours - h) * 60))
        return f'{h}:{m:02d}'

    # ── Schedule import ───────────────────────────────────────────────────────

    def _import_all_schedules(self, csv_files):
        """Dispatch each CSV file to its matching scenario; return count imported."""
        sc_map = {self._tjp_scenario_id(sc): sc for sc in self.scenario_ids}
        imported = 0
        for filename, csv_content in csv_files.items():
            base = filename.rsplit('.', 1)[0]
            sc_key = base[len('schedule_'):] if base.startswith('schedule_') else base
            scenario = sc_map.get(sc_key)
            if not scenario:
                continue
            self._import_scenario_csv(csv_content, scenario)
            imported += 1
        self._sync_gantt_dates()
        return imported

    def _sync_gantt_dates(self):
        """Push the baseline scenario's schedule into the standard Gantt
        fields — insight.task.schedule alone isn't read by any Gantt view.
        date_deadline is a base `project` field; planned_date_begin only
        exists when `project_enterprise` is installed (not a dependency of
        this module), so it's only written when present."""
        self.ensure_one()
        baseline = self.scenario_ids.filtered('is_baseline')[:1]
        if not baseline:
            return
        schedules = self.env['insight.task.schedule'].search([
            ('scenario_id', '=', baseline.id),
            ('task_id.project_id', '=', self.id),
        ])
        has_planned_date_begin = 'planned_date_begin' in self.env['project.task']._fields
        for schedule in schedules:
            vals = {'date_deadline': schedule.end_scheduled}
            if has_planned_date_begin:
                vals['planned_date_begin'] = schedule.start_scheduled
            if schedule.resource_ids:
                vals['user_ids'] = [(6, 0, schedule.resource_ids.ids)]
            schedule.task_id.write(vals)

    def _import_scenario_csv(self, csv_content, scenario):
        """Parse a TJ3 CSV report and upsert insight.task.schedule records."""
        Schedule = self.env['insight.task.schedule']
        Schedule.search([
            ('scenario_id', '=', scenario.id),
            ('task_id.project_id', '=', self.id),
        ]).unlink()

        tz_name = self.tj_timezone or 'UTC'
        valid_task_ids = set(
            self.env['project.task'].search([('project_id', '=', self.id)]).ids
        )
        valid_milestone_ids = set(self.milestone_ids.ids)

        vals_list = []
        milestone_dates = {}
        first_line = csv_content.split('\n')[0] if csv_content else ''
        delimiter = ';' if ';' in first_line else ','
        reader = csv.DictReader(io.StringIO(csv_content), delimiter=delimiter)
        for row in reader:
            norm = {k.strip().lower(): (v or '').strip() for k, v in row.items() if k is not None}
            tj_id = norm.get('id', '')
            task_odoo_id = self._parse_task_id_from_tj_id(tj_id)
            if task_odoo_id and task_odoo_id in valid_task_ids:
                vals_list.append({
                    'task_id': task_odoo_id,
                    'scenario_id': scenario.id,
                    'start_scheduled': self._parse_tj_datetime(norm.get('start', ''), tz_name),
                    'end_scheduled': self._parse_tj_datetime(norm.get('end', ''), tz_name),
                    'effort_days': self._parse_tj_duration(norm.get('effort', '')),
                    'duration_days': self._parse_tj_duration(norm.get('duration', '')),
                    'is_critical_path': self._parse_tj_criticalness(norm.get('criticalness', '')),
                    'bsi': norm.get('bsi', ''),
                    'resource_ids': [(6, 0, self._parse_tj_resource_ids(norm.get('resources', '')))],
                })
                continue
            milestone_odoo_id = self._parse_milestone_id_from_tj_id(tj_id)
            if scenario.is_baseline and milestone_odoo_id and milestone_odoo_id in valid_milestone_ids:
                end = self._parse_tj_datetime(norm.get('end', ''), tz_name)
                milestone_dates[milestone_odoo_id] = end.date() if end else False
        if vals_list:
            Schedule.create(vals_list)
        for milestone_id, scheduled_date in milestone_dates.items():
            self.env['project.milestone'].browse(milestone_id).tj_scheduled_date = scheduled_date

    @staticmethod
    def _parse_task_id_from_tj_id(tj_id):
        """Extract Odoo task ID from TJ3 path (e.g. 't42.t99' → 99)."""
        if not tj_id:
            return None
        try:
            return int(tj_id.strip().split('.')[-1].lstrip('t'))
        except (ValueError, IndexError):
            return None

    @staticmethod
    def _parse_milestone_id_from_tj_id(tj_id):
        """Extract Odoo project.milestone ID from a synthetic TJ3 milestone
        task id (e.g. 'm42' → 42). Milestones are always root-level, never
        nested under a real task."""
        if not tj_id:
            return None
        match = re.fullmatch(r'm(\d+)', tj_id.strip())
        return int(match.group(1)) if match else None

    @staticmethod
    def _parse_tj_datetime(value, tz_name='UTC'):
        """Parse TJ3 date/datetime and return a UTC-naive datetime for Odoo storage."""
        if not value:
            return False
        import pytz
        for fmt in ('%Y-%m-%d %H:%M', '%Y-%m-%d'):
            try:
                naive = datetime.strptime(value.strip(), fmt)
                break
            except ValueError:
                continue
        else:
            return False
        try:
            local_tz = pytz.timezone(tz_name)
            return local_tz.localize(naive).astimezone(pytz.UTC).replace(tzinfo=None)
        except Exception:
            return naive

    @staticmethod
    def _parse_tj_duration(value):
        """Convert TJ3 duration string to float days (e.g. '5.0d'→5.0, '40h'→5.0)."""
        if not value:
            return 0.0
        v = value.strip()
        try:
            if v.endswith('d'):
                return float(v[:-1])
            if v.endswith('h'):
                return float(v[:-1]) / 8.0
            if v.endswith('w'):
                return float(v[:-1]) * 5.0
            return float(v)
        except (ValueError, AttributeError):
            return 0.0

    @staticmethod
    def _parse_tj_criticalness(value):
        """Return True when TJ3 criticalness > 0 (task is on the critical path)."""
        try:
            return float(value or '0') > 0.0
        except (ValueError, TypeError):
            return False

    @staticmethod
    def _parse_tj_resource_ids(value):
        """Parse the taskreport 'resources' column (e.g. 'u12, u34') into
        Odoo res.users ids — the inverse of _tjp_resource_id's 'u{user.id}'."""
        if not value:
            return []
        ids = []
        for token in value.split(','):
            token = token.strip()
            if token.startswith('u'):
                token = token[1:]
            try:
                ids.append(int(token))
            except ValueError:
                continue
        return ids

    # ── Gantt SVG renderer ────────────────────────────────────────────────────

    def _render_gantt_svg(self):
        """Generate a plain SVG Gantt from insight.task.schedule records."""
        import calendar

        def _esc(s):
            return (str(s)
                    .replace('&', '&amp;')
                    .replace('<', '&lt;')
                    .replace('>', '&gt;')
                    .replace('"', '&quot;'))

        def _bsi_key(bsi):
            return [int(p) if p.isdigit() else p for p in (bsi or '0').split('.')]

        schedules = self.env['insight.task.schedule'].search(
            [('task_id.project_id', '=', self.id)],
        ).filtered(lambda s: s.start_scheduled and s.end_scheduled)

        if not schedules:
            return (
                '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="90"'
                ' font-family="Arial, sans-serif">'
                '<rect width="640" height="90" fill="#fafafa"/>'
                '<text x="32" y="50" font-size="13" fill="#757575">'
                'No hay datos de schedule. Ejecute "Ejecutar Schedule" primero.</text>'
                '</svg>'
            )

        # Collect scenarios preserving first-seen order
        seen_sc = {}
        for s in schedules:
            seen_sc.setdefault(s.scenario_id.id, s.scenario_id)
        scenarios = list(seen_sc.values())

        BAR_NORMAL   = ['#43A047', '#1E88E5', '#FB8C00', '#8E24AA', '#00ACC1']
        BAR_CRITICAL = ['#C62828', '#1565C0', '#E65100', '#6A1B9A', '#00695C']
        sc_color = {
            sc.id: (BAR_NORMAL[i % 5], BAR_CRITICAL[i % 5])
            for i, sc in enumerate(scenarios)
        }

        min_dt = min(s.start_scheduled for s in schedules)
        max_dt = max(s.end_scheduled   for s in schedules)
        span_secs = max((max_dt - min_dt).total_seconds(), 86400.0)

        # Group by BSI in sorted order
        groups = {}
        for s in schedules:
            groups.setdefault(s.bsi or '?', []).append(s)
        ordered_bsis = sorted(groups.keys(), key=_bsi_key)

        # Layout
        LW, RW = 340, 1060
        TW = LW + RW
        RH = 26
        HDR, LEG, AXIS = 56, 24, 24
        TOP = HDR + LEG + AXIS

        n_rows = sum(len(v) for v in groups.values())
        TH = TOP + n_rows * RH + 16

        def xp(dt):
            return LW + (dt - min_dt).total_seconds() / span_secs * RW

        o = []
        o.append(
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{TW}" height="{TH}"'
            f' font-family="Arial, Helvetica, sans-serif" font-size="11">'
        )
        o.append(f'<rect width="{TW}" height="{TH}" fill="#ffffff"/>')

        # Title + subtitle
        o.append(
            f'<text x="10" y="22" font-size="15" font-weight="bold" fill="#212121">'
            f'{_esc(self.name or "Proyecto")}</text>'
        )
        if self.last_scheduled:
            o.append(
                f'<text x="10" y="40" font-size="10" fill="#9E9E9E">'
                f'Último schedule: {self.last_scheduled.strftime("%Y-%m-%d %H:%M")} UTC</text>'
            )

        # Scenario legend
        xl, yl = 10, HDR + 16
        for sc in scenarios:
            cn, _ = sc_color[sc.id]
            o.append(f'<rect x="{xl}" y="{yl-11}" width="13" height="13" fill="{cn}" rx="2"/>')
            o.append(f'<text x="{xl+17}" y="{yl}" fill="#424242">{_esc(sc.name)}</text>')
            xl += 20 + len(sc.name) * 7
        o.append(
            f'<text x="{xl+6}" y="{yl}" fill="#C62828" font-weight="bold">⚡ camino crítico</text>'
        )

        # Left / right divider
        o.append(
            f'<line x1="{LW}" y1="{HDR}" x2="{LW}" y2="{TH}"'
            f' stroke="#BDBDBD" stroke-width="1"/>'
        )

        # Month grid lines + labels
        ms = datetime(min_dt.year, min_dt.month, 1)
        while ms <= max_dt:
            if ms >= min_dt:
                mx = xp(ms)
                o.append(
                    f'<line x1="{mx:.1f}" y1="{TOP}" x2="{mx:.1f}" y2="{TH}"'
                    f' stroke="#F0F0F0" stroke-width="1"/>'
                )
                o.append(
                    f'<text x="{mx+3:.1f}" y="{HDR+LEG+17}"'
                    f' fill="#9E9E9E" font-size="10">'
                    f'{calendar.month_abbr[ms.month]} {ms.year}</text>'
                )
            ms = datetime(ms.year + (ms.month == 12), ms.month % 12 + 1, 1)

        # "Today" marker (UTC)
        now_utc = datetime.utcnow()
        if min_dt <= now_utc <= max_dt:
            nx = xp(now_utc)
            o.append(
                f'<line x1="{nx:.1f}" y1="{TOP}" x2="{nx:.1f}" y2="{TH}"'
                f' stroke="#E53935" stroke-width="1.5"'
                f' stroke-dasharray="5,3" opacity="0.7"/>'
            )
            o.append(
                f'<text x="{nx+2:.1f}" y="{HDR+LEG+17}"'
                f' fill="#E53935" font-size="9" font-weight="bold">Hoy</text>'
            )

        # Task rows
        yc = TOP
        for bsi in ordered_bsis:
            rows = groups[bsi]
            task = rows[0].task_id
            indent = bsi.count('.') * 12

            for ridx, sched in enumerate(rows):
                bg = '#FAFAFA' if (yc // RH) % 2 == 0 else '#FFFFFF'
                o.append(f'<rect x="0" y="{yc}" width="{TW}" height="{RH}" fill="{bg}"/>')

                if ridx == 0:
                    weight = 'bold' if not task.parent_id else 'normal'
                    label = _esc((task.name or '')[:44])
                    o.append(
                        f'<text x="{8+indent}" y="{yc+17}" fill="#424242">'
                        f'<tspan font-size="10" fill="#9E9E9E">{_esc(bsi)} </tspan>'
                        f'<tspan font-weight="{weight}">{label}</tspan></text>'
                    )

                x1 = xp(sched.start_scheduled)
                x2 = xp(sched.end_scheduled)
                bw = max(x2 - x1, 4.0)
                cn, cc = sc_color[sched.scenario_id.id]
                fill = cc if sched.is_critical_path else cn
                stroke = ' stroke="#b71c1c" stroke-width="1.5"' if sched.is_critical_path else ''
                o.append(
                    f'<rect x="{x1:.1f}" y="{yc+5}" width="{bw:.1f}" height="{RH-10}"'
                    f' fill="{fill}" rx="3" opacity="0.88"{stroke}/>'
                )
                if sched.is_critical_path:
                    o.append(
                        f'<text x="{x1+bw+2:.1f}" y="{yc+15}" font-size="10">⚡</text>'
                    )
                if len(scenarios) > 1 and bw > 50:
                    o.append(
                        f'<text x="{x1+4:.1f}" y="{yc+15}"'
                        f' fill="white" font-size="9" font-weight="bold">'
                        f'{_esc(sched.scenario_id.name[:9])}</text>'
                    )

                yc += RH

        o.append('</svg>')
        return '\n'.join(o)
