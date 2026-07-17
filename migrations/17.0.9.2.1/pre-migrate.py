def migrate(cr, version):
    """tj_now/tj_end_date se eliminan: duplicaban date_start/date, ya
    nativos de project.project. El código de scheduling ahora lee
    date_start/date directamente en vez de mantener un override propio.
    Corre en pre-migrate para copiar los valores ya cargados antes de que
    el ORM dropee las columnas viejas al actualizar con los campos ya
    removidos del modelo; no pisa date_start/date si ya tienen un valor
    cargado a mano.
    """
    cr.execute("""
        UPDATE project_project
        SET date_start = tj_now
        WHERE tj_now IS NOT NULL AND date_start IS NULL
    """)
    cr.execute("""
        UPDATE project_project
        SET date = tj_end_date
        WHERE tj_end_date IS NOT NULL
          AND date IS NULL
          AND tj_end_date >= COALESCE(date_start, tj_end_date)
    """)
