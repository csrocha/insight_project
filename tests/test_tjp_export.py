# -*- coding: utf-8 -*-
"""Regression tests for the TJP generator (models/project_project.py).

The task/resource shapes below mirror structural patterns seen in a real
exported .tjp — deep task nesting, a leaf task allocated to several
resources at once, "empty" leaf tasks with no effort used as milestones/
summary points, a resource with no linked hr.employee, and a root scenario
with nested alternates — so the generator's textual output stays pinned
even though the project content used here is synthetic.
"""
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase


class TestTjpProjectHeader(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env['project.project'].create({
            'name': 'IT Plan',
            'is_tj_enabled': True,
            'tj_now': '2026-06-29',
        })

    def test_project_id_and_dates_in_header(self):
        lines = self.project._tjp_project_header([])
        self.assertTrue(
            lines[0].startswith(f'project p{self.project.id} "IT Plan" 2026-06-29 - '),
            lines[0],
        )
        self.assertIn('  timezone "America/Argentina/Buenos_Aires"', lines)
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
            'tj_now': '2026-06-29',
        })

    def test_explicit_horizon_wins(self):
        self.project.tj_end_date = '2027-01-01'
        end = self.project._tjp_project_end_date(self.project.tj_now)
        self.assertEqual(str(end), '2027-01-01')

    def test_falls_back_to_two_years_without_deadlines(self):
        end = self.project._tjp_project_end_date(self.project.tj_now)
        self.assertEqual(str(end), '2028-06-29')

    def test_derives_horizon_from_latest_task_deadline(self):
        self.env['project.task'].create({
            'name': 'Deadline task',
            'project_id': self.project.id,
            'date_deadline': '2026-09-01 00:00:00',
        })
        end = self.project._tjp_project_end_date(self.project.tj_now)
        # latest deadline (2026-09-01) + max((latest-start).days // 3, 30)
        self.assertGreater(str(end), '2026-09-01')
        self.assertGreaterEqual((end - self.project.tj_now).days, 64 + 30)


class TestTjpResourceBlock(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env['project.project'].create({
            'name': 'Resource Block Project',
            'is_tj_enabled': True,
            'tj_now': '2026-06-29',
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


class TestTjpTaskBlock(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env['project.project'].create({
            'name': 'Task Block Project',
            'is_tj_enabled': True,
            'tj_now': '2026-06-29',
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
            '}',
            '',
        ])

    def test_milestone_emits_milestone_keyword(self):
        task = self._task(name='Milestone Task', is_milestone=True, allocated_hours=8.0)
        lines = self.project._tjp_task_block(task)
        self.assertIn('  milestone', lines)
        self.assertNotIn('  effort 1.00d', lines)

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


class TestGenerateTjpEndToEnd(TransactionCase):
    """Smoke test: _generate_tjp must assemble header + resources + tasks +
    reports into one syntactically balanced document without raising."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env['project.project'].create({
            'name': 'Full Plan',
            'is_tj_enabled': True,
            'tj_now': '2026-06-29',
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
