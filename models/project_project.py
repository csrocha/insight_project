# -*- coding: utf-8 -*-
import base64
import csv
import io
import re
from collections import defaultdict
from datetime import datetime, timedelta

import pytz
from markupsafe import Markup

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
    cost_budget_ids = fields.One2many(
        'insight.cost.budget', 'project_id', string='Costos extra (infra/SaaS)',
    )
    schedule_dirty = fields.Boolean(string='Schedule desactualizado')
    last_scheduled = fields.Datetime(string='Último schedule', readonly=True)
    tj_allocation_selection = fields.Selection(
        [
            ('minallocated', 'Menor carga asignada'),
            ('minloaded', 'Menor carga relativa'),
            ('maxloaded', 'Mayor carga relativa'),
            ('order', 'Orden de la lista'),
            ('random', 'Aleatorio'),
        ],
        string='Criterio de selección TJ3', default='minallocated',
        help='Criterio que usa TaskJuggler (atributo "select" de un bloque '
             'allocate) para elegir un recurso entre el candidato principal '
             'y sus alternativas cuando una tarea tiene más de un candidato.',
    )
    scenario_selection_strategy = fields.Selection(
        [
            ('manual', 'Mantener selección manual'),
            ('automatic', 'Selección automática (ponderada)'),
        ],
        string='Estrategia de selección de escenario', default='manual',
        help='Cómo elegir automáticamente, después de cada corrida de schedule, '
             'cuál escenario pasa a ser el baseline (el que sincroniza con el '
             'Gantt nativo de Odoo). "Mantener selección manual" preserva el '
             'comportamiento de siempre: nadie cambia is_baseline salvo el usuario. '
             '"Selección automática" pondera costo/duración/recursos según los pesos '
             'de abajo — poné en 0 los ejes que no te interesen para reproducir un '
             'criterio de un solo objetivo (ej. peso costo=1 y el resto en 0 para '
             '"menor costo").',
    )
    scenario_weight_cost = fields.Float(string='Peso: costo', default=1.0)
    scenario_weight_duration = fields.Float(string='Peso: duración', default=1.0)
    scenario_weight_resources = fields.Float(string='Peso: recursos', default=1.0)

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
            message = _('No se pudo conectar con el microservicio TJ3 en %s.') % base_url
            self._tj_post_error(message)
            raise UserError(message)
        except requests.exceptions.Timeout:
            message = _('Timeout esperando respuesta del microservicio TJ3.')
            self._tj_post_error(message)
            raise UserError(message)
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
                self.message_post(body=Markup('<br/>').join(message.split('\n')))
                raise UnscheduledTasksError(n_unscheduled, message)
            message = _('Error del microservicio TJ3: %s\n%s') % (str(e), detail)
            self._tj_post_error(message)
            raise UserError(message)

    def _tj_post_error(self, message):
        """Deja constancia en el chatter de cualquier fallo al llamar al
        microservicio TJ3 (conexión, timeout, o error genérico de scheduling
        como un .tjp mal formado) — sin esto, el error solo se ve como un
        popup momentáneo en el momento y no queda ningún rastro para
        diagnosticarlo después (el caso de "unscheduled tasks" ya lo hacía;
        acá se extiende a los demás)."""
        if self.id:
            self.message_post(body=Markup('<br/>').join(message.split('\n')))

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
        now_date = self._tjp_now_date()
        lines = []
        lines += self._tjp_project_header(scenarios, now_date)
        lines += self._tjp_cost_account()
        lines += self._tjp_shift_declarations(now_date)
        for user in self._tj_project_users():
            lines += self._tjp_resource_block(user)
        for scenario in scenarios:
            lines += self._tjp_scenario_supplement(scenario)
        for task in self.task_ids.filtered(
            lambda t: not t.parent_id
        ).sorted('sequence'):
            lines += self._tjp_task_block(task, depth=0, now_date=now_date)
        for milestone in self.milestone_ids:
            lines += self._tjp_milestone_block(milestone)
        lines += self._tjp_reports(scenarios)
        return '\n'.join(lines)

    def _tjp_now_date(self):
        """Referencia real de 'hoy' para el scheduler — a diferencia del
        `start` del proyecto (fijo, `date_start`), esta fecha debe avanzar en
        cada corrida para que los `booking` (ver _tjp_bookings) protejan
        correctamente el trabajo ya realizado. Nunca antes de `date_start`:
        si el proyecto todavía no arrancó, no puede haber bookings pasados
        que proteger."""
        self.ensure_one()
        start = self.date_start or fields.Date.today()
        return max(fields.Date.today(), start)

    def _tjp_project_header(self, scenarios=None, now_date=None):
        if scenarios is None:
            scenarios = self.scenario_ids
        proj_id = f'p{self.id}'
        name = (self.name or 'Project').replace('"', "'")
        start = self.date_start or fields.Date.today()
        end = self._tjp_project_end_date(start)
        tz = self.tj_timezone or 'UTC'
        if now_date is None:
            now_date = self._tjp_now_date()

        currency = (self.company_id.currency_id.name if self.company_id else False) or 'USD'
        lines = [
            f'project {proj_id} "{name}" {start} - {end} {{',
            f'  timezone "{tz}"',
            f'  now {now_date}',
            f'  currency "{currency}"',
            # Fuerza un formato numérico plano (punto decimal, sin separador
            # de miles) para las columnas de costo de los reportes — sin
            # esto, TJ3 usa el separador decimal del locale del contenedor
            # (confirmado contra el binario real: coma decimal, ej.
            # "300,00"), que _parse_tj_cost interpretaría como separador de
            # miles y leería 100 veces más grande de lo real.
            '  currencyformat "-" "" "" "." 2',
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

    _TJP_COST_ACCOUNT_ID = 'cost'
    # Cuenta "revenue" dummy: nunca se le carga nada (no facturamos vía TJ3),
    # existe solo porque `balance` exige dos cuentas de nivel superior — sin
    # `balance`, la columna `cost` del taskreport devuelve el string literal
    # "No 'balance' defined!" en vez de un número (confirmado contra el
    # binario real).
    _TJP_REVENUE_ACCOUNT_ID = 'revenue'
    # TJ3 priority es un entero 1-1000, default 500 si no se declara. Solo
    # emitimos la línea para 'Important' (task.priority nativo de Odoo es
    # binario Low/High): 800 alcanza para que gane contención de recursos
    # frente a cualquier tarea que se quede en el default implícito.
    _TJP_HIGH_PRIORITY = 800
    # Cuentas/reportes del desglose de costo (ver _generate_cost_report_tjp
    # / _tj_cost_by_phase_and_skill) — separadas de _TJP_COST_ACCOUNT_ID
    # (el schedule normal). Las hojas se nombran phase_<task.id>/
    # skill_<skill.id> para poder mapear de vuelta al registro real al
    # parsear la columna 'id' del accountreport.
    _TJP_PHASE_ACCOUNT_ID = 'by_phase'
    _TJP_SKILL_ACCOUNT_ID = 'by_skill'
    _TJP_PHASE_REPORT_ID = 'cost_by_phase'
    _TJP_SKILL_REPORT_ID = 'cost_by_skill'

    def _tjp_cost_account(self):
        """Cuenta de costo declarada una sola vez para que la columna 'cost' de
        los reportes tenga algo contra qué acumular (ver _tjp_task_block, que
        le asigna 'chargeset' a cada tarea raíz), más la cuenta "revenue"
        dummy que solo existe para poder declarar `balance` (ver _tjp_reports)."""
        return [
            f'account {self._TJP_COST_ACCOUNT_ID} "Costo"',
            f'account {self._TJP_REVENUE_ACCOUNT_ID} "Ingresos"',
            '',
        ]

    def _tjp_shift_declarations(self, now_date=None, users=None):
        """Bloques `shift` reusables (uno por cada resource.calendar
        distinto usado en algún cambio temporal de disponibilidad,
        hr.employee.tj_shift_ids, de los empleados de este proyecto),
        declarados una sola vez antes de los `resource` que los referencian
        — TJ3 exige que existan antes de usarse. Cada `resource` referencia
        el shift por id y agrega su propia ventana de fechas (ver
        _tjp_shift_assignments)."""
        if now_date is None:
            now_date = self._tjp_now_date()
        if users is None:
            users = self._tj_project_users()
        calendars = self.env['resource.calendar']
        for user in users:
            employee = self.env['hr.employee'].sudo().search(
                [('user_id', '=', user.id)], limit=1
            )
            if employee:
                calendars |= employee.tj_shift_ids.mapped('calendar_id')
        lines = []
        for calendar in calendars:
            shift_id = self._tjp_shift_id(calendar)
            shift_name = (calendar.name or 'Shift').replace('"', "'")
            lines.append(f'shift {shift_id} "{shift_name}" {{')
            for l in self._tjp_calendar_hours(calendar, False, now_date):
                lines.append(f'  {l}')
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
        user_ids), más el de cada puesto adicional simultáneo
        (extra_skill_group_ids, ver project_improve). Cualquier candidato
        potencial de una tarea necesita su propio bloque `resource`, no solo
        quien termine asignado.

        También se incluye a quien haya imputado timesheets en la tarea aunque
        no esté en ese pool: su `booking` (ver _tjp_bookings) referenciaría un
        recurso no declarado y TJ3 fallaría al parsear el .tjp. Esto no lo
        convierte en candidato para trabajo futuro — _tjp_allocate sigue
        leyendo solo resource_pool_ids/user_ids/extra_skill_group_ids."""
        self.ensure_one()
        users = self.env['res.users']
        for task in self.task_ids:
            users |= task.resource_pool_ids or task.user_ids
            users |= task.extra_skill_group_ids.mapped('resource_pool_ids')
            users |= task.timesheet_ids.mapped('user_id')
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

        if employee and employee.tj_daily_rate:
            lines.append(f'  rate {employee.tj_daily_rate:.2f}')

        lines += self._tjp_resource_limits(employee)
        lines += self._tjp_hr_schedule(employee)

        lines += ['}', '']
        return lines

    def _tjp_resource_limits(self, employee):
        """Bloque `limits` opcional: topes de dedicación distintos del
        calendario laboral (ej. alguien medio tiempo en este proyecto porque
        el resto de su jornada va a otro proyecto que este .tjp no modela).
        0 en cualquiera de los dos campos significa "sin tope" y no emite esa
        línea; sin ningún tope seteado no se emite el bloque."""
        if not employee:
            return []
        sub_lines = []
        if employee.tj_daily_max_hours:
            sub_lines.append(f'    dailymax {employee.tj_daily_max_hours:.2f}h')
        if employee.tj_weekly_max_hours:
            sub_lines.append(f'    weeklymax {employee.tj_weekly_max_hours:.2f}h')
        if not sub_lines:
            return []
        return ['  limits {'] + sub_lines + ['  }']

    def _tjp_hr_schedule(self, employee):
        lines = []
        if not employee:
            return lines

        ref_date = self.date_start or fields.Date.today()

        calendar = employee.resource_calendar_id
        if calendar:
            lines += self._tjp_calendar_hours(calendar, employee.resource_id, ref_date)
            lines += self._tjp_global_leaves(calendar, ref_date)

        lines += self._tjp_shift_assignments(employee, ref_date)

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

    def _tjp_shift_assignments(self, employee, ref_date):
        """Ventanas de `shifts {shift_id} {desde} - {hasta}` para los
        cambios temporales de disponibilidad del empleado
        (hr.employee.tj_shift_ids) — el bloque `shift` en sí ya se declaró
        una vez para todo el proyecto (ver _tjp_shift_declarations). Se
        excluyen ventanas ya vencidas (mismo criterio que _tjp_global_leaves
        y los hr.leave individuales)."""
        lines = []
        for shift in employee.tj_shift_ids.sorted('date_from'):
            if shift.date_to < ref_date:
                continue
            shift_id = self._tjp_shift_id(shift.calendar_id)
            lines.append(f'  shifts {shift_id} {shift.date_from} - {shift.date_to}')
        return lines

    def _tjp_global_leaves(self, calendar, ref_date):
        """Feriados de empresa: `resource.calendar.global_leave_ids` son
        `resource.calendar.leaves` con resource_id vacío (aplican a
        cualquiera que use ese calendario), a diferencia de `hr.leave` que
        es individual. Se exportan como `leaves holiday` — sin esto, TJ3
        no tiene forma de saber que nadie trabaja esos días y planifica
        esfuerzo sobre fechas donde en la realidad no hay nadie disponible."""
        lines = []
        for leave in calendar.global_leave_ids.sorted('date_from'):
            if not leave.date_from or not leave.date_to or leave.date_to.date() < ref_date:
                continue
            lines.append(f'  leaves holiday {leave.date_from.date()} - {leave.date_to.date()}')
        return lines

    def _tjp_calendar_hours(self, calendar, resource, ref_date):
        week_type = False
        if calendar.two_weeks_calendar:
            week_type = str(self.env['resource.calendar.attendance'].get_week_type(ref_date))

        day_slots = defaultdict(list)
        for att in calendar.attendance_ids:
            if att.display_type or (att.resource_id and att.resource_id != resource):
                continue
            if att.week_type and att.week_type != week_type:
                continue
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
            res_id = self._tjp_resource_id(eff.user_id.partner_id.id)
            lines += [
                f'supplement resource {res_id} {{',
                f'  {sc_id}:efficiency {eff.efficiency:.2f}',
                '}',
                '',
            ]
        return lines

    def _tjp_task_block(self, task, depth=0, now_date=None, extra_chargeset_fn=None):
        if now_date is None:
            now_date = self._tjp_now_date()
        t_id = self._tjp_task_id(task)
        t_name = (task.name or 'Task').replace('"', "'")
        ind = '  ' * depth

        lines = [f'{ind}task {t_id} "{t_name}" {{']
        if task.priority == '1':
            lines.append(f'{ind}  priority {self._TJP_HIGH_PRIORITY}')
        # complete no afecta el scheduling (TJ3 lo documenta como solo para
        # reporting) — se emite siempre, aunque sea 0, para pisar el cálculo
        # naive de TJ3 basado en `now` con el avance real (horas imputadas
        # vs. allocated_hours, ver project.task.progress de hr_timesheet).
        # Se clampea a 100 porque TJ3 rechaza valores > 100 (progress puede
        # superarlo con overtime).
        complete = min(max(task.progress, 0.0), 100.0)
        lines.append(f'{ind}  complete {complete:.2f}')
        if depth == 0:
            # chargeset se hereda a las subtareas; alcanza con declararlo una
            # sola vez en la tarea raíz para que 'cost' se acumule correctamente.
            lines.append(f'{ind}  chargeset {self._TJP_COST_ACCOUNT_ID}')
        # Hook para los reportes de costo por fase/skill (ver
        # _generate_cost_report_tjp): una tarea puede tener cualquier
        # cantidad de `chargeset`, uno por cada cuenta de nivel superior
        # distinta (confirmado contra el binario real) — no interfiere con
        # el chargeset de 'cost' de arriba.
        if extra_chargeset_fn:
            for cl in extra_chargeset_fn(task, depth):
                lines.append(f'{ind}  {cl}')

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
                    for bl in self._tjp_bookings(task, now_date):
                        lines.append(f'{ind}  {bl}')
                else:
                    # No resource assigned → use duration (TJ3 needs resource for effort)
                    duration_d = task.allocated_hours / 8.0
                    lines.append(f'{ind}  duration {duration_d:.2f}d')

        # Dependencies: FS (default) y SS mapean a `depends`/`depends {
        # onstart }` (ancla el INICIO de esta tarea). FF mapea a `precedes
        # {path} { onend }` (ancla el FIN de esta tarea al fin del
        # bloqueante) — confirmado contra el binario real de tj3-ms, sin
        # hito sintético ni `alap` explícito: `precedes` ya fuerza ALAP por
        # su cuenta. El tipo es por arista (dependency_type_ids, ver
        # project_task.py), con tj_dependency_type de la tarea como default
        # cuando una arista no tiene override propio.
        #
        # Dos reglas duras confirmadas empíricamente, no deducibles de la
        # sintaxis sola:
        # 1) Los `depends` deben ir ANTES que el `precedes` en el bloque —
        #    si se declaran en el orden inverso, TJ3 rechaza el archivo
        #    ("Tasks with on-end dependencies must be ALAP scheduled"),
        #    porque "la última política declarada gana" (ASAP vs ALAP).
        # 2) TJ3 3.8.4 solo respeta UN `precedes { onend }` por tarea — con
        #    dos o más, el segundo se ignora en silencio (probado con líneas
        #    separadas y con lista por comas, mismo resultado en ambas). Por
        #    eso como máximo una arista FF por tarea; más de una falla loud
        #    en vez de exportar un .tjp que TJ3 agenda mal sin avisar.
        ff_dep = None
        for dep in task.depend_on_ids:
            if dep.project_id != self:
                continue
            dep_type = task._tj_dependency_type_for(dep)
            if dep_type == 'FF':
                if ff_dep is not None:
                    raise UserError(_(
                        'La tarea "%(task)s" tiene más de una dependencia '
                        'Finish→Finish ("%(dep1)s" y "%(dep2)s"). TJ3 solo '
                        'respeta una por tarea (con más de una, ignora la '
                        'segunda en silencio) — deje una sola arista FF por '
                        'tarea.'
                    ) % {'task': task.name, 'dep1': ff_dep.name, 'dep2': dep.name})
                ff_dep = dep
                continue
            dep_path = self._tjp_task_abs_path(dep)
            suffix = ' { onstart }' if dep_type == 'SS' else ''
            lines.append(f'{ind}  depends {dep_path}{suffix}')
        if ff_dep is not None:
            ff_path = self._tjp_task_abs_path(ff_dep)
            lines.append(f'{ind}  precedes {ff_path} {{ onend }}')

        # Subtasks (recursive)
        for child in child_tasks:
            lines += self._tjp_task_block(
                child, depth=depth + 1, now_date=now_date,
                extra_chargeset_fn=extra_chargeset_fn,
            )

        lines.append(f'{ind}}}')
        lines.append('')
        return lines

    def _tjp_bookings(self, task, now_date):
        """Bloques `booking` con el trabajo ya imputado (timesheets) en esta
        tarea, agrupado por (usuario, día). Solo se consideran días hasta
        `now_date` — TJ3 no acepta bookings en el futuro respecto a `now`.
        Con al menos un booking, TJ3 activa "projection mode" y resta ese
        trabajo del `effort` total al planificar lo que falta.

        TJ3 exige que la duración de un booking sea múltiplo exacto del
        timingresolution del proyecto (60 min, default/máximo de TJ3 — no se
        baja porque penaliza mucho la performance del scheduler en un
        horizonte de varios años). Los timesheets con minutos sueltos (ej.
        0.14h) se truncan a la hora entera, y el truncamiento se aplica sobre
        la suma ya agrupada por (usuario, día), no por cada línea de
        timesheet individual, para no perder minutos de más de lo necesario.

        `overtime 2`: un timesheet puede superar la capacidad de calendario
        del recurso ese día (alguien trabajó de más, o imputó horas en un
        feriado/licencia) — es trabajo que ya sucedió, no algo que deba
        cumplir el calendario. Sin `overtime`, TJ3 intenta completar la
        duración pedida derramándose al próximo día hábil con lugar; si ese
        día cae en o después de `now` (típico si el derrame llega justo al
        día actual, ya que fines de semana/feriados no tienen capacidad),
        falla con "has no duty". `overtime 2` deja que la duración se
        cubra dentro del mismo día usando horas fuera de calendario
        (incluida licencia si hiciera falta), evitando ese derrame."""
        hours_by_user_date = defaultdict(float)
        for line in task.timesheet_ids:
            if not line.user_id or not line.date or line.date > now_date:
                continue
            hours_by_user_date[(line.user_id, line.date)] += line.unit_amount

        lines = []
        for (user, date), hours in sorted(
            hours_by_user_date.items(), key=lambda kv: (kv[0][1], kv[0][0].id)
        ):
            whole_hours = int(hours)
            if whole_hours <= 0:
                continue
            res_id = self._tjp_resource_id(user.partner_id.id)
            lines.append(f'booking {res_id} {date} +{whole_hours}.00h {{ overtime 2 }}')
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
        vez de asignarlas todas en simultáneo.

        Si la tarea tiene puestos adicionales (extra_skill_group_ids, ver
        project_improve), cada uno se agrega como otra entrada dentro del
        MISMO `allocate`, marcada `mandatory`: TJ3 solo agenda una franja
        horaria cuando TODOS los puestos mandatory están disponibles a la
        vez, y las horas de todos cuentan contra el mismo `effort` de la
        tarea — pensado para trabajo conjunto (pair programming, taller con
        2 facilitadores), no para roles con cargas horarias distintas
        dentro de la misma tarea (eso requeriría subtareas encadenadas, no
        puestos simultáneos)."""
        pool = task.resource_pool_ids or task.user_ids
        extra_pools = [group.resource_pool_ids for group in task.extra_skill_group_ids.sorted('sequence')]
        if not pool and not extra_pools:
            return []
        mandatory = bool(extra_pools)
        persistent = bool(task.tj_persistent_allocation)
        selection = task.project_id.tj_allocation_selection or 'minallocated'

        entries = []
        for i, pool_n in enumerate([pool] + extra_pools):
            if not pool_n:
                if i == 0:
                    raise UserError(_(
                        'La tarea "%s" tiene puestos adicionales '
                        '(extra_skill_group_ids) pero ningún candidato en '
                        'su pool principal (resource_pool_ids/user_ids) — '
                        'sin al menos un candidato ahí, esa franja nunca '
                        'podría agendarse.'
                    ) % task.name)
                raise UserError(_(
                    'La tarea "%s" tiene un puesto adicional sin ningún '
                    'candidato disponible (revise sus skills requeridas o '
                    'el roster de candidatos del proyecto) — no se puede '
                    'agendar.'
                ) % task.name)
            entries.append(self._tjp_allocate_entry_lines(pool_n, selection, mandatory, persistent))

        lines = [f'allocate {entries[0][0]}'] + entries[0][1:]
        for entry in entries[1:]:
            lines[-1] = f'{lines[-1]}, {entry[0]}'
            lines += entry[1:]
        return lines

    def _tjp_allocate_entry_lines(self, pool, selection, mandatory, persistent):
        """Una entrada de `allocate` (candidato principal + alternativas +
        criterio de selección + `persistent`/`mandatory` opcionales), sin la
        palabra clave `allocate` — _tjp_allocate combina una o más de estas
        en un solo bloque `allocate a, b, c`.

        `persistent` solo tiene efecto real con alternativas (fuerza que,
        una vez elegida una persona de la lista, siga siendo esa hasta el
        final); sin alternativas no hay nada entre qué persistir, así que
        no se emite."""
        ids = [self._tjp_resource_id(u.partner_id.id) for u in pool]
        primary, *alternatives = ids
        body = []
        if alternatives:
            body.append(f'  alternative {", ".join(alternatives)}')
            body.append(f'  select {selection}')
            if persistent:
                body.append('  persistent')
        if mandatory:
            body.append('  mandatory')
        if not body:
            return [primary]
        return [f'{primary} {{'] + body + ['}']

    def _tjp_reports(self, scenarios=None):
        """One taskreport per scenario so each CSV file maps to exactly one scenario."""
        if scenarios is None:
            scenarios = self.scenario_ids
        # balance es lo que hace que la columna 'cost' devuelva un número en
        # vez del string literal "No 'balance' defined!" (confirmado contra
        # el binario real) — 'revenue' es la cuenta dummy de _tjp_cost_account,
        # nunca se le carga nada, solo existe porque balance exige 2 cuentas.
        balance_line = f'  balance {self._TJP_COST_ACCOUNT_ID} {self._TJP_REVENUE_ACCOUNT_ID}'
        if not scenarios:
            return [
                'taskreport "schedule_plan" {',
                '  formats csv',
                balance_line,
                '  columns id, bsi, name, start, end, effort, duration, cost, resources, criticalness, complete',
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
                balance_line,
                '  columns id, bsi, name, start, end, effort, duration, cost, resources, criticalness, complete',
                f'  scenarios {sc_id}',
                '}',
                '',
            ]
        return lines

    # ── Reportes de costo (fase / skill / departamento) ─────────────────────────
    #
    # Fase y skill se conocen antes de programar (atributos fijos de la
    # tarea) → cuentas TJ3 reales (`account`/`chargeset`/`accountreport`),
    # corridas en un .tjp aparte, acotado a un solo escenario, que NO
    # escribe en insight.task.schedule. Departamento depende de quién
    # termina realmente asignado (recién se sabe al volver el schedule) →
    # se calcula 100% en Python sobre datos ya importados (ver
    # _cost_by_department). Guardado como versiones de knowledge.asset
    # (ver _get_or_create_cost_asset/_compute_and_save_cost_reports) para
    # tener histórico navegable, no solo el último cálculo.

    def _tjp_phase_skill_account_lines(self, root_tasks, skills):
        """Declara las cuentas de nivel superior 'by_phase'/'by_skill', una
        hoja por cada tarea raíz / skill distinta. Se omite la cuenta
        entera si no hay nada que declarar (ej. proyecto sin ninguna
        required_skill_ids en sus tareas)."""
        lines = []
        if root_tasks:
            lines.append(f'account {self._TJP_PHASE_ACCOUNT_ID} "Por fase" {{')
            for task in root_tasks:
                name = (task.name or 'Fase').replace('"', "'")
                lines.append(f'  account phase_{task.id} "{name}"')
            lines += ['}', '']
        if skills:
            lines.append(f'account {self._TJP_SKILL_ACCOUNT_ID} "Por categoría" {{')
            for skill in skills:
                name = (skill.name or 'Skill').replace('"', "'")
                lines.append(f'  account skill_{skill.id} "{name}"')
            lines += ['}', '']
        return lines

    def _tjp_extra_chargeset_fn(self, leaf_task_ids):
        """Callable para _tjp_task_block (parámetro extra_chargeset_fn):
        cada tarea raíz suma su costo a su cuenta de fase (heredado a las
        subtareas, igual que `cost`); cada tarea hoja con
        required_skill_ids suma el suyo a sus cuentas de skill, repartido
        en partes iguales entre ellas si requiere más de una (confirmado
        contra el binario real: `chargeset a, b` sin porcentaje explícito
        reparte parejo — no hace falta calcular el % a mano)."""
        def fn(task, depth):
            lines = []
            if depth == 0:
                lines.append(f'chargeset phase_{task.id}')
            if task.id in leaf_task_ids and task.required_skill_ids:
                skill_accounts = ", ".join(f'skill_{sid}' for sid in task.required_skill_ids.ids)
                lines.append(f'chargeset {skill_accounts}')
            return lines
        return fn

    def _tjp_accountreports(self, has_phase, has_skill):
        """accountreport en modo normal (sin `balance` — eso solo hace
        falta para taskreport, ver _tjp_reports). Las columnas de período
        ('monthly') son la única forma de sacar un valor de cuenta en TJ3
        3.8.4 (no existe una columna de 'total' plano) — vienen ACUMULADAS
        a la fecha (confirmado contra el binario real), así que
        _parse_accountreport_csv se queda con la última, nunca las suma."""
        lines = []
        if has_phase:
            lines += [
                f'accountreport "{self._TJP_PHASE_REPORT_ID}" {{',
                '  formats csv',
                f'  accountroot {self._TJP_PHASE_ACCOUNT_ID}',
                '  columns id, bsi, name, monthly',
                '}',
                '',
            ]
        if has_skill:
            lines += [
                f'accountreport "{self._TJP_SKILL_REPORT_ID}" {{',
                '  formats csv',
                f'  accountroot {self._TJP_SKILL_ACCOUNT_ID}',
                '  columns id, bsi, name, monthly',
                '}',
                '',
            ]
        return lines

    def _generate_cost_report_tjp(self, scenario):
        """.tjp aparte del schedule normal (_generate_tjp): acotado a UN
        escenario, sin taskreport de schedule ni milestones — solo lo
        necesario para los accountreport de fase/skill. No se importa a
        insight.task.schedule; ese modelo sigue siendo dueño solo del
        schedule real."""
        self.ensure_one()
        now_date = self._tjp_now_date()
        root_tasks = self.task_ids.filtered(lambda t: not t.parent_id).sorted('sequence')
        skills = self.task_ids.mapped('required_skill_ids')
        leaf_task_ids = self._tjp_leaf_task_ids()
        extra_fn = self._tjp_extra_chargeset_fn(leaf_task_ids)

        lines = []
        lines += self._tjp_project_header(scenario, now_date)
        lines += self._tjp_cost_account()
        lines += self._tjp_phase_skill_account_lines(root_tasks, skills)
        lines += self._tjp_shift_declarations(now_date)
        for user in self._tj_project_users():
            lines += self._tjp_resource_block(user)
        lines += self._tjp_scenario_supplement(scenario)
        for task in root_tasks:
            lines += self._tjp_task_block(task, depth=0, now_date=now_date, extra_chargeset_fn=extra_fn)
        lines += self._tjp_accountreports(bool(root_tasks), bool(skills))
        return '\n'.join(lines)

    @staticmethod
    def _parse_accountreport_csv(csv_content):
        """Parsea un accountreport CSV ('id', 'bsi', 'name', <períodos...>)
        a {account_id: costo_final}. Las columnas de período (ej.
        '2026-07-01') vienen acumuladas a la fecha — el costo real de la
        cuenta es el de la ÚLTIMA en orden cronológico, sumarlas
        duplicaría costo."""
        if not csv_content:
            return {}
        first_line = csv_content.split('\n')[0] if csv_content else ''
        delimiter = ';' if ';' in first_line else ','
        reader = csv.DictReader(io.StringIO(csv_content), delimiter=delimiter)
        period_re = re.compile(r'^\d{4}-\d{2}-\d{2}$')
        result = {}
        for row in reader:
            norm = {k.strip().lower(): (v or '').strip() for k, v in row.items() if k is not None}
            account_id = norm.get('id', '')
            if not account_id:
                continue
            period_cols = sorted(k for k in norm if period_re.match(k))
            if not period_cols:
                continue
            try:
                result[account_id] = float(norm[period_cols[-1]].replace(',', ''))
            except (ValueError, AttributeError):
                result[account_id] = 0.0
        return result

    def _tj_cost_by_phase_and_skill(self, scenario):
        """Corre el .tjp de _generate_cost_report_tjp contra el
        microservicio TJ3 y devuelve ({project.task raíz: costo},
        {hr.skill: costo}). No escribe en insight.task.schedule."""
        self.ensure_one()
        if self.schedule_dirty:
            raise UserError(_(
                'El schedule está desactualizado. Ejecute "Ejecutar '
                'Schedule" antes de generar reportes de costos.'
            ))
        root_tasks = self.task_ids.filtered(lambda t: not t.parent_id).sorted('sequence')
        skills = self.task_ids.mapped('required_skill_ids')
        if not root_tasks:
            return {}, {}

        ICP = self.env['ir.config_parameter'].sudo()
        url = ICP.get_param('insight_project.tj_microservice_url')
        if not url:
            raise UserError(_('Configure la URL del microservicio TJ3 en Ajustes → TaskJuggler.'))
        try:
            timeout = int(ICP.get_param('insight_project.tj_microservice_timeout') or 120)
        except (ValueError, TypeError):
            timeout = 120

        tjp_content = self._generate_cost_report_tjp(scenario)
        response_data = self._call_tj_microservice(url.rstrip('/'), tjp_content, timeout)
        csv_files = response_data.get('csv_files', {})

        phase_costs = {}
        parsed = self._parse_accountreport_csv(csv_files.get(f'{self._TJP_PHASE_REPORT_ID}.csv', ''))
        for task in root_tasks:
            cost = parsed.get(f'phase_{task.id}')
            if cost is not None:
                phase_costs[task] = cost

        skill_costs = {}
        parsed = self._parse_accountreport_csv(csv_files.get(f'{self._TJP_SKILL_REPORT_ID}.csv', ''))
        for skill in skills:
            cost = parsed.get(f'skill_{skill.id}')
            if cost is not None:
                skill_costs[skill] = cost

        return phase_costs, skill_costs

    def _cost_by_department(self, scenario):
        """Costo por departamento, 100% en Python: a diferencia de fase/
        skill, depende de quién termina REALMENTE asignado — algo que TJ3
        recién resuelve al devolver el schedule, no se puede declarar como
        chargeset estático en el .tjp de entrada. Reparte el costo de una
        tarea hoja en partes iguales entre los departamentos distintos de
        sus recursos asignados (resource_ids, ya resuelto e importado)."""
        self.ensure_one()
        leaf_ids = self._tjp_leaf_task_ids()
        no_department = _('Sin departamento')
        totals = defaultdict(float)
        for sched in scenario.schedule_ids.filtered(lambda s: s.task_id.id in leaf_ids):
            departments = set()
            for user in sched.resource_ids:
                employee = self.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)
                departments.add(employee.department_id.name if employee and employee.department_id else False)
            if not departments:
                departments = {False}
            share = sched.cost / len(departments)
            for dept_name in departments:
                totals[dept_name or no_department] += share
        return dict(totals)

    _TJP_COST_REPORT_CATEGORY = 'insight_project.cost_report'

    def _get_or_create_cost_asset(self, scenario, dimension, label):
        """Un knowledge.asset por (escenario, dimensión) — cada
        "Generar reportes de costos" agrega una VERSIÓN nueva al mismo
        asset (ver _compute_and_save_cost_reports), así el histórico sale
        gratis vía asset.version_ids. `visibility='shared'` +
        `shared_group_ids` (managers de proyecto) para que lo vea todo el
        equipo de PM, no solo quien lo generó (el owner por default)."""
        self.ensure_one()
        Asset = self.env['knowledge.asset']
        asset = Asset.search([
            ('res_model', '=', 'insight.scenario'),
            ('res_id', '=', scenario.id),
            ('category', '=', self._TJP_COST_REPORT_CATEGORY),
            ('tags', '=', dimension),
        ], limit=1)
        if asset:
            return asset
        manager_group = self.env.ref('project.group_project_manager', raise_if_not_found=False)
        return Asset.create({
            'name': _('%(label)s — %(project)s / %(scenario)s') % {
                'label': label, 'project': self.name, 'scenario': scenario.name,
            },
            'res_model': 'insight.scenario',
            'res_id': scenario.id,
            'category': self._TJP_COST_REPORT_CATEGORY,
            'tags': dimension,
            'visibility': 'shared',
            'shared_group_ids': [(6, 0, manager_group.ids)] if manager_group else False,
        })

    def _compute_and_save_cost_reports(self, scenario):
        """Orquestador de 'Generar reportes de costos': calcula las 3
        dimensiones y guarda cada una como una versión nueva de su
        knowledge.asset (get-or-create)."""
        self.ensure_one()
        phase_costs, skill_costs = self._tj_cost_by_phase_and_skill(scenario)
        dept_costs = self._cost_by_department(scenario)
        currency = (self.company_id.currency_id.name if self.company_id else False) or 'USD'
        generated_at = fields.Datetime.to_string(fields.Datetime.now())

        dimensions = [
            ('phase', _('Costo por fase'),
             [{'label': task.name, 'cost': cost} for task, cost in phase_costs.items()]),
            ('skill', _('Costo por categoría'),
             [{'label': skill.name, 'cost': cost} for skill, cost in skill_costs.items()]),
            ('department', _('Costo por departamento'),
             [{'label': label, 'cost': cost} for label, cost in dept_costs.items()]),
        ]
        for dimension, label, items in dimensions:
            asset = self._get_or_create_cost_asset(scenario, dimension, label)
            payload = {
                'title': label,
                'currency': currency,
                'generated_at': generated_at,
                'items': items,
                'total': sum(item['cost'] for item in items),
            }
            asset.create_version(
                payload, schema=f'insight_project.cost_by_{dimension}', schema_version='1.0',
            )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Reportes de costos generados'),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_generate_cost_reports(self):
        """Wrapper de conveniencia sobre el proyecto: resuelve el
        escenario baseline y delega en insight.scenario (que es el dueño
        real de la acción, ver models/insight_scenario.py) — así el botón
        de un escenario puntual y el de la pestaña TaskJuggler del
        proyecto hacen exactamente lo mismo."""
        self.ensure_one()
        scenario = self.scenario_ids.filtered('is_baseline')[:1]
        if not scenario:
            raise UserError(_('No hay un escenario baseline. Ejecute el schedule primero.'))
        return scenario.action_generate_cost_reports()

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
    def _tjp_shift_id(calendar):
        return f'shift_cal{calendar.id}'

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
        self._apply_selection_strategy()
        self._sync_gantt_dates()
        return imported

    # ── Selección de escenario ───────────────────────────────────────────────

    def _tjp_leaf_task_ids(self):
        """IDs de project.task sin subtareas dentro de este proyecto — las
        únicas que reciben 'effort'/'allocate' reales en el .tjp (ver
        _tjp_task_block). Las filas de sus tareas padre en el reporte son un
        rollup de TJ3, no una asignación de recurso propia, así que no deben
        contarse al medir concurrencia de recursos."""
        return {
            t.id for t in self.task_ids
            if not t.child_ids.filtered(lambda c: c.project_id == self)
        }

    def _peak_concurrent_resources(self, scenario, leaf_task_ids):
        """Pico de recursos distintos trabajando en simultáneo en este
        escenario: sweep-line sobre los intervalos [start, end) de sus tareas
        hoja (cada una asignada a un único recurso, ver _tjp_allocate). Se
        usa un intervalo semiabierto para que una tarea que termina justo
        cuando otra empieza no cuente como concurrente."""
        events = []
        for schedule in scenario.schedule_ids:
            if schedule.task_id.id not in leaf_task_ids:
                continue
            if not schedule.start_scheduled or not schedule.end_scheduled:
                continue
            for _user in schedule.resource_ids:
                events.append((schedule.start_scheduled, 1))
                events.append((schedule.end_scheduled, -1))
        if not events:
            return 0
        events.sort(key=lambda e: (e[0], e[1]))  # end (-1) antes que start (+1) al mismo instante
        current = peak = 0
        for _when, delta in events:
            current += delta
            peak = max(peak, current)
        return peak

    def _compute_scenario_aggregates(self, scenarios):
        """Recalcula total_cost / computed_end_date / peak_resources de cada
        escenario en base a sus insight.task.schedule vigentes."""
        root_task_ids = set(self.task_ids.filtered(lambda t: not t.parent_id).ids)
        leaf_task_ids = self._tjp_leaf_task_ids()
        for scenario in scenarios:
            root_schedules = scenario.schedule_ids.filtered(
                lambda s: s.task_id.id in root_task_ids
            )
            ends = [e for e in scenario.schedule_ids.mapped('end_scheduled') if e]
            scenario.write({
                'total_cost': sum(root_schedules.mapped('cost')),
                'computed_end_date': max(ends) if ends else False,
                'peak_resources': self._peak_concurrent_resources(scenario, leaf_task_ids),
            })

    def _weighted_scenario_scores(self, candidates):
        """Normaliza costo/duración/pico de recursos (min-max, 0=mejor,
        1=peor) entre `candidates` y combina con los pesos configurados en el
        proyecto. Guarda selection_score en cada escenario para que quede
        visible en la UI por qué ganó."""
        def _normalized(raw):
            lo, hi = min(raw.values()), max(raw.values())
            span = hi - lo
            if not span:
                return {k: 0.0 for k in raw}
            return {k: (v - lo) / span for k, v in raw.items()}

        cost_n = _normalized({s.id: s.grand_total_cost for s in candidates})
        duration_n = _normalized({
            s.id: s.computed_end_date.timestamp() if s.computed_end_date else 0.0
            for s in candidates
        })
        resources_n = _normalized({s.id: float(s.peak_resources) for s in candidates})

        scores = {}
        for s in candidates:
            score = (
                self.scenario_weight_cost * cost_n[s.id]
                + self.scenario_weight_duration * duration_n[s.id]
                + self.scenario_weight_resources * resources_n[s.id]
            )
            scores[s.id] = score
            s.selection_score = score
        return scores

    def _apply_selection_strategy(self):
        """Recalcula los agregados de cada escenario y, según
        scenario_selection_strategy, decide cuál pasa a ser is_baseline —
        dejando la decisión y el motivo en el chatter, porque a partir de acá
        is_baseline puede cambiar sin que nadie lo haya tocado a mano."""
        self.ensure_one()
        scenarios = self.scenario_ids
        if not scenarios:
            return
        self._compute_scenario_aggregates(scenarios)
        scenarios.write({'selection_score': 0.0})
        if self.scenario_selection_strategy == 'manual' or len(scenarios) == 1:
            return

        candidates = scenarios
        missed_deadline = False
        if self.date:
            within_deadline = scenarios.filtered(
                lambda s: not s.computed_end_date or s.computed_end_date.date() <= self.date
            )
            if within_deadline:
                candidates = within_deadline
            else:
                missed_deadline = True

        metric_by_scenario = self._weighted_scenario_scores(candidates)
        best_value = min(metric_by_scenario.values())
        tied = candidates.filtered(lambda s: metric_by_scenario[s.id] == best_value)

        current_baseline = scenarios.filtered('is_baseline')
        winner = (
            current_baseline[:1]
            if current_baseline and current_baseline in tied
            else tied[:1]
        )

        scenarios.write({'is_baseline': False})
        winner.is_baseline = True
        self._post_selection_message(scenarios, winner, candidates, missed_deadline)

    def _post_selection_message(self, scenarios, winner, candidates, missed_deadline):
        strategy_label = dict(
            self._fields['scenario_selection_strategy'].selection
        )[self.scenario_selection_strategy]
        lines = [_('Selección automática de escenario — estrategia: %s') % strategy_label]
        if missed_deadline:
            lines.append(_(
                'Ningún escenario cumple la fecha pactada (%s); se compararon todos igual.'
            ) % self.date)
        for sc in scenarios:
            marker = '→' if sc.id == winner.id else '·'
            note = ''
            if sc not in candidates and not missed_deadline:
                note = _(' (excede la fecha pactada)')
            end_txt = str(sc.computed_end_date) if sc.computed_end_date else '-'
            lines.append(_(
                '%(marker)s %(name)s — costo %(cost).2f, fin %(end)s, '
                'pico de recursos %(peak)d%(note)s'
            ) % {
                'marker': marker, 'name': sc.name, 'cost': sc.grand_total_cost,
                'end': end_txt, 'peak': sc.peak_resources, 'note': note,
            })
        self.message_post(body=Markup('<br/>').join(lines))

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
                    'cost': self._parse_tj_cost(norm.get('cost', '')),
                    'is_critical_path': self._parse_tj_criticalness(norm.get('criticalness', '')),
                    'complete': self._parse_tj_complete(norm.get('completion', '')),
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
    def _parse_tj_cost(value):
        """Convert TJ3 'cost' column text (e.g. '1234.00', '$1,234.00') to float."""
        if not value:
            return 0.0
        cleaned = re.sub(r'[^0-9.\-]', '', value.strip())
        try:
            return float(cleaned) if cleaned else 0.0
        except ValueError:
            return 0.0

    @staticmethod
    def _parse_tj_criticalness(value):
        """Return True when TJ3 criticalness > 0 (task is on the critical path)."""
        try:
            return float(value or '0') > 0.0
        except (ValueError, TypeError):
            return False

    @staticmethod
    def _parse_tj_complete(value):
        """Convert the taskreport 'Completion' column (e.g. '62%') to a
        plain float 0-100."""
        if not value:
            return 0.0
        try:
            return float(value.strip().rstrip('%'))
        except (ValueError, AttributeError):
            return 0.0

    @staticmethod
    def _parse_tj_resource_ids(value):
        """Parse the taskreport 'resources' column into Odoo res.users ids.
        TJ3 renders each allocated resource as its full name followed by its
        id in parentheses (e.g. 'Juan Perez (u12), Maria Lopez (u34)'), never
        as a bare 'u12' token — the id must be pulled out of the parens."""
        if not value:
            return []
        return [int(m) for m in re.findall(r'\(u(\d+)\)', value)]

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
                if sched.complete > 0:
                    # Franja de avance real (project.task.progress al momento
                    # del export, ver _tjp_task_block) sobre el borde inferior
                    # de la barra — no lo calcula TJ3, es solo visual.
                    complete_w = bw * min(sched.complete, 100.0) / 100.0
                    o.append(
                        f'<rect x="{x1:.1f}" y="{yc+RH-8}" width="{complete_w:.1f}" height="3"'
                        f' fill="#212121" opacity="0.55" rx="1.5"/>'
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
