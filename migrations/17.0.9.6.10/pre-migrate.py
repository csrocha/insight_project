import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """tj_dependency_type pierde la opción 'FF' (pasa a vivir solo como
    override por arista en insight.task.dependency, ver
    dependency_type_ids) — cualquier tarea que la tuviera seteada a nivel
    general se lleva a 'FS' (el default) para no dejar un valor fuera de
    la Selection tras el upgrade.
    """
    cr.execute("""
        SELECT id FROM project_task WHERE tj_dependency_type = 'FF'
    """)
    affected = cr.fetchall()
    if affected:
        _logger.warning(
            "project.task: %d tarea(s) tenían tj_dependency_type='FF' a "
            "nivel de tarea (nunca funcional, siempre fallaba al exportar) "
            "— se llevan a 'FS'. Si alguna necesita FF de verdad, agregar "
            "un override puntual en insight.task.dependency: %s",
            len(affected), [row[0] for row in affected],
        )
        cr.execute("""
            UPDATE project_task SET tj_dependency_type = 'FS'
            WHERE tj_dependency_type = 'FF'
        """)
