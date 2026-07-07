# -*- coding: utf-8 -*-
import json

from odoo.tests.common import TransactionCase

from ..models.insight_import_wizard import InsightImportWizard


# ---------------------------------------------------------------------------
# Static helpers — no DB needed
# ---------------------------------------------------------------------------

class TestImportWizardParsing(TransactionCase):
    """Unit tests for the static parsing helpers — no microservice involved."""

    _TJ3_CSV = (
        '"Id";"Bsi";"Name";"Start";"End";"Effort";"Duration";"Resources";"Criticalness";"Complete"\n'
        '"p.t1";"1";"Task A";"2024-01-01";"2024-01-10";"5.0d";"5.0d";"John Doe (jdoe)";"100";"0%"\n'
        '"p.t2";"2";"Task B";"2024-01-11";"2024-01-20";"3.0d";"3.0d";"Jane Smith (jsmith)";"50";"100%"\n'
        '"p.t3";"3";"Empty";"2024-01-21";"2024-01-25";"0.0d";"0.0d";"";"0";"0%"\n'
    )

    def test_semicolon_delimiter_detected(self):
        tasks, resource_ids = InsightImportWizard._parse_csv_preview(self._TJ3_CSV)
        self.assertEqual(len(tasks), 3)

    def test_resource_ids_extracted_from_parens(self):
        tasks, resource_ids = InsightImportWizard._parse_csv_preview(self._TJ3_CSV)
        self.assertIn('jdoe', resource_ids)
        self.assertIn('jsmith', resource_ids)
        self.assertNotIn('', resource_ids)

    def test_complete_field_preserved(self):
        tasks, _ = InsightImportWizard._parse_csv_preview(self._TJ3_CSV)
        self.assertEqual(tasks[0]['complete'], '0%')
        self.assertEqual(tasks[1]['complete'], '100%')

    def test_empty_resources_row(self):
        tasks, resource_ids = InsightImportWizard._parse_csv_preview(self._TJ3_CSV)
        self.assertEqual(tasks[2]['resources'], [])
        self.assertNotIn('', resource_ids)

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

    def test_find_milestone_task_ids_detects_bare_keyword(self):
        tjp = (
            'task t1 "Deliverable" {\n'
            '  effort 5d\n'
            '}\n'
            'task t2 "Go live" {\n'
            '  milestone\n'
            '  depends !t1\n'
            '}\n'
        )
        self.assertEqual(InsightImportWizard._find_milestone_task_ids(tjp), {'t2'})

    def test_find_milestone_task_ids_ignores_nested_children(self):
        """A parent task without its own `milestone` line must not be
        flagged just because a nested child happens to declare one."""
        tjp = (
            'task t1 "Phase" {\n'
            '  task t1_1 "Kickoff" {\n'
            '    milestone\n'
            '  }\n'
            '}\n'
        )
        self.assertEqual(InsightImportWizard._find_milestone_task_ids(tjp), {'t1_1'})

    def test_parse_csv_preview_flags_milestone_rows(self):
        tasks, _ = InsightImportWizard._parse_csv_preview(self._TJ3_CSV, {'t2'})
        by_bsi = {t['bsi']: t for t in tasks}
        self.assertFalse(by_bsi['1']['is_milestone'])
        self.assertTrue(by_bsi['2']['is_milestone'])

    def _stages(self):
        return object(), object(), object()  # refine, backlog, done

    def test_resolve_stage_done(self):
        refine, backlog, done = self._stages()
        result = InsightImportWizard._resolve_task_stage(
            {'complete': '100%', 'effort': '5.0d', 'resources': ['x']},
            refine, backlog, done,
        )
        self.assertIs(result, done)

    def test_resolve_stage_refine_no_effort_no_resources(self):
        refine, backlog, done = self._stages()
        result = InsightImportWizard._resolve_task_stage(
            {'complete': '0%', 'effort': '0.0d', 'resources': []},
            refine, backlog, done,
        )
        self.assertIs(result, refine)

    def test_resolve_stage_backlog_with_effort(self):
        refine, backlog, done = self._stages()
        result = InsightImportWizard._resolve_task_stage(
            {'complete': '50%', 'effort': '5.0d', 'resources': ['csr']},
            refine, backlog, done,
        )
        self.assertIs(result, backlog)

    def test_resolve_stage_backlog_no_resources_with_effort(self):
        """Container task (effort, no resources) → backlog."""
        refine, backlog, done = self._stages()
        result = InsightImportWizard._resolve_task_stage(
            {'complete': '0%', 'effort': '10.0d', 'resources': []},
            refine, backlog, done,
        )
        self.assertIs(result, backlog)


