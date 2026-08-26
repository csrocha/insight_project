import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """insight.scenario.project_id (Many2one, required, ondelete=cascade) se
    reemplaza por el modelo intermedio insight.scenario.project
    (scenario_id, project_id, is_baseline): un escenario pasa a poder
    compartirse entre proyectos, y is_baseline pasa a ser una propiedad del
    vínculo (escenario, proyecto), no del escenario solo — ver
    insight_project/models/insight_scenario_project.py.

    A diferencia de la migración 17.0.9.5.0 (skill_id → skill_ids, una
    Many2many pura sin columnas propias, migrada en pre-migrate creando la
    tabla de relación a mano), acá el destino es un modelo completo con su
    propio campo is_baseline y columnas de auditoría — es más simple dejar
    que _auto_init cree la tabla insight_scenario_project con el esquema
    correcto, y recién después copiar los datos. Corre en post-migrate por
    eso: Odoo no borra columnas que un modelo deja de declarar, así que
    insight_scenario.project_id/is_baseline siguen existiendo físicamente
    en este punto, después de que _auto_init ya creó la tabla nueva.
    """
    cr.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'insight_scenario' AND column_name = 'project_id'
    """)
    if not cr.fetchone():
        return

    cr.execute("""
        INSERT INTO insight_scenario_project
            (scenario_id, project_id, is_baseline, create_uid, create_date, write_uid, write_date)
        SELECT id, project_id, COALESCE(is_baseline, false), create_uid, create_date, write_uid, write_date
        FROM insight_scenario WHERE project_id IS NOT NULL
    """)
    cr.execute("""
        SELECT count(*) FROM insight_scenario WHERE project_id IS NULL
    """)
    orphans = cr.fetchone()[0]
    if orphans:
        _logger.warning(
            "insight.scenario: %d fila(s) sin project_id (ya inconsistentes "
            "antes de esta migración, dado que el campo era required) — "
            "quedan sin ningún proyecto vinculado tras la migración.",
            orphans,
        )

    cr.execute("ALTER TABLE insight_scenario DROP COLUMN project_id")
    cr.execute("ALTER TABLE insight_scenario DROP COLUMN IF EXISTS is_baseline")
    _logger.info(
        "insight.scenario: migrado project_id/is_baseline al modelo "
        "intermedio insight.scenario.project."
    )
