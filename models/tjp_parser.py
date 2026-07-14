# -*- coding: utf-8 -*-
"""Parser real (consciente de llaves y strings) de un subconjunto de la
sintaxis TaskJuggler 3 (.tjp) — extrae la jerarquía de tareas, dependencias
(`depends`/`precedes`), pools de recursos (`allocate`), notas y milestones
directamente del texto fuente, porque ninguno de esos datos existe en el CSV
que devuelve TJ3 (el reporte de schedule calculado no tiene columna de
dependencias ni de notas). Usado por `insight_import_wizard.py`.

Verificado contra la gramática real de TaskJuggler (repo
taskjuggler/TaskJuggler, lib/taskjuggler/TjpSyntaxRules.rb) y, para el
algoritmo de resolución de ids relativos en `depends`/`precedes`, contra el
binario real de tj3-ms (v3.8.4) — no es una reimplementación de la gramática
completa de TJ3, solo el subconjunto que necesita este wizard.

Explícitamente fuera de alcance (limitaciones documentadas, no manejo
silencioso incorrecto):
- Strings multilínea "cut-mark" (`-8<- ... ->8-`): si aparecen, se levanta
  TjpParseError en vez de tokenizar mal.
- Modificadores de dependencia `gapduration`/`gaplength` (no los emite
  nuestro propio exportador).
- Modificadores de `allocate` `select`/`shifts` (se ignoran si aparecen; no
  hay dónde mapearlos hoy en el modelo de Odoo).
"""
import re


class TjpParseError(Exception):
    pass


# ── Tokenizer ────────────────────────────────────────────────────────────

_TOKEN_SPEC = [
    ('COMMENT_LINE', r'(?:\#|//)[^\n]*'),
    ('COMMENT_BLOCK', r'/\*.*?\*/'),
    ('WHITESPACE', r'\s+'),
    ('STRING_DQ', r'"(?:\\.|[^"\\])*"'),
    ('STRING_SQ', r"'(?:\\.|[^'\\])*'"),
    ('DURATION', r'\d+(?:\.\d+)?[dwmyhDWMYH]\b'),
    ('NUMBER', r'\d+(?:\.\d+)?'),
    ('DOTTED_ID', r'[a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)+'),
    ('IDENT', r'[a-zA-Z_]\w*'),
    ('BANG', r'!'),
    ('LBRACE', r'\{'),
    ('RBRACE', r'\}'),
    ('COMMA', r','),
    ('OTHER', r'.'),
]
_TOKEN_RE = re.compile(
    '|'.join(f'(?P<{name}>{pattern})' for name, pattern in _TOKEN_SPEC),
    re.DOTALL,
)


class Token:
    __slots__ = ('type', 'value', 'pos')

    def __init__(self, type_, value, pos):
        self.type = type_
        self.value = value
        self.pos = pos

    def __repr__(self):
        return f'Token({self.type}, {self.value!r})'


def tokenize(text):
    """Tokeniza `text` ignorando espacios y comentarios. Los strings
    (comilla simple o doble, con `\\` escapando la comilla que corresponda)
    se consumen enteros como un solo token — así una `{`/`}` dentro de un
    string (ej. `note "algo con { llaves }"`) nunca se cuenta como apertura
    o cierre real de un bloque."""
    if '-8<-' in text:
        raise TjpParseError(
            "Strings multilínea 'cut-mark' (-8<- ... ->8-) no están "
            "soportados por este parser."
        )
    tokens = []
    pos = 0
    length = len(text)
    while pos < length:
        m = _TOKEN_RE.match(text, pos)
        if not m:
            raise TjpParseError(f'No se pudo tokenizar en la posición {pos}')
        kind = m.lastgroup
        value = m.group()
        start = m.start()
        pos = m.end()
        if kind in ('WHITESPACE', 'COMMENT_LINE', 'COMMENT_BLOCK'):
            continue
        if kind == 'STRING_DQ':
            value = value[1:-1].replace('\\"', '"')
        elif kind == 'STRING_SQ':
            value = value[1:-1].replace("\\'", "'")
        tokens.append(Token(kind, value, start))
    return tokens


def find_matching_brace(tokens, open_index):
    """`tokens[open_index]` debe ser un LBRACE. Devuelve el índice del
    RBRACE que lo cierra, contando anidamiento."""
    depth = 1
    i = open_index + 1
    n = len(tokens)
    while i < n:
        if tokens[i].type == 'LBRACE':
            depth += 1
        elif tokens[i].type == 'RBRACE':
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise TjpParseError('Llave sin cerrar en el archivo .tjp')


# ── Árbol de tareas ──────────────────────────────────────────────────────

class Allocation:
    def __init__(self, primary, alternatives=None, persistent=False, mandatory=False):
        self.primary = primary
        self.alternatives = alternatives or []
        self.persistent = persistent
        self.mandatory = mandatory


