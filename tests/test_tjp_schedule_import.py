# -*- coding: utf-8 -*-
"""Regression tests for importing a TJ3 taskreport CSV back into Odoo
(models/project_project.py: _import_scenario_csv / _import_all_schedules /
_sync_gantt_dates and their small parsing helpers).

This is the other half of the TJP round trip: _generate_tjp() (tested in
test_tjp_export.py) produces the .tjp sent to the tj3 microservice; these
tests pin what happens to the CSV taskreport that comes back.
"""
from datetime import date

from odoo.tests.common import TransactionCase

from ..models.project_project import ProjectProject


class TestTjCsvParsingHelpers(TransactionCase):
    """Pure static helpers — no DB needed, no tj3 call involved."""

    def test_parse_task_id_from_simple_tj_id(self):
        self.assertEqual(ProjectProject._parse_task_id_from_tj_id('t42'), 42)

    def test_parse_task_id_from_nested_tj_path(self):
        self.assertEqual(ProjectProject._parse_task_id_from_tj_id('t1.t5.t99'), 99)

    def test_parse_task_id_from_tj_id_invalid(self):
        self.assertIsNone(ProjectProject._parse_task_id_from_tj_id(''))
        self.assertIsNone(ProjectProject._parse_task_id_from_tj_id('not-a-task'))

    def test_parse_tj_duration_units(self):
        cases = [('5.0d', 5.0), ('40h', 5.0), ('1w', 5.0), ('0.0d', 0.0), ('', 0.0), ('bogus', 0.0)]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertAlmostEqual(ProjectProject._parse_tj_duration(raw), expected)

    def test_parse_tj_criticalness(self):
        self.assertTrue(ProjectProject._parse_tj_criticalness('55'))
        self.assertFalse(ProjectProject._parse_tj_criticalness('0'))
        self.assertFalse(ProjectProject._parse_tj_criticalness(''))
        self.assertFalse(ProjectProject._parse_tj_criticalness('not-a-number'))

    def test_parse_tj_datetime_date_only(self):
        dt = ProjectProject._parse_tj_datetime('2024-01-15', 'UTC')
        self.assertEqual(dt.strftime('%Y-%m-%d'), '2024-01-15')

    def test_parse_tj_datetime_localizes_to_utc(self):
        # 2024-01-15 09:00 in Buenos Aires (UTC-3) is 12:00 UTC.
        dt = ProjectProject._parse_tj_datetime('2024-01-15 09:00', 'America/Argentina/Buenos_Aires')
        self.assertEqual(dt.strftime('%Y-%m-%d %H:%M'), '2024-01-15 12:00')

    def test_parse_tj_datetime_invalid_or_empty(self):
        self.assertFalse(ProjectProject._parse_tj_datetime('', 'UTC'))
        self.assertFalse(ProjectProject._parse_tj_datetime('not-a-date', 'UTC'))


