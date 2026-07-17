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
from odoo.exceptions import UserError, ValidationError
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

    def test_currencyformat_forces_plain_decimal_point(self):
        """Sin esto, TJ3 usa el separador decimal del locale del contenedor
        (confirmado contra el binario real: coma, ej. "300,00"), que
        _parse_tj_cost interpretaría como separador de miles y leería 100
        veces más grande de lo real."""
        lines = self.project._tjp_project_header([])
        self.assertIn('  currencyformat "-" "" "" "." 2', lines)

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
        plan_id = self.project._tjp_scenario_id(plan)
        self.assertIn(f'scenario {plan_id} "Plan" {{', text)
        for sc in self.project.scenario_ids.filtered(lambda s: s.name != 'Plan'):
            sc_id = self.project._tjp_scenario_id(sc)
            self.assertIn(f'    scenario {sc_id} "{sc.name}"', text)
        plan.unlink()
        self.project.scenario_ids.unlink()

    def test_cost_account_declares_dummy_revenue_account(self):
        """'revenue' nunca recibe chargeset — existe solo porque `balance`
        (ver _tjp_reports) exige dos cuentas de nivel superior."""
        lines = self.project._tjp_cost_account()
        self.assertIn('account cost "Costo"', lines)
        self.assertIn('account revenue "Ingresos"', lines)

    def test_reports_declare_balance_against_dummy_revenue(self):
        """Sin `balance`, la columna 'cost' del taskreport devuelve el string
        literal "No 'balance' defined!" en vez de un número (confirmado
        contra el binario real de tj3-ms)."""
        lines = self.project._tjp_reports([])
        self.assertIn('  balance cost revenue', lines)


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

    def test_shift_assignment_emitted_for_active_window(self):
        crunch_calendar = self.env['resource.calendar'].create({
            'name': 'Crunch',
            'attendance_ids': [(5, 0, 0)] + [
                (0, 0, {'name': 'Crunch', 'dayofweek': dow, 'hour_from': 8.0, 'hour_to': 20.0})
                for dow in ('0', '1', '2', '3', '4')
            ],
        })
        shift = self.env['insight.employee.shift'].create({
            'employee_id': self.employee_with_calendar.id,
            'date_from': '2026-07-20', 'date_to': '2026-08-02',
            'calendar_id': crunch_calendar.id,
        })
        text = '\n'.join(self.project._tjp_resource_block(self.user_with_calendar))
        self.assertIn(f'  shifts {self.project._tjp_shift_id(crunch_calendar)} 2026-07-20 - 2026-08-02', text)
        shift.unlink()

    def test_shift_assignment_excludes_expired_window(self):
        crunch_calendar = self.env['resource.calendar'].create({'name': 'Crunch pasado'})
        shift = self.env['insight.employee.shift'].create({
            'employee_id': self.employee_with_calendar.id,
            'date_from': '2026-01-01', 'date_to': '2026-01-15',
            'calendar_id': crunch_calendar.id,
        })
        text = '\n'.join(self.project._tjp_resource_block(self.user_with_calendar))
        self.assertNotIn('shifts', text)
        shift.unlink()

    def test_shift_declarations_include_workinghours_of_referenced_calendar(self):
        crunch_calendar = self.env['resource.calendar'].create({
            'name': 'Crunch',
            'attendance_ids': [(5, 0, 0), (0, 0, {
                'name': 'Crunch', 'dayofweek': '0', 'hour_from': 8.0, 'hour_to': 20.0,
            })],
        })
        shift = self.env['insight.employee.shift'].create({
            'employee_id': self.employee_with_calendar.id,
            'date_from': '2026-07-20', 'date_to': '2026-08-02',
            'calendar_id': crunch_calendar.id,
        })
        text = '\n'.join(self.project._tjp_shift_declarations(users=self.user_with_calendar))
        shift_id = self.project._tjp_shift_id(crunch_calendar)
        self.assertIn(f'shift {shift_id} "Crunch" {{', text)
        self.assertIn('  workinghours mon 8:00 - 20:00', text)
        shift.unlink()

    def test_shift_declarations_empty_without_any_shift(self):
        self.assertEqual(
            self.project._tjp_shift_declarations(users=self.user_with_calendar), [],
        )

    def test_global_calendar_leave_emitted_as_holiday(self):
        """resource.calendar.leaves sin resource_id es un feriado de empresa
        (aplica a cualquiera que use ese calendario) — se exporta como
        `leaves holiday`, distinto del `leaves annual` individual."""
        leave = self.env['resource.calendar.leaves'].create({
            'name': 'Feriado nacional',
            'calendar_id': self.calendar.id,
            'date_from': '2026-07-09 00:00:00',
            'date_to': '2026-07-09 23:59:59',
        })
        text = '\n'.join(self.project._tjp_resource_block(self.user_with_calendar))
        self.assertIn('  leaves holiday 2026-07-09 - 2026-07-09', text)
        leave.unlink()

    def test_global_calendar_leave_before_project_start_excluded(self):
        leave = self.env['resource.calendar.leaves'].create({
            'name': 'Feriado pasado',
            'calendar_id': self.calendar.id,
            'date_from': '2026-01-01 00:00:00',
            'date_to': '2026-01-01 23:59:59',
        })
        text = '\n'.join(self.project._tjp_resource_block(self.user_with_calendar))
        self.assertNotIn('holiday', text)
        leave.unlink()

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

    def test_daily_and_weekly_max_emit_limits_block(self):
        self.employee_with_calendar.tj_daily_max_hours = 4.0
        self.employee_with_calendar.tj_weekly_max_hours = 20.0
        text = '\n'.join(self.project._tjp_resource_block(self.user_with_calendar))
        self.assertIn('  limits {\n    dailymax 4.00h\n    weeklymax 20.00h\n  }', text)
        self.employee_with_calendar.tj_daily_max_hours = 0.0
        self.employee_with_calendar.tj_weekly_max_hours = 0.0

    def test_only_daily_max_emits_single_line_limits_block(self):
        self.employee_with_calendar.tj_daily_max_hours = 6.0
        text = '\n'.join(self.project._tjp_resource_block(self.user_with_calendar))
        self.assertIn('  limits {\n    dailymax 6.00h\n  }', text)
        self.assertNotIn('weeklymax', text)
        self.employee_with_calendar.tj_daily_max_hours = 0.0

    def test_no_max_hours_omits_limits_block(self):
        text = '\n'.join(self.project._tjp_resource_block(self.user_with_calendar))
        self.assertNotIn('limits', text)

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


