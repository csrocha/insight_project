# AGENTS.md - Directrices de Desarrollo para Agentes de IA

**Modulo**: Insight Project
**Proposito**: Integración de Odoo con TaskJuggler 3 para scheduling de proyectos.
**Version actual**: 17.0.1.0.0 | **Entorno**: Odoo 17, rama `develop`

Para las directrices generales de desarrollo de modulos Odoo en Observatorio PyME,
ver el [AGENTS.md de fop_odoo_theme](https://github.com/observatoriopyme/fop_odoo_theme/blob/develop/AGENTS.md).

## Contexto del módulo

- Extiende `project.project` y `project.task`
- El microservicio TJ3 es el canal de scheduling; Odoo no ejecuta TJ3 directamente
- `insight.task.schedule` es de solo escritura del microservicio — el usuario no edita estos registros

## Checklist Pre-commit

- [ ] `__manifest__.py` version en formato `17.0.X.Y.Z` e incrementada correctamente
- [ ] `__init__.py` importa todos los subdirectorios con modulos nuevos
- [ ] Nuevos modelos tienen su entrada en `security/ir.model.access.csv`
- [ ] Vistas usan sintaxis Odoo 17: `invisible="expr"` (no `attrs=`), `<list>` (no `<tree>`)
- [ ] No se usa SQL crudo salvo necesidad justificada de performance
- [ ] Los templates XML usan `t-out` (no `t-esc`) para Odoo 17

## Actualizacion de CHANGELOG (obligatorio)

**Antes de cada commit**, agregar una entrada en `CHANGELOG.md` siguiendo el
formato y las reglas definidas en la **Sección 17 del AGENTS.md raíz** de `fop-odoo`.

No es un checkbox opcional: sin entrada en CHANGELOG no se completa el commit.
