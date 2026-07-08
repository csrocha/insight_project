import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Dos cambios de esquema en esta versión:

    1. project.project.scenario_selection_strategy pasa de 5 opciones
       (manual/min_cost/min_duration/min_resources/weighted_score) a solo 2
       (manual/automatic): las tres estrategias de un solo eje son casos
       particulares de la ponderada con un peso en 1 y el resto en 0 (la
       normalización min-max es monótona, el orden resultante es idéntico),
       así que se reescriben los pesos para preservar el comportamiento
       exacto de cada proyecto.
    2. insight.cost.budget.skill_id (Many2one) pasa a skill_ids (Many2many):
       una línea de costo extra ahora puede depender de más de un skill
       (basta con que la tarea requiera alguno). Se migra el dato existente
       a la nueva tabla de relación antes de que el ORM dropee la columna
       vieja al detectar que el modelo ya no la declara.
    """
    cr.execute("""
        UPDATE project_project
        SET scenario_selection_strategy = 'automatic',
            scenario_weight_cost = 1, scenario_weight_duration = 0, scenario_weight_resources = 0
        WHERE scenario_selection_strategy = 'min_cost'
    """)
    cr.execute("""
        UPDATE project_project
        SET scenario_selection_strategy = 'automatic',
            scenario_weight_cost = 0, scenario_weight_duration = 1, scenario_weight_resources = 0
        WHERE scenario_selection_strategy = 'min_duration'
    """)
    cr.execute("""
        UPDATE project_project
        SET scenario_selection_strategy = 'automatic',
            scenario_weight_cost = 0, scenario_weight_duration = 0, scenario_weight_resources = 1
        WHERE scenario_selection_strategy = 'min_resources'
    """)
    cr.execute("""
        UPDATE project_project SET scenario_selection_strategy = 'automatic'
        WHERE scenario_selection_strategy = 'weighted_score'
    """)

    cr.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'insight_cost_budget' AND column_name = 'skill_id'
    """)
    if cr.fetchone():
        cr.execute("""
            CREATE TABLE IF NOT EXISTS insight_cost_budget_hr_skill_rel (
                cost_budget_id INTEGER NOT NULL REFERENCES insight_cost_budget(id) ON DELETE CASCADE,
                skill_id INTEGER NOT NULL REFERENCES hr_skill(id) ON DELETE CASCADE,
                PRIMARY KEY (cost_budget_id, skill_id)
            )
        """)
        cr.execute("""
            INSERT INTO insight_cost_budget_hr_skill_rel (cost_budget_id, skill_id)
            SELECT id, skill_id FROM insight_cost_budget WHERE skill_id IS NOT NULL
            ON CONFLICT DO NOTHING
        """)
        cr.execute("ALTER TABLE insight_cost_budget DROP COLUMN skill_id")
        _logger.info(
            "insight.cost.budget: migrado skill_id (Many2one) a skill_ids (Many2many)."
        )