class TestImportScenarioCsv(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env['project.project'].create({
            'name': 'CSV Import Project',
            'is_tj_enabled': True,
        })
        cls.scenario = cls.env['insight.scenario'].create({
            'name': 'Plan', 'project_id': cls.project.id, 'is_baseline': True,
        })
        cls.task1 = cls.env['project.task'].create({'name': 'Task 1', 'project_id': cls.project.id})
        cls.task2 = cls.env['project.task'].create({'name': 'Task 2', 'project_id': cls.project.id})

    @staticmethod
    def _csv(task_id, bsi='1', start='2024-01-01', end='2024-01-10', effort='5.0d', duration='5.0d', crit='0'):
        return (
            '"Id";"Bsi";"Name";"Start";"End";"Effort";"Duration";"Resources";"Criticalness"\n'
            f'"t{task_id}";"{bsi}";"Task";"{start}";"{end}";"{effort}";"{duration}";"";"{crit}"\n'
        )

    def test_creates_schedule_record_from_csv_row(self):
        self.project._import_scenario_csv(self._csv(self.task1.id), self.scenario)
        schedule = self.env['insight.task.schedule'].search([
            ('task_id', '=', self.task1.id), ('scenario_id', '=', self.scenario.id),
        ])
        self.assertEqual(len(schedule), 1)
        self.assertEqual(schedule.effort_days, 5.0)
        self.assertEqual(schedule.duration_days, 5.0)
        self.assertEqual(schedule.bsi, '1')
        self.assertFalse(schedule.is_critical_path)

    def test_skips_rows_for_tasks_outside_the_project(self):
        other_project = self.env['project.project'].create({'name': 'Other Project'})
        outside_task = self.env['project.task'].create({'name': 'Outside', 'project_id': other_project.id})
        self.project._import_scenario_csv(self._csv(outside_task.id), self.scenario)
        self.assertFalse(self.env['insight.task.schedule'].search([('scenario_id', '=', self.scenario.id)]))

    def test_reimport_replaces_previous_rows_for_the_scenario(self):
        self.project._import_scenario_csv(self._csv(self.task1.id, effort='5.0d'), self.scenario)
        self.project._import_scenario_csv(self._csv(self.task1.id, effort='8.0d'), self.scenario)
        schedules = self.env['insight.task.schedule'].search([
            ('task_id', '=', self.task1.id), ('scenario_id', '=', self.scenario.id),
        ])
        self.assertEqual(len(schedules), 1, 'Re-importing must not accumulate stale rows')
        self.assertEqual(schedules.effort_days, 8.0)

    def test_criticalness_above_zero_flags_critical_path(self):
        self.project._import_scenario_csv(self._csv(self.task1.id, crit='55'), self.scenario)
        schedule = self.env['insight.task.schedule'].search([('task_id', '=', self.task1.id)])
        self.assertTrue(schedule.is_critical_path)

    def test_comma_delimited_csv_also_parses(self):
        csv_content = (
            'Id,Bsi,Name,Start,End,Effort,Duration,Resources,Criticalness\n'
            f't{self.task2.id},2,Task,2024-02-01,2024-02-05,3.0d,3.0d,,0\n'
        )
        self.project._import_scenario_csv(csv_content, self.scenario)
        schedule = self.env['insight.task.schedule'].search([('task_id', '=', self.task2.id)])
        self.assertEqual(schedule.effort_days, 3.0)


class TestImportAllSchedules(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env['project.project'].create({
            'name': 'Dispatch Project',
            'is_tj_enabled': True,
        })
        cls.plan = cls.env['insight.scenario'].create({
            'name': 'Plan', 'project_id': cls.project.id, 'is_baseline': True,
        })
        cls.noai = cls.env['insight.scenario'].create({
            'name': 'Noai', 'project_id': cls.project.id,
        })
        cls.task = cls.env['project.task'].create({'name': 'Dispatch Task', 'project_id': cls.project.id})

    def _csv_for(self, task):
        return (
            '"Id";"Bsi";"Name";"Start";"End";"Effort";"Duration";"Resources";"Criticalness"\n'
            f'"t{task.id}";"1";"Task";"2024-01-01";"2024-01-10";"5.0d";"5.0d";"";"0"\n'
        )

    def test_dispatches_each_file_to_its_matching_scenario(self):
        csv_files = {
            f'schedule_{self.project._tjp_scenario_id(self.plan)}.csv': self._csv_for(self.task),
            f'schedule_{self.project._tjp_scenario_id(self.noai)}.csv': self._csv_for(self.task),
        }
        imported = self.project._import_all_schedules(csv_files)
        self.assertEqual(imported, 2)
        for scenario in (self.plan, self.noai):
            self.assertTrue(self.env['insight.task.schedule'].search([
                ('task_id', '=', self.task.id), ('scenario_id', '=', scenario.id),
            ]))

    def test_ignores_files_with_no_matching_scenario(self):
        csv_files = {'schedule_unknown_scenario.csv': self._csv_for(self.task)}
        imported = self.project._import_all_schedules(csv_files)
        self.assertEqual(imported, 0)


class TestSyncGanttDates(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env['project.project'].create({
            'name': 'Gantt Sync Project',
            'is_tj_enabled': True,
        })
        cls.baseline = cls.env['insight.scenario'].create({
            'name': 'Plan', 'project_id': cls.project.id, 'is_baseline': True,
        })
        cls.alternate = cls.env['insight.scenario'].create({
            'name': 'Noai', 'project_id': cls.project.id, 'is_baseline': False,
        })
        cls.task = cls.env['project.task'].create({'name': 'Synced Task', 'project_id': cls.project.id})

    def _csv_for(self, task, end):
        return (
            '"Id";"Bsi";"Name";"Start";"End";"Effort";"Duration";"Resources";"Criticalness"\n'
            f'"t{task.id}";"1";"Task";"2024-01-01";"{end}";"5.0d";"5.0d";"";"0"\n'
        )

    def test_pushes_baseline_end_date_into_task_deadline(self):
        self.project._import_scenario_csv(self._csv_for(self.task, '2024-02-20'), self.baseline)
        self.project._sync_gantt_dates()
        self.assertTrue(self.task.date_deadline, 'date_deadline should have been populated from the schedule')
        # When project_enterprise is installed it snaps written dates to the
        # task/company working calendar, so we can't assert exact equality
        # here — just that _sync_gantt_dates pushed something in the right
        # ballpark (same date give or take a business day).
        delta_days = abs((self.task.date_deadline.date() - date(2024, 2, 20)).days)
        self.assertLessEqual(delta_days, 3)

    def test_ignores_non_baseline_scenario(self):
        self.project._import_scenario_csv(self._csv_for(self.task, '2099-01-01'), self.alternate)
        self.project._sync_gantt_dates()
        self.assertFalse(self.task.date_deadline)

    def test_noop_without_any_baseline_scenario(self):
        project = self.env['project.project'].create({'name': 'No Baseline Project', 'is_tj_enabled': True})
        # Should not raise even though scenario_ids has no baseline flagged.
        project._sync_gantt_dates()
