# -*- coding: utf-8 -*-
"""Regression tests for running the TJ3 scheduler (action_run_schedule and
_call_tj_microservice). The tj3 microservice is always mocked — either at
the HTTP boundary (requests.post) to pin _call_tj_microservice's own error
handling, or at the _call_tj_microservice boundary to test action_run_schedule
in isolation from HTTP concerns entirely.
"""
import requests
from unittest.mock import MagicMock, patch

from odoo import fields
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

        # El aviso flotante (result['params']) desaparece solo — el éxito
        # también debe quedar como nota en el chatter, igual que ya pasa con
        # cualquier error de la corrida (ver _tj_post_error).
        messages = self.env['mail.message'].search([
            ('model', '=', 'project.project'), ('res_id', '=', self.project.id),
        ])
        self.assertTrue(
            messages.filtered(lambda m: result['params']['message'] in (m.body or '')),
            'El mensaje de éxito debe quedar posteado en el chatter del proyecto',
        )

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


class TestActionRunScheduleSuccessPortfolio(TransactionCase):
    """Bug real (2026-07-30): en estado 'progress', una sola corrida
    recalcula TODOS los proyectos 'en progreso' a la vez — un único
    `.tjp` combinado, un único POST a tj3-ms (ver
    _tj_portfolio_recordset/_generate_tjp) — pero la nota de éxito en el
    chatter (agregada en esta misma sesión) al principio solo se posteaba
    en `self` (el proyecto que disparó el click), dejando a los demás
    proyectos combinados sin ningún rastro del schedule que también se
    les acaba de aplicar. Corregido postéandola en `persisted` (mismo
    recordset que ya se usa para el write-back de schedule_dirty/
    last_scheduled), iterando porque message_post no acepta multi-record."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.driver = cls.env['project.project'].create({
            'name': 'Portfolio Driver', 'is_tj_enabled': True, 'state': 'progress',
        })
        cls.peer = cls.env['project.project'].create({
            'name': 'Portfolio Peer', 'is_tj_enabled': True, 'state': 'progress',
        })
        cls.env['insight.scenario'].create({
            'name': 'Plan', 'project_id': cls.driver.id, 'is_baseline': True,
        })
        cls.env['insight.scenario'].create({
            'name': 'Plan', 'project_id': cls.peer.id, 'is_baseline': True,
        })
        cls.env['ir.config_parameter'].sudo().set_param('insight_project.tj_microservice_url', 'http://tj3.local')

    def test_success_note_posted_on_every_persisted_project_with_a_single_call(self):
        with patch.object(
            ProjectProject, '_call_tj_microservice',
            return_value={'csv_files': {}},
        ) as mocked_call:
            self.driver.action_run_schedule()

        self.assertEqual(
            mocked_call.call_count, 1,
            'Un solo _call_tj_microservice por corrida, sin importar cuántos '
            'proyectos "en progreso" se combinen — no debe ejecutarse una '
            'vez por proyecto.',
        )
        for project in (self.driver, self.peer):
            messages = self.env['mail.message'].search([
                ('model', '=', 'project.project'), ('res_id', '=', project.id),
            ])
            self.assertTrue(
                messages.filtered(lambda m: 'Schedule actualizado' in (m.body or '')),
                f'{project.name} debe tener la nota de éxito en su propio chatter',
            )


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

    def _messages_on_project(self):
        return self.env['mail.message'].search([
            ('model', '=', 'project.project'), ('res_id', '=', self.project.id),
        ])

    def test_connection_error_raises_user_error(self):
        with patch('requests.post', side_effect=requests.exceptions.ConnectionError()):
            with self.assertRaises(UserError):
                self.project._call_tj_microservice('http://tj3.local', 'project p1 {}', 60)

    def test_connection_error_posts_a_message_on_the_project(self):
        # Plain try/except, no assertRaises(): ver comentario en
        # test_unscheduled_tasks_error_posts_a_message_on_the_project — el
        # savepoint de assertRaises revertiría el message_post.
        with patch('requests.post', side_effect=requests.exceptions.ConnectionError()):
            try:
                self.project._call_tj_microservice('http://tj3.local', 'project p1 {}', 60)
                raised = False
            except UserError:
                raised = True
        self.assertTrue(raised)
        self.assertTrue(
            self._messages_on_project().filtered(lambda m: 'tj3.local' in (m.body or '')),
            'Un error de conexión al microservicio TJ3 debe quedar asentado en el chatter',
        )

    def test_timeout_raises_user_error(self):
        with patch('requests.post', side_effect=requests.exceptions.Timeout()):
            with self.assertRaises(UserError):
                self.project._call_tj_microservice('http://tj3.local', 'project p1 {}', 60)

    def test_timeout_posts_a_message_on_the_project(self):
        with patch('requests.post', side_effect=requests.exceptions.Timeout()):
            try:
                self.project._call_tj_microservice('http://tj3.local', 'project p1 {}', 60)
                raised = False
            except UserError:
                raised = True
        self.assertTrue(raised)
        self.assertTrue(
            self._messages_on_project().filtered(lambda m: 'Timeout' in (m.body or '')),
            'Un timeout del microservicio TJ3 debe quedar asentado en el chatter',
        )

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

    def test_generic_http_error_posts_a_message_on_the_project(self):
        """Este es el caso que faltaba: un error de parseo/scheduling de TJ3
        (.tjp mal formado, 'no duty', timing resolution, etc.) que no matchea
        el patrón de 'unscheduled tasks' antes no dejaba ningún rastro en el
        chatter — solo un popup momentáneo que se perdía apenas se cerraba."""
        error_response = MagicMock()
        error_response.json.return_value = {'detail': {'error': 'malformed tjp'}}
        http_error = requests.exceptions.HTTPError(response=error_response)
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = http_error
        with patch('requests.post', return_value=mock_response):
            try:
                self.project._call_tj_microservice('http://tj3.local', 'project p1 {}', 60)
                raised = False
            except UserError:
                raised = True
        self.assertTrue(raised)
        self.assertTrue(
            self._messages_on_project().filtered(lambda m: 'malformed tjp' in (m.body or '')),
            'Un error genérico del microservicio TJ3 debe quedar asentado en el chatter',
        )

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
        self.assertEqual(str(self.project.date), '2027-01-01')

    def test_wizard_modify_project_does_not_touch_the_horizon(self):
        wizard = self.env['insight.unscheduled.tasks.wizard'].create({
            'project_id': self.project.id,
            'message': '2 tarea(s) no entran en el horizonte.',
            'suggested_horizon': '2027-01-01',
        })
        wizard.action_modify_project()
        self.assertFalse(self.project.date)


class TestActionRunScheduleHorizonWarning(TransactionCase):
    """action_run_schedule debe avisar (chatter + actividad) cuando el
    horizonte derivado de las tareas supera la fecha pactada (self.date),
    sin sobreescribir jamás self.date."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env['project.project'].create({
            'name': 'Horizon Warning Project',
            'is_tj_enabled': True,
            'date_start': '2026-01-01',
            'date': '2026-02-01',
        })
        cls.env['insight.scenario'].create({
            'name': 'Plan', 'project_id': cls.project.id, 'is_baseline': True,
        })
        cls.env['ir.config_parameter'].sudo().set_param('insight_project.tj_microservice_url', 'http://tj3.local')

    def _run_schedule(self):
        with patch.object(
            ProjectProject, '_call_tj_microservice',
            return_value={'csv_files': {}},
        ):
            self.project.action_run_schedule()

    def test_warns_and_does_not_overwrite_agreed_date_when_horizon_overruns(self):
        self._run_schedule()

        self.assertEqual(
            str(self.project.date), '2026-02-01',
            'self.date (fecha pactada) nunca debe sobreescribirse automáticamente',
        )

        messages = self.env['mail.message'].search([
            ('model', '=', 'project.project'), ('res_id', '=', self.project.id),
        ])
        self.assertTrue(
            messages.filtered(lambda m: 'Requiere revisión' in (m.body or '')),
            'Debe postearse un aviso en el chatter cuando el horizonte derivado supera self.date',
        )

        activities = self.env['mail.activity'].search([
            ('res_model', '=', 'project.project'), ('res_id', '=', self.project.id),
        ])
        self.assertTrue(activities, 'Debe agendarse una actividad de revisión')
        self.assertEqual(activities.user_id, self.project.user_id or self.env.user)

    def test_no_warning_when_agreed_date_covers_the_horizon(self):
        self.project.date = '2028-06-29'  # más allá del fallback de +2 años

        self._run_schedule()

        activities = self.env['mail.activity'].search([
            ('res_model', '=', 'project.project'), ('res_id', '=', self.project.id),
        ])
        self.assertFalse(activities, 'No debe agendarse revisión si self.date ya cubre el horizonte derivado')


