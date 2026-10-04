"""Status vocabularies shared by the orchestrator, API and dashboard."""

from __future__ import annotations

from enum import StrEnum


class ProjectStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    AWAITING_APPROVAL = "awaiting_approval"
    NEEDS_ATTENTION = "needs_attention"  # escalated: retries / fix iterations exhausted
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"


ACTIVE_PROJECT_STATUSES = {ProjectStatus.RUNNING}
TERMINAL_PROJECT_STATUSES = {ProjectStatus.COMPLETED, ProjectStatus.STOPPED, ProjectStatus.FAILED}


class Phase(StrEnum):
    REQUIREMENTS = "requirements"
    PLANNING = "planning"
    ARCHITECTURE = "architecture"
    IMPLEMENTATION = "implementation"
    TESTING = "testing"
    REVIEW = "review"
    FIXING = "fixing"
    APPROVAL = "approval"
    DEPLOYMENT = "deployment"
    DONE = "done"


PHASE_ORDER = list(Phase)


class TaskStatus(StrEnum):
    BACKLOG = "backlog"  # created, dependencies not yet satisfied
    PLANNED = "planned"  # ready to run
    IN_PROGRESS = "in_progress"
    TESTING = "testing"  # a verification task is running
    REVIEW = "review"  # a review task is running
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


RUNNING_TASK_STATUSES = {TaskStatus.IN_PROGRESS, TaskStatus.TESTING, TaskStatus.REVIEW}
TERMINAL_TASK_STATUSES = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}


class TaskKind(StrEnum):
    INTAKE = "intake"
    REQUIREMENTS = "requirements"
    STRATEGY = "strategy"
    ARCHITECTURE = "architecture"
    DESIGN = "design"
    BREAKDOWN = "breakdown"
    IMPLEMENT = "implement"
    FIX = "fix"
    TEST = "test"
    SECURITY = "security"
    REVIEW = "review"
    FINAL_REVIEW = "final_review"
    DEPLOY = "deploy"


TESTING_KINDS = {TaskKind.TEST, TaskKind.SECURITY}
REVIEW_KINDS = {TaskKind.REVIEW, TaskKind.FINAL_REVIEW}
VERIFICATION_KINDS = {TaskKind.TEST, TaskKind.SECURITY, TaskKind.REVIEW}

KIND_PHASE: dict[TaskKind, Phase] = {
    TaskKind.INTAKE: Phase.REQUIREMENTS,
    TaskKind.REQUIREMENTS: Phase.REQUIREMENTS,
    TaskKind.STRATEGY: Phase.PLANNING,
    TaskKind.ARCHITECTURE: Phase.ARCHITECTURE,
    TaskKind.DESIGN: Phase.ARCHITECTURE,
    TaskKind.BREAKDOWN: Phase.PLANNING,
    TaskKind.IMPLEMENT: Phase.IMPLEMENTATION,
    TaskKind.FIX: Phase.FIXING,
    TaskKind.TEST: Phase.TESTING,
    TaskKind.SECURITY: Phase.TESTING,
    TaskKind.REVIEW: Phase.REVIEW,
    TaskKind.FINAL_REVIEW: Phase.APPROVAL,
    TaskKind.DEPLOY: Phase.DEPLOYMENT,
}


def running_status_for(kind: TaskKind) -> TaskStatus:
    if kind in TESTING_KINDS:
        return TaskStatus.TESTING
    if kind in REVIEW_KINDS:
        return TaskStatus.REVIEW
    return TaskStatus.IN_PROGRESS


class AgentStatus(StrEnum):
    IDLE = "idle"
    WORKING = "working"
    RETRYING = "retrying"
    ERROR = "error"