class TestInsightEmployeeShift(TransactionCase):
    """Validaciones del modelo insight.employee.shift — el export en sí ya
    se prueba en TestTjpResourceBlock."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Shift Test', 'login': 'shift_test@insight.test', 'email': 'shift_test@insight.test',
            'groups_id': [(4, cls.env.ref('base.group_user').id)],
        })
        cls.employee = cls.env['hr.employee'].create({'name': 'Shift Test', 'user_id': user.id})
        cls.calendar = cls.env['resource.calendar'].create({'name': 'Alt Calendar'})

    def test_date_from_after_date_to_raises(self):
        with self.assertRaises(ValidationError):
            self.env['insight.employee.shift'].create({
                'employee_id': self.employee.id,
                'date_from': '2026-08-01', 'date_to': '2026-07-01',
                'calendar_id': self.calendar.id,
            })

    def test_overlapping_windows_for_same_employee_raises(self):
        self.env['insight.employee.shift'].create({
            'employee_id': self.employee.id,
            'date_from': '2026-07-01', 'date_to': '2026-07-15',
            'calendar_id': self.calendar.id,
        })
        with self.assertRaises(ValidationError):
            self.env['insight.employee.shift'].create({
                'employee_id': self.employee.id,
                'date_from': '2026-07-10', 'date_to': '2026-07-20',
                'calendar_id': self.calendar.id,
            })

    def test_adjacent_non_overlapping_windows_are_allowed(self):
        self.env['insight.employee.shift'].create({
            'employee_id': self.employee.id,
            'date_from': '2026-07-01', 'date_to': '2026-07-15',
            'calendar_id': self.calendar.id,
        })
        second = self.env['insight.employee.shift'].create({
            'employee_id': self.employee.id,
            'date_from': '2026-07-16', 'date_to': '2026-07-31',
            'calendar_id': self.calendar.id,
        })
        self.assertTrue(second)


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

        skill_type = cls.env['hr.skill.type'].create({
            'name': 'Puesto adicional Test',
            'skill_level_ids': [(0, 0, {
                'name': 'Expert', 'level_progress': 100, 'default_level': True,
            })],
        })
        cls.skill = cls.env['hr.skill'].create({
            'name': 'Skill Test', 'skill_type_id': skill_type.id,
        })

    def _task(self, **vals):
        vals.setdefault('project_id', self.project.id)
        return self.env['project.task'].create(vals)

    def _skill_group(self, task, user_ids):
        """Puesto adicional simultáneo con candidatos forzados a mano — el
        matching real por skill ya se prueba en project_improve, acá solo
        interesa cómo _tjp_allocate consume extra_skill_group_ids."""
        group = self.env['project.task.skill.group'].create({
            'task_id': task.id,
            'required_skill_ids': [(6, 0, self.skill.ids)],
        })
        group.resource_pool_ids = [(6, 0, user_ids)]
        return group

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

    def test_persistent_allocation_emits_persistent_line_with_alternatives(self):
        task = self._task(
            name='Persistente con alternativas',
            allocated_hours=40.0,
            user_ids=[(6, 0, [self.u1.id, self.u2.id])],
            tj_persistent_allocation=True,
        )
        lines = self.project._tjp_task_block(task)
        text = '\n'.join(lines)
        self.assertIn(f'  allocate u{self.u1.id} {{', text)
        self.assertIn('    persistent', text)

    def test_persistent_flag_without_alternatives_emits_nothing(self):
        """Sin alternativas no hay nada entre qué persistir — TJ3 no gana
        nada con la línea, así que no se emite."""
        task = self._task(
            name='Persistente sin alternativas',
            allocated_hours=40.0,
            user_ids=[(6, 0, [self.u1.id])],
            tj_persistent_allocation=True,
        )
        lines = self.project._tjp_task_block(task)
        self.assertNotIn('persistent', '\n'.join(lines))

    def test_persistent_off_by_default_even_with_alternatives(self):
        task = self._task(
            name='Con alternativas, flag default',
            allocated_hours=40.0,
            user_ids=[(6, 0, [self.u1.id, self.u2.id])],
        )
        lines = self.project._tjp_task_block(task)
        self.assertNotIn('persistent', '\n'.join(lines))

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
            '  complete 0.00',
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

    def test_dependency_from_nested_task_uses_extra_bang_per_ancestor(self):
        """Bug real, confirmado empíricamente contra el binario real de TJ3
        (v3.8.4): antes de este fix, _tjp_task_abs_path siempre emitía UN
        solo '!' sin importar la profundidad de la tarea que declara el
        `depends` — TJ3 rechaza eso para cualquier tarea anidada
        dependiendo de una hermana bajo el mismo padre ("Error: Task a.c
        has unknown depends a.a.b", reproducido contra tj3-ms). TJ3
        resuelve cada '!' subiendo un nivel desde la tarea que declara la
        dependencia (no desde la raíz del proyecto) — acá 'dependent' está
        a profundidad 1 bajo 'parent', así que hacen falta 2 '!' (no 1)
        para que el resto del path ('t{parent}.t{blocker}') se interprete
        como global."""
        parent = self._task(name='Parent')
        blocker = self._task(name='Bloqueante', parent_id=parent.id)
        dependent = self._task(
            name='Dependiente', parent_id=parent.id,
            depend_on_ids=[(6, 0, [blocker.id])],
        )
        text = '\n'.join(self.project._tjp_task_block(parent))
        self.assertIn(f'depends !!t{parent.id}.t{blocker.id}', text)

    def test_dependency_multiple_blockers_share_task_type(self):
        """tj_dependency_type es el default de la tarea: sin overrides por
        arista (dependency_type_ids), se aplica igual a todos sus
        bloqueantes."""
        blocker1 = self._task(name='Bloqueante 1')
        blocker2 = self._task(name='Bloqueante 2')
        dependent = self._task(
            name='Dependiente', tj_dependency_type='SS',
            depend_on_ids=[(6, 0, [blocker1.id, blocker2.id])],
        )
        lines = self.project._tjp_task_block(dependent)
        self.assertIn(f'  depends !t{blocker1.id} {{ onstart }}', lines)
        self.assertIn(f'  depends !t{blocker2.id} {{ onstart }}', lines)

    def test_ff_not_selectable_as_task_level_default(self):
        """FF no es un default razonable para todos los bloqueantes de una
        tarea — solo tiene sentido como override puntual de una arista
        (ver dependency_type_ids), así que ni siquiera es una opción
        válida de tj_dependency_type."""
        blocker = self._task(name='Bloqueante')
        dependent = self._task(name='Dependiente', depend_on_ids=[(6, 0, [blocker.id])])
        with self.assertRaises(ValueError):
            dependent.tj_dependency_type = 'FF'

    def test_dependency_type_override_applies_only_to_its_own_edge(self):
        """Un override en dependency_type_ids cambia el tipo de UNA arista
        puntual sin afectar a los demás bloqueantes, que siguen usando el
        default de la tarea (tj_dependency_type)."""
        blocker1 = self._task(name='Bloqueante 1')
        blocker2 = self._task(name='Bloqueante 2')
        dependent = self._task(
            name='Dependiente', tj_dependency_type='FS',
            depend_on_ids=[(6, 0, [blocker1.id, blocker2.id])],
        )
        self.env['insight.task.dependency'].create({
            'task_id': dependent.id, 'depends_on_id': blocker1.id, 'dependency_type': 'SS',
        })
        lines = self.project._tjp_task_block(dependent)
        self.assertIn(f'  depends !t{blocker1.id} {{ onstart }}', lines)
        self.assertIn(f'  depends !t{blocker2.id}', lines)
        self.assertNotIn(f'  depends !t{blocker2.id} {{ onstart }}', lines)

    def test_dependency_type_override_ff_emits_precedes_onend(self):
        """FF real (sin hito sintético): `precedes {path} { onend }`,
        confirmado contra el binario real de tj3-ms (ver CHANGELOG) — ancla
        el FIN de esta tarea al fin del bloqueante."""
        blocker = self._task(name='Bloqueante FF')
        dependent = self._task(name='Dependiente', depend_on_ids=[(6, 0, [blocker.id])])
        self.env['insight.task.dependency'].create({
            'task_id': dependent.id, 'depends_on_id': blocker.id, 'dependency_type': 'FF',
        })
        lines = self.project._tjp_task_block(dependent)
        self.assertIn(f'  precedes !t{blocker.id} {{ onend }}', lines)
        self.assertFalse(any(l.strip().startswith('depends') for l in lines))

    def test_dependency_type_mixed_fs_and_ff_depends_before_precedes(self):
        """Regla dura confirmada empíricamente: si `precedes` se declara
        antes que `depends` en el bloque de la tarea, TJ3 rechaza el
        archivo ('Tasks with on-end dependencies must be ALAP scheduled')
        porque la última política declarada (ASAP/ALAP) gana. El export
        tiene que emitir siempre los `depends` FS/SS antes que el
        `precedes` FF, sea cual sea el orden de los bloqueantes en Odoo."""
        blocker_ff = self._task(name='Bloqueante FF')
        blocker_fs = self._task(name='Bloqueante FS')
        dependent = self._task(
            name='Dependiente mixto', tj_dependency_type='FS',
            # FF primero en depend_on_ids a propósito, para probar que el
            # orden de salida no depende del orden de entrada.
            depend_on_ids=[(6, 0, [blocker_ff.id, blocker_fs.id])],
        )
        self.env['insight.task.dependency'].create({
            'task_id': dependent.id, 'depends_on_id': blocker_ff.id, 'dependency_type': 'FF',
        })
        lines = self.project._tjp_task_block(dependent)
        depends_idx = next(i for i, l in enumerate(lines) if l.strip().startswith('depends'))
        precedes_idx = next(i for i, l in enumerate(lines) if l.strip().startswith('precedes'))
        self.assertLess(depends_idx, precedes_idx,
                         'depends debe ir antes que precedes en el bloque de la tarea')
        self.assertIn(f'  depends !t{blocker_fs.id}', lines)
        self.assertIn(f'  precedes !t{blocker_ff.id} {{ onend }}', lines)

    def test_dependency_type_mixed_ss_and_ff(self):
        blocker_ff = self._task(name='Bloqueante FF')
        blocker_ss = self._task(name='Bloqueante SS')
        dependent = self._task(
            name='Dependiente SS+FF', tj_dependency_type='SS',
            depend_on_ids=[(6, 0, [blocker_ss.id, blocker_ff.id])],
        )
        self.env['insight.task.dependency'].create({
            'task_id': dependent.id, 'depends_on_id': blocker_ff.id, 'dependency_type': 'FF',
        })
        lines = self.project._tjp_task_block(dependent)
        self.assertIn(f'  depends !t{blocker_ss.id} {{ onstart }}', lines)
        self.assertIn(f'  precedes !t{blocker_ff.id} {{ onend }}', lines)

    def test_dependency_type_two_ff_blockers_raises(self):
        """TJ3 3.8.4 solo respeta un `precedes { onend }` por tarea — con
        dos, ignora el segundo en silencio (confirmado empíricamente, tanto
        con líneas separadas como con lista por comas). Falla loud en vez
        de exportar un .tjp que TJ3 agenda mal sin avisar."""
        blocker1 = self._task(name='Bloqueante FF 1')
        blocker2 = self._task(name='Bloqueante FF 2')
        dependent = self._task(
            name='Dependiente con dos FF',
            depend_on_ids=[(6, 0, [blocker1.id, blocker2.id])],
        )
        self.env['insight.task.dependency'].create({
            'task_id': dependent.id, 'depends_on_id': blocker1.id, 'dependency_type': 'FF',
        })
        self.env['insight.task.dependency'].create({
            'task_id': dependent.id, 'depends_on_id': blocker2.id, 'dependency_type': 'FF',
        })
        with self.assertRaises(UserError):
            self.project._tjp_task_block(dependent)

    def test_dependency_type_override_requires_a_real_dependency(self):
        blocker = self._task(name='Bloqueante')
        not_a_blocker = self._task(name='No es bloqueante')
        dependent = self._task(name='Dependiente', depend_on_ids=[(6, 0, [blocker.id])])
        with self.assertRaises(ValidationError):
            self.env['insight.task.dependency'].create({
                'task_id': dependent.id, 'depends_on_id': not_a_blocker.id, 'dependency_type': 'SS',
            })

    def test_high_priority_emits_priority_line(self):
        task = self._task(name='Urgente', priority='1')
        lines = self.project._tjp_task_block(task)
        self.assertIn('  priority 800', lines)

    def test_low_priority_omits_priority_line(self):
        """Low es el default de Odoo y coincide con el default implícito de
        TJ3 (500) — no hace falta declarar la línea."""
        task = self._task(name='Normal', priority='0')
        lines = self.project._tjp_task_block(task)
        self.assertNotIn('  priority 800', '\n'.join(lines))
        self.assertFalse(any(l.strip().startswith('priority') for l in lines))

    def test_high_priority_applies_at_any_depth(self):
        root = self._task(name='Eje', priority='1')
        leaf = self._task(name='Cierre', parent_id=root.id, priority='1',
                           allocated_hours=8.0, user_ids=[(6, 0, [self.u1.id])])
        lines = self.project._tjp_task_block(root, depth=0)
        text = '\n'.join(lines)
        self.assertIn('  priority 800', text)
        self.assertIn('    priority 800', text)

    def test_default_resource_priority_omits_priority_line(self):
        """resource_priority default (10, project_improve) es 'neutral':
        cero cambio de comportamiento para proyectos que nunca tocaron el
        campo, igual que Low en task.priority."""
        self.assertEqual(self.project.resource_priority, 10)
        task = self._task(name='Sin configurar')
        lines = self.project._tjp_task_block(task)
        self.assertFalse(any(l.strip().startswith('priority') for l in lines))

    def test_higher_resource_priority_emits_value_above_default(self):
        self.project.resource_priority = 20
        task = self._task(name='Proyecto prioritario')
        lines = self.project._tjp_task_block(task)
        self.assertIn('  priority 600', '\n'.join(lines))
        self.project.resource_priority = 10

    def test_lower_resource_priority_emits_value_below_default(self):
        self.project.resource_priority = 5
        task = self._task(name='Proyecto de baja prioridad')
        lines = self.project._tjp_task_block(task)
        self.assertIn('  priority 450', '\n'.join(lines))
        self.project.resource_priority = 10

    def test_resource_priority_never_reaches_high_priority_ceiling(self):
        """Un resource_priority extremo satura en 799 — nunca puede igualar
        ni superar la estrella de tarea (_TJP_HIGH_PRIORITY = 800)."""
        self.project.resource_priority = 1000
        task = self._task(name='Prioridad extrema')
        lines = self.project._tjp_task_block(task)
        self.assertIn('  priority 799', '\n'.join(lines))
        self.project.resource_priority = 10

    def test_starred_task_wins_over_any_resource_priority(self):
        self.project.resource_priority = 1000
        task = self._task(name='Urgente en proyecto prioritario', priority='1')
        lines = self.project._tjp_task_block(task)
        self.assertIn('  priority 800', '\n'.join(lines))
        self.project.resource_priority = 10

    def test_two_projects_with_different_resource_priority_emit_different_values(self):
        """Criterio de aceptación de la Épica 1: dado un candidato en dos
        proyectos con distinta prioridad, cada uno emite un valor `priority`
        distinto en el .tjp combinado — TJ3 prioriza al de mayor valor."""
        other_project = self.env['project.project'].create({
            'name': 'Otro proyecto', 'is_tj_enabled': True,
            'date_start': '2026-06-29', 'resource_priority': 30,
        })
        self.project.resource_priority = 5
        task_a = self._task(name='Tarea A')
        task_b = self.env['project.task'].create({
            'name': 'Tarea B', 'project_id': other_project.id,
        })
        line_a = self.project._tjp_task_priority_line(task_a, '')
        line_b = other_project._tjp_task_priority_line(task_b, '')
        self.assertNotEqual(line_a, line_b)
        self.assertIn('priority 450', line_a)
        self.assertIn('priority 700', line_b)
        self.project.resource_priority = 10

    def test_extra_skill_group_emits_second_mandatory_allocate_entry(self):
        task = self._task(name='Par de desarrollo', allocated_hours=16.0, user_ids=[(6, 0, [self.u1.id])])
        self._skill_group(task, [self.u2.id])
        text = '\n'.join(self.project._tjp_task_block(task))
        self.assertIn(f'  allocate u{self.u1.id} {{', text)
        self.assertIn('    mandatory', text)
        self.assertIn(f'  }}, u{self.u2.id} {{', text)

    def test_single_pool_without_extra_groups_has_no_mandatory_keyword(self):
        """Sin extra_skill_group_ids, el output no cambia respecto a antes
        de este feature — ni rastro de `mandatory`."""
        task = self._task(name='Sin puestos extra', allocated_hours=8.0, user_ids=[(6, 0, [self.u1.id])])
        self.assertNotIn('mandatory', '\n'.join(self.project._tjp_task_block(task)))

    def test_extra_skill_group_without_candidates_raises(self):
        task = self._task(name='Puesto sin cubrir', allocated_hours=8.0, user_ids=[(6, 0, [self.u1.id])])
        group = self.env['project.task.skill.group'].create({
            'task_id': task.id,
            'required_skill_ids': [(6, 0, self.skill.ids)],
        })
        group.resource_pool_ids = [(6, 0, [])]
        with self.assertRaises(UserError):
            self.project._tjp_task_block(task)

    def test_missing_primary_pool_with_extra_group_raises(self):
        task = self._task(name='Sin pool principal', allocated_hours=8.0, user_ids=[(6, 0, [])])
        self._skill_group(task, [self.u2.id])
        with self.assertRaises(UserError):
            self.project._tjp_task_block(task)

    def test_project_users_includes_extra_skill_group_candidates(self):
        task = self._task(name='Con puesto extra', allocated_hours=8.0, user_ids=[(6, 0, [self.u1.id])])
        self._skill_group(task, [self.u2.id, self.u3.id])
        project_users = self.project._tj_project_users()
        self.assertIn(self.u2, project_users)
        self.assertIn(self.u3, project_users)

    def test_reports_one_per_scenario(self):
        plan = self.env['insight.scenario'].create(
            {'name': 'Plan', 'project_id': self.project.id, 'is_baseline': True})
        noai = self.env['insight.scenario'].create({'name': 'Noai', 'project_id': self.project.id})
        lines = self.project._tjp_reports(plan | noai)
        text = '\n'.join(lines)
        plan_id = self.project._tjp_scenario_id(plan)
        noai_id = self.project._tjp_scenario_id(noai)
        self.assertIn(f'taskreport "schedule_{plan_id}" {{', text)
        self.assertIn(f'  scenarios {plan_id}', text)
        self.assertIn(f'taskreport "schedule_{noai_id}" {{', text)
        self.assertIn(f'  scenarios {noai_id}', text)


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
        self._log_time(task, '2026-06-30', 3.0)
        lines = self.project._tjp_task_block(task, now_date=date(2026, 7, 1))
        self.assertIn(f'  booking u{self.user.id} 2026-06-30 +3.00h {{ overtime 2 }}', lines)

    def test_bookings_for_same_user_and_day_are_summed(self):
        task = self._task(name='Dos líneas mismo día', allocated_hours=40.0, user_ids=[(6, 0, [self.user.id])])
        self._log_time(task, '2026-06-30', 2.0)
        self._log_time(task, '2026-06-30', 1.5)
        lines = self.project._tjp_task_block(task, now_date=date(2026, 7, 1))
        self.assertIn(f'  booking u{self.user.id} 2026-06-30 +3.00h {{ overtime 2 }}', lines)
        self.assertEqual(
            sum(1 for l in lines if l.strip().startswith('booking')), 1,
            'Dos timesheets del mismo usuario/día deben colapsar en un solo booking',
        )

    def test_booking_hours_truncated_to_whole_hour(self):
        """TJ3 rechaza bookings cuya duración no sea múltiplo del
        timingresolution del proyecto (60 min, default de TJ3). Un timesheet
        con minutos sueltos (ej. 0.14h) generaba `+0.14h` y TJ3 fallaba con
        'interval duration must be a multiple of the specified timing
        resolution'. Se trunca a la hora entera."""
        task = self._task(name='Minutos sueltos', allocated_hours=40.0, user_ids=[(6, 0, [self.user.id])])
        self._log_time(task, '2026-06-30', 10.14)
        lines = self.project._tjp_task_block(task, now_date=date(2026, 7, 1))
        self.assertIn(f'  booking u{self.user.id} 2026-06-30 +10.00h {{ overtime 2 }}', lines)

    def test_booking_omitted_when_truncated_hours_are_zero(self):
        task = self._task(name='Menos de una hora', allocated_hours=40.0, user_ids=[(6, 0, [self.user.id])])
        self._log_time(task, '2026-06-30', 0.14)
        lines = self.project._tjp_task_block(task, now_date=date(2026, 7, 1))
        self.assertFalse(any(l.strip().startswith('booking') for l in lines))

    def test_booking_truncation_applies_to_summed_total_not_each_line(self):
        """El truncamiento debe aplicarse sobre la suma agrupada por
        (usuario, día), no línea por línea — si se truncara cada timesheet
        individualmente, dos líneas de 0.6h (que suman 1.2h reales) perderían
        toda la hora en vez de solo los 0.2h sobrantes."""
        task = self._task(name='Dos líneas fraccionarias', allocated_hours=40.0, user_ids=[(6, 0, [self.user.id])])
        self._log_time(task, '2026-06-30', 0.6)
        self._log_time(task, '2026-06-30', 0.6)
        lines = self.project._tjp_task_block(task, now_date=date(2026, 7, 1))
        self.assertIn(f'  booking u{self.user.id} 2026-06-30 +1.00h {{ overtime 2 }}', lines)

    def test_booking_allows_overtime_beyond_daily_calendar_capacity(self):
        """Un timesheet puede superar la capacidad de calendario del
        recurso ese día (horas extra). Sin `overtime`, TJ3 intenta
        completar la duración derramándose al próximo día hábil con lugar
        — si ese día cae en o después de `now` (fin de semana/feriado de
        por medio), falla con 'has no duty'. `overtime 2` evita el
        derrame dejando que la duración se cubra el mismo día."""
        task = self._task(name='Horas extra', allocated_hours=40.0, user_ids=[(6, 0, [self.user.id])])
        self._log_time(task, '2026-06-30', 12.0)
        lines = self.project._tjp_task_block(task, now_date=date(2026, 7, 1))
        self.assertIn(f'  booking u{self.user.id} 2026-06-30 +12.00h {{ overtime 2 }}', lines)

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
        self.assertIn(f'  booking u{helper_user.id} 2026-06-30 +3.00h {{ overtime 2 }}', text)
        # No se lo agrega como candidato de asignación futura de la tarea.
        self.assertNotIn(f'allocate u{helper_user.id}', text)

    def test_complete_reflects_task_progress(self):
        """complete no lo calcula TJ3 (ver discusión de diseño en el
        CHANGELOG) — es un espejo de project.task.progress (horas
        imputadas / allocated_hours) al momento del export."""
        task = self._task(name='A mitad de camino', allocated_hours=10.0, user_ids=[(6, 0, [self.user.id])])
        self._log_time(task, '2026-06-30', 5.0)
        self.assertEqual(task.progress, 50.0)
        lines = self.project._tjp_task_block(task, now_date=date(2026, 7, 1))
        self.assertIn('  complete 50.00', lines)

    def test_complete_clamped_to_100_with_overtime(self):
        """task.progress puede superar 100 (overtime); TJ3 rechaza
        `complete` fuera de [0, 100], así que se clampea."""
        task = self._task(name='Con overtime', allocated_hours=5.0, user_ids=[(6, 0, [self.user.id])])
        self._log_time(task, '2026-06-30', 8.0)
        self.assertGreater(task.progress, 100.0)
        lines = self.project._tjp_task_block(task, now_date=date(2026, 7, 1))
        self.assertIn('  complete 100.00', lines)

    def test_complete_zero_without_any_hours_logged(self):
        task = self._task(name='Sin avance', allocated_hours=10.0, user_ids=[(6, 0, [self.user.id])])
        lines = self.project._tjp_task_block(task, now_date=date(2026, 7, 1))
        self.assertIn('  complete 0.00', lines)


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
        cls.scenario = cls.env['insight.scenario'].create(
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
        sc_id = self.project._tjp_scenario_id(self.scenario)
        self.assertIn(f'taskreport "schedule_{sc_id}"', tjp)


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
