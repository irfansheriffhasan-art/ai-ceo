"""Task graph helpers: creation from specs, dependency resolution, readiness."""

from __future__ import annotations

from ..agents import TaskSpec
from ..db import Store, Task
from ..states import TERMINAL_TASK_STATUSES, TaskKind, TaskStatus

# Deterministic agents need fewer attempts; LLM agents get the configured budget.
_DETERMINISTIC_KINDS = {TaskKind.BREAKDOWN, TaskKind.SECURITY, TaskKind.DEPLOY}


def create_from_specs(
    store: Store,
    project_id: str,
    specs: list[TaskSpec],
    *,
    iteration: int,
    created_by: str,
    max_attempts: int,
    timeout_s: float,
) -> list[Task]:
    """Create tasks, resolving ``depends_on_keys`` against the specs in this batch."""
    key_to_id: dict[str, str] = {}
    created: list[Task] = []
    pending = list(specs)
    # Create in dependency order so keys resolve; fall back to given order on cycles.
    for _ in range(len(specs) + 1):
        progressed = False
        for spec in list(pending):
            if all(k in key_to_id for k in spec.depends_on_keys):
                deps = [key_to_id[k] for k in spec.depends_on_keys] + list(spec.depends_on_ids)
                t = store.create_task(
                    project_id=project_id,
                    title=spec.title[:200],
                    description=spec.description,
                    role=spec.role,
                    kind=spec.kind,
                    priority=spec.priority,
                    depends_on=deps,
                    iteration=iteration,
                    max_attempts=2 if spec.kind in _DETERMINISTIC_KINDS else max_attempts,
                    timeout_s=timeout_s,
                    input=spec.input,
                    created_by=created_by,
                    status=TaskStatus.BACKLOG,
                )
                key_to_id[spec.key] = t.id
                created.append(t)
                pending.remove(spec)
                progressed = True
        if not pending:
            break
        if not progressed:  # cycle or unknown key: drop the unresolved deps rather than deadlock
            spec = pending[0]
            spec.depends_on_keys = [k for k in spec.depends_on_keys if k in key_to_id]
    return created


def deps_satisfied(task: Task, by_id: dict[str, Task]) -> bool:
    for dep in task.depends_on or []:
        d = by_id.get(dep)
        if d is None:
            continue  # dependency was deleted; don't deadlock
        if d.status not in (TaskStatus.COMPLETED, TaskStatus.CANCELLED):
            return False
    return True


def blocked_by_failure(task: Task, by_id: dict[str, Task]) -> list[Task]:
    return [by_id[d] for d in task.depends_on or [] if d in by_id and by_id[d].status == TaskStatus.FAILED]


def is_terminal(task: Task) -> bool:
    return task.status in TERMINAL_TASK_STATUSES
