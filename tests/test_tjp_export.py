# -*- coding: utf-8 -*-
"""Regression tests for the TJP generator (models/project_project.py).

The task/resource shapes below mirror structural patterns seen in a real
exported .tjp — deep task nesting, a leaf task allocated to several
resources at once, "empty" leaf tasks with no effort used as milestones/
summary points, a resource with no linked hr.employee, and a root scenario
with nested alternates — so the generator's textual output stays pinned
even though the project content used here is synthetic.
"""
from datetime import date
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase


class TestTjpProjectHeader(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env['project.project'].create({
            'name': 'IT Plan',
            'is_tj_enabled': True,
            'date_start': '2026-06-29',
        })

    def test_project_id_and_dates_in_header(self):
        with patch.object(fields.Date, 'today', return_value=date(2026, 6, 29)):
            lines = self.project._tjp_project_header([])
        self.assertTrue(
            lines[0].startswith(f'project p{self.project.id} "IT Plan" 2026-06-29 - '),
            lines[0],
        )
        self.assertIn('  timezone "America/Argentina/Buenos_Aires"', lines)
        self.assertIn('  now 2026-06-29', lines)

    def test_now_reflects_todays_date_not_pinned_to_date_start(self):
        """`now` debe reflejar la fecha real de la corrida (para que los
        `booking` protejan el pasado correctamente en cada reschedule),
        no quedar pinneado al date_start fijo del proyecto."""
        with patch.object(fields.Date, 'today', return_value=date(2026, 7, 15)):
            lines = self.project._tjp_project_header([])
        self.assertIn('  now 2026-07-15', lines)

    def test_now_never_before_date_start(self):
        """Si el proyecto todavía no arrancó (date_start en el futuro), `now`
        no puede quedar antes de esa fecha — no hay bookings pasados que
        proteger todavía."""
        with patch.object(fields.Date, 'today', return_value=date(2026, 1, 1)):
            lines = self.project._tjp_project_header([])
        self.assertIn('  now 2026-06-29', lines)

    def test_single_scenario_when_none_defined(self):
        lines = self.project._tjp_project_header([])
        self.assertIn('  scenario plan "Plan"', lines)

    def test_alternates_nested_under_root_scenario(self):
        plan = self.env['insight.scenario'].create(
            {'name': 'Plan', 'project_id': self.project.id, 'is_baseline': True})
        self.env['insight.scenario'].create({'name': 'Noai', 'project_id': self.project.id})
        self.env['insight.scenario'].create({'name': 'Withia', 'project_id': self.project.id})

        text = '\n'.join(self.project._tjp_project_header(self.project.scenario_ids))
        self.assertIn('scenario plan "Plan" {', text)
        self.assertIn('    scenario noai "Noai"', text)
        self.assertIn('    scenario withia "Withia"', text)
        plan.unlink()
        self.project.scenario_ids.unlink()


class TestTjpProjectEndDate(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env['project.project'].create({
            'name': 'End Date Project',
            'is_tj_enabled': True,
            'date_start': '2026-06-29',
        })

    def test_explicit_horizon_wins(self):
        self.project.date = '2027-01-01'
        end = self.project._tjp_project_end_date(self.project.date_start)
        self.assertEqual(str(end), '2027-01-01')

    def test_falls_back_to_two_years_without_deadlines(self):
        end = self.project._tjp_project_end_date(self.project.date_start)
        self.assertEqual(str(end), '2028-06-29')

    def test_derives_horizon_from_latest_task_deadline(self):
        self.env['project.task'].create({
            'name': 'Deadline task',
            'project_id': self.project.id,
            'date_deadline': '2026-09-01 00:00:00',
        })
        end = self.project._tjp_project_end_date(self.project.date_start)
        # latest deadline (2026-09-01) + max((latest-start).days // 3, 30)
        self.assertGreater(str(end), '2026-09-01')
        self.assertGreaterEqual((end - self.project.date_start).days, 64 + 30)


class TestTjpResourceBlock(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env['project.project'].create({
            'name': 'Resource Block Project',
            'is_tj_enabled': True,
            'date_start': '2026-06-29',
        })
        cls.leave_type = cls.env['hr.leave.type'].create({
            'name': 'Test Annual Leave',
            'requires_allocation': 'no',
            'leave_validation_type': 'no_validation',
        })
        cls.calendar = cls.env['resource.calendar'].create({
            'name': 'Jornada estándar de prueba',
            'attendance_ids': [(5, 0, 0)] + [
                (0, 0, {'name': 'AM', 'dayofweek': dow, 'hour_from': 8.0, 'hour_to': 12.0})
                for dow in ('0', '1', '2', '3', '4')
            ] + [
                (0, 0, {'name': 'PM', 'dayofweek': dow, 'hour_from': 13.0, 'hour_to': 17.0})
                for dow in ('0', '1', '2', '3', '4')
            ],
        })
        cls.user_with_calendar = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Mitchell Admin Test',
            'login': 'mitchell_test@insight.test',
            'email': 'mitchell_test@insight.test',
            'groups_id': [(4, cls.env.ref('base.group_user').id)],
        })
        cls.employee_with_calendar = cls.env['hr.employee'].create({
            'name': 'Mitchell Admin Test',
            'user_id': cls.user_with_calendar.id,
            'resource_calendar_id': cls.calendar.id,
        })
        leave = cls.env['hr.leave'].create({
            'employee_id': cls.employee_with_calendar.id,
            'holiday_status_id': cls.leave_type.id,
            'request_date_from': '2026-07-20',
            'request_date_to': '2026-07-22',
        })
        leave.sudo().write({'state': 'validate'})

        cls.user_no_employee = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Joel Willis Test',
            'login': 'joel_test@insight.test',
            'email': 'joel_test@insight.test',
            'groups_id': [(4, cls.env.ref('base.group_user').id)],
        })

    def test_resource_block_emits_working_hours_and_leaves(self):
        lines = self.project._tjp_resource_block(self.user_with_calendar)
        text = '\n'.join(lines)
        self.assertIn('  workinghours mon 8:00 - 12:00', text)
        self.assertIn('  workinghours mon 13:00 - 17:00', text)
        self.assertIn('  workinghours sat off', text)
        self.assertIn('  workinghours sun off', text)
        self.assertIn('  leaves annual 2026-07-20 - 2026-07-22', text)

    def test_resource_block_empty_without_employee(self):
        """A user with no linked hr.employee still gets a resource block, but
        with no schedule content — matches how externally-assigned users
        (no HR record) show up in the generated TJP."""
        lines = self.project._tjp_resource_block(self.user_no_employee)
        res_name = self.user_no_employee.partner_id.name or self.user_no_employee.name
        self.assertEqual(lines[0], f'resource u{self.user_no_employee.id} "{res_name}" {{')
        self.assertEqual(lines[1], '}')

    def test_resource_id_raises_when_no_user_for_partner(self):
        """Interface guard: every TJ3 resource must map back to an Odoo user."""
        orphan_partner = self.env['res.partner'].create({'name': 'Orphan Contact'})
        with self.assertRaises(UserError):
            self.project._tjp_resource_id(orphan_partner.id)

    def test_resource_specific_attendance_override_does_not_leak_to_other_employees(self):
        """Una fila de `attendance_ids` con `resource_id` seteado es una
        excepción individual dentro de un calendario compartido — no debe
        filtrarse al horario exportado de otro empleado que usa el mismo
        calendario."""
        other_user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Marc Demo Test',
            'login': 'marc_test@insight.test',
            'email': 'marc_test@insight.test',
            'groups_id': [(4, self.env.ref('base.group_user').id)],
        })
        other_employee = self.env['hr.employee'].create({
            'name': 'Marc Demo Test',
            'user_id': other_user.id,
            'resource_calendar_id': self.calendar.id,
        })
        self.env['resource.calendar.attendance'].create({
            'name': 'Excepción sábado Marc',
            'calendar_id': self.calendar.id,
            'resource_id': other_employee.resource_id.id,
            'dayofweek': '5',
            'hour_from': 9.0,
            'hour_to': 13.0,
        })

        mitchell_text = '\n'.join(self.project._tjp_resource_block(self.user_with_calendar))
        marc_text = '\n'.join(self.project._tjp_resource_block(other_user))

        self.assertIn('  workinghours sat off', mitchell_text)
        self.assertNotIn('9:00 - 13:00', mitchell_text)
        self.assertIn('  workinghours sat 9:00 - 13:00', marc_text)

    def test_two_weeks_calendar_uses_only_the_week_matching_the_reference_date(self):
        """Un calendario rotativo (`two_weeks_calendar`) no debe fundir las
        horas de ambas semanas en un mismo día — solo aplican las de la
        semana vigente en la fecha de referencia (date_start del proyecto)."""
        ref_week_type = str(
            self.env['resource.calendar.attendance'].get_week_type(self.project.date_start)
        )
        other_week_type = '1' if ref_week_type == '0' else '0'

        rotating_calendar = self.env['resource.calendar'].create({
            'name': 'Calendario rotativo de prueba',
            'two_weeks_calendar': True,
            'attendance_ids': [(5, 0, 0)] + [
                (0, 0, {
                    'name': 'Semana vigente', 'dayofweek': '0',
                    'hour_from': 8.0, 'hour_to': 12.0, 'week_type': ref_week_type,
                }),
                (0, 0, {
                    'name': 'Otra semana', 'dayofweek': '1',
                    'hour_from': 8.0, 'hour_to': 12.0, 'week_type': other_week_type,
                }),
            ],
        })
        rotating_user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Rotativo Test',
            'login': 'rotativo_test@insight.test',
            'email': 'rotativo_test@insight.test',
            'groups_id': [(4, self.env.ref('base.group_user').id)],
        })
        self.env['hr.employee'].create({
            'name': 'Rotativo Test',
            'user_id': rotating_user.id,
            'resource_calendar_id': rotating_calendar.id,
        })

        text = '\n'.join(self.project._tjp_resource_block(rotating_user))
        self.assertIn('  workinghours mon 8:00 - 12:00', text)
        self.assertIn('  workinghours tue off', text)


