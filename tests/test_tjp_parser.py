# -*- coding: utf-8 -*-
"""Tests for models/tjp_parser.py — the real (brace/string-aware) .tjp
source parser that replaces the old non-brace-matching regex heuristic
(_find_milestone_task_ids) used by the import wizard.

No DB needed: pure Python, uses odoo.tests.common.BaseCase just to get
picked up by the Odoo test runner alongside the rest of the module's suite.
"""
from odoo.tests.common import BaseCase

from ..models import tjp_parser as tp


class TestTokenize(BaseCase):

    def test_strips_whitespace_and_line_comments(self):
        tokens = tp.tokenize('task a "A" { # comment\n  effort 1d // trailing\n}')
        kinds = [t.type for t in tokens]
        self.assertNotIn('COMMENT_LINE', kinds)
        values = [t.value for t in tokens]
        self.assertIn('effort', values)
        self.assertIn('a', values)

    def test_strips_block_comments_multiline(self):
        tokens = tp.tokenize('task a "A" {\n/* this\nis a\nblock */\n  milestone\n}')
        values = [t.value for t in tokens]
        self.assertIn('milestone', values)
        self.assertNotIn('this', values)

    def test_string_with_braces_is_a_single_token_not_real_braces(self):
        tokens = tp.tokenize('note "algo con { llaves } adentro"')
        types = [t.type for t in tokens]
        self.assertEqual(types, ['IDENT', 'STRING_DQ'])
        self.assertEqual(tokens[1].value, 'algo con { llaves } adentro')

    def test_escaped_quote_inside_string(self):
        tokens = tp.tokenize(r'note "she said \"hi\""')
        self.assertEqual(tokens[1].value, 'she said "hi"')

    def test_single_quoted_string(self):
        tokens = tp.tokenize("note 'hola'")
        self.assertEqual(tokens[1].value, 'hola')

    def test_duration_token(self):
        tokens = tp.tokenize('effort 6w')
        self.assertEqual(tokens[1].type, 'DURATION')
        self.assertEqual(tokens[1].value, '6w')

    def test_dotted_id_token(self):
        tokens = tp.tokenize('depends !eje7.m7_sso')
        self.assertEqual(tokens[0].type, 'IDENT')
        self.assertEqual(tokens[1].type, 'BANG')
        self.assertEqual(tokens[2].type, 'DOTTED_ID')
        self.assertEqual(tokens[2].value, 'eje7.m7_sso')

    def test_cut_mark_string_raises(self):
        with self.assertRaises(tp.TjpParseError):
            tp.tokenize('note -8<-\nmultiline\n->8-')


class TestFindMatchingBrace(BaseCase):

    def test_finds_matching_brace_with_nesting(self):
        tokens = tp.tokenize('{ a { b } c }')
        close = tp.find_matching_brace(tokens, 0)
        self.assertEqual(tokens[close].type, 'RBRACE')
        self.assertEqual(close, len(tokens) - 1)

    def test_braces_inside_string_do_not_confuse_matching(self):
        """El bug real que reemplaza este parser: la heurística vieja
        (_find_milestone_task_ids) cortaba por texto plano, sin contar
        llaves — una nota con '{'/'}' literales adentro la confundía."""
        tokens = tp.tokenize('task a "A" { note "{ not a brace }" milestone }')
        open_idx = next(i for i, t in enumerate(tokens) if t.type == 'LBRACE')
        close = tp.find_matching_brace(tokens, open_idx)
        self.assertEqual(close, len(tokens) - 1)

    def test_unclosed_brace_raises(self):
        tokens = tp.tokenize('{ a { b }')
        with self.assertRaises(tp.TjpParseError):
            tp.find_matching_brace(tokens, 0)


