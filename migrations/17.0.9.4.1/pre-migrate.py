import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """insight.scenario.efficiency.partner_id (res.partner) se reemplaza por
    user_id (res.users): los recursos seleccionables de tareas/proyecto
    (resource_pool_ids, candidate_user_ids, user_ids) ya eran siempre
    res.users, no res.partner — el picker de eficiencia por escenario
    permitía elegir cualquier contacto, no solo un recurso válido del
    proyecto. Corre en pre-migrate para poblar user_id antes de que el ORM
    agregue la constraint NOT NULL sobre la nueva columna.
    """
    cr.execute("""
        ALTER TABLE insight_scenario_efficiency
        ADD COLUMN IF NOT EXISTS user_id INTEGER
    """)
    cr.execute("""
        UPDATE insight_scenario_efficiency e
        SET user_id = ru.id
        FROM res_users ru
        WHERE ru.partner_id = e.partner_id
    """)
    cr.execute("""
        SELECT id, partner_id FROM insight_scenario_efficiency
        WHERE user_id IS NULL
    """)
    orphans = cr.fetchall()
    if orphans:
        _logger.warning(
            "insight.scenario.efficiency: %d fila(s) sin res.users para su "
            "partner_id (contacto sin usuario Odoo asociado), se eliminan "
            "por no poder migrarse a user_id: %s",
            len(orphans), orphans,
        )
        cr.execute("""
            DELETE FROM insight_scenario_efficiency WHERE user_id IS NULL
        """)
