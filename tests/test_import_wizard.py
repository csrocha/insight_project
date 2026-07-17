# -*- coding: utf-8 -*-
"""Tests for insight.import.wizard. Since v17.0.9.7.5, action_analyze parses
the .tjp SOURCE text with tjp_parser (real, brace-aware) instead of TJ3's
CSV report — the CSV has no dependency/note columns, so depend_on_ids and
milestone.task_ids used to be lost on import. Parsing/hierarchy/dependency
concerns now belong to test_tjp_parser.py; this file covers
_resolve_task_stage/_effort_to_hours (unchanged helpers) and the
action_import integration (given an already-parsed `parsed_tasks_json`, does
it create the right tasks/milestones/dependencies)."""
import json

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase

from ..models import tjp_parser
from ..models.insight_import_wizard import InsightImportWizard


class TestImportWizardParsing(TransactionCase):
    """Unit tests for the static helpers that survive the tjp_parser
    rewrite — pure functions, no microservice, no DB writes needed."""

    def test_effort_to_hours(self):
        cases = [
            ('5.0d', 40.0),
            ('1d', 8.0),
            ('8h', 8.0),
            ('1w', 40.0),
            ('0.0d', 0.0),
            ('', 0.0),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertAlmostEqual(InsightImportWizard._effort_to_hours(raw), expected)

    def _stages(self):
        return object(), object(), object()  # refine, backlog, done

    def test_resolve_stage_done(self):
        refine, backlog, done = self._stages()
        result = InsightImportWizard._resolve_task_stage(
            {'complete': '100', 'effort': '5.0d', 'resources': ['x']},
            refine, backlog, done,
        )
        self.assertIs(result, done)

    def test_resolve_stage_refine_no_effort_no_resources(self):
        refine, backlog, done = self._stages()
        result = InsightImportWizard._resolve_task_stage(
            {'complete': '0', 'effort': '0.0d', 'resources': []},
            refine, backlog, done,
        )
        self.assertIs(result, refine)

    def test_resolve_stage_backlog_with_effort(self):
        refine, backlog, done = self._stages()
        result = InsightImportWizard._resolve_task_stage(
            {'complete': '50', 'effort': '5.0d', 'resources': ['csr']},
            refine, backlog, done,
        )
        self.assertIs(result, backlog)

    def test_resolve_stage_backlog_no_resources_with_effort(self):
        """Container task (effort, no resources) → backlog."""
        refine, backlog, done = self._stages()
        result = InsightImportWizard._resolve_task_stage(
            {'complete': '0', 'effort': '10.0d', 'resources': []},
            refine, backlog, done,
        )
        self.assertIs(result, backlog)

    def test_serialize_tree_matches_parser_output(self):
        """_serialize_tree (el puente entre tjp_parser y action_import) debe
        conservar jerarquía, resolver depends/precedes a full_id, y separar
        el pool de recursos de cada `allocate`."""
        roots = tjp_parser.parse_tasks(
            'task a "A" {\n'
            '  task b "B" { }\n'
            '  task c "C" {\n'
            '    depends !b\n'
            '    allocate csr { alternative noel }\n'
            '    note "algo"\n'
            '  }\n'
            '}\n'
        )
        flat = InsightImportWizard._serialize_tree(roots)
        by_full_id = {n['full_id']: n for n in flat}
        self.assertEqual(by_full_id['a']['parent_full_id'], None)
        self.assertEqual(by_full_id['a.b']['parent_full_id'], 'a')
        self.assertEqual(by_full_id['a.c']['depends'], [{'target': 'a.b', 'modifier': None}])
        self.assertEqual(by_full_id['a.c']['resource_ids'], ['csr', 'noel'])
        self.assertEqual(by_full_id['a.c']['note'], 'algo')
        # padre siempre antes que hijo (pre-orden)
        order = [n['full_id'] for n in flat]
        self.assertLess(order.index('a'), order.index('a.b'))
        self.assertLess(order.index('a'), order.index('a.c'))


# ---------------------------------------------------------------------------
# Integration — action_import without microservice
# ---------------------------------------------------------------------------

class TestImportWizardAction(TransactionCase):
    """Tests for action_import: sets up wizard state directly (a
    parsed_tasks_json already in the new tjp_parser/_serialize_tree shape),
    bypassing the microservice call that action_analyze would perform."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env['project.project'].create({
            'name': 'Test Import Project',
        })
        cls.user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Import Test User',
            'login': 'import_test_user@insight.test',
            'email': 'import_test_user@insight.test',
            'groups_id': [(4, cls.env.ref('base.group_user').id)],
        })

    def _make_wizard(self, tasks, resource_maps=None, csv_files=None):
        map_commands = [
            (0, 0, m) for m in (resource_maps or [])
        ]
        return self.env['insight.import.wizard'].create({
            'project_id': self.project.id,
            'state': 'mapping',
            'parsed_tasks_json': json.dumps(tasks),
            'csv_files_json': json.dumps(csv_files or {}),
            'resource_map_ids': map_commands,
        })

    @staticmethod
    def _node(full_id, name, parent_full_id=None, effort='0.0d', complete='0',
              resource_ids=None, primary_ids=None, is_milestone=False, note=None,
              depends=None, precedes=None):
        resource_ids = resource_ids or []
        return {
            'full_id': full_id,
            'parent_full_id': parent_full_id,
            'name': name,
            'effort': effort,
            'complete': complete,
            'is_milestone': is_milestone,
            'note': note,
            'resource_ids': resource_ids,
            # Por defecto, un solo `allocate` cuyo primario es el propio
            # resource_ids (caso simple de un solo recurso, que es lo que
            # usan casi todos estos tests) — pasar primary_ids explícito
            # para simular alternativas (resource_ids con más de un id).
            'primary_ids': primary_ids if primary_ids is not None else resource_ids,
            'depends': depends or [],
            'precedes': precedes or [],
        }

    def _find_task(self, name):
        return self.env['project.task'].search([
            ('project_id', '=', self.project.id), ('name', '=', name),
        ], limit=1)

    # -- Solo en draft / reimportar reemplaza todo -------------------------
    #
    # Proyecto propio (no cls.project, compartido por el resto de la clase)
    # para no interferir con otros tests: action_import borra TODAS las
    # tareas/milestones del proyecto antes de recrear, así que correrlo
    # sobre el proyecto compartido arriesgaría borrar fixtures de otros
    # tests que no controlan el orden de ejecución.

    def test_import_blocked_outside_draft(self):
        project = self.env['project.project'].create({
            'name': 'Reimport Guard Project', 'state': 'progress',
        })
        wizard = self.env['insight.import.wizard'].create({
            'project_id': project.id,
            'state': 'mapping',
            'parsed_tasks_json': json.dumps([self._node('t1', 'Task A')]),
        })
        with self.assertRaises(UserError):
            wizard.action_import()
        self.assertFalse(self.env['project.task'].search([('project_id', '=', project.id)]))

    def test_reimport_blocked_when_a_task_has_logged_timesheets(self):
        """'draft' no garantiza que no haya horas imputadas — reimportar
        borraría esa tarea y Odoo lo rechazaría a mitad de camino
        (hr_timesheet._unlink_except_contains_entries). Se valida antes,
        con un mensaje propio, y no se toca nada del proyecto."""
        project = self.env['project.project'].create({
            'name': 'Reimport With Timesheets Project', 'state': 'draft',
        })
        analytic_plan = self.env['account.analytic.plan'].create({'name': 'Reimport Test Plan'})
        analytic_account = self.env['account.analytic.account'].create({
            'name': 'Reimport Test Analytic', 'plan_id': analytic_plan.id,
        })
        project.analytic_account_id = analytic_account.id
        existing_task = self.env['project.task'].create({
            'name': 'Tarea con horas', 'project_id': project.id,
        })
        employee = self.env['hr.employee'].create({'name': 'Reimport Test Employee'})
        self.env['account.analytic.line'].create({
            'name': '/', 'account_id': analytic_account.id,
            'task_id': existing_task.id, 'employee_id': employee.id,
            'date': '2026-07-01', 'unit_amount': 2.0,
        })

        wizard = self.env['insight.import.wizard'].create({
            'project_id': project.id,
            'state': 'mapping',
            'parsed_tasks_json': json.dumps([self._node('t1', 'Nueva Tarea')]),
        })
        with self.assertRaises(UserError):
            wizard.action_import()

        self.assertTrue(existing_task.exists(), 'La tarea con horas imputadas no debe tocarse')
        self.assertFalse(self.env['project.task'].search([
            ('project_id', '=', project.id), ('name', '=', 'Nueva Tarea'),
        ]), 'No debe haberse creado nada del import fallido')

    def test_reimport_replaces_previous_tasks_and_milestones(self):
        project = self.env['project.project'].create({
            'name': 'Reimport Project', 'state': 'draft',
        })

        def _wizard(tasks):
            return self.env['insight.import.wizard'].create({
                'project_id': project.id,
                'state': 'mapping',
                'parsed_tasks_json': json.dumps(tasks),
            })

        _wizard([
            self._node('old1', 'Old Task', effort='1.0d'),
            self._node('old_m', 'Old Milestone', is_milestone=True),
        ]).action_import()
        self.assertTrue(self.env['project.task'].search([
            ('project_id', '=', project.id), ('name', '=', 'Old Task'),
        ]))

        _wizard([
            self._node('new1', 'New Task', effort='2.0d'),
        ]).action_import()

        self.assertFalse(self.env['project.task'].search([
            ('project_id', '=', project.id), ('name', '=', 'Old Task'),
        ]), 'La tarea de la importación anterior debe desaparecer')
        self.assertFalse(self.env['project.milestone'].search([
            ('project_id', '=', project.id), ('name', '=', 'Old Milestone'),
        ]), 'El milestone de la importación anterior debe desaparecer')
        self.assertTrue(self.env['project.task'].search([
            ('project_id', '=', project.id), ('name', '=', 'New Task'),
        ]))

    # -- User assignment -------------------------------------------------------

    def test_user_assigned_to_task(self):
        """El recurso primario de un `allocate` mapeado debe terminar en
        user_ids del task creado."""
        wizard = self._make_wizard(
            tasks=[self._node('t1', 'Task A', effort='5.0d', resource_ids=['csr'])],
            resource_maps=[{
                'tj_resource_id': 'csr',
                'tj_resource_name': 'Import Test User',
                'action': 'map',
                'user_id': self.user.id,
            }],
        )
        wizard.action_import()

        task = self._find_task('Task A')
        self.assertTrue(task, "Task should have been created")
        self.assertIn(self.user, task.user_ids)
        self.assertIn(self.user, task.resource_pool_ids)

    def test_skipped_resource_not_assigned(self):
        """Resources with action='skip' must not appear in task.user_ids."""
        wizard = self._make_wizard(
            tasks=[self._node('t1', 'Task Skip', effort='3.0d', resource_ids=['csr'])],
            resource_maps=[{
                'tj_resource_id': 'csr',
                'tj_resource_name': 'Import Test User',
                'action': 'skip',
                'user_id': self.user.id,
            }],
        )
        wizard.action_import()

        task = self._find_task('Task Skip')
        self.assertFalse(task.user_ids)

    def test_unmatched_resource_not_assigned(self):
        """Resource with action='map' but no user_id selected → not assigned to task."""
        wizard = self._make_wizard(
            tasks=[self._node('t1', 'Task Unmatched', effort='3.0d', resource_ids=['ext'])],
            resource_maps=[{
                'tj_resource_id': 'ext',
                'tj_resource_name': 'Unknown Person',
                'action': 'map',
                'user_id': False,
            }],
        )
        wizard.action_import()

        task = self._find_task('Task Unmatched')
        self.assertFalse(task.user_ids, "No user selected — task must have no assignees")

    # -- Task hierarchy --------------------------------------------------------

    def test_hierarchy_parent_child(self):
        wizard = self._make_wizard(tasks=[
            self._node('p', 'Phase 1', effort='10.0d'),
            self._node('p.1', 'Subtask 1.1', parent_full_id='p', effort='5.0d'),
            self._node('p.2', 'Subtask 1.2', parent_full_id='p', effort='5.0d'),
        ])
        wizard.action_import()

        parent = self._find_task('Phase 1')
        child1 = self._find_task('Subtask 1.1')
        child2 = self._find_task('Subtask 1.2')
        self.assertTrue(parent)
        self.assertEqual(child1.parent_id, parent)
        self.assertEqual(child2.parent_id, parent)

    def test_root_tasks_have_no_parent(self):
        wizard = self._make_wizard(tasks=[
            self._node('r1', 'Root 1', effort='2.0d'),
            self._node('r2', 'Root 2', effort='2.0d'),
        ])
        wizard.action_import()

        for name in ('Root 1', 'Root 2'):
            self.assertFalse(self._find_task(name).parent_id)

    # -- Stage assignment ------------------------------------------------------

    def test_stage_done_for_100_percent(self):
        wizard = self._make_wizard(tasks=[
            self._node('t1', 'Done Task', effort='5.0d', complete='100'),
        ])
        wizard.action_import()
        self.assertEqual(
            self._find_task('Done Task').stage_id,
            self.env.ref('insight_project.task_type_done'),
        )

    def test_state_done_for_100_percent(self):
        """project.task.state (nativo, distinto de stage_id) también debe
        quedar en 'Hecho' para una tarea 100% completa — si no, su
        _compute_state la deja en 'En progreso'/'Esperando' aunque el
        stage_id ya diga 'Completada'."""
        wizard = self._make_wizard(tasks=[
            self._node('t1', 'Done Task State', effort='5.0d', complete='100'),
        ])
        wizard.action_import()
        self.assertEqual(self._find_task('Done Task State').state, '1_done')

    def test_state_not_forced_for_incomplete_task(self):
        wizard = self._make_wizard(tasks=[
            self._node('t1', 'Incomplete Task', effort='5.0d', complete='50'),
        ])
        wizard.action_import()
        self.assertNotEqual(self._find_task('Incomplete Task').state, '1_done')

    def test_dependent_task_not_waiting_on_a_done_blocker(self):
        """Si el bloqueante quedó con state='1_done', la tarea dependiente
        no debe computarse como 'Esperando' (04_waiting_normal) por su
        causa — ver _compute_state nativo (project/models/project_task.py)."""
        wizard = self._make_wizard(tasks=[
            self._node('a', 'Bloqueante Completo', effort='1.0d', complete='100'),
            self._node('b', 'Dependiente', effort='1.0d', complete='0',
                       depends=[{'target': 'a', 'modifier': None}]),
        ])
        wizard.action_import()
        self.assertEqual(self._find_task('Bloqueante Completo').state, '1_done')
        self.assertNotEqual(self._find_task('Dependiente').state, '04_waiting_normal')

    def test_stage_refine_for_no_effort_no_resources(self):
        wizard = self._make_wizard(tasks=[
            self._node('t1', 'Unrefined', effort='0.0d', complete='0'),
        ])
        wizard.action_import()
        self.assertEqual(
            self._find_task('Unrefined').stage_id,
            self.env.ref('insight_project.task_type_refine'),
        )

    def test_stage_backlog_for_normal_task(self):
        wizard = self._make_wizard(tasks=[
            self._node('t1', 'Normal Task', effort='8.0d', complete='50'),
        ])
        wizard.action_import()
        self.assertEqual(
            self._find_task('Normal Task').stage_id,
            self.env.ref('insight_project.task_type_planned'),
        )

    # -- Milestone linking -------------------------------------------------

    def test_milestone_flagged_node_creates_milestone_not_task(self):
        wizard = self._make_wizard(tasks=[
            self._node('m1', 'Go live', effort='0.0d', is_milestone=True),
        ])
        wizard.action_import()

        self.assertFalse(self._find_task('Go live'), 'Milestone nodes must not create a project.task')
        milestone = self.env['project.milestone'].search([
            ('project_id', '=', self.project.id), ('name', '=', 'Go live'),
        ], limit=1)
        self.assertTrue(milestone)
        self.assertTrue(self.project.allow_milestones)

    def test_non_milestone_task_has_no_milestone_link(self):
        wizard = self._make_wizard(tasks=[
            self._node('t1', 'Regular Task', effort='5.0d', is_milestone=False),
        ])
        wizard.action_import()
        task = self._find_task('Regular Task')
        self.assertTrue(task)
        self.assertFalse(task.milestone_id)

    def test_milestone_node_does_not_break_sibling_hierarchy(self):
        """Un nodo milestone entre hermanos reales no debe romper la
        resolución de parent_id de los demás — simplemente no genera
        project.task ni entra en record_by_full_id como tarea."""
        wizard = self._make_wizard(tasks=[
            self._node('p', 'Phase 1', effort='10.0d'),
            self._node('p.1', 'Subtask A', parent_full_id='p', effort='5.0d'),
            self._node('p.2', 'Milestone A', parent_full_id='p', effort='0.0d', is_milestone=True),
            self._node('p.3', 'Subtask B', parent_full_id='p', effort='5.0d'),
        ])
        wizard.action_import()

        parent = self._find_task('Phase 1')
        subtask_b = self._find_task('Subtask B')
        self.assertEqual(subtask_b.parent_id, parent)
        self.assertFalse(self._find_task('Milestone A'))

    # -- Dependencies (nuevo: antes se perdían por completo) --------------

    def test_fs_dependency_populates_depend_on_ids(self):
        wizard = self._make_wizard(tasks=[
            self._node('a', 'Bloqueante', effort='1.0d'),
            self._node('b', 'Dependiente', effort='1.0d',
                       depends=[{'target': 'a', 'modifier': None}]),
        ])
        wizard.action_import()
        blocker = self._find_task('Bloqueante')
        dependent = self._find_task('Dependiente')
        self.assertIn(blocker, dependent.depend_on_ids)
        self.assertFalse(self.env['insight.task.dependency'].search([('task_id', '=', dependent.id)]))

    def test_ss_dependency_creates_override(self):
        wizard = self._make_wizard(tasks=[
            self._node('a', 'Bloqueante', effort='1.0d'),
            self._node('b', 'Dependiente', effort='1.0d',
                       depends=[{'target': 'a', 'modifier': 'onstart'}]),
        ])
        wizard.action_import()
        blocker = self._find_task('Bloqueante')
        dependent = self._find_task('Dependiente')
        self.assertIn(blocker, dependent.depend_on_ids)
        override = self.env['insight.task.dependency'].search([
            ('task_id', '=', dependent.id), ('depends_on_id', '=', blocker.id),
        ])
        self.assertEqual(override.dependency_type, 'SS')

    def test_precedes_creates_ff_override(self):
        wizard = self._make_wizard(tasks=[
            self._node('a', 'Bloqueante FF', effort='1.0d'),
            self._node('b', 'Dependiente', effort='1.0d',
                       precedes=[{'target': 'a', 'modifier': 'onend'}]),
        ])
        wizard.action_import()
        blocker = self._find_task('Bloqueante FF')
        dependent = self._find_task('Dependiente')
        self.assertIn(blocker, dependent.depend_on_ids)
        override = self.env['insight.task.dependency'].search([
            ('task_id', '=', dependent.id), ('depends_on_id', '=', blocker.id),
        ])
        self.assertEqual(override.dependency_type, 'FF')

    def test_dependency_target_outside_import_is_ignored(self):
        """Una referencia a un full_id que no existe en este import (ej.
        otra rama en un archivo separado) no debe romper el import — se
        ignora en silencio, no hay nada contra qué linkear."""
        wizard = self._make_wizard(tasks=[
            self._node('b', 'Dependiente', effort='1.0d',
                       depends=[{'target': 'otro_archivo.tarea_x', 'modifier': None}]),
        ])
        wizard.action_import()
        dependent = self._find_task('Dependiente')
        self.assertFalse(dependent.depend_on_ids)

    def test_milestone_task_ids_populated_from_depends(self):
        wizard = self._make_wizard(tasks=[
            self._node('t1', 'Deliverable', effort='5.0d'),
            self._node('m1', 'Go live', effort='0.0d', is_milestone=True,
                       depends=[{'target': 't1', 'modifier': None}]),
        ])
        wizard.action_import()
        deliverable = self._find_task('Deliverable')
        milestone = self.env['project.milestone'].search([
            ('project_id', '=', self.project.id), ('name', '=', 'Go live'),
        ], limit=1)
        self.assertIn(deliverable, milestone.task_ids)

    # -- End-to-end con el fixture real reportado (bug de milestones) ------

    def test_full_pipeline_eje8_fixture_creates_dependencies_and_milestone_links(self):
        """Reproducción end-to-end del caso real reportado (m8_portal/
        m8_comunidad anidados dentro de "eje8", con `depends` antes de
        `milestone` y una `note` final): antes de tjp_parser, esto solo
        se probaba para el detalle de "no crear project.task" — ahora
        además debe poblar depend_on_ids de las tareas reales y task_ids
        de los milestones, que es exactamente lo que se perdía con el
        parseo basado en CSV."""
        eje8_tjp = (
            'task eje8 "Eje VIII: Ecosistema de Micrositios y Portal FOP" {\n'
            '  task t8_1 "Portal FOP Central" {\n'
            '    effort 6w\n'
            '    allocate csr { alternative noel }\n'
            '  }\n'
            '  task t8_2 "Micrositio Comunidad FOP" {\n'
            '    depends !t8_1\n'
            '    effort 4w\n'
            '    allocate csr\n'
            '  }\n'
            '  task m8_portal "Portal FOP Central en producción" {\n'
            '    depends !t8_1\n'
            '    milestone\n'
            '    note "Entregable: Portal institucional FOP con SSO en producción"\n'
            '  }\n'
            '  task m8_comunidad "Micrositio Comunidad FOP en producción" {\n'
            '    depends !t8_2\n'
            '    milestone\n'
            '  }\n'
            '}\n'
        )
        roots = tjp_parser.parse_tasks(eje8_tjp)
        tasks = InsightImportWizard._serialize_tree(roots)
        wizard = self._make_wizard(tasks=tasks)
        wizard.action_import()

        for name in ('Portal FOP Central en producción', 'Micrositio Comunidad FOP en producción'):
            self.assertFalse(
                self._find_task(name),
                f'"{name}" es un milestone — no debe crear un project.task',
            )
            self.assertTrue(
                self.env['project.milestone'].search([
                    ('project_id', '=', self.project.id), ('name', '=', name),
                ]),
                f'"{name}" debería existir como project.milestone',
            )

        t8_1 = self._find_task('Portal FOP Central')
        t8_2 = self._find_task('Micrositio Comunidad FOP')
        self.assertTrue(t8_1)
        # milestone_id es el inverso nativo de project.milestone.task_ids —
        # queda seteado porque t8_1 es la tarea real detrás del hito, no
        # un bug (antes ni siquiera llegaba a poblarse task_ids).
        self.assertEqual(t8_1.milestone_id.name, 'Portal FOP Central en producción')
        self.assertIn(t8_1, t8_2.depend_on_ids, 'depend_on_ids ya no debe perderse en el import')

        portal_milestone = self.env['project.milestone'].search([
            ('project_id', '=', self.project.id),
            ('name', '=', 'Portal FOP Central en producción'),
        ], limit=1)
        comunidad_milestone = self.env['project.milestone'].search([
            ('project_id', '=', self.project.id),
            ('name', '=', 'Micrositio Comunidad FOP en producción'),
        ], limit=1)
        self.assertIn(t8_1, portal_milestone.task_ids, 'task_ids del milestone ya no debe quedar vacío')
        self.assertIn(t8_2, comunidad_milestone.task_ids)

    def test_note_maps_to_task_description(self):
        wizard = self._make_wizard(tasks=[
            self._node('t1', 'Con nota', effort='1.0d', note='Detalle importante'),
        ])
        wizard.action_import()
        task = self._find_task('Con nota')
        # `description` es un campo Html (sanitizado por Odoo al guardar),
        # así que se compara por contenido, no por igualdad exacta de string.
        self.assertIn('Detalle importante', task.description or '')
