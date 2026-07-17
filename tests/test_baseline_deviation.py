# -*- coding: utf-8 -*-
"""Regression tests para Épica 2 del roadmap de ecosistema (memoria
project_ecosystem_roadmap, insight_project/BACKLOG.md ítems 6/7): freeze
inmutable del baseline al pasar a "En progreso" (action_start) y el reporte
de desviación baseline vs. real calculado contra ese freeze — ver
models/project_project.py (_freeze_baseline_snapshot/
_compute_and_save_deviation_report) y models/insight_scenario.py
(action_generate_reports)."""
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase

from ..models.project_project import ProjectProject


class TestFreezeBaselineSnapshot(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env['project.project'].create({
            'name': 'Freeze Project', 'is_tj_enabled': True, 'date_start': '2026-07-06',
        })
        cls.scenario = cls.env['insight.scenario'].create({
            'name': 'Plan', 'project_id': cls.project.id, 'is_baseline': True,
        })
        cls.root = cls.env['project.task'].create({
            'name': 'Fase 1', 'project_id': cls.project.id, 'allocated_hours': 40.0,
            'user_ids': [(6, 0, [])],
        })

    def _seed_schedule(self, cost=1000.0, end='2026-07-10 00:00:00'):
        return self.env['insight.task.schedule'].create({
            'task_id': self.root.id, 'scenario_id': self.scenario.id,
            'cost': cost, 'end_scheduled': end, 'effort_days': 5.0,
        })

    def test_action_start_creates_snapshot_version(self):
        self._seed_schedule()
        self.project.action_start()
        self.assertEqual(self.project.state, 'progress')
        asset = self.env['knowledge.asset'].search([
            ('res_model', '=', 'insight.scenario'), ('res_id', '=', self.scenario.id),
            ('category', '=', 'insight_project.baseline_snapshot'),
        ])
        self.assertEqual(len(asset), 1)
        version = asset.latest_version()
        self.assertEqual(version.version, 1)
        payload = version.payload
        self.assertEqual(len(payload['tasks']), 1)
        self.assertEqual(payload['tasks'][0]['task_id'], self.root.id)
        self.assertEqual(payload['tasks'][0]['cost'], 1000.0)
        self.assertEqual(payload['total_cost'], 1000.0)

    def test_action_start_called_again_creates_new_version_not_new_asset(self):
        """Un re-baseline a mitad de proyecto (reevaluar → iniciar de nuevo)
        agrega una versión nueva, sin pisar el historial de aprobaciones."""
        self._seed_schedule()
        self.project.action_start()
        self.project.action_start()
        asset = self.env['knowledge.asset'].search([
            ('res_model', '=', 'insight.scenario'), ('res_id', '=', self.scenario.id),
            ('category', '=', 'insight_project.baseline_snapshot'),
        ])
        self.assertEqual(len(asset), 1, 'debe reusar el mismo asset, no duplicarlo')
        self.assertEqual(len(asset.version_ids), 2)

    def test_action_start_without_baseline_scenario_does_not_raise(self):
        project = self.env['project.project'].create({
            'name': 'Sin escenario', 'is_tj_enabled': True,
        })
        project.action_start()
        self.assertEqual(project.state, 'progress')
        count = self.env['knowledge.asset'].search_count([
            ('category', '=', 'insight_project.baseline_snapshot'),
        ])
        self.assertEqual(count, 0)

    def test_snapshot_is_immutable_except_state(self):
        """El freeze reusa knowledge.asset.version — su write() ya bloquea
        todo salvo state (ver knowledge_asset_version.py), así que el
        snapshot no puede alterarse una vez creado."""
        self._seed_schedule()
        self.project.action_start()
        version = self.env['knowledge.asset'].search([
            ('res_model', '=', 'insight.scenario'), ('res_id', '=', self.scenario.id),
            ('category', '=', 'insight_project.baseline_snapshot'),
        ]).latest_version()
        with self.assertRaises(UserError):
            version.write({'payload': {'tampered': True}})


class TestComputeAndSaveDeviationReport(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env['project.project'].create({
            'name': 'Deviation Project', 'is_tj_enabled': True, 'date_start': '2026-07-06',
        })
        cls.scenario = cls.env['insight.scenario'].create({
            'name': 'Plan', 'project_id': cls.project.id, 'is_baseline': True,
        })
        cls.root = cls.env['project.task'].create({
            'name': 'Fase 1', 'project_id': cls.project.id, 'allocated_hours': 40.0,
            'user_ids': [(6, 0, [])],
        })

    def _seed_schedule(self, cost=1000.0, end='2026-07-10 00:00:00', complete=40.0):
        return self.env['insight.task.schedule'].create({
            'task_id': self.root.id, 'scenario_id': self.scenario.id,
            'cost': cost, 'end_scheduled': end, 'effort_days': 5.0, 'complete': complete,
        })

    def test_requires_progress_state(self):
        self._seed_schedule()
        with self.assertRaises(UserError):
            self.project._compute_and_save_deviation_report(self.scenario)

    def test_requires_existing_snapshot(self):
        self._seed_schedule()
        self.project.state = 'progress'  # bypassea action_start: nunca se congeló nada
        with self.assertRaises(UserError):
            self.project._compute_and_save_deviation_report(self.scenario)

    def test_computes_deltas_against_frozen_snapshot(self):
        schedule = self._seed_schedule(cost=1000.0, end='2026-07-10 00:00:00', complete=40.0)
        self.project.action_start()  # congela cost=1000, end=2026-07-10

        # Reschedule real: costo/fecha final/avance cambiaron desde el freeze.
        schedule.write({
            'cost': 1500.0, 'end_scheduled': '2026-07-15 00:00:00', 'complete': 60.0,
        })

        self.project._compute_and_save_deviation_report(self.scenario)
        asset = self.env['knowledge.asset'].search([
            ('res_model', '=', 'insight.scenario'), ('res_id', '=', self.scenario.id),
            ('category', '=', 'insight_project.deviation_report'),
        ])
        self.assertEqual(len(asset), 1)
        self.assertEqual(asset.visibility, 'shared')
        payload = asset.latest_version().payload
        self.assertEqual(len(payload['items']), 1)
        item = payload['items'][0]
        self.assertEqual(item['baseline_cost'], 1000.0)
        self.assertEqual(item['current_cost'], 1500.0)
        self.assertEqual(item['cost_delta'], 500.0)
        self.assertEqual(item['end_delta_days'], 5.0)
        self.assertEqual(item['complete'], 60.0)
        self.assertEqual(payload['total_baseline_cost'], 1000.0)
        self.assertEqual(payload['total_current_cost'], 1500.0)
        self.assertEqual(payload['total_cost_delta'], 500.0)

    def test_second_call_creates_new_version_not_new_asset(self):
        self._seed_schedule()
        self.project.action_start()
        self.project._compute_and_save_deviation_report(self.scenario)
        self.project._compute_and_save_deviation_report(self.scenario)
        asset = self.env['knowledge.asset'].search([
            ('res_model', '=', 'insight.scenario'), ('res_id', '=', self.scenario.id),
            ('category', '=', 'insight_project.deviation_report'),
        ])
        self.assertEqual(len(asset), 1, 'debe reusar el mismo asset, no duplicarlo')
        self.assertEqual(len(asset.version_ids), 2)

    def test_evm_fields_when_task_already_due(self):
        """Tarea cuyo fin baseline ya pasó: todo su presupuesto cuenta como
        planned_value (debería estar 100% hecha a hoy según el plan)."""
        past = fields.Datetime.now() - timedelta(days=10)
        schedule = self._seed_schedule(cost=1000.0, end=fields.Datetime.to_string(past), complete=0.0)
        self.project.action_start()  # congela cost=1000, end=pasado
        schedule.write({'cost': 1200.0, 'complete': 50.0})  # avance real: 50%, costo actual 1200

        self.project._compute_and_save_deviation_report(self.scenario)
        asset = self.env['knowledge.asset'].search([
            ('res_model', '=', 'insight.scenario'), ('res_id', '=', self.scenario.id),
            ('category', '=', 'insight_project.deviation_report'),
        ])
        payload = asset.latest_version().payload
        self.assertEqual(payload['planned_value'], 1000.0)
        self.assertEqual(payload['earned_value'], 500.0)
        self.assertEqual(payload['actual_cost'], 1200.0)
        self.assertAlmostEqual(payload['cost_performance_index'], 500.0 / 1200.0)
        self.assertAlmostEqual(payload['schedule_performance_index'], 0.5)

    def test_evm_indices_are_none_when_nothing_due_or_spent_yet(self):
        """Tarea cuyo fin baseline todavía no llegó y sin avance real: PV/AC
        en 0 no deben producir división por cero, sino None (índice sin
        sentido todavía, no 'malo')."""
        future = fields.Datetime.now() + timedelta(days=10)
        self._seed_schedule(cost=1000.0, end=fields.Datetime.to_string(future), complete=0.0)
        self.project.action_start()

        self.project._compute_and_save_deviation_report(self.scenario)
        asset = self.env['knowledge.asset'].search([
            ('res_model', '=', 'insight.scenario'), ('res_id', '=', self.scenario.id),
            ('category', '=', 'insight_project.deviation_report'),
        ])
        payload = asset.latest_version().payload
        self.assertEqual(payload['planned_value'], 0.0)
        self.assertEqual(payload['earned_value'], 0.0)
        self.assertEqual(payload['actual_cost'], 0.0)
        self.assertIsNone(payload['cost_performance_index'])
        self.assertIsNone(payload['schedule_performance_index'])

    def test_task_added_after_freeze_is_omitted_from_items(self):
        """Una tarea nueva desde el freeze no tiene punto de comparación —
        se omite del detalle en vez de romper el cálculo."""
        self._seed_schedule()
        self.project.action_start()
        new_task = self.env['project.task'].create({
            'name': 'Fase nueva', 'project_id': self.project.id, 'allocated_hours': 10.0,
            'user_ids': [(6, 0, [])],
        })
        self.env['insight.task.schedule'].create({
            'task_id': new_task.id, 'scenario_id': self.scenario.id, 'cost': 200.0,
        })
        self.project._compute_and_save_deviation_report(self.scenario)
        asset = self.env['knowledge.asset'].search([
            ('res_model', '=', 'insight.scenario'), ('res_id', '=', self.scenario.id),
            ('category', '=', 'insight_project.deviation_report'),
        ])
        item_task_ids = {i['task_id'] for i in asset.latest_version().payload['items']}
        self.assertNotIn(new_task.id, item_task_ids)
        self.assertIn(self.root.id, item_task_ids)


class TestActionGenerateReportsIncludesDeviation(TransactionCase):
    """insight.scenario.action_generate_reports (ver también
    test_gantt.py/test_cost_reports.py) suma el reporte de desviación solo
    cuando el proyecto está en ejecución."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env['project.project'].create({
            'name': 'Unified Reports Project', 'is_tj_enabled': True, 'date_start': '2026-07-06',
        })
        cls.scenario = cls.env['insight.scenario'].create({
            'name': 'Plan', 'project_id': cls.project.id, 'is_baseline': True,
        })
        cls.root = cls.env['project.task'].create({
            'name': 'Fase 1', 'project_id': cls.project.id, 'allocated_hours': 40.0,
            'user_ids': [(6, 0, [])],
        })
        cls.env['insight.task.schedule'].create({
            'task_id': cls.root.id, 'scenario_id': cls.scenario.id, 'cost': 1000.0,
        })

    def test_draft_project_generates_no_deviation_report(self):
        self.scenario.action_generate_reports()
        count = self.env['knowledge.asset'].search_count([
            ('res_model', '=', 'insight.scenario'), ('res_id', '=', self.scenario.id),
            ('category', '=', 'insight_project.deviation_report'),
        ])
        self.assertEqual(count, 0)

    def test_progress_project_also_generates_deviation_report(self):
        self.project.action_start()  # congela el baseline, requisito del reporte
        self.scenario.action_generate_reports()
        count = self.env['knowledge.asset'].search_count([
            ('res_model', '=', 'insight.scenario'), ('res_id', '=', self.scenario.id),
            ('category', '=', 'insight_project.deviation_report'),
        ])
        self.assertEqual(count, 1)


class TestCronRegeneratesReports(TransactionCase):
    """_cron_run_portfolio_schedule (ver también test_portfolio_scheduling.py)
    ahora regenera costo+Gantt+desviación de cada proyecto en progreso tras
    el recálculo nocturno, no solo el schedule."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env['project.project'].create({
            'name': 'Cron Reports Project', 'is_tj_enabled': True, 'date_start': '2026-07-06',
        })
        cls.scenario = cls.env['insight.scenario'].create({
            'name': 'Plan', 'project_id': cls.project.id, 'is_baseline': True,
        })
        cls.root = cls.env['project.task'].create({
            'name': 'Fase 1', 'project_id': cls.project.id, 'allocated_hours': 40.0,
            'user_ids': [(6, 0, [])],
        })
        cls.env['insight.task.schedule'].create({
            'task_id': cls.root.id, 'scenario_id': cls.scenario.id, 'cost': 1000.0,
            'end_scheduled': '2026-07-10 00:00:00',
        })
        cls.env['ir.config_parameter'].sudo().set_param(
            'insight_project.tj_microservice_url', 'http://tj3.local',
        )
        # El proyecto ya pasó por 'progreso' una vez (congela el baseline) —
        # simula el estado real antes de que corra el cron nocturno.
        cls.project.action_start()

    def _csv_for_root(self, end='2026-07-12'):
        sc_id = self.project._tjp_scenario_id(self.scenario)
        header = '"Id";"Bsi";"Name";"Start";"End";"Effort";"Duration";"Resources";"Criticalness"\n'
        row = f'"t{self.root.id}";"1";"Fase 1";"2026-07-06";"{end}";"5.0d";"5.0d";"";"0"\n'
        return sc_id, header + row

    def test_cron_regenerates_cost_gantt_and_deviation_reports(self):
        sc_id, csv_content = self._csv_for_root()
        with patch.object(
            ProjectProject, '_call_tj_microservice',
            return_value={'csv_files': {f'schedule_{sc_id}.csv': csv_content}},
        ):
            self.project._cron_run_portfolio_schedule()

        cost_count = self.env['knowledge.asset'].search_count([
            ('res_model', '=', 'insight.scenario'), ('res_id', '=', self.scenario.id),
            ('category', '=', 'insight_project.cost_report'),
        ])
        gantt_count = self.env['knowledge.asset'].search_count([
            ('res_model', '=', 'project.project'), ('res_id', '=', self.project.id),
            ('category', '=', 'insight_project.gantt_report'),
        ])
        deviation_count = self.env['knowledge.asset'].search_count([
            ('res_model', '=', 'insight.scenario'), ('res_id', '=', self.scenario.id),
            ('category', '=', 'insight_project.deviation_report'),
        ])
        self.assertEqual(cost_count, 3, 'fase/skill/departamento')
        self.assertEqual(gantt_count, 1)
        self.assertEqual(deviation_count, 1)

    def test_cron_does_not_regenerate_reports_when_schedule_fails(self):
        with patch.object(
            ProjectProject, '_call_tj_microservice',
            side_effect=UserError('TJ3 no disponible'),
        ):
            self.project._cron_run_portfolio_schedule()

        deviation_count = self.env['knowledge.asset'].search_count([
            ('res_model', '=', 'insight.scenario'), ('res_id', '=', self.scenario.id),
            ('category', '=', 'insight_project.deviation_report'),
        ])
        self.assertEqual(deviation_count, 0)
