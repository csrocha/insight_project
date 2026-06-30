# -*- coding: utf-8 -*-
import base64
import csv
import io
import re
from collections import defaultdict
from datetime import datetime, timedelta

from odoo import _, fields, models
from odoo.exceptions import UserError

# Odoo resource.calendar dayofweek → TJ3 day name
_DOW_TJ = {
    '0': 'mon', '1': 'tue', '2': 'wed',
    '3': 'thu', '4': 'fri', '5': 'sat', '6': 'sun',
}
_DOW_ORDER = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']


class ProjectProject(models.Model):
    _inherit = 'project.project'

    tj_now = fields.Date(string='Fecha base del plan')
    tj_timezone = fields.Char(
        string='Zona horaria TJ',
        default='America/Argentina/Buenos_Aires',
    )
    is_tj_enabled = fields.Boolean(string='Habilitar integración TaskJuggler')
    scenario_ids = fields.One2many('insight.scenario', 'project_id', string='Escenarios')
    resource_ids = fields.One2many('insight.resource', 'project_id', string='Recursos')
    schedule_dirty = fields.Boolean(string='Schedule desactualizado')
    last_scheduled = fields.Datetime(string='Último schedule', readonly=True)

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

    def action_run_schedule(self):
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
        response_data = self._call_tj_microservice(url.rstrip('/'), tjp_content, timeout)

        imported = self._import_all_schedules(response_data.get('csv_files', {}))
        self.write({
            'schedule_dirty': False,
            'last_scheduled': fields.Datetime.now(),
        })
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

    def _call_tj_microservice(self, base_url, tjp_content, timeout):
        import requests
        try:
            resp = requests.post(
                f'{base_url}/schedule',
                json={'tjp_content': tjp_content, 'timeout': timeout},
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
            raise UserError(_('Error del microservicio TJ3: %s\n%s') % (str(e), detail))

    # ── TJP Generator ─────────────────────────────────────────────────────────

    def _generate_tjp(self):
        self.ensure_one()
        lines = []
        lines += self._tjp_project_header()
        for res in self.resource_ids:
            lines += self._tjp_resource_block(res)
        for scenario in self.scenario_ids:
            lines += self._tjp_scenario_supplement(scenario)
        for task in self.task_ids.filtered(
            lambda t: not t.parent_id
        ).sorted('sequence'):
            lines += self._tjp_task_block(task, depth=0)
        lines += self._tjp_reports()
        return '\n'.join(lines)

    def _tjp_project_header(self):
        proj_id = f'p{self.id}'
        name = (self.name or 'Project').replace('"', "'")
        start = self.tj_now or fields.Date.today()
        end = self._tjp_project_end_date(start)
        tz = (self.tj_timezone or 'UTC').replace('_', ' ')

        lines = [
            f'project {proj_id} "{name}" {start} - {end} {{',
            f'  timezone "{tz}"',
            f'  now {start}',
        ]
        if not self.scenario_ids:
            lines.append('  scenario plan "Plan"')
        else:
            for sc in self.scenario_ids:
                sc_id = self._tjp_scenario_id(sc)
                sc_name = (sc.name or 'Scenario').replace('"', "'")
                lines.append(f'  scenario {sc_id} "{sc_name}"')
        lines += ['}', '']
        return lines

    def _tjp_project_end_date(self, start):
        latest = None
        for task in self.task_ids:
            if task.date_deadline and (latest is None or task.date_deadline > latest):
                latest = task.date_deadline
        if latest and latest > start:
            buffer = max((latest - start).days // 3, 30)
            return latest + timedelta(days=buffer)
        try:
            from dateutil.relativedelta import relativedelta
            return start + relativedelta(years=2)
        except ImportError:
            return start + timedelta(days=730)

    def _tjp_resource_block(self, res):
        res_id = self._tjp_resource_id(res.partner_id.id)
        res_name = (res.partner_id.name or 'Resource').replace('"', "'")

        lines = [f'resource {res_id} "{res_name}" {{']

        if res.base_efficiency and res.base_efficiency != 1.0:
            lines.append(f'  efficiency {res.base_efficiency:.2f}')

        if res.daily_max_hours:
            lines.append(f'  limits {{ dailymax {res.daily_max_hours:.1f}h }}')

        if res.source == 'hr':
            lines += self._tjp_hr_schedule(res)
        else:
            lines += self._tjp_manual_schedule(res)

        lines += ['}', '']
        return lines

    def _tjp_hr_schedule(self, res):
        lines = []
        employee = self.env['hr.employee'].search(
            [('address_home_id', '=', res.partner_id.id)], limit=1
        )
        if not employee:
            return lines

        calendar = employee.resource_calendar_id
        if calendar:
            lines += self._tjp_calendar_hours(calendar)

        ref_date = self.tj_now or fields.Date.today()
        leaves = self.env['hr.leave'].search([
            ('employee_id', '=', employee.id),
            ('state', '=', 'validate'),
            ('date_to', '>=', str(ref_date)),
        ], order='date_from')
        for leave in leaves:
            d_from = leave.date_from.date()
            d_to = leave.date_to.date()
            lines.append(f'  leaves vacation {d_from} - {d_to}')

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

    def _tjp_manual_schedule(self, res):
        lines = []
        if res.shift_ids:
            day_shifts = defaultdict(list)
            for shift in res.shift_ids:
                day_shifts[shift.day_of_week].append((shift.hour_from, shift.hour_to))
            for dow in _DOW_ORDER:
                if dow in day_shifts:
                    for h_from, h_to in sorted(day_shifts[dow]):
                        lines.append(
                            f'  workinghours {dow}'
                            f' {self._float_to_hhmm(h_from)}'
                            f' - {self._float_to_hhmm(h_to)}'
                        )
                else:
                    lines.append(f'  workinghours {dow} off')
        else:
            # Default Mon–Fri 9–17 when no shifts are defined
            for dow in ['mon', 'tue', 'wed', 'thu', 'fri']:
                lines.append(f'  workinghours {dow} 9:00 - 17:00')
            for dow in ['sat', 'sun']:
                lines.append(f'  workinghours {dow} off')

        for vacation in res.vacation_ids:
            lines.append(f'  leaves vacation {vacation.date_from} - {vacation.date_to}')

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

        if task.is_milestone:
            lines.append(f'{ind}  milestone')
        elif not child_tasks:
            # Leaf task: emit effort/duration and allocations
            if task.planned_hours:
                allocate_lines = self._tjp_allocate(task)
                if allocate_lines:
                    effort_d = task.planned_hours / 8.0
                    if effort_d < 0.125:
                        lines.append(f'{ind}  effort {task.planned_hours:.2f}h')
                    else:
                        lines.append(f'{ind}  effort {effort_d:.2f}d')
                    for al in allocate_lines:
                        lines.append(f'{ind}  {al}')
                else:
                    # No resource assigned → use duration (TJ3 needs resource for effort)
                    duration_d = task.planned_hours / 8.0
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

    def _tjp_allocate(self, task):
        resource_map = {
            res.partner_id.id: self._tjp_resource_id(res.partner_id.id)
            for res in self.resource_ids
        }
        primary_ids = [
            resource_map[u.partner_id.id]
            for u in task.user_ids
            if u.partner_id.id in resource_map
        ]
        if not primary_ids:
            return []

        alt_id = resource_map.get(
            task.alternative_assignee_id.id
        ) if task.alternative_assignee_id else None

        if alt_id:
            alts = [alt_id] + [r for r in primary_ids[1:]]
            return [f'allocate {primary_ids[0]} {{ alternative {", ".join(alts)} }}']
        return [f'allocate {", ".join(primary_ids)}']

    def _tjp_reports(self):
        """One taskreport per scenario so each CSV file maps to exactly one scenario."""
        if not self.scenario_ids:
            return [
                'taskreport "schedule_plan" {',
                '  formats csv',
                '  columns id, bsi, name, start, end, effort, duration, resources, criticalness',
                '  scenarios plan',
                '}',
                '',
            ]
        lines = []
        for sc in self.scenario_ids:
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

    @staticmethod
    def _tjp_resource_id(partner_id):
        return f'res{partner_id}'

    @staticmethod
    def _tjp_task_id(task):
        return f't{task.id}'

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
        return imported

    def _import_scenario_csv(self, csv_content, scenario):
        """Parse a TJ3 CSV report and upsert insight.task.schedule records."""
        Schedule = self.env['insight.task.schedule']
        Schedule.search([
            ('scenario_id', '=', scenario.id),
            ('task_id.project_id', '=', self.id),
        ]).unlink()

        tz_name = (self.tj_timezone or 'UTC').replace(' ', '_')
        valid_task_ids = set(
            self.env['project.task'].search([('project_id', '=', self.id)]).ids
        )

        vals_list = []
        reader = csv.DictReader(io.StringIO(csv_content))
        for row in reader:
            norm = {k.strip().lower(): (v or '').strip() for k, v in row.items()}
            task_odoo_id = self._parse_task_id_from_tj_id(norm.get('id', ''))
            if not task_odoo_id or task_odoo_id not in valid_task_ids:
                continue
            vals_list.append({
                'task_id': task_odoo_id,
                'scenario_id': scenario.id,
                'start_scheduled': self._parse_tj_datetime(norm.get('start', ''), tz_name),
                'end_scheduled': self._parse_tj_datetime(norm.get('end', ''), tz_name),
                'effort_days': self._parse_tj_duration(norm.get('effort', '')),
                'duration_days': self._parse_tj_duration(norm.get('duration', '')),
                'is_critical_path': self._parse_tj_criticalness(norm.get('criticalness', '')),
                'bsi': norm.get('bsi', ''),
            })
        if vals_list:
            Schedule.create(vals_list)

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
