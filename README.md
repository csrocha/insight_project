# Insight Project — TaskJuggler Integration

Odoo 17 addon that integrates TaskJuggler 3 scheduling into Odoo projects.

## Features

- Schedule Odoo projects via a TaskJuggler 3 microservice
- Multiple planning scenarios per project (baseline, alternative)
- Resource availability from HR employees or manual shifts/vacations
- Schedule results stored in Odoo (`insight.task.schedule`)
- Critical path flag propagated to `project.task`
- TJ3 microservice URL configurable via Settings

## Installation

```bash
git submodule add -b develop https://github.com/csrocha/insight_project addons/insight_project
```

Depends: `project`, `hr_holidays`

## License

OPL-1 — Cristian S. Rocha <csrocha@gmail.com>
