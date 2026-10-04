"""The AI company's staff and the registry that maps roles to agents."""

from __future__ import annotations

from ..states import TaskKind
from .base import Agent, AgentContext, AgentError, AgentResult, TaskSpec
from .ceo import CEOAgent
from .developers import AIMLAgent, BackendDeveloper, DatabaseAgent, FrontendDeveloper
from .devops import DevOpsAgent
from .planning import ArchitectAgent, PlannerAgent, ProductAgent, ProjectManagerAgent, UIUXAgent
from .quality import ReviewerAgent, SecurityAgent
from .testing import TestingAgent

# Display order mirrors the org chart: leadership, then specialists.
AGENT_CLASSES: list[type[Agent]] = [
    CEOAgent,
    PlannerAgent,
    ProjectManagerAgent,
    ProductAgent,
    ArchitectAgent,
    UIUXAgent,
    FrontendDeveloper,
    BackendDeveloper,
    DatabaseAgent,
    AIMLAgent,
    SecurityAgent,
    TestingAgent,
    ReviewerAgent,
    DevOpsAgent,
]

# Who can take over a failing task of a given owner (CEO escalation / manual reassignment).
ESCALATION = {
    "frontend": "aiml",
    "aiml": "frontend",
    "backend": "aiml",
    "database": "backend",
}


class AgentRegistry:
    def __init__(self, classes: list[type[Agent]] | None = None):
        self._agents: dict[str, Agent] = {}
        for cls in classes or AGENT_CLASSES:
            self.register(cls())

    def register(self, agent: Agent) -> None:
        if agent.role in self._agents:
            raise ValueError(f"duplicate agent role {agent.role}")
        self._agents[agent.role] = agent

    def get(self, role: str) -> Agent:
        try:
            return self._agents[role]
        except KeyError as e:
            raise KeyError(f"no agent registered for role {role!r}") from e

    def roles(self) -> list[str]:
        return list(self._agents)

    def all(self) -> list[Agent]:
        return list(self._agents.values())

    def can_handle(self, role: str, kind: TaskKind | str) -> bool:
        agent = self._agents.get(role)
        return agent is not None and TaskKind(kind) in agent.kinds

    def candidates(self, kind: TaskKind | str) -> list[str]:
        return [a.role for a in self._agents.values() if TaskKind(kind) in a.kinds]

    def title(self, role: str) -> str:
        agent = self._agents.get(role)
        return agent.title if agent else role


__all__ = [
    "AGENT_CLASSES",
    "ESCALATION",
    "Agent",
    "AgentContext",
    "AgentError",
    "AgentRegistry",
    "AgentResult",
    "TaskSpec",
]
