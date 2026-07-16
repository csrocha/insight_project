# -*- coding: utf-8 -*-
"""Regression tests for the Gantt-as-knowledge.asset pipeline: payload
assembly (project.project._tj_gantt_schedule_payload), asset get-or-create/
versioning (_compute_and_save_gantt_report), the action_view_gantt guard, the
pure SVG renderer (report_gantt_report.render_gantt_svg) and the report
model that wires it to the knowledge.asset framework. The SVG renderer is
payload-driven and needs no DB — it's the direct continuation of what used
to be project_project._render_gantt_svg, split into "gather data" (ORM,
tested here against real records) and "draw SVG" (pure, tested against
hand-built fixture dicts).
"""
import re
from datetime import datetime, timedelta

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase

from ..models.report_gantt_report import render_gantt_svg


class TestGanttSchedulePayload(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env['project.project'].create({
            'name': 'Gantt Payload Project', 'is_tj_enabled': True,
        })
        cls.plan = cls.env['insight.scenario'].create({
            'name': 'Plan', 'project_id': cls.project.id, 'is_baseline': True,
        })
        cls.root = cls.env['project.task'].create({
            'name': 'Fase 1', 'project_id': cls.project.id,
        })
        cls.leaf = cls.env['project.task'].create({
            'name': 'Leaf', 'project_id': cls.project.id, 'parent_id': cls.root.id,
            'depend_on_ids': [(6, 0, [cls.root.id])],
        })
        cls.milestone = cls.env['project.milestone'].create({
            'name': 'Entrega 1', 'project_id': cls.project.id,
            'deadline': '2024-02-01', 'tj_scheduled_date': '2024-01-20',
            'task_ids': [(6, 0, [cls.leaf.id])],
        })

    def _schedule(self, task, start, end, bsi, critical=False, complete=0.0):
        return self.env['insight.task.schedule'].create({
            'task_id': task.id, 'scenario_id': self.plan.id,
            'start_scheduled': start, 'end_scheduled': end, 'bsi': bsi,
            'is_critical_path': critical, 'complete': complete,
        })

    def test_payload_contains_scheduled_tasks(self):
        self._schedule(self.root, '2024-01-01', '2024-01-10', '1', critical=True, complete=40.0)
        payload = self.project._tj_gantt_schedule_payload()

        self.assertEqual(payload['title'], 'Gantt Payload Project')
        self.assertEqual(len(payload['tasks']), 1)
        task = payload['tasks'][0]
        self.assertEqual(task['task_id'], self.root.id)
        self.assertEqual(task['bsi'], '1')
        self.assertEqual(task['name'], 'Fase 1')
        self.assertIsNone(task['parent_id'])
        self.assertEqual(task['start'], '2024-01-01 00:00:00')
        self.assertEqual(task['end'], '2024-01-10 00:00:00')
        self.assertTrue(task['is_critical_path'])
        self.assertEqual(task['complete'], 40.0)
        self.assertEqual(len(payload['scenarios']), 1)
        self.assertEqual(payload['scenarios'][0]['name'], 'Plan')

    def test_unscheduled_tasks_are_excluded(self):
        # No insight.task.schedule row at all for self.leaf.
        payload = self.project._tj_gantt_schedule_payload()
        self.assertEqual(payload['tasks'], [])

    def test_payload_captures_milestones(self):
        payload = self.project._tj_gantt_schedule_payload()
        self.assertEqual(len(payload['milestones']), 1)
        milestone = payload['milestones'][0]
        self.assertEqual(milestone['id'], self.milestone.id)
        self.assertEqual(milestone['name'], 'Entrega 1')
        self.assertEqual(milestone['date'], '2024-01-20')
        self.assertEqual(milestone['task_ids'], [self.leaf.id])

    def test_payload_falls_back_to_deadline_without_tj_scheduled_date(self):
        self.milestone.tj_scheduled_date = False
        payload = self.project._tj_gantt_schedule_payload()
        self.assertEqual(payload['milestones'][0]['date'], '2024-02-01')

    def test_payload_captures_dependencies(self):
        payload = self.project._tj_gantt_schedule_payload()
        self.assertIn(
            {'task_id': self.leaf.id, 'depends_on_id': self.root.id, 'type': 'FS'},
            payload['dependencies'],
        )

    def test_dependency_type_override_is_reflected(self):
        self.env['insight.task.dependency'].create({
            'task_id': self.leaf.id, 'depends_on_id': self.root.id, 'dependency_type': 'SS',
        })
        payload = self.project._tj_gantt_schedule_payload()
        dep = next(d for d in payload['dependencies'] if d['task_id'] == self.leaf.id)
        self.assertEqual(dep['type'], 'SS')


class TestComputeAndSaveGanttReport(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env['project.project'].create({
            'name': 'Gantt Asset Project', 'is_tj_enabled': True,
        })
        cls.plan = cls.env['insight.scenario'].create({
            'name': 'Plan', 'project_id': cls.project.id, 'is_baseline': True,
        })
        cls.task = cls.env['project.task'].create({
            'name': 'Fase 1', 'project_id': cls.project.id,
        })

    def _seed_schedule(self):
        self.env['insight.task.schedule'].create({
            'task_id': self.task.id, 'scenario_id': self.plan.id,
            'start_scheduled': '2024-01-01', 'end_scheduled': '2024-01-10', 'bsi': '1',
        })

    def test_creates_one_asset_scoped_to_the_project(self):
        self._seed_schedule()
        asset = self.project._compute_and_save_gantt_report()

        self.assertEqual(asset.res_model, 'project.project')
        self.assertEqual(asset.res_id, self.project.id)
        self.assertEqual(asset.category, 'insight_project.gantt_report')
        self.assertEqual(asset.tags, 'gantt')
        self.assertEqual(asset.visibility, 'shared')
        self.assertTrue(asset.shared_group_ids)
        version = asset.latest_version()
        self.assertEqual(version.version, 1)
        self.assertEqual(version.schema, 'insight_project.gantt')

    def test_second_call_creates_new_version_not_new_asset(self):
        self._seed_schedule()
        self.project._compute_and_save_gantt_report()
        self.project._compute_and_save_gantt_report()

        assets = self.env['knowledge.asset'].search([
            ('res_model', '=', 'project.project'), ('res_id', '=', self.project.id),
            ('category', '=', 'insight_project.gantt_report'),
        ])
        self.assertEqual(len(assets), 1, 'debe reusar el mismo asset, no duplicarlo')
        self.assertEqual(len(assets.version_ids), 2)
        self.assertEqual(assets.latest_version().version, 2)

    def test_action_generate_cost_reports_also_regenerates_gantt(self):
        """El botón 'Actualizar reportes' (insight.scenario.action_generate_
        cost_reports) dispara ambos reportes en un solo click."""
        self._seed_schedule()
        self.plan.action_generate_cost_reports()

        count = self.env['knowledge.asset'].search_count([
            ('res_model', '=', 'project.project'), ('res_id', '=', self.project.id),
            ('category', '=', 'insight_project.gantt_report'),
        ])
        self.assertEqual(count, 1)


class TestActionViewGantt(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env['project.project'].create({
            'name': 'Gantt Guard Project', 'is_tj_enabled': True,
        })
        cls.plan = cls.env['insight.scenario'].create({
            'name': 'Plan', 'project_id': cls.project.id, 'is_baseline': True,
        })

    def test_raises_without_a_prior_schedule_run(self):
        with self.assertRaises(UserError):
            self.project.action_view_gantt()

    def test_raises_without_a_generated_report(self):
        self.project.last_scheduled = '2026-01-01 00:00:00'
        with self.assertRaises(UserError):
            self.project.action_view_gantt()

    def test_returns_report_action_once_generated(self):
        self.env['insight.task.schedule'].create({
            'task_id': self.env['project.task'].create({
                'name': 'Fase 1', 'project_id': self.project.id,
            }).id,
            'scenario_id': self.plan.id,
            'start_scheduled': '2024-01-01', 'end_scheduled': '2024-01-10', 'bsi': '1',
        })
        self.project.last_scheduled = '2026-01-01 00:00:00'
        self.project._compute_and_save_gantt_report()

        action = self.project.action_view_gantt()
        self.assertEqual(action['type'], 'ir.actions.report')
        self.assertEqual(action['report_name'], 'insight_project.report_gantt_report_svg')


class TestRenderGanttSvg(TransactionCase):
    """render_gantt_svg no toca el ORM — se prueba con dicts de payload
    armados a mano, igual que consumiría el asset guardado."""

    def _payload(self, tasks=None, scenarios=None, **extra):
        payload = {
            'title': 'Payload Project',
            'last_scheduled': '2026-01-01 00:00:00',
            'scenarios': scenarios if scenarios is not None else [{'id': 1, 'name': 'Plan'}],
            'tasks': tasks if tasks is not None else [],
            'milestones': [],
            'dependencies': [],
        }
        payload.update(extra)
        return payload

    def test_placeholder_svg_when_no_tasks(self):
        svg = render_gantt_svg(self._payload(tasks=[]))
        self.assertTrue(svg.startswith('<svg'))
        self.assertIn('No hay datos de schedule', svg)

    def test_svg_contains_task_labels_and_scenario_legend(self):
        svg = render_gantt_svg(self._payload(tasks=[
            {
                'task_id': 1, 'bsi': '1', 'name': 'Critical Task', 'parent_id': None,
                'scenario_id': 1, 'start': '2024-01-01 00:00:00', 'end': '2024-01-10 00:00:00',
                'complete': 0.0, 'is_critical_path': True,
            },
            {
                'task_id': 2, 'bsi': '2', 'name': 'Normal Task', 'parent_id': None,
                'scenario_id': 1, 'start': '2024-01-05 00:00:00', 'end': '2024-01-15 00:00:00',
                'complete': 0.0, 'is_critical_path': False,
            },
        ]))
        self.assertIn('Critical Task', svg)
        self.assertIn('Normal Task', svg)
        self.assertIn('Plan', svg)
        self.assertIn('camino crítico', svg)
        self.assertIn('⚡', svg)

    def test_svg_lists_every_scenario_present(self):
        svg = render_gantt_svg(self._payload(
            scenarios=[{'id': 1, 'name': 'Plan'}, {'id': 2, 'name': 'Noai'}],
            tasks=[
                {
                    'task_id': 1, 'bsi': '1', 'name': 'Task', 'parent_id': None,
                    'scenario_id': 1, 'start': '2024-01-01 00:00:00', 'end': '2024-01-10 00:00:00',
                    'complete': 0.0, 'is_critical_path': False,
                },
                {
                    'task_id': 1, 'bsi': '1', 'name': 'Task', 'parent_id': None,
                    'scenario_id': 2, 'start': '2024-01-01 00:00:00', 'end': '2024-01-12 00:00:00',
                    'complete': 0.0, 'is_critical_path': False,
                },
            ],
        ))
        self.assertIn('Plan', svg)
        self.assertIn('Noai', svg)

    def test_legend_items_and_bars_are_taggable_for_the_toggle_script(self):
        """Cada escenario debe quedar identificable por data-scenario tanto
        en su entrada de leyenda (clickeable) como en el grupo de su barra
        (lo que el <script> embebido oculta/muestra al togglear)."""
        svg = render_gantt_svg(self._payload(
            scenarios=[{'id': 7, 'name': 'Plan'}],
            tasks=[
                {
                    'task_id': 1, 'bsi': '1', 'name': 'Task', 'parent_id': None,
                    'scenario_id': 7, 'start': '2024-01-01 00:00:00', 'end': '2024-01-10 00:00:00',
                    'complete': 0.0, 'is_critical_path': False,
                },
            ],
        ))
        self.assertIn('<g class="gantt-legend-item" data-scenario="7">', svg)
        self.assertIn('<g class="gantt-bar-group" data-scenario="7">', svg)
        self.assertIn('gantt-hidden', svg)
        # El script busca su propio <svg> por id, no por document.currentScript
        # (no confiable para <script> embebido dentro de <svg>, ver comentario
        # en report_gantt_report.render_gantt_svg) — el id debe matchear entre
        # la etiqueta <svg> y el getElementById del script.
        self.assertNotIn('document.currentScript', svg)
        match = re.search(r'<svg xmlns="[^"]+" id="([^"]+)"', svg)
        self.assertIsNotNone(match)
        svg_id = match.group(1)
        self.assertIn(f'document.getElementById("{svg_id}")', svg)

    def test_dependency_group_is_taggable_for_the_toggle_script(self):
        svg = render_gantt_svg(self._payload(tasks=[
            self._task(task_id=1, bsi='1', name='Blocker',
                       start='2024-01-01 00:00:00', end='2024-01-05 00:00:00'),
            self._task(task_id=2, bsi='2', name='Dependent',
                       start='2024-01-06 00:00:00', end='2024-01-10 00:00:00'),
        ], dependencies=[{'task_id': 2, 'depends_on_id': 1, 'type': 'FS'}]))
        self.assertIn('<g class="gantt-dep-group" data-scenario="1">', svg)

    def _task(self, **overrides):
        task = {
            'task_id': 1, 'bsi': '1', 'name': 'Task', 'parent_id': None,
            'scenario_id': 1, 'start': '2024-01-01 00:00:00', 'end': '2024-01-10 00:00:00',
            'complete': 0.0, 'is_critical_path': False,
        }
        task.update(overrides)
        return task

    def test_progress_overlay_drawn_when_complete_is_set(self):
        svg = render_gantt_svg(self._payload(tasks=[self._task(complete=40.0)]))
        self.assertIn('fill="#212121" opacity="0.55"', svg)

    def test_no_progress_overlay_when_complete_is_zero(self):
        svg = render_gantt_svg(self._payload(tasks=[self._task(complete=0.0)]))
        self.assertNotIn('fill="#212121" opacity="0.55"', svg)

    def test_today_marker_shown_when_now_falls_within_the_range(self):
        now = datetime.utcnow()
        svg = render_gantt_svg(self._payload(tasks=[self._task(
            start=(now - timedelta(days=365)).strftime('%Y-%m-%d %H:%M:%S'),
            end=(now + timedelta(days=365)).strftime('%Y-%m-%d %H:%M:%S'),
        )]))
        self.assertIn('Hoy', svg)

    def test_today_marker_absent_when_schedule_is_entirely_in_the_past(self):
        svg = render_gantt_svg(self._payload(tasks=[self._task(
            start='2010-01-01 00:00:00', end='2010-01-10 00:00:00',
        )]))
        self.assertNotIn('>Hoy<', svg)

    def test_dependency_arrow_drawn_between_two_scheduled_tasks(self):
        svg = render_gantt_svg(self._payload(tasks=[
            self._task(task_id=1, bsi='1', name='Blocker',
                       start='2024-01-01 00:00:00', end='2024-01-05 00:00:00'),
            self._task(task_id=2, bsi='2', name='Dependent',
                       start='2024-01-05 00:00:00', end='2024-01-10 00:00:00'),
        ], dependencies=[{'task_id': 2, 'depends_on_id': 1, 'type': 'FS'}]))
        self.assertIn('stroke="#757575"', svg)

    def test_no_dependency_arrow_without_a_matching_edge(self):
        svg = render_gantt_svg(self._payload(tasks=[self._task()], dependencies=[]))
        self.assertNotIn('stroke="#757575"', svg)

    def test_dependency_arrow_skipped_when_one_end_is_unscheduled(self):
        # depends_on_id=99 never appears in `tasks` — no position to draw from.
        svg = render_gantt_svg(self._payload(
            tasks=[self._task(task_id=2)],
            dependencies=[{'task_id': 2, 'depends_on_id': 99, 'type': 'FS'}],
        ))
        self.assertNotIn('stroke="#757575"', svg)

    @staticmethod
    def _dependency_path_d(svg):
        match = re.search(r'<path d="([^"]+)" fill="none" stroke="#757575"', svg)
        return match.group(1) if match else None

    def test_simple_elbow_connector_when_there_is_room_between_tasks(self):
        svg = render_gantt_svg(self._payload(tasks=[
            self._task(task_id=1, bsi='1', name='Blocker',
                       start='2024-01-01 00:00:00', end='2024-01-02 00:00:00'),
            self._task(task_id=2, bsi='2', name='Dependent',
                       start='2024-06-01 00:00:00', end='2024-06-10 00:00:00'),
        ], dependencies=[{'task_id': 2, 'depends_on_id': 1, 'type': 'FS'}]))
        path_d = self._dependency_path_d(svg)
        self.assertIsNotNone(path_d)
        self.assertEqual(path_d.count(' L '), 3, 'escuadra simple: M + 3 L')

    def test_s_connector_when_dependent_starts_immediately_after_blocker(self):
        svg = render_gantt_svg(self._payload(tasks=[
            self._task(task_id=1, bsi='1', name='Blocker',
                       start='2024-01-01 00:00:00', end='2024-01-05 00:00:00'),
            self._task(task_id=2, bsi='2', name='Dependent',
                       start='2024-01-05 00:00:00', end='2024-01-10 00:00:00'),
        ], dependencies=[{'task_id': 2, 'depends_on_id': 1, 'type': 'FS'}]))
        path_d = self._dependency_path_d(svg)
        self.assertIsNotNone(path_d)
        self.assertEqual(path_d.count(' L '), 5, 'S invertida: M + 5 L')

    def test_s_connector_when_tasks_overlap(self):
        svg = render_gantt_svg(self._payload(tasks=[
            self._task(task_id=1, bsi='1', name='Blocker',
                       start='2024-01-01 00:00:00', end='2024-01-10 00:00:00'),
            self._task(task_id=2, bsi='2', name='Dependent',
                       start='2024-01-05 00:00:00', end='2024-01-15 00:00:00'),
        ], dependencies=[{'task_id': 2, 'depends_on_id': 1, 'type': 'FS'}]))
        path_d = self._dependency_path_d(svg)
        self.assertIsNotNone(path_d)
        self.assertEqual(path_d.count(' L '), 5, 'S invertida: M + 5 L')


class TestReportGanttReportSvg(TransactionCase):
    """report.insight_project.report_gantt_report_svg: delega el dibujo en
    render_gantt_svg, el QWeb solo embebe el string devuelto."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env['project.project'].create({
            'name': 'Report Model Gantt Project', 'is_tj_enabled': True,
        })
        cls.plan = cls.env['insight.scenario'].create({
            'name': 'Plan', 'project_id': cls.project.id, 'is_baseline': True,
        })
        cls.task = cls.env['project.task'].create({
            'name': 'Fase 1', 'project_id': cls.project.id,
        })
        cls.env['insight.task.schedule'].create({
            'task_id': cls.task.id, 'scenario_id': cls.plan.id,
            'start_scheduled': '2024-01-01', 'end_scheduled': '2024-01-10', 'bsi': '1',
        })
        cls.asset = cls.project._compute_and_save_gantt_report()

    def test_get_report_values_returns_docs_and_svg(self):
        Report = self.env['report.insight_project.report_gantt_report_svg']
        values = Report._get_report_values(self.asset.ids)
        self.assertEqual(values['docs'], self.asset)
        self.assertEqual(len(values['reports']), 1)
        self.assertIn('Fase 1', values['reports'][0]['svg'])

    def test_asset_without_version_yields_placeholder(self):
        empty_asset = self.env['knowledge.asset'].create({
            'name': 'Sin versión', 'category': 'insight_project.gantt_report',
        })
        Report = self.env['report.insight_project.report_gantt_report_svg']
        report = Report._get_report_values(empty_asset.ids)['reports'][0]
        self.assertIn('No hay datos de schedule', report['svg'])

    def test_action_open_category_report_resolves_to_svg_action(self):
        action = self.asset.action_open_category_report()
        self.assertEqual(action['type'], 'ir.actions.report')
        self.assertEqual(action['report_name'], 'insight_project.report_gantt_report_svg')

    def test_render_qweb_html_embeds_the_svg(self):
        html = self.env['ir.actions.report']._render_qweb_html(
            'insight_project.report_gantt_report_svg', self.asset.ids,
        )[0]
        html_text = html.decode() if isinstance(html, bytes) else html
        self.assertIn('<svg', html_text)
        self.assertIn('Fase 1', html_text)
