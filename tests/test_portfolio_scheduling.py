# -*- coding: utf-8 -*-
"""Regression tests for portfolio scheduling (project.project.state
draft/evaluation/progress from project_improve, _tj_portfolio_recordset,
multi-project _generate_tjp/_tj_project_users, and the write-back asymmetry
in _import_all_schedules — see BACKLOG.md item 3 / memoria
project_portfolio_scheduling_states)."""
from odoo.tests.common import TransactionCase


class TestPortfolioRecordset(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.active = cls.env['project.project'].create({
            'name': 'Active Project', 'is_tj_enabled': True, 'state': 'evaluation',
        })
        cls.progress1 = cls.env['project.project'].create({
            'name': 'Progress 1', 'is_tj_enabled': True, 'state': 'progress',
        })
        cls.progress2 = cls.env['project.project'].create({
            'name': 'Progress 2', 'is_tj_enabled': True, 'state': 'progress',
        })
        cls.draft = cls.env['project.project'].create({
            'name': 'Draft Project', 'is_tj_enabled': True, 'state': 'draft',
        })

    def test_combines_all_progress_projects_with_self(self):
        combined = self.active._tj_portfolio_recordset()
        self.assertEqual(combined, self.active | self.progress1 | self.progress2)
        self.assertNotIn(self.draft, combined)

    def test_progress_project_includes_itself_and_peers(self):
        combined = self.progress1._tj_portfolio_recordset()
        self.assertIn(self.progress1, combined)
        self.assertIn(self.progress2, combined)


class TestMultiProjectGeneration(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Shared Resource', 'login': 'shared_resource@insight.test',
            'email': 'shared_resource@insight.test',
            'groups_id': [(4, cls.env.ref('base.group_user').id)],
        })
        cls.project_a = cls.env['project.project'].create({
            'name': 'Project A', 'is_tj_enabled': True, 'state': 'evaluation',
        })
        cls.project_b = cls.env['project.project'].create({
            'name': 'Project B', 'is_tj_enabled': True, 'state': 'progress',
        })
        cls.task_a = cls.env['project.task'].create({
            'name': 'Task A', 'project_id': cls.project_a.id,
            'allocated_hours': 8.0, 'user_ids': [(6, 0, [cls.user.id])],
        })
        cls.task_b = cls.env['project.task'].create({
            'name': 'Task B', 'project_id': cls.project_b.id,
            'allocated_hours': 8.0, 'user_ids': [(6, 0, [cls.user.id])],
        })
        cls.scenario_a = cls.env['insight.scenario'].create({
            'name': 'Default', 'project_id': cls.project_a.id, 'is_baseline': True,
        })
        cls.scenario_b = cls.env['insight.scenario'].create({
            'name': 'Default', 'project_id': cls.project_b.id, 'is_baseline': True,
        })

    def test_tjp_scenario_id_is_qualified_by_project(self):
        """Dos escenarios con el mismo nombre en proyectos distintos no
        deben colisionar al combinarse en una sola corrida."""
        id_a = self.project_a._tjp_scenario_id(self.scenario_a)
        id_b = self.project_a._tjp_scenario_id(self.scenario_b)
        self.assertNotEqual(id_a, id_b)

    def test_combined_tjp_declares_shared_resource_once(self):
        combined = self.project_a | self.project_b
        tjp = combined._generate_tjp(active_project=self.project_a)
        res_id = combined._tjp_resource_id(self.user.partner_id.id)
        self.assertEqual(
            tjp.count(f'resource {res_id}'), 1,
            'Un recurso compartido por dos proyectos combinados debe declararse una sola vez',
        )

    def test_combined_tjp_includes_both_task_trees(self):
        combined = self.project_a | self.project_b
        tjp = combined._generate_tjp(active_project=self.project_a)
        self.assertIn(f'task {combined._tjp_task_id(self.task_a)}', tjp)
        self.assertIn(f'task {combined._tjp_task_id(self.task_b)}', tjp)

    def test_single_project_generation_is_unchanged(self):
        """N=1 no debe ser un caso especial: mismo resultado que antes."""
        tjp = self.project_a._generate_tjp()
        self.assertIn(f'project p{self.project_a.id}', tjp)
        self.assertIn(f'task {self.project_a._tjp_task_id(self.task_a)}', tjp)
        self.assertNotIn(f'task {self.project_a._tjp_task_id(self.task_b)}', tjp)


