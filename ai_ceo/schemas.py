"""Structured outputs produced by LLM-backed agents.

Kept deliberately small and flat: these schemas are enforced with
constrained decoding on local 8B models, where deep or wide schemas
degrade output quality.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, field_validator

DevRole = Literal["frontend", "backend", "database", "aiml"]


class IntakeOutput(BaseModel):
    project_name: str
    objective: str
    app_type: Literal["static_web", "web_with_backend"]
    target_users: str
    constraints: list[str]
    summary: str


class Feature(BaseModel):
    name: str
    description: str
    priority: Literal["must", "should", "could"]


class RequirementsOutput(BaseModel):
    user_stories: list[str]
    features: list[Feature]
    acceptance_criteria: list[str]
    out_of_scope: list[str]
    summary: str


class Milestone(BaseModel):
    name: str
    goal: str


class StrategyOutput(BaseModel):
    milestones: list[Milestone]
    priorities: list[str]
    risks: list[str]
    definition_of_done: list[str]
    summary: str


class Stack(BaseModel):
    frontend: str
    backend: str
    storage: str


class FileSpec(BaseModel):
    path: str
    purpose: str
    owner_role: DevRole


class Entity(BaseModel):
    name: str
    fields: list[str]


class Endpoint(BaseModel):
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: str
    description: str


class Decision(BaseModel):
    decision: str
    rationale: str


class ArchitectureOutput(BaseModel):
    needs_backend: bool
    stack: Stack
    files: list[FileSpec]
    data_model: list[Entity]
    api_endpoints: list[Endpoint]
    decisions: list[Decision]
    summary: str


class Palette(BaseModel):
    primary: str
    secondary: str
    background: str
    surface: str
    text: str
    accent: str


class Component(BaseModel):
    name: str
    description: str


class DesignOutput(BaseModel):
    style_name: str
    palette: Palette
    font_family: str
    layout: str
    components: list[Component]
    accessibility: list[str]
    summary: str


TestAction = Literal[
    "fill",
    "click",
    "press",
    "select",
    "check",
    "wait",
    "expect_visible",
    "expect_hidden",
    "expect_text",
    "expect_length",
    "expect_count",
    "expect_value",
]


class TestStep(BaseModel):
    action: TestAction
    selector: str
    value: str


class TestScenario(BaseModel):
    name: str
    criterion: str
    steps: list[TestStep]


class TestPlanOutput(BaseModel):
    scenarios: list[TestScenario]


class ApiTestCase(BaseModel):
    name: str
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: str
    body_json: str
    expect_status: int
    expect_contains: str


class ApiTestPlanOutput(BaseModel):
    cases: list[ApiTestCase]


class ReviewIssue(BaseModel):
    severity: Literal["blocker", "major", "minor"]
    file: str
    description: str
    suggestion: str


class ReviewOutput(BaseModel):
    approved: bool
    score: int
    issues: list[ReviewIssue]
    strengths: list[str]
    summary: str

    @field_validator("score")
    @classmethod
    def _clamp(cls, v: int) -> int:
        return max(0, min(10, v))


class FinalReviewOutput(BaseModel):
    decision: Literal["approve", "revise"]
    unmet_criteria: list[str]
    release_notes: str
    summary: str
