# Insight Project — TaskJuggler Integration

Odoo 17 addon that integrates TaskJuggler 3 scheduling into Odoo projects.

## Features

- Schedule Odoo projects via a TaskJuggler 3 microservice
- Multiple planning scenarios per project (baseline, alternative)
- Resource availability from HR employees or manual shifts/vacations
- Schedule results stored in Odoo (`insight.task.schedule`)
- Critical path flag propagated to `project.task`
- TJ3 microservice URL configurable via Settings
- Task systray widget to track active work and switch tasks

## Task flow

A task's flow is made up of three independent dimensions, none of which
replaces the others:

- **Stage (`stage_id`)**: where the task sits within the work process
  (kanban stage).
- **State (`state`)**: the status of the work done on the task.
- **Blocked (`blocked`)**: whether there is an impediment preventing the
  work from continuing.

### Stages (`stage_id`)

- **Needs refinement** — the task was created but doesn't yet have the
  information required to be scheduled (it may be missing description,
  acceptance criteria, assignee, estimate, priority or dependencies). It
  must not be considered by the scheduler.
- **Backlog** — the task is fully defined and ready to be
  prioritized/assigned once resources are available. It's the default
  stage assigned to tasks imported from TaskJuggler that already have
  effort/resources (see `insight_import_wizard.py`).
- **In progress** — at least one assignee is actively working on the
  task.
- **In review** — development is finished and the task is being reviewed
  (technical, functional, QA or user review).
- **Done** — the task was accepted and finished; no further work is
  required.
- **Cancelled** — the task is no longer part of the project (scope
  change, duplicate, client decision, lost priority).

Transitions between "In progress"/"In review"/"Done"/"Cancelled" are made
manually from the task kanban; the TaskJuggler import only assigns Needs
refinement/Backlog/Done based on the effort/resources/percentage-complete
heuristic.

### States (`state`, native to `project.task`)

- **`01_in_progress`** — work continues normally; default state for
  active tasks.
- **`02_changes_requested`** — changes were requested during review; the
  task goes back to active work to be fixed.
- **`03_approved`** — the review was approved; the task is ready to move
  to the Done stage.
- **`04_waiting_normal`** / closed states (`done`/`canceled`) — the task
  is waiting, finished or cancelled.

### `blocked` field

`fields.Boolean` on `project.task`. Indicates that the task temporarily
cannot continue due to an impediment:

- it doesn't change the stage or the state;
- it can happen in any active stage/state;
- it can be turned on and off at any time;
- **it doesn't store the reason** — the reason is recorded as a comment
  in the task's chatter or in the timesheet line
  (`account.analytic.line`), not in this field.

In the session systray (`insight.user.session`):

- On **entering** a task (`switch_task`), `blocked` is reset to `False`
  — actively resuming a task unblocks it, and the captured intent note
  ("what are you going to do?") plays the role of the unblocking
  comment.
- On **leaving** a task (`_close_active_period`), `blocked` is only set
  to `True` if the chosen closing template has `sets_blocked=True` (seed
  template: "The task was blocked because:", with mandatory detail). No
  other exit template touches this field.

## Task systray

The systray widget (`insight_project.InsightSystrayItem`) shows the
current work session in the top bar and lets the user switch tasks or
take a break without leaving the current page.

Backed by `insight.user.session` — a single active session per user
(`user_uniq` SQL constraint) with two states:

- **`active`** — working on `task_id`, timer running since
  `start_datetime`.
- **`break`** — no task assigned.

What the widget shows:

- A chip with the current task name (⚡ if it's on the critical path,
  ✅ otherwise) and a live elapsed/remaining time chip:
  - if the task has `allocated_hours`, it counts down the remaining
    budget and turns warning/critical/overtime colored as it runs out;
  - otherwise it counts up from `start_datetime` with a neutral color.
- A dropdown with:
  - a hint card for the current task (name, description excerpt, "Open
    task" button);
  - the user's tasks due this week (or next week if none are due this
    week), flagging ❗ tasks in review (`needs_review`) and ⚡ tasks on
    the critical path;
  - actions to take a break, pick one of those tasks, or start a new
    one.

Switching task or taking a break opens
`insight.session.switch.wizard`, which:

1. closes the current active period, optionally recording an "outcome"
   note/template (can mark the task as `blocked`) and logging an
   `account.analytic.line` combining the intent note from when the
   period started with the outcome note from when it ended;
2. for a task switch, opens a new period on the target task (existing or
   newly created on the fly), captures an "intent" note/template for
   what's about to be done, and clears `blocked` on that task.

Both notes can be picked from `insight.session.message.template`
(`direction`: `enter`/`leave`), which lets the templates prefill the free
text and, for `leave` templates, opt into `sets_blocked`.

Session changes are pushed over the Odoo bus
(`insight_project.session_updated`) so the widget refreshes live for the
user without a page reload.

## Installation

```bash
git submodule add -b develop https://github.com/csrocha/insight_project addons/insight_project
```

Depends: `project`, `hr_holidays`

## License

OPL-1 — Cristian S. Rocha <csrocha@gmail.com>