class TestParseTasks(BaseCase):

    def test_single_task_no_attributes(self):
        roots = tp.parse_tasks('task t1 "Simple" { }')
        self.assertEqual(len(roots), 1)
        self.assertEqual(roots[0].tj_id, 't1')
        self.assertEqual(roots[0].name, 'Simple')
        self.assertEqual(roots[0].full_id, 't1')

    def test_nested_hierarchy_and_full_id(self):
        roots = tp.parse_tasks(
            'task a "A" {\n'
            '  task b "B" {\n'
            '    task c "C" { }\n'
            '  }\n'
            '}\n'
        )
        a = roots[0]
        b = a.children[0]
        c = b.children[0]
        self.assertEqual(a.full_id, 'a')
        self.assertEqual(b.full_id, 'a.b')
        self.assertEqual(c.full_id, 'a.b.c')

    def test_multiple_root_tasks(self):
        roots = tp.parse_tasks('task a "A" { }\ntask b "B" { }\n')
        self.assertEqual([r.tj_id for r in roots], ['a', 'b'])

    def test_skips_unknown_top_level_constructs(self):
        """resource/shift/project declarations no deben confundirse con
        tareas ni romper el conteo de profundidad."""
        text = (
            'project p "P" 2024-01-01 - 2024-06-01 {\n'
            '  timezone "UTC"\n'
            '}\n'
            'resource r1 "R1" {\n'
            '  rate 100\n'
            '}\n'
            'task a "A" {\n'
            '  effort 1d\n'
            '}\n'
        )
        roots = tp.parse_tasks(text)
        self.assertEqual([r.tj_id for r in roots], ['a'])
        self.assertEqual(roots[0].effort, '1d')

    def test_effort_and_duration(self):
        roots = tp.parse_tasks('task a "A" { effort 6w duration 10d }')
        self.assertEqual(roots[0].effort, '6w')
        self.assertEqual(roots[0].duration, '10d')

    def test_priority(self):
        roots = tp.parse_tasks('task a "A" { priority 800 }')
        self.assertEqual(roots[0].priority, '800')

    def test_note_maps_to_note_field(self):
        roots = tp.parse_tasks('task a "A" { note "Entregable importante" }')
        self.assertEqual(roots[0].note, 'Entregable importante')

    def test_note_containing_braces_does_not_break_parsing(self):
        roots = tp.parse_tasks(
            'task a "A" {\n'
            '  note "resultado esperado: { 100% listo }"\n'
            '  milestone\n'
            '}\n'
        )
        self.assertTrue(roots[0].is_milestone)
        self.assertIn('{ 100% listo }', roots[0].note)

    def test_milestone_bare_keyword(self):
        roots = tp.parse_tasks('task a "A" { milestone }')
        self.assertTrue(roots[0].is_milestone)

    def test_milestone_not_inherited_by_parent(self):
        roots = tp.parse_tasks(
            'task a "A" {\n  task b "B" {\n    milestone\n  }\n}\n'
        )
        self.assertFalse(roots[0].is_milestone)
        self.assertTrue(roots[0].children[0].is_milestone)

    def test_allocate_primary_only(self):
        roots = tp.parse_tasks('task a "A" { allocate csr }')
        allocs = roots[0].allocations
        self.assertEqual(len(allocs), 1)
        self.assertEqual(allocs[0].primary, 'csr')
        self.assertEqual(allocs[0].alternatives, [])

    def test_allocate_with_alternatives_and_modifiers(self):
        roots = tp.parse_tasks(
            'task a "A" { allocate csr { alternative noel, ana persistent mandatory } }'
        )
        alloc = roots[0].allocations[0]
        self.assertEqual(alloc.primary, 'csr')
        self.assertEqual(alloc.alternatives, ['noel', 'ana'])
        self.assertTrue(alloc.persistent)
        self.assertTrue(alloc.mandatory)

    def test_multiple_allocate_lines_are_separate_puestos(self):
        roots = tp.parse_tasks('task a "A" { allocate noel\n  allocate csr }')
        self.assertEqual([a.primary for a in roots[0].allocations], ['noel', 'csr'])

    def test_depends_simple_and_comma_list(self):
        roots = tp.parse_tasks('task a "A" { depends !b, !!c.d }')
        refs = [d.ref for d in roots[0].raw_depends]
        self.assertEqual(refs, ['!b', '!!c.d'])

    def test_depends_with_onstart_modifier(self):
        roots = tp.parse_tasks('task a "A" { depends !b { onstart } }')
        dep = roots[0].raw_depends[0]
        self.assertEqual(dep.ref, '!b')
        self.assertEqual(dep.modifier, 'onstart')

    def test_precedes_with_onend_modifier(self):
        roots = tp.parse_tasks('task a "A" { precedes !b { onend } }')
        dep = roots[0].raw_precedes[0]
        self.assertEqual(dep.ref, '!b')
        self.assertEqual(dep.modifier, 'onend')


class TestBuildIdIndexAndResolve(BaseCase):

    def _tree(self):
        return tp.parse_tasks(
            'task a "A" {\n'
            '  task b "B" { }\n'
            '  task c "C" {\n'
            '    depends !b\n'
            '  }\n'
            '}\n'
            'task x "X" { }\n'
        )

    def test_build_id_index_covers_all_nodes(self):
        roots = self._tree()
        index = tp.build_id_index(roots)
        self.assertEqual(set(index.keys()), {'a', 'a.b', 'a.c', 'x'})

    def test_resolve_absolute_id_used_as_is(self):
        self.assertEqual(tp.resolve_dep_ref(object(), 'a.b'), 'a.b')

    def test_resolve_single_bang_from_sibling(self):
        roots = self._tree()
        index = tp.build_id_index(roots)
        c = index['a.c']
        resolved = tp.resolve_dep_ref(c, '!b')
        self.assertEqual(resolved, 'a.b')
        self.assertIn(resolved, index)

    def test_resolve_double_bang_reaches_global_scope(self):
        """Reproduce el fixture real (!!eje7.m7_sso): 2 '!' desde una
        tarea de profundidad 1 agotan sus ancestros y dejan el resto del
        id como global."""
        roots = self._tree()
        index = tp.build_id_index(roots)
        b = index['a.b']  # profundidad 1 (padre: a)
        resolved = tp.resolve_dep_ref(b, '!!x')
        self.assertEqual(resolved, 'x')
        self.assertIn(resolved, index)

    def test_too_many_bangs_raises(self):
        roots = self._tree()
        index = tp.build_id_index(roots)
        b = index['a.b']
        with self.assertRaises(tp.TjpParseError):
            tp.resolve_dep_ref(b, '!!!x')

    def test_real_fixture_cross_branch_reference(self):
        """El caso real del fixture EJE8: !!eje7.m7_sso declarado dentro
        de una tarea de profundidad 1 debe resolver al id global
        'eje7.m7_sso', sin importar que 'eje7' no exista en este árbol
        (la resolución de refs no depende de que el target exista — eso
        se valida en un paso posterior, al buscar en el índice)."""
        roots = tp.parse_tasks(
            'task eje8 "Eje VIII" {\n'
            '  task t8_1 "Portal" {\n'
            '    depends !!eje7.m7_sso\n'
            '    effort 6w\n'
            '  }\n'
            '}\n'
        )
        t8_1 = roots[0].children[0]
        ref = t8_1.raw_depends[0].ref
        self.assertEqual(ref, '!!eje7.m7_sso')
        self.assertEqual(tp.resolve_dep_ref(t8_1, ref), 'eje7.m7_sso')