class TestImportAllSchedulesPortfolio(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project_a = cls.env['project.project'].create({
            'name': 'Active Eval Project', 'is_tj_enabled': True, 'state': 'evaluation',
        })
        cls.project_b = cls.env['project.project'].create({
            'name': 'Progress Peer Project', 'is_tj_enabled': True, 'state': 'progress',
        })
        cls.scenario_a = cls.env['insight.scenario'].create({
            'name': 'Plan', 'project_id': cls.project_a.id, 'is_baseline': True,
        })
        cls.scenario_b = cls.env['insight.scenario'].create({
            'name': 'Plan', 'project_id': cls.project_b.id, 'is_baseline': True,
        })
        cls.task_a = cls.env['project.task'].create({'name': 'Task A', 'project_id': cls.project_a.id})
        cls.task_b = cls.env['project.task'].create({'name': 'Task B', 'project_id': cls.project_b.id})

    @staticmethod
    def _csv_multi(tasks_and_ends):
        header = '"Id";"Bsi";"Name";"Start";"End";"Effort";"Duration";"Resources";"Criticalness"\n'
        rows = ''.join(
            f'"t{task.id}";"1";"Task";"2024-01-01";"{end}";"5.0d";"5.0d";"";"0"\n'
            for task, end in tasks_and_ends
        )
        return header + rows

    def test_evaluation_mode_persists_only_active_project(self):
        combined = self.project_a | self.project_b
        csv_files = {
            f'schedule_{self.project_a._tjp_scenario_id(self.scenario_a)}.csv':
                self._csv_multi([(self.task_a, '2024-01-10'), (self.task_b, '2024-01-15')]),
        }
        imported = combined._import_all_schedules(csv_files, active_project=self.project_a)
        self.assertEqual(imported, 1)
        self.assertTrue(self.env['insight.task.schedule'].search([
            ('task_id', '=', self.task_a.id), ('scenario_id', '=', self.scenario_a.id),
        ]))
        self.assertFalse(
            self.env['insight.task.schedule'].search([('task_id', '=', self.task_b.id)]),
            'Un proyecto en progreso no debe persistir schedule nuevo mientras el '
            'proyecto activo solo está en evaluación',
        )

    def test_progress_mode_persists_all_included_projects(self):
        self.project_a.state = 'progress'
        combined = self.project_a | self.project_b
        csv_files = {
            f'schedule_{self.project_a._tjp_scenario_id(self.scenario_a)}.csv':
                self._csv_multi([(self.task_a, '2024-01-10'), (self.task_b, '2024-01-15')]),
        }
        combined._import_all_schedules(csv_files, active_project=self.project_a)
        self.assertTrue(self.env['insight.task.schedule'].search([
            ('task_id', '=', self.task_a.id), ('scenario_id', '=', self.scenario_a.id),
        ]))
        self.assertTrue(self.env['insight.task.schedule'].search([
            ('task_id', '=', self.task_b.id), ('scenario_id', '=', self.scenario_b.id),
        ]), 'En modo progreso, los proyectos pares incluidos en la corrida sí se persisten')

    def test_evaluation_mode_reports_date_slip_for_peer_project(self):
        # Simula que Project B ya tenía un schedule comprometido (ej. de una
        # corrida 'progress' anterior) con Task B terminando el 2024-01-05.
        self.project_b._import_scenario_csv(
            self._csv_multi([(self.task_b, '2024-01-05')]), self.scenario_b,
        )

        combined = self.project_a | self.project_b
        csv_files = {
            f'schedule_{self.project_a._tjp_scenario_id(self.scenario_a)}.csv':
                self._csv_multi([(self.task_a, '2024-01-10'), (self.task_b, '2024-01-15')]),
        }
        combined._import_all_schedules(csv_files, active_project=self.project_a)

        asset = self.env['knowledge.asset'].search([
            ('res_model', '=', 'project.project'), ('res_id', '=', self.project_a.id),
            ('category', '=', 'insight_project.evaluation_impact_report'),
        ])
        self.assertTrue(asset, 'Debe publicarse un reporte de impacto cuando un proyecto par se ve afectado')
        payload = asset.latest_version().payload
        projects_payload = payload['projects']
        self.assertEqual(len(projects_payload), 1)
        self.assertEqual(projects_payload[0]['project_id'], self.project_b.id)
        self.assertEqual(projects_payload[0]['max_slip_days'], 10)
        # Project B no debe haber sido tocado: sigue con su schedule viejo.
        schedule_b = self.env['insight.task.schedule'].search([
            ('task_id', '=', self.task_b.id), ('scenario_id', '=', self.scenario_b.id),
        ])
        self.assertEqual(str(schedule_b.end_scheduled.date()), '2024-01-05')

    def test_no_impact_report_when_nothing_changes_for_peers(self):
        combined = self.project_a | self.project_b
        csv_files = {
            f'schedule_{self.project_a._tjp_scenario_id(self.scenario_a)}.csv':
                self._csv_multi([(self.task_a, '2024-01-10')]),
        }
        combined._import_all_schedules(csv_files, active_project=self.project_a)
        count = self.env['knowledge.asset'].search_count([
            ('res_model', '=', 'project.project'), ('res_id', '=', self.project_a.id),
            ('category', '=', 'insight_project.evaluation_impact_report'),
        ])
        self.assertEqual(count, 0)
