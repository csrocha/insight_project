# -*- coding: utf-8 -*-
"""Regression tests for the cost breakdown reports (fase/skill/departamento,
ver models/project_project.py). Las 3 dimensiones se calculan 100% en Python
sobre insight.task.schedule ya importado — _call_tj_microservice solo se
mockea para poblar ese schedule (vía action_run_schedule), nunca para pedir
un desglose de costo aparte.
"""
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase

from ..models.project_project import ProjectProject


class TestCostByPhaseAndSkill(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env['project.project'].create({
            'name': 'Phase Skill Cost Project', 'is_tj_enabled': True,
        })
        cls.scenario = cls.env['insight.scenario'].create({
            'name': 'Plan', 'project_id': cls.project.id, 'is_baseline': True,
        })
        skill_type = cls.env['hr.skill.type'].create({
            'name': 'Phase Skill Cost Type',
            'skill_level_ids': [(0, 0, {
                'name': 'Expert', 'level_progress': 100, 'default_level': True,
            })],
        })
        cls.skill_a, cls.skill_b = cls.env['hr.skill'].create([
            {'name': 'Skill A', 'skill_type_id': skill_type.id},
            {'name': 'Skill B', 'skill_type_id': skill_type.id},
        ])
        cls.root = cls.env['project.task'].create({'name': 'Fase 1', 'project_id': cls.project.id})
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

    def _schedule(self, task, cost):
        return self.env['insight.task.schedule'].create({
            'task_id': task.id, 'scenario_id': self.scenario.id, 'cost': cost,
        })

    def test_phase_cost_is_root_task_own_cost(self):
        """TJ3 ya acumula el costo de las subtareas en la raíz (mismo dato
        que insight.scenario.total_cost) — no hace falta ninguna cuenta
        TJ3 aparte para "costo por fase"."""
        self._schedule(self.root, 3200.0)
        phase_costs, _ = self.project._tj_cost_by_phase_and_skill(self.scenario)
        self.assertEqual(phase_costs.get(self.root), 3200.0)

    def test_leaf_with_one_skill_gets_full_cost(self):
        self._schedule(self.leaf_one_skill, 100.0)
        _, skill_costs = self.project._tj_cost_by_phase_and_skill(self.scenario)
        self.assertEqual(skill_costs.get(self.skill_a), 100.0)

    def test_leaf_with_two_skills_splits_evenly(self):
        self._schedule(self.leaf_two_skills, 200.0)
        _, skill_costs = self.project._tj_cost_by_phase_and_skill(self.scenario)
        self.assertEqual(skill_costs.get(self.skill_a), 100.0)
        self.assertEqual(skill_costs.get(self.skill_b), 100.0)

    def test_leaf_without_skills_contributes_nothing(self):
        self._schedule(self.leaf_no_skill, 50.0)
        _, skill_costs = self.project._tj_cost_by_phase_and_skill(self.scenario)
        self.assertEqual(skill_costs, {})

    def test_skill_costs_accumulate_across_leaves(self):
        self._schedule(self.leaf_one_skill, 100.0)
        self._schedule(self.leaf_two_skills, 200.0)
        _, skill_costs = self.project._tj_cost_by_phase_and_skill(self.scenario)
        self.assertEqual(skill_costs.get(self.skill_a), 200.0)
        self.assertEqual(skill_costs.get(self.skill_b), 100.0)

    def test_blocked_when_schedule_dirty(self):
        self.project.schedule_dirty = True
        with self.assertRaises(UserError):
            self.project._tj_cost_by_phase_and_skill(self.scenario)
        self.project.schedule_dirty = False


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

    def _seed_schedule(self):
        """Simula el insight.task.schedule que deja una corrida real de
        'Ejecutar Schedule' (ver _import_scenario_csv) — de ahí en más,
        _compute_and_save_cost_reports calcula fase/skill/departamento
        100% en Python, sin llamar a TJ3."""
        self.env['insight.task.schedule'].create({
            'task_id': self.root.id, 'scenario_id': self.scenario.id, 'cost': 3200.0,
        })

    def test_generates_three_snapshots_with_correct_metadata(self):
        self._seed_schedule()
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
        self._seed_schedule()
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


class TestReportCostReportHtml(TransactionCase):
    """report.insight_project.report_cost_report_html: arma filas/
    porcentajes desde el payload del asset — el QWeb del template solo
    itera lo que este método ya preparó."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env['project.project'].create({
            'name': 'Report Model Project', 'is_tj_enabled': True,
        })
        cls.scenario = cls.env['insight.scenario'].create({
            'name': 'Plan', 'project_id': cls.project.id, 'is_baseline': True,
        })
        cls.asset = cls.env['knowledge.asset'].create({
            'name': 'Costo por fase', 'res_model': 'insight.scenario',
            'res_id': cls.scenario.id, 'category': 'insight_project.cost_report',
            'tags': 'phase',
        })
        cls.asset.create_version({
            'title': 'Costo por fase', 'currency': 'ARS',
            'generated_at': '2026-07-13 20:00:00',
            'items': [{'label': 'Fase 1', 'cost': 5000.0}, {'label': 'Fase 2', 'cost': 3000.0}],
            'total': 8000.0,
        }, schema='insight_project.cost_by_phase')

    def test_get_report_values_returns_docs_and_reports(self):
        Report = self.env['report.insight_project.report_cost_report_html']
        values = Report._get_report_values(self.asset.ids)
        self.assertEqual(values['docs'], self.asset)
        self.assertEqual(len(values['reports']), 1)
        report = values['reports'][0]
        self.assertEqual(report['title'], 'Costo por fase')
        self.assertEqual(report['total'], 8000.0)
        self.assertEqual(len(report['rows']), 2)

    def test_bar_percent_is_relative_to_max(self):
        Report = self.env['report.insight_project.report_cost_report_html']
        report = Report._get_report_values(self.asset.ids)['reports'][0]
        by_label = {row['label']: row['percent'] for row in report['rows']}
        self.assertEqual(by_label['Fase 1'], 100.0)
        self.assertEqual(by_label['Fase 2'], 60.0)

    def test_asset_without_version_yields_empty_rows(self):
        empty_asset = self.env['knowledge.asset'].create({
            'name': 'Sin versión', 'category': 'insight_project.cost_report',
        })
        Report = self.env['report.insight_project.report_cost_report_html']
        report = Report._get_report_values(empty_asset.ids)['reports'][0]
        self.assertEqual(report['rows'], [])

    def test_action_open_category_report_resolves_to_html_action(self):
        action = self.asset.action_open_category_report()
        self.assertEqual(action['type'], 'ir.actions.report')
        self.assertEqual(action['report_name'], 'insight_project.report_cost_report_html')

    def test_render_qweb_html_produces_expected_markup(self):
        html = self.env['ir.actions.report']._render_qweb_html(
            'insight_project.report_cost_report_html', self.asset.ids,
        )[0]
        html_text = html.decode() if isinstance(html, bytes) else html
        self.assertIn('Costo por fase', html_text)
        self.assertIn('Fase 1', html_text)
        self.assertIn('width: 100.0%', html_text)
        self.assertIn('width: 60.0%', html_text)


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
