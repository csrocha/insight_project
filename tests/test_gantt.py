# -*- coding: utf-8 -*-
"""Regression tests for the Gantt SVG renderer (models/project_project.py:
_render_gantt_svg) and the action_view_gantt guard that gates it. These pin
the visual contract (task labels, scenario legend, critical-path styling)
without needing a browser — the controller just serves this SVG string as-is
(see controllers/main.py).
"""
from datetime import datetime, timedelta

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase


class TestActionViewGantt(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env['project.project'].create({
            'name': 'Gantt Guard Project',
            'is_tj_enabled': True,
        })

    def test_raises_without_a_prior_schedule_run(self):
        with self.assertRaises(UserError):
            self.project.action_view_gantt()

    def test_returns_gantt_url_once_scheduled(self):
        self.project.last_scheduled = '2026-01-01 00:00:00'
        result = self.project.action_view_gantt()
        self.assertEqual(result['type'], 'ir.actions.act_url')
        self.assertEqual(result['url'], f'/insight_project/gantt/{self.project.id}')


class TestRenderGanttSvgEmpty(TransactionCase):

    def test_placeholder_svg_when_no_schedule_data(self):
        project = self.env['project.project'].create({'name': 'Empty Gantt Project', 'is_tj_enabled': True})
        svg = project._render_gantt_svg()
        self.assertTrue(svg.startswith('<svg'))
        self.assertIn('No hay datos de schedule', svg)


class TestRenderGanttSvgWithData(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env['project.project'].create({
            'name': 'Populated Gantt Project',
            'is_tj_enabled': True,
        })
        cls.plan = cls.env['insight.scenario'].create({
            'name': 'Plan', 'project_id': cls.project.id, 'is_baseline': True,
        })
        cls.noai = cls.env['insight.scenario'].create({
            'name': 'Noai', 'project_id': cls.project.id,
        })
        cls.task_critical = cls.env['project.task'].create({
            'name': 'Critical Task', 'project_id': cls.project.id,
        })
        cls.task_normal = cls.env['project.task'].create({
            'name': 'Normal Task', 'project_id': cls.project.id,
        })

    def _schedule(self, task, scenario, start, end, bsi, critical=False):
        return self.env['insight.task.schedule'].create({
            'task_id': task.id,
            'scenario_id': scenario.id,
            'start_scheduled': start,
            'end_scheduled': end,
            'bsi': bsi,
            'is_critical_path': critical,
        })

    def test_svg_contains_task_labels_and_scenario_legend(self):
        self._schedule(self.task_critical, self.plan, '2024-01-01', '2024-01-10', '1', critical=True)
        self._schedule(self.task_normal, self.plan, '2024-01-05', '2024-01-15', '2', critical=False)

        svg = self.project._render_gantt_svg()
        self.assertIn('Critical Task', svg)
        self.assertIn('Normal Task', svg)
        self.assertIn('Plan', svg)  # scenario legend entry
        self.assertIn('camino crítico', svg)
        self.assertIn('⚡', svg)  # critical-path marker drawn for the critical task

    def test_svg_lists_every_scenario_present_in_the_schedule(self):
        self._schedule(self.task_critical, self.plan, '2024-01-01', '2024-01-10', '1')
        self._schedule(self.task_critical, self.noai, '2024-01-01', '2024-01-12', '1')

        svg = self.project._render_gantt_svg()
        self.assertIn('Plan', svg)
        self.assertIn('Noai', svg)

    def test_today_marker_shown_when_now_falls_within_the_range(self):
        now = datetime.utcnow()
        self._schedule(
            self.task_normal, self.plan,
            now - timedelta(days=365), now + timedelta(days=365), '1',
        )
        svg = self.project._render_gantt_svg()
        self.assertIn('Hoy', svg)

    def test_today_marker_absent_when_schedule_is_entirely_in_the_past(self):
        self._schedule(self.task_normal, self.plan, '2010-01-01', '2010-01-10', '1')
        svg = self.project._render_gantt_svg()
        self.assertNotIn('>Hoy<', svg)
