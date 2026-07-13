# -*- coding: utf-8 -*-
"""Regression tests for the cost breakdown reports (fase/skill/departamento,
ver models/project_project.py). Fase y skill se calculan con cuentas TJ3
reales (nunca contra el servicio real — _call_tj_microservice siempre
mockeado acá); departamento se calcula 100% en Python sobre
insight.task.schedule ya importado, sin llamar a TJ3 en absoluto.
"""
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase

from ..models.project_project import ProjectProject


class TestTjpPhaseSkillAccountLines(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env['project.project'].create({
            'name': 'Cost Report Accounts Project', 'is_tj_enabled': True,
        })
        skill_type = cls.env['hr.skill.type'].create({
            'name': 'Cost Report Skill Type',
            'skill_level_ids': [(0, 0, {
                'name': 'Expert', 'level_progress': 100, 'default_level': True,
            })],
        })
        cls.skill_python = cls.env['hr.skill'].create({
            'name': 'Python', 'skill_type_id': skill_type.id,
        })
        cls.root = cls.env['project.task'].create({
            'name': 'Fase 1', 'project_id': cls.project.id,
        })

    def test_phase_account_declared_with_leaf_per_root_task(self):
        lines = self.project._tjp_phase_skill_account_lines(self.root, self.env['hr.skill'])
        text = '\n'.join(lines)
        self.assertIn('account by_phase "Por fase" {', text)
        self.assertIn(f'  account phase_{self.root.id} "Fase 1"', text)
        self.assertNotIn('by_skill', text)

    def test_skill_account_declared_with_leaf_per_skill(self):
        lines = self.project._tjp_phase_skill_account_lines(self.env['project.task'], self.skill_python)
        text = '\n'.join(lines)
        self.assertIn('account by_skill "Por categoría" {', text)
        self.assertIn(f'  account skill_{self.skill_python.id} "Python"', text)
        self.assertNotIn('by_phase', text)

    def test_no_accounts_declared_when_both_empty(self):
        lines = self.project._tjp_phase_skill_account_lines(
            self.env['project.task'], self.env['hr.skill'],
        )
        self.assertEqual(lines, [])


class TestTjpExtraChargesetFn(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env['project.project'].create({
            'name': 'Chargeset Fn Project', 'is_tj_enabled': True,
        })
        skill_type = cls.env['hr.skill.type'].create({
            'name': 'Chargeset Skill Type',
            'skill_level_ids': [(0, 0, {
                'name': 'Expert', 'level_progress': 100, 'default_level': True,
            })],
        })
        cls.skill_a, cls.skill_b = cls.env['hr.skill'].create([
            {'name': 'Skill A', 'skill_type_id': skill_type.id},
            {'name': 'Skill B', 'skill_type_id': skill_type.id},
        ])
        cls.root = cls.env['project.task'].create({'name': 'Root', 'project_id': cls.project.id})
        cls.leaf_one_skill = cls.env['project.task'].create({
            'name': 'Leaf one skill', 'project_id': cls.project.id, 'parent_id': cls.root.id,
            'required_skill_ids': [(6, 0, [cls.skill_a.id])],
        })
        cls.leaf_two_skills = cls.env['project.task'].create({
            'name': 'Leaf two skills', 'project_id': cls.project.id, 'parent_id': cls.root.id,
            'required_skill_ids': [(6, 0, [cls.skill_a.id, cls.skill_b.id])],
        })
        cls.leaf_no_skill = cls.env['project.task'].create({
            'name': 'Leaf no skill', 'project_id': cls.project.id, 'parent_id': cls.root.id,
        })

    def test_root_task_gets_phase_chargeset(self):
        leaf_ids = self.project._tjp_leaf_task_ids()
        fn = self.project._tjp_extra_chargeset_fn(leaf_ids)
        self.assertEqual(fn(self.root, 0), [f'chargeset phase_{self.root.id}'])

    def test_leaf_with_one_skill_gets_single_chargeset(self):
        leaf_ids = self.project._tjp_leaf_task_ids()
        fn = self.project._tjp_extra_chargeset_fn(leaf_ids)
        self.assertEqual(fn(self.leaf_one_skill, 1), [f'chargeset skill_{self.skill_a.id}'])

    def test_leaf_with_two_skills_gets_comma_joined_chargeset(self):
        leaf_ids = self.project._tjp_leaf_task_ids()
        fn = self.project._tjp_extra_chargeset_fn(leaf_ids)
        lines = fn(self.leaf_two_skills, 1)
        self.assertEqual(len(lines), 1)
        self.assertIn(f'skill_{self.skill_a.id}', lines[0])
        self.assertIn(f'skill_{self.skill_b.id}', lines[0])
        self.assertTrue(lines[0].startswith('chargeset '))

    def test_leaf_without_skills_gets_no_chargeset(self):
        leaf_ids = self.project._tjp_leaf_task_ids()
        fn = self.project._tjp_extra_chargeset_fn(leaf_ids)
        self.assertEqual(fn(self.leaf_no_skill, 1), [])


class TestParseAccountreportCsv(TransactionCase):

    def test_takes_last_period_column_not_sum(self):
        """Las columnas de período son ACUMULADAS a la fecha (confirmado
        contra el binario real) — sumarlas duplicaría/triplicaría el
        costo. El valor correcto es el de la última columna."""
        csv_content = (
            '"Id";"BSI";"Name";"2026-07-01";"2026-08-01";"2026-09-01"\n'
            '"phase_1";"1.1";"Fase 1";0.0;300.0;300.0\n'
            '"phase_2";"1.2";"Fase 2";0.0;500.0;500.0\n'
        )
        result = ProjectProject._parse_accountreport_csv(csv_content)
        self.assertEqual(result['phase_1'], 300.0)
        self.assertEqual(result['phase_2'], 500.0)

    def test_empty_csv_returns_empty_dict(self):
        self.assertEqual(ProjectProject._parse_accountreport_csv(''), {})

    def test_row_without_period_columns_is_skipped(self):
        csv_content = '"Id";"Name"\n"phase_1";"Fase 1"\n'
        self.assertEqual(ProjectProject._parse_accountreport_csv(csv_content), {})


class TestCostByDepartment(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env['project.project'].create({
            'name': 'Department Cost Project', 'is_tj_enabled': True,
        })
        cls.scenario = cls.env['insight.scenario'].create({
            'name': 'Plan', 'project_id': cls.project.id, 'is_baseline': True,
        })
        cls.dept_dev = cls.env['hr.department'].create({'name': 'Desarrollo'})
        cls.dept_qa = cls.env['hr.department'].create({'name': 'QA'})

        cls.user_dev, cls.user_qa, cls.user_no_employee = cls.env['res.users'].with_context(
            no_reset_password=True,
        ).create([
            {
                'name': f'DeptUser{i}', 'login': f'deptuser{i}@insight.test',
                'email': f'deptuser{i}@insight.test',
                'groups_id': [(4, cls.env.ref('base.group_user').id)],
            }
            for i in range(3)
        ])
        cls.env['hr.employee'].create({
            'name': 'DeptUser0', 'user_id': cls.user_dev.id, 'department_id': cls.dept_dev.id,
        })
        cls.env['hr.employee'].create({
            'name': 'DeptUser1', 'user_id': cls.user_qa.id, 'department_id': cls.dept_qa.id,
        })
        # user_no_employee tiene res.users pero ningún hr.employee vinculado.

        cls.task_dev = cls.env['project.task'].create({'name': 'Dev only', 'project_id': cls.project.id})
        cls.task_mixed = cls.env['project.task'].create({'name': 'Dev + QA', 'project_id': cls.project.id})
        cls.task_unassigned = cls.env['project.task'].create({'name': 'Sin empleado', 'project_id': cls.project.id})

    def _schedule(self, task, users, cost):
        return self.env['insight.task.schedule'].create({
            'task_id': task.id, 'scenario_id': self.scenario.id,
            'cost': cost, 'resource_ids': [(6, 0, [u.id for u in users])],
        })

    def test_single_department_gets_full_cost(self):
        self._schedule(self.task_dev, [self.user_dev], 1000.0)
        totals = self.project._cost_by_department(self.scenario)
        self.assertEqual(totals.get('Desarrollo'), 1000.0)

    def test_two_departments_split_evenly(self):
        self._schedule(self.task_mixed, [self.user_dev, self.user_qa], 1000.0)
        totals = self.project._cost_by_department(self.scenario)
        self.assertEqual(totals.get('Desarrollo'), 500.0)
        self.assertEqual(totals.get('QA'), 500.0)

    def test_user_without_employee_falls_back_to_unassigned_bucket(self):
        self._schedule(self.task_unassigned, [self.user_no_employee], 400.0)
        totals = self.project._cost_by_department(self.scenario)
        self.assertEqual(totals.get('Sin departamento'), 400.0)

    def test_totals_sum_to_grand_total_without_double_counting(self):
        self._schedule(self.task_dev, [self.user_dev], 1000.0)
        self._schedule(self.task_mixed, [self.user_dev, self.user_qa], 1000.0)
        self._schedule(self.task_unassigned, [self.user_no_employee], 400.0)
        totals = self.project._cost_by_department(self.scenario)
        self.assertEqual(sum(totals.values()), 2400.0)


class TestComputeAndSaveCostReports(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env['project.project'].create({
            'name': 'Cost Reports E2E Project', 'is_tj_enabled': True, 'date_start': '2026-07-06',
        })
        cls.scenario = cls.env['insight.scenario'].create({
            'name': 'Plan', 'project_id': cls.project.id, 'is_baseline': True,
        })
        cls.root = cls.env['project.task'].create({
            'name': 'Fase 1', 'project_id': cls.project.id, 'allocated_hours': 40.0,
            'user_ids': [(6, 0, [])],
        })
        cls.env['ir.config_parameter'].sudo().set_param(
            'insight_project.tj_microservice_url', 'http://tj3.local',
        )

    def _mock_csv_files(self):
        phase_csv = (
            '"Id";"BSI";"Name";"2026-07-01";"2026-08-01"\n'
            f'"phase_{self.root.id}";"1";"Fase 1";0.0;3200.0\n'
        )
        return {f'{self.project._TJP_PHASE_REPORT_ID}.csv': phase_csv}

    def test_generates_three_snapshots_with_correct_metadata(self):
        with patch.object(ProjectProject, '_call_tj_microservice', return_value={'csv_files': self._mock_csv_files()}):
            self.project._compute_and_save_cost_reports(self.scenario)

        assets = self.env['knowledge.asset'].search([
            ('res_model', '=', 'insight.scenario'), ('res_id', '=', self.scenario.id),
            ('category', '=', 'insight_project.cost_report'),
        ])
        self.assertEqual(len(assets), 3)
        self.assertEqual(set(assets.mapped('tags')), {'phase', 'skill', 'department'})
        for asset in assets:
            self.assertEqual(asset.visibility, 'shared')
            self.assertTrue(asset.shared_group_ids)
            version = asset.latest_version()
            self.assertEqual(version.version, 1)
            self.assertTrue(version.schema.startswith('insight_project.cost_by_'))

    def test_second_call_creates_new_version_not_new_asset(self):
        with patch.object(ProjectProject, '_call_tj_microservice', return_value={'csv_files': self._mock_csv_files()}):
            self.project._compute_and_save_cost_reports(self.scenario)
            self.project._compute_and_save_cost_reports(self.scenario)

        assets = self.env['knowledge.asset'].search([
            ('res_model', '=', 'insight.scenario'), ('res_id', '=', self.scenario.id),
            ('category', '=', 'insight_project.cost_report'),
        ])
        self.assertEqual(len(assets), 3, 'debe reusar los mismos 3 assets, no duplicarlos')
        for asset in assets:
            self.assertEqual(len(asset.version_ids), 2)
            self.assertEqual(asset.latest_version().version, 2)

    def test_blocked_when_schedule_dirty(self):
        self.project.schedule_dirty = True
        with self.assertRaises(UserError):
            self.project._compute_and_save_cost_reports(self.scenario)
        self.project.schedule_dirty = False

    def test_action_run_schedule_alone_creates_no_snapshot(self):
        """El disparo es explícito ('Generar reportes de costos'), nunca
        automático en un reschedule normal."""
        sc_id = self.project._tjp_scenario_id(self.scenario)
        csv_content = (
            '"Id";"Bsi";"Name";"Start";"End";"Effort";"Duration";"Resources";"Criticalness"\n'
            f'"t{self.root.id}";"1";"Fase 1";"2026-07-06";"2026-07-10";"5.0d";"5.0d";"";"0"\n'
        )
        with patch.object(
            ProjectProject, '_call_tj_microservice',
            return_value={'csv_files': {f'schedule_{sc_id}.csv': csv_content}},
        ):
            self.project.action_run_schedule(interactive=False)

        count = self.env['knowledge.asset'].search_count([
            ('res_model', '=', 'insight.scenario'), ('res_id', '=', self.scenario.id),
            ('category', '=', 'insight_project.cost_report'),
        ])
        self.assertEqual(count, 0)


class TestActionGenerateCostReportsGuards(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env['project.project'].create({
            'name': 'Cost Reports Guard Project', 'is_tj_enabled': True,
        })

    def test_project_wrapper_requires_baseline_scenario(self):
        with self.assertRaises(UserError):
            self.project.action_generate_cost_reports()