class DepRef:
    def __init__(self, ref, modifier=None):
        self.ref = ref  # ej. "!!eje7.m7_sso", incluye los '!' originales
        self.modifier = modifier  # 'onstart' | 'onend' | None


class TaskNode:
    def __init__(self, tj_id, name, parent=None):
        self.tj_id = tj_id
        self.name = name
        self.parent = parent
        self.children = []
        self.effort = None
        self.duration = None
        self.allocations = []
        self.raw_depends = []
        self.raw_precedes = []
        self.note = None
        self.is_milestone = False
        self.priority = None
        self.complete = None

    @property
    def full_id(self):
        if self.parent is None:
            return self.tj_id
        return f'{self.parent.full_id}.{self.tj_id}'

    def walk(self):
        """Recorre este nodo y todos sus descendientes (pre-orden)."""
        yield self
        for child in self.children:
            yield from child.walk()

    def __repr__(self):
        return f'TaskNode({self.full_id!r})'


_KNOWN_ATTRIBUTES = {
    'effort', 'duration', 'allocate', 'depends', 'precedes',
    'note', 'milestone', 'priority', 'complete',
}


def parse_tasks(text):
    """Punto de entrada: devuelve la lista de TaskNode raíz (de nivel
    superior) encontrados en `text` — sin importar si están envueltos en un
    bloque `project { ... }` o no (nuestro propio exportador los declara
    fuera de ese bloque; algunos .tjp de afuera podrían anidarlos adentro,
    ambos casos funcionan igual porque el recorrido es por profundidad de
    llaves, no por estructura fija del archivo)."""
    tokens = tokenize(text)
    return _parse_task_list(tokens, 0, len(tokens), parent=None)


def _parse_task_list(tokens, start, end, parent):
    """Recorre tokens[start:end] a profundidad 0 relativa a este rango,
    devolviendo los TaskNode encontrados en ese nivel (hijos directos de
    `parent`, o raíces si `parent` es None). Todo lo demás a este nivel
    (declaraciones de resource/shift/account/project, u otros atributos
    desconocidos) se ignora token por token — sus propios bloques `{}`
    internos se saltean solos por el conteo de profundidad, sin que este
    parser necesite conocer su gramática."""
    nodes = []
    i = start
    depth = 0
    while i < end:
        tok = tokens[i]
        if depth == 0 and tok.type == 'IDENT' and tok.value == 'task':
            node, i = _parse_task_block(tokens, i, end, parent)
            nodes.append(node)
            continue
        if tok.type == 'LBRACE':
            depth += 1
        elif tok.type == 'RBRACE':
            depth -= 1
        i += 1
    return nodes


def _parse_task_block(tokens, i, end, parent):
    """`tokens[i]` es el IDENT 'task'. Devuelve (TaskNode, índice
    siguiente al '}' que cierra su bloque)."""
    i += 1
    if i >= end or tokens[i].type not in ('IDENT', 'DOTTED_ID'):
        raise TjpParseError('Se esperaba un id después de "task"')
    tj_id = tokens[i].value
    i += 1
    if i >= end or tokens[i].type not in ('STRING_DQ', 'STRING_SQ'):
        raise TjpParseError(f'Se esperaba el nombre (string) de la tarea "{tj_id}"')
    name = tokens[i].value
    i += 1
    if i >= end or tokens[i].type != 'LBRACE':
        raise TjpParseError(f'Se esperaba "{{" para abrir el bloque de la tarea "{tj_id}"')
    open_idx = i
    close_idx = find_matching_brace(tokens, open_idx)
    node = TaskNode(tj_id=tj_id, name=name, parent=parent)
    _parse_task_body(tokens, open_idx + 1, close_idx, node)
    return node, close_idx + 1


def _parse_task_body(tokens, start, end, node):
    i = start
    depth = 0
    while i < end:
        tok = tokens[i]
        if depth == 0 and tok.type == 'IDENT':
            kw = tok.value
            if kw == 'task':
                child, i = _parse_task_block(tokens, i, end, node)
                node.children.append(child)
                continue
            if kw in _KNOWN_ATTRIBUTES:
                i = _parse_known_attribute(tokens, i, end, node, kw)
                continue
        if tok.type == 'LBRACE':
            depth += 1
        elif tok.type == 'RBRACE':
            depth -= 1
        i += 1


