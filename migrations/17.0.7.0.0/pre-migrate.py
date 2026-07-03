def migrate(cr, version):
    """insight.user.session -> work.item.session (task_id Many2one ->
    work_item_ref Reference; project_id se descarta) e
    insight.session.message.template -> work.item.message.template pasan a
    vivir en el addon work_item_systray. Sin este script, la próxima
    actualización de insight_project borraría esas tablas y sus datos
    (sesiones activas, plantillas) al ya no declararlas.

    insight.session.switch.wizard no se migra: es un TransientModel sin
    datos que preservar, se deja que la tabla vieja quede huérfana y que
    work.item.session.switch.wizard cree la suya.
    """

    # --- insight.user.session -> work.item.session ---
    cr.execute("ALTER TABLE insight_user_session RENAME TO work_item_session")
    cr.execute("ALTER TABLE work_item_session ADD COLUMN work_item_ref character varying")
    cr.execute("""
        UPDATE work_item_session
        SET work_item_ref = 'project.task,' || task_id
        WHERE task_id IS NOT NULL
    """)
    cr.execute("ALTER TABLE work_item_session DROP COLUMN task_id")
    cr.execute("ALTER TABLE work_item_session DROP COLUMN project_id")

    # --- insight.session.message.template -> work.item.message.template ---
    cr.execute("ALTER TABLE insight_session_message_template RENAME TO work_item_message_template")

    cr.execute("UPDATE ir_model SET model = 'work.item.session' WHERE model = 'insight.user.session'")
    cr.execute(
        "UPDATE ir_model SET model = 'work.item.message.template' "
        "WHERE model = 'insight.session.message.template'"
    )

    # Reasigna la propiedad (módulo + nombre del xmlid) del ir.model y de los
    # ir.model.fields reflejados que sobreviven, de insight_project a
    # work_item_systray. Sin esto, la próxima vez que se actualicen los
    # módulos, cada uno vería un xmlid que "ya no declara" y lo borraría —
    # arrastrando consigo el ir.model/ir.model.fields real.
    moves = [
        # (tabla vieja, tabla nueva, [campos que sobreviven sin cambios])
        ('insight_user_session', 'work_item_session',
         ['user_id', 'state', 'start_datetime', 'intent_note']),
        ('insight_session_message_template', 'work_item_message_template',
         ['name', 'direction', 'requires_detail', 'sets_blocked', 'sequence', 'active']),
    ]
    for old_table, new_table, fields_kept in moves:
        cr.execute("""
            UPDATE ir_model_data
            SET module = 'work_item_systray', name = %s
            WHERE module = 'insight_project' AND name = %s
        """, (f'model_{new_table}', f'model_{old_table}'))
        for field in fields_kept:
            cr.execute("""
                UPDATE ir_model_data
                SET module = 'work_item_systray', name = %s
                WHERE module = 'insight_project' AND name = %s
            """, (f'field_{new_table}__{field}', f'field_{old_table}__{field}'))