class TestSuggestHorizonNeverShrinks(TransactionCase):
    """Bug real (2026-07-29, datos de producción): _tjp_suggest_horizon
    sumaba la duración estimada siempre desde `date_start` solo, sin pisar
    contra el horizonte YA configurado (`self.date`). Con un proyecto viejo
    (`date_start` lejano) y `self.date` ya extendido varias veces a mano, la
    cuenta a secas podía dar una fecha MENOR a la ya puesta — el botón
    "Extender horizonte de planificación" del wizard terminaba ENCOGIENDO
    el horizonte en vez de ampliarlo, y volver a programar fallaba de nuevo
    con el mismo "N tareas no entran" (confirmado contra el historial real
    de tracking de un proyecto de producción: `date` pasó de 2029-08-31 a
    2029-08-16 al apretar "Extender")."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env['project.project'].create({
            'name': 'Suggest Horizon Project',
            'is_tj_enabled': True,
            'date_start': '2020-01-01',
        })
        Task = cls.env['project.task'].with_context(default_project_id=cls.project.id)
        Task.create({
            'name': 'Tarea con esfuerzo',
            'project_id': cls.project.id,
            'allocated_hours': 40.0,
            'user_ids': [(6, 0, [cls.env.user.id])],
        })

    def test_never_suggests_earlier_than_the_already_configured_date(self):
        far_future = fields.Date.from_string('2035-01-01')
        self.project.date = far_future

        suggested = self.project._tjp_suggest_horizon(self.project.date_start)

        self.assertGreater(
            suggested, far_future,
            '"Extender" nunca debe sugerir (ni aplicar) una fecha anterior '
            'o igual a la ya configurada.',
        )

    def test_falls_back_to_start_when_no_date_is_configured(self):
        self.project.date = False
        start = fields.Date.from_string('2020-01-01')

        suggested = self.project._tjp_suggest_horizon(start)

        self.assertGreater(suggested, start)