def _parse_known_attribute(tokens, i, end, node, kw):
    if kw == 'effort':
        i, value = _parse_single_value(tokens, i, end, kw)
        node.effort = value
        return i
    if kw == 'duration':
        i, value = _parse_single_value(tokens, i, end, kw)
        node.duration = value
        return i
    if kw == 'note':
        i, value = _parse_single_value(tokens, i, end, kw)
        node.note = value
        return i
    if kw == 'priority':
        i, value = _parse_single_value(tokens, i, end, kw)
        node.priority = value
        return i
    if kw == 'complete':
        i, value = _parse_single_value(tokens, i, end, kw)
        node.complete = value
        return i
    if kw == 'milestone':
        node.is_milestone = True
        return i + 1
    if kw == 'allocate':
        i, allocation = _parse_allocate(tokens, i, end)
        node.allocations.append(allocation)
        return i
    if kw in ('depends', 'precedes'):
        i, refs = _parse_dep_list(tokens, i, end)
        target = node.raw_depends if kw == 'depends' else node.raw_precedes
        target.extend(refs)
        return i
    raise AssertionError(f'atributo conocido sin manejar: {kw}')  # pragma: no cover


def _parse_single_value(tokens, i, end, kw):
    i += 1
    if i >= end:
        raise TjpParseError(f'"{kw}" sin valor')
    value = tokens[i].value
    return i + 1, value


def _parse_allocate(tokens, i, end):
    """`allocate <id> [{ [alternative <id>[, <id>...]] [persistent]
    [mandatory] ... }]` — `select`/`shifts` (si aparecen dentro del bloque)
    se ignoran, fuera de alcance."""
    i += 1
    if i >= end or tokens[i].type not in ('IDENT', 'DOTTED_ID'):
        raise TjpParseError('Se esperaba un id de recurso después de "allocate"')
    primary = tokens[i].value
    i += 1
    alternatives, persistent, mandatory = [], False, False
    if i < end and tokens[i].type == 'LBRACE':
        close = find_matching_brace(tokens, i)
        j = i + 1
        while j < close:
            t = tokens[j]
            if t.type == 'IDENT' and t.value == 'alternative':
                j += 1
                while j < close and tokens[j].type in ('IDENT', 'DOTTED_ID'):
                    alternatives.append(tokens[j].value)
                    j += 1
                    if j < close and tokens[j].type == 'COMMA':
                        j += 1
                        continue
                    break
                continue
            if t.type == 'IDENT' and t.value == 'persistent':
                persistent = True
            elif t.type == 'IDENT' and t.value == 'mandatory':
                mandatory = True
            j += 1
        i = close + 1
    return i, Allocation(primary, alternatives, persistent, mandatory)


def _parse_dep_list(tokens, i, end):
    """`depends`/`precedes <item>[, <item>]*`, cada item con uno o más
    '!' opcionales, un id (simple o dotted), y un modificador
    `{ onstart }`/`{ onend }` opcional."""
    i += 1
    refs = []
    while True:
        bangs = 0
        while i < end and tokens[i].type == 'BANG':
            bangs += 1
            i += 1
        if i >= end or tokens[i].type not in ('IDENT', 'DOTTED_ID'):
            raise TjpParseError('Se esperaba un id de tarea en la lista de dependencias')
        ref_id = tokens[i].value
        i += 1
        modifier = None
        if i < end and tokens[i].type == 'LBRACE':
            close = find_matching_brace(tokens, i)
            for t in tokens[i + 1:close]:
                if t.type == 'IDENT' and t.value in ('onstart', 'onend'):
                    modifier = t.value
            i = close + 1
        refs.append(DepRef('!' * bangs + ref_id, modifier))
        if i < end and tokens[i].type == 'COMMA':
            i += 1
            continue
        break
    return i, refs


# ── Resolución de dependencias ──────────────────────────────────────────

def build_id_index(roots):
    """Mapa `full_id -> TaskNode` de todo el árbol (todas las raíces y sus
    descendientes) — equivalente al `@propertyMap` de TJ3."""
    index = {}
    for root in roots:
        for node in root.walk():
            index[node.full_id] = node
    return index


def resolve_dep_ref(owner_node, ref):
    """Resuelve `ref` (ej. '!!eje7.m7_sso', '!b', 'a.c') al full_id
    apuntado, tal como lo hace TJ3 real (TjpSyntaxRules.rb,
    rule_taskDepId/rule_relativeId — confirmado además empíricamente
    contra el binario real, ver CHANGELOG): sin '!' el id ya es global, se
    usa tal cual; con uno o más '!', cada uno sube un nivel **desde
    owner_node** (la tarea que declara la dependencia, no desde la raíz
    del proyecto ni desde el target) antes de interpretar el resto como
    relativo a ese ancestro."""
    if not ref.startswith('!'):
        return ref
    node = owner_node
    remainder = ref
    while node is not None and remainder.startswith('!'):
        remainder = remainder[1:]
        node = node.parent
    if remainder.startswith('!'):
        raise TjpParseError(f"Demasiados '!' para la tarea en este contexto: {ref}")
    if node is not None:
        return f'{node.full_id}.{remainder}'
    return remainder