# ---------------------------------------------------------------------------
# Integration — action_import without microservice
# ---------------------------------------------------------------------------

class TestImportWizardAction(TransactionCase):
    """Tests for action_import: sets up wizard state directly, bypassing the
    microservice call that action_analyze would perform."""

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

    # -- User assignment -------------------------------------------------------

    def test_user_assigned_to_task(self):
        """Mapped user must appear in task.user_ids."""
        wizard = self._make_wizard(
            tasks=[{'bsi': '1', 'name': 'Task A', 'effort': '5.0d',
                    'resources': ['csr'], 'complete': '0%'}],
            resource_maps=[{
                'tj_resource_id': 'csr',
                'tj_resource_name': 'Import Test User',
                'action': 'map',
                'user_id': self.user.id,
            }],
        )
        wizard.action_import()

        task = self.env['project.task'].search([
            ('project_id', '=', self.project.id),
            ('name', '=', 'Task A'),
        ], limit=1)
        self.assertTrue(task, "Task should have been created")
        self.assertIn(
            self.user,
            task.user_ids,
            f"Expected {self.user.name} in user_ids; got {task.user_ids.mapped('name')}",
        )

    def test_skipped_resource_not_assigned(self):
        """Resources with action='skip' must not appear in task.user_ids."""
        wizard = self._make_wizard(
            tasks=[{'bsi': '1', 'name': 'Task Skip', 'effort': '3.0d',
                    'resources': ['csr'], 'complete': '0%'}],
            resource_maps=[{
                'tj_resource_id': 'csr',
                'tj_resource_name': 'Import Test User',
                'action': 'skip',
                'user_id': self.user.id,
            }],
        )
        wizard.action_import()

        task = self.env['project.task'].search([
            ('project_id', '=', self.project.id),
            ('name', '=', 'Task Skip'),
        ], limit=1)
        self.assertFalse(task.user_ids, f"No user should be assigned; got {task.user_ids.mapped('name')}")

    def test_unmatched_resource_not_assigned(self):
        """Resource with action='map' but no user_id selected → not assigned to task."""
        wizard = self._make_wizard(
            tasks=[{'bsi': '1', 'name': 'Task Unmatched', 'effort': '3.0d',
                    'resources': ['ext'], 'complete': '0%'}],
            resource_maps=[{
                'tj_resource_id': 'ext',
                'tj_resource_name': 'Unknown Person',
                'action': 'map',
                'user_id': False,
            }],
        )
        wizard.action_import()

        task = self.env['project.task'].search([
            ('project_id', '=', self.project.id),
            ('name', '=', 'Task Unmatched'),
        ], limit=1)
        self.assertFalse(task.user_ids, "No user selected — task must have no assignees")

    # -- Task hierarchy --------------------------------------------------------

    def test_bsi_hierarchy_parent_child(self):
        """BSI dotted notation must produce parent → child task relationships."""
        wizard = self._make_wizard(tasks=[
            {'bsi': '1',   'name': 'Phase 1',    'effort': '10.0d', 'resources': [], 'complete': '0%'},
            {'bsi': '1.1', 'name': 'Subtask 1.1','effort': '5.0d',  'resources': [], 'complete': '0%'},
            {'bsi': '1.2', 'name': 'Subtask 1.2','effort': '5.0d',  'resources': [], 'complete': '0%'},
        ])
        wizard.action_import()

        parent = self.env['project.task'].search([
            ('project_id', '=', self.project.id), ('name', '=', 'Phase 1')
        ], limit=1)
        child1 = self.env['project.task'].search([
            ('project_id', '=', self.project.id), ('name', '=', 'Subtask 1.1')
        ], limit=1)
        child2 = self.env['project.task'].search([
            ('project_id', '=', self.project.id), ('name', '=', 'Subtask 1.2')
        ], limit=1)
        self.assertTrue(parent, "Parent task should exist")
        self.assertEqual(child1.parent_id, parent, "Subtask 1.1 should have Phase 1 as parent")
        self.assertEqual(child2.parent_id, parent, "Subtask 1.2 should have Phase 1 as parent")

    def test_root_tasks_have_no_parent(self):
        wizard = self._make_wizard(tasks=[
            {'bsi': '1', 'name': 'Root 1', 'effort': '2.0d', 'resources': [], 'complete': '0%'},
            {'bsi': '2', 'name': 'Root 2', 'effort': '2.0d', 'resources': [], 'complete': '0%'},
        ])
        wizard.action_import()

        for name in ('Root 1', 'Root 2'):
            task = self.env['project.task'].search([
                ('project_id', '=', self.project.id), ('name', '=', name)
            ], limit=1)
            self.assertFalse(task.parent_id, f"{name} should have no parent")

    # -- Stage assignment ------------------------------------------------------

    def test_stage_done_for_100_percent(self):
        wizard = self._make_wizard(tasks=[
            {'bsi': '1', 'name': 'Done Task', 'effort': '5.0d',
             'resources': [], 'complete': '100%'},
        ])
        wizard.action_import()

        task = self.env['project.task'].search([
            ('project_id', '=', self.project.id), ('name', '=', 'Done Task')
        ], limit=1)
        stage_done = self.env.ref('insight_project.task_type_done')
        self.assertEqual(task.stage_id, stage_done)

    def test_stage_refine_for_no_effort_no_resources(self):
        wizard = self._make_wizard(tasks=[
            {'bsi': '1', 'name': 'Unrefined', 'effort': '0.0d',
             'resources': [], 'complete': '0%'},
        ])
        wizard.action_import()

        task = self.env['project.task'].search([
            ('project_id', '=', self.project.id), ('name', '=', 'Unrefined')
        ], limit=1)
        stage_refine = self.env.ref('insight_project.task_type_refine')
        self.assertEqual(task.stage_id, stage_refine)

    def test_stage_backlog_for_normal_task(self):
        wizard = self._make_wizard(tasks=[
            {'bsi': '1', 'name': 'Normal Task', 'effort': '8.0d',
             'resources': [], 'complete': '50%'},
        ])
        wizard.action_import()

        task = self.env['project.task'].search([
            ('project_id', '=', self.project.id), ('name', '=', 'Normal Task')
        ], limit=1)
        stage_backlog = self.env.ref('insight_project.task_type_planned')
        self.assertEqual(task.stage_id, stage_backlog)

    # -- Milestone linking -------------------------------------------------

    def test_milestone_flagged_task_gets_linked_to_new_milestone(self):
        """A task detected as a TJP `milestone` (see _find_milestone_task_ids)
        must not just be created as a bare 0-effort task: it must be linked
        to a real project.milestone, same as our own tjp export/import
        round-trip does."""
        wizard = self._make_wizard(tasks=[
            {'bsi': '1', 'name': 'Go live', 'effort': '0.0d',
             'resources': [], 'complete': '0%', 'is_milestone': True},
        ])
        wizard.action_import()

        task = self.env['project.task'].search([
            ('project_id', '=', self.project.id), ('name', '=', 'Go live')
        ], limit=1)
        self.assertTrue(task.milestone_id, "Task should be linked to a project.milestone")
        self.assertEqual(task.milestone_id.name, 'Go live')
        self.assertTrue(self.project.allow_milestones)

    def test_non_milestone_task_has_no_milestone_link(self):
        wizard = self._make_wizard(tasks=[
            {'bsi': '1', 'name': 'Regular Task', 'effort': '5.0d',
             'resources': [], 'complete': '0%', 'is_milestone': False},
        ])
        wizard.action_import()

        task = self.env['project.task'].search([
            ('project_id', '=', self.project.id), ('name', '=', 'Regular Task')
        ], limit=1)
        self.assertFalse(task.milestone_id)