class TestTjpTaskBlock(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env['project.project'].create({
            'name': 'Task Block Project',
            'is_tj_enabled': True,
            'date_start': '2026-06-29',
        })
        cls.users = cls.env['res.users'].with_context(no_reset_password=True).create([
            {
                'name': f'Resource Test {i}',
                'login': f'resource_test_{i}@insight.test',
                'email': f'resource_test_{i}@insight.test',
                'groups_id': [(4, cls.env.ref('base.group_user').id)],
            }
            for i in range(3)
        ])
        cls.u1, cls.u2, cls.u3 = cls.users

    def _task(self, **vals):
        vals.setdefault('project_id', self.project.id)
        return self.env['project.task'].create(vals)

    def test_leaf_task_emits_effort_and_single_allocate(self):
        task = self._task(name='Leaf with effort', allocated_hours=40.0, user_ids=[(6, 0, [self.u1.id])])
        lines = self.project._tjp_task_block(task)
        text = '\n'.join(lines)
        self.assertIn('  effort 5.00d', text)
        self.assertIn(f'  allocate u{self.u1.id}', text)

    def test_leaf_task_with_multiple_resources_uses_alternative_block(self):
        """Con más de un candidato, TJ3 debe elegir uno solo: se emite un
        bloque `allocate primary { alternative ...; select ... }` en vez de
        una lista plana que TJ3 interpretaría como 'todos en simultáneo'."""
        task = self._task(
            name='Validación cruzada',
            allocated_hours=80.0,
            user_ids=[(6, 0, [self.u1.id, self.u2.id, self.u3.id])],
        )
        lines = self.project._tjp_task_block(task)
        text = '\n'.join(lines)
        self.assertIn(f'  allocate u{self.u1.id} {{', text)
        self.assertIn(f'    alternative u{self.u2.id}, u{self.u3.id}', text)
        self.assertIn('    select minallocated', text)

    def test_allocate_respects_project_selection_criterion(self):
        self.project.tj_allocation_selection = 'order'
        task = self._task(
            name='Orden explícito',
            allocated_hours=40.0,
            user_ids=[(6, 0, [self.u1.id, self.u2.id])],
        )
        lines = self.project._tjp_task_block(task)
        self.assertIn('    select order', '\n'.join(lines))
        self.project.tj_allocation_selection = 'minallocated'

    def test_resource_pool_ids_overrides_user_ids_for_allocation(self):
        """resource_pool_ids (el pool de candidatos, potencialmente derivado
        de skills en project_improve) manda sobre user_ids al exportar."""
        task = self._task(
            name='Pool explícito',
            allocated_hours=40.0,
            user_ids=[(6, 0, [self.u1.id])],
        )
        task.resource_pool_ids = [(6, 0, [self.u2.id, self.u3.id])]
        lines = self.project._tjp_task_block(task)
        text = '\n'.join(lines)
        self.assertNotIn(f'u{self.u1.id}', text)
        self.assertIn(f'  allocate u{self.u2.id} {{', text)
        self.assertIn(f'    alternative u{self.u3.id}', text)

    def test_leaf_task_without_resources_uses_duration(self):
        task = self._task(name='No resource leaf', allocated_hours=16.0, user_ids=[(6, 0, [])])
        lines = self.project._tjp_task_block(task)
        text = '\n'.join(lines)
        self.assertIn('  duration 2.00d', text)
        self.assertNotIn('allocate', text)

    def test_empty_leaf_task_has_no_effort_or_duration(self):
        """Zero-effort, no-children leaf tasks (used as summary/tracking
        points, e.g. 'Polling en producción') render as bare empty blocks."""
        task = self._task(name='Hito sin esfuerzo')
        lines = self.project._tjp_task_block(task)
        self.assertEqual(lines, [
            f'task t{task.id} "Hito sin esfuerzo" {{',
            '  chargeset cost',
            '}',
            '',
        ])

    def test_task_linked_to_milestone_keeps_its_own_effort(self):
        """A real task linked to a project.milestone via milestone_id keeps
        emitting its own effort/duration — the milestone itself becomes a
        separate synthetic TJP task (see TestTjpMilestoneBlock), it no
        longer suppresses the linked task's block."""
        milestone = self.env['project.milestone'].create({
            'name': 'Entrega fase 1', 'project_id': self.project.id,
        })
        task = self._task(
            name='Milestone Task', allocated_hours=8.0, milestone_id=milestone.id,
            user_ids=[(6, 0, [self.u1.id])],
        )
        lines = self.project._tjp_task_block(task)
        text = '\n'.join(lines)
        self.assertIn('  effort 1.00d', text)
        self.assertNotIn('  milestone', text)

    def test_three_level_nesting_indentation(self):
        root = self._task(name='Eje')
        mid = self._task(name='Fase', parent_id=root.id)
        leaf = self._task(name='Cierre', parent_id=mid.id, allocated_hours=16.0, user_ids=[(6, 0, [self.u1.id])])

        lines = self.project._tjp_task_block(root, depth=0)
        text = '\n'.join(lines)
        self.assertIn(f'task t{root.id} "Eje" {{', text)
        self.assertIn(f'  task t{mid.id} "Fase" {{', text)
        self.assertIn(f'    task t{leaf.id} "Cierre" {{', text)
        self.assertIn('      effort 2.00d', text)

    def test_dependency_renders_absolute_path(self):
        blocker = self._task(name='Bloqueante')
        dependent = self._task(name='Dependiente', depend_on_ids=[(6, 0, [blocker.id])])
        lines = self.project._tjp_task_block(dependent)
        self.assertIn(f'  depends !t{blocker.id}', lines)

    def test_dependency_ss_emits_onstart_modifier(self):
        blocker = self._task(name='Bloqueante')
        dependent = self._task(
            name='Dependiente', tj_dependency_type='SS',
            depend_on_ids=[(6, 0, [blocker.id])],
        )
        lines = self.project._tjp_task_block(dependent)
        self.assertIn(f'  depends !t{blocker.id} {{ onstart }}', lines)

    def test_dependency_multiple_blockers_share_task_type(self):
        """tj_dependency_type vive en la tarea, no por arista: se aplica
        igual a todos sus bloqueantes."""
        blocker1 = self._task(name='Bloqueante 1')
        blocker2 = self._task(name='Bloqueante 2')
        dependent = self._task(
            name='Dependiente', tj_dependency_type='SS',
            depend_on_ids=[(6, 0, [blocker1.id, blocker2.id])],
        )
        lines = self.project._tjp_task_block(dependent)
        self.assertIn(f'  depends !t{blocker1.id} {{ onstart }}', lines)
        self.assertIn(f'  depends !t{blocker2.id} {{ onstart }}', lines)

    def test_dependency_ff_raises_user_error(self):
        """Finish→Finish no tiene constraint nativo en TJ3 (depends solo
        ancla el inicio de la tarea dependiente) — falla alto en vez de
        exportar un .tjp que ignora en silencio la elección del usuario."""
        blocker = self._task(name='Bloqueante')
        dependent = self._task(
            name='Dependiente', tj_dependency_type='FF',
            depend_on_ids=[(6, 0, [blocker.id])],
        )
        with self.assertRaises(UserError):
            self.project._tjp_task_block(dependent)

    def test_reports_one_per_scenario(self):
        plan = self.env['insight.scenario'].create(
            {'name': 'Plan', 'project_id': self.project.id, 'is_baseline': True})
        noai = self.env['insight.scenario'].create({'name': 'Noai', 'project_id': self.project.id})
        lines = self.project._tjp_reports(plan | noai)
        text = '\n'.join(lines)
        self.assertIn('taskreport "schedule_plan" {', text)
        self.assertIn('  scenarios plan', text)
        self.assertIn('taskreport "schedule_noai" {', text)
        self.assertIn('  scenarios noai', text)


class TestTjpBookings(TransactionCase):
    """`_tjp_bookings` exporta el trabajo ya imputado (timesheets) de una
    tarea como `booking`, para que TJ3 descuente ese esfuerzo del `effort`
    total en cada reschedule (ver models/project_project.py)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env['project.project'].create({
            'name': 'Bookings Project',
            'is_tj_enabled': True,
            'date_start': '2026-06-29',
        })
        cls.analytic_plan = cls.env['account.analytic.plan'].create({
            'name': 'Bookings Test Plan',
        })
        cls.analytic_account = cls.env['account.analytic.account'].create({
            'name': 'Bookings Project - Analytic',
            'plan_id': cls.analytic_plan.id,
        })
        cls.project.analytic_account_id = cls.analytic_account.id
        cls.user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Timesheet Resource',
            'login': 'timesheet_resource@insight.test',
            'email': 'timesheet_resource@insight.test',
            'groups_id': [(4, cls.env.ref('base.group_user').id)],
        })
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Timesheet Resource',
            'user_id': cls.user.id,
        })

    def _task(self, **vals):
        vals.setdefault('project_id', self.project.id)
        return self.env['project.task'].create(vals)

    def _log_time(self, task, emp_date, hours):
        return self.env['account.analytic.line'].create({
            'name': '/',
            'account_id': self.analytic_account.id,
            'task_id': task.id,
            'employee_id': self.employee.id,
            'date': emp_date,
            'unit_amount': hours,
        })

    def test_booking_emitted_for_past_timesheet(self):
        task = self._task(name='Con horas', allocated_hours=40.0, user_ids=[(6, 0, [self.user.id])])
        self._log_time(task, '2026-06-30', 3.5)
        lines = self.project._tjp_task_block(task, now_date=date(2026, 7, 1))
        self.assertIn(f'  booking u{self.user.id} 2026-06-30 +3.50h', lines)

    def test_bookings_for_same_user_and_day_are_summed(self):
        task = self._task(name='Dos líneas mismo día', allocated_hours=40.0, user_ids=[(6, 0, [self.user.id])])
        self._log_time(task, '2026-06-30', 2.0)
        self._log_time(task, '2026-06-30', 1.5)
        lines = self.project._tjp_task_block(task, now_date=date(2026, 7, 1))
        self.assertIn(f'  booking u{self.user.id} 2026-06-30 +3.50h', lines)
        self.assertEqual(
            sum(1 for l in lines if l.strip().startswith('booking')), 1,
            'Dos timesheets del mismo usuario/día deben colapsar en un solo booking',
        )

    def test_booking_excludes_lines_after_now_date(self):
        task = self._task(name='Horas futuras', allocated_hours=40.0, user_ids=[(6, 0, [self.user.id])])
        self._log_time(task, '2026-07-02', 4.0)
        lines = self.project._tjp_task_block(task, now_date=date(2026, 7, 1))
        self.assertFalse(any(l.strip().startswith('booking') for l in lines))

    def test_project_users_includes_timesheet_only_user(self):
        """Alguien que imputó horas en una tarea sin estar en resource_pool_ids
        ni en user_ids igual necesita su bloque `resource` — si no, su
        `booking` referenciaría un recurso no declarado y TJ3 fallaría al
        parsear el .tjp."""
        helper_user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Ayuda Puntual',
            'login': 'ayuda_puntual@insight.test',
            'email': 'ayuda_puntual@insight.test',
            'groups_id': [(4, self.env.ref('base.group_user').id)],
        })
        helper_employee = self.env['hr.employee'].create({
            'name': 'Ayuda Puntual', 'user_id': helper_user.id,
        })
        task = self._task(name='Con ayuda puntual', allocated_hours=40.0, user_ids=[(6, 0, [self.user.id])])
        self.env['account.analytic.line'].create({
            'name': '/',
            'account_id': self.analytic_account.id,
            'task_id': task.id,
            'employee_id': helper_employee.id,
            'date': '2026-06-30',
            'unit_amount': 3.0,
        })
        project_users = self.project._tj_project_users()
        self.assertIn(helper_user, project_users)

        lines = self.project._tjp_task_block(task, now_date=date(2026, 7, 1))
        text = '\n'.join(lines)
        self.assertIn(f'  booking u{helper_user.id} 2026-06-30 +3.00h', text)
        # No se lo agrega como candidato de asignación futura de la tarea.
        self.assertNotIn(f'allocate u{helper_user.id}', text)


class TestTjpMilestoneBlock(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env['project.project'].create({
            'name': 'Milestone Block Project',
            'is_tj_enabled': True,
            'date_start': '2026-06-29',
        })

    def _task(self, **vals):
        vals.setdefault('project_id', self.project.id)
        vals.setdefault('user_ids', [(6, 0, [])])
        return self.env['project.task'].create(vals)

    def test_milestone_emits_synthetic_task_with_dependencies(self):
        t1 = self._task(name='Deliverable 1', allocated_hours=8.0)
        t2 = self._task(name='Deliverable 2', allocated_hours=8.0)
        milestone = self.env['project.milestone'].create({
            'name': 'Entrega fase 1', 'project_id': self.project.id,
            'task_ids': [(6, 0, [t1.id, t2.id])],
        })
        lines = self.project._tjp_milestone_block(milestone)
        self.assertEqual(lines, [
            f'task m{milestone.id} "Entrega fase 1" {{',
            '  milestone',
            f'  depends !t{t1.id}',
            f'  depends !t{t2.id}',
            '}',
            '',
        ])

    def test_milestone_without_tasks_emits_nothing(self):
        milestone = self.env['project.milestone'].create({
            'name': 'Sin tareas', 'project_id': self.project.id,
        })
        self.assertEqual(self.project._tjp_milestone_block(milestone), [])

    def test_generate_tjp_includes_milestone_block(self):
        t1 = self._task(name='Deliverable 1', allocated_hours=8.0)
        milestone = self.env['project.milestone'].create({
            'name': 'Entrega fase 1', 'project_id': self.project.id,
            'task_ids': [(6, 0, [t1.id])],
        })
        text = self.project._generate_tjp()
        self.assertIn(f'task m{milestone.id} "Entrega fase 1" {{', text)
        self.assertIn(f'  depends !t{t1.id}', text)


class TestGenerateTjpEndToEnd(TransactionCase):
    """Smoke test: _generate_tjp must assemble header + resources + tasks +
    reports into one syntactically balanced document without raising."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env['project.project'].create({
            'name': 'Full Plan',
            'is_tj_enabled': True,
            'date_start': '2026-06-29',
        })
        cls.user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Full Plan Resource',
            'login': 'full_plan_resource@insight.test',
            'email': 'full_plan_resource@insight.test',
            'groups_id': [(4, cls.env.ref('base.group_user').id)],
        })
        cls.env['insight.scenario'].create(
            {'name': 'Plan', 'project_id': cls.project.id, 'is_baseline': True})
        root = cls.env['project.task'].create({
            'name': 'Eje', 'project_id': cls.project.id, 'user_ids': [(6, 0, [])],
        })
        cls.env['project.task'].create({
            'name': 'Leaf',
            'project_id': cls.project.id,
            'parent_id': root.id,
            'allocated_hours': 8.0,
            'user_ids': [(6, 0, [cls.user.id])],
        })

    def test_generate_tjp_is_brace_balanced_and_contains_all_sections(self):
        tjp = self.project._generate_tjp()
        self.assertEqual(tjp.count('{'), tjp.count('}'))
        self.assertIn(f'project p{self.project.id} "Full Plan"', tjp)
        self.assertIn(f'resource u{self.user.id} "Full Plan Resource"', tjp)
        self.assertIn('task t', tjp)
        self.assertIn('taskreport "schedule_plan"', tjp)


class TestActionExportTjp(TransactionCase):

    def test_raises_when_tj_disabled(self):
        project = self.env['project.project'].create({'name': 'Disabled TJ Project'})
        with self.assertRaises(UserError):
            project.action_export_tjp()

    def test_creates_downloadable_attachment(self):
        project = self.env['project.project'].create({
            'name': 'Enabled TJ Project',
            'is_tj_enabled': True,
        })
        result = project.action_export_tjp()
        self.assertEqual(result['type'], 'ir.actions.act_url')
        self.assertIn('/web/content/', result['url'])
        self.assertIn('Enabled_TJ_Project.tjp', result['url'])

        attachment = self.env['ir.attachment'].search([
            ('res_model', '=', 'project.project'),
            ('res_id', '=', project.id),
        ])
        self.assertTrue(attachment)
        content = attachment.raw.decode('utf-8')
        self.assertIn(f'project p{project.id} "Enabled TJ Project"', content)
