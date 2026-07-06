# -*- coding: utf-8 -*-
"""Regression tests for running the TJ3 scheduler (action_run_schedule and
_call_tj_microservice). The tj3 microservice is always mocked — either at
the HTTP boundary (requests.post) to pin _call_tj_microservice's own error
handling, or at the _call_tj_microservice boundary to test action_run_schedule
in isolation from HTTP concerns entirely.
"""
import requests
from unittest.mock import MagicMock, patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase

from ..models.project_project import ProjectProject, UnscheduledTasksError


class TestActionRunScheduleGuards(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env['project.project'].create({'name': 'Scheduler Guard Project'})

    def test_requires_tj_enabled(self):
        with self.assertRaises(UserError):
            self.project.action_run_schedule()

    def test_requires_at_least_one_scenario(self):
        self.project.is_tj_enabled = True
        with self.assertRaises(UserError):
            self.project.action_run_schedule()

    def test_requires_microservice_url_configured(self):
        self.project.is_tj_enabled = True
        self.env['insight.scenario'].create({
            'name': 'Plan', 'project_id': self.project.id, 'is_baseline': True,
        })
        self.env['ir.config_parameter'].sudo().set_param('insight_project.tj_microservice_url', '')
        with self.assertRaises(UserError):
            self.project.action_run_schedule()


class TestActionRunScheduleSuccess(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env['project.project'].create({
            'name': 'Scheduler Success Project',
            'is_tj_enabled': True,
        })
        cls.scenario = cls.env['insight.scenario'].create({
            'name': 'Plan', 'project_id': cls.project.id, 'is_baseline': True,
        })
        cls.task = cls.env['project.task'].create({
            'name': 'Task A', 'project_id': cls.project.id, 'user_ids': [(6, 0, [])],
        })
        cls.env['ir.config_parameter'].sudo().set_param('insight_project.tj_microservice_url', 'http://tj3.local')

    def _mock_csv_files(self):
        sc_id = self.project._tjp_scenario_id(self.scenario)
        content = (
            '"Id";"Bsi";"Name";"Start";"End";"Effort";"Duration";"Resources";"Criticalness"\n'
            f'"t{self.task.id}";"1";"Task A";"2024-01-01";"2024-01-10";"5.0d";"5.0d";"";"0"\n'
        )
        return {f'schedule_{sc_id}.csv': content}

    def test_success_marks_project_and_imports_schedule(self):
        with patch.object(
            ProjectProject, '_call_tj_microservice',
            return_value={'csv_files': self._mock_csv_files()},
        ) as mocked_call:
            result = self.project.action_run_schedule()

        self.assertTrue(mocked_call.called)
        self.assertFalse(self.project.schedule_dirty)
        self.assertTrue(self.project.last_scheduled)
        self.assertEqual(result['params']['type'], 'success')

        schedule = self.env['insight.task.schedule'].search([
            ('task_id', '=', self.task.id), ('scenario_id', '=', self.scenario.id),
        ])
        self.assertTrue(schedule, 'Schedule should have been imported from the mocked tj3 response')

    def test_generated_tjp_and_url_are_passed_to_the_microservice(self):
        with patch.object(
            ProjectProject, '_call_tj_microservice',
            return_value={'csv_files': {}},
        ) as mocked_call:
            self.project.action_run_schedule()

        args, _kwargs = mocked_call.call_args
        # patch.object() replaces the class attribute with a plain MagicMock,
        # which isn't a descriptor — Python won't auto-bind `self` when it's
        # invoked via the instance, so only (base_url, tjp_content, timeout)
        # show up here regardless.
        base_url, tjp_content, timeout = args[-3:]
        self.assertEqual(base_url, 'http://tj3.local')
        self.assertIn(f'project p{self.project.id}', tjp_content)
        self.assertIsInstance(timeout, int)


class TestCallTjMicroservice(TransactionCase):
    """Pins the HTTP contract with the tj3 microservice: payload shape and
    how each requests.exceptions family maps to a UserError."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env['project.project'].create({'name': 'Microservice Contract Project'})

    def test_posts_expected_payload_shape(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {'csv_files': {}}
        with patch('requests.post', return_value=mock_response) as mocked_post:
            result = self.project._call_tj_microservice('http://tj3.local', 'project p1 {}', 60)

        self.assertEqual(result, {'csv_files': {}})
        called_url = mocked_post.call_args.args[0]
        called_kwargs = mocked_post.call_args.kwargs
        self.assertEqual(called_url, 'http://tj3.local/schedule')
        self.assertEqual(called_kwargs['json'], {'tjp_content': 'project p1 {}', 'timeout': 60})
        self.assertEqual(called_kwargs['timeout'], 75)

    def test_connection_error_raises_user_error(self):
        with patch('requests.post', side_effect=requests.exceptions.ConnectionError()):
            with self.assertRaises(UserError):
                self.project._call_tj_microservice('http://tj3.local', 'project p1 {}', 60)

    def test_timeout_raises_user_error(self):
        with patch('requests.post', side_effect=requests.exceptions.Timeout()):
            with self.assertRaises(UserError):
                self.project._call_tj_microservice('http://tj3.local', 'project p1 {}', 60)

    def test_generic_http_error_includes_detail(self):
        error_response = MagicMock()
        error_response.json.return_value = {'detail': {'error': 'malformed tjp'}}
        http_error = requests.exceptions.HTTPError(response=error_response)
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = http_error
        with patch('requests.post', return_value=mock_response):
            with self.assertRaises(UserError) as ctx:
                self.project._call_tj_microservice('http://tj3.local', 'project p1 {}', 60)
        self.assertIn('malformed tjp', str(ctx.exception))

    def _mock_unscheduled_response(self, n):
        error_response = MagicMock()
        error_response.json.return_value = {'detail': {'stderr': f'{n} tasks could not be scheduled'}}
        http_error = requests.exceptions.HTTPError(response=error_response)
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = http_error
        return mock_response

    def test_unscheduled_tasks_raises_the_dedicated_exception_type(self):
        """UnscheduledTasksError (a UserError subclass) lets action_run_schedule
        tell this specific failure apart from any other UserError and offer
        the interactive wizard instead of just failing."""
        with patch('requests.post', return_value=self._mock_unscheduled_response(3)):
            with self.assertRaises(UnscheduledTasksError) as ctx:
                self.project._call_tj_microservice('http://tj3.local', 'project p1 {}', 60)
        self.assertEqual(ctx.exception.n_unscheduled, 3)
        self.assertIn('3 tarea(s)', ctx.exception.message)
        self.assertIn('3 tarea(s)', str(ctx.exception))

    def test_unscheduled_tasks_error_posts_a_message_on_the_project(self):
        # Deliberately plain try/except instead of self.assertRaises(): Odoo's
        # TransactionCase.assertRaises wraps its block in a savepoint and
        # rolls back to it once it catches the expected exception, which
        # would silently undo the message_post() that happened right before
        # the raise — defeating the point of this test.
        with patch('requests.post', return_value=self._mock_unscheduled_response(2)):
            try:
                self.project._call_tj_microservice('http://tj3.local', 'project p1 {}', 60)
                raised = False
            except UnscheduledTasksError:
                raised = True
        self.assertTrue(raised)

        messages = self.env['mail.message'].search([
            ('model', '=', 'project.project'), ('res_id', '=', self.project.id),
        ])
        self.assertTrue(
            messages.filtered(lambda m: '2 tarea(s)' in (m.body or '')),
            'An explanatory message should have been posted on the project chatter',
        )


class TestActionRunScheduleUnscheduledTasks(TransactionCase):
    """action_run_schedule(interactive=...) branches on UnscheduledTasksError:
    interactively it offers a wizard to extend the horizon; non-interactive
    callers (cron, RPC) just get the plain UserError."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env['project.project'].create({
            'name': 'Unscheduled Tasks Project',
            'is_tj_enabled': True,
        })
        cls.env['insight.scenario'].create({
            'name': 'Plan', 'project_id': cls.project.id, 'is_baseline': True,
        })
        cls.env['ir.config_parameter'].sudo().set_param('insight_project.tj_microservice_url', 'http://tj3.local')

    def _mock_unscheduled(self, n=2):
        return patch.object(
            ProjectProject, '_call_tj_microservice',
            side_effect=UnscheduledTasksError(n, f'{n} tarea(s) no entran en el horizonte.'),
        )

    def test_interactive_default_returns_wizard_instead_of_raising(self):
        with self._mock_unscheduled(2):
            result = self.project.action_run_schedule()

        self.assertEqual(result['res_model'], 'insight.unscheduled.tasks.wizard')
        wizard = self.env['insight.unscheduled.tasks.wizard'].browse(result['res_id'])
        self.assertEqual(wizard.project_id, self.project)
        self.assertIn('tarea(s)', wizard.message)

    def test_non_interactive_raises_user_error_instead(self):
        with self._mock_unscheduled(2):
            with self.assertRaises(UserError):
                self.project.action_run_schedule(interactive=False)

    def test_wizard_extend_horizon_writes_suggested_date_on_project(self):
        wizard = self.env['insight.unscheduled.tasks.wizard'].create({
            'project_id': self.project.id,
            'message': '2 tarea(s) no entran en el horizonte.',
            'suggested_horizon': '2027-01-01',
        })
        wizard.action_extend_horizon()
        self.assertEqual(str(self.project.tj_end_date), '2027-01-01')

    def test_wizard_modify_project_does_not_touch_the_horizon(self):
        wizard = self.env['insight.unscheduled.tasks.wizard'].create({
            'project_id': self.project.id,
            'message': '2 tarea(s) no entran en el horizonte.',
            'suggested_horizon': '2027-01-01',
        })
        wizard.action_modify_project()
        self.assertFalse(self.project.tj_end_date)
