from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class RegisterRequest(BaseModel):
    email: str = Field(min_length=5, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    password: str = Field(min_length=12, max_length=128)
    name: str = Field(min_length=1, max_length=100)
    workspace_name: str = Field(default="My workspace", min_length=1, max_length=100)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value):
        return value.strip().lower()


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class InvestigationCreate(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    question: str = Field(min_length=10, max_length=8000)
    selected_sources: list[Literal["knowledge", "analytics", "github", "monitoring", "incidents"]] = Field(default_factory=lambda: ["knowledge", "analytics", "github", "monitoring"], min_length=1, max_length=5)


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=2000)
    limit: int = Field(default=6, ge=1, le=20)
    document_ids: list[str] = Field(default_factory=list, max_length=50)


class ModelSettings(BaseModel):
    model: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_.:/-]+$")
    context_window: int = Field(default=4096, ge=2048, le=16384)
    temperature: float = Field(default=0, ge=0, le=1)


class MemberCreate(BaseModel):
    email: str = Field(max_length=254)
    role: Literal["admin", "analyst", "viewer"] = "analyst"


class MemberUpdate(BaseModel):
    role: Literal["admin", "analyst", "viewer"]


class ApprovalDecision(BaseModel):
    decision: Literal["approve", "reject"]


class ToolInvocation(BaseModel):
    server: Literal["github", "analytics", "knowledge", "monitoring", "incidents"]
    tool: str = Field(min_length=1, max_length=100)
    arguments: dict = Field(default_factory=dict)
    investigation_id: str | None = None


class WorkspaceUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    source: str
    title: str
    content: str
    reference: dict = Field(default_factory=dict)
    score: float | None = None


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    objective: str = Field(max_length=1000)
    hypotheses: list[str] = Field(min_length=1, max_length=5)
    steps: list[str] = Field(min_length=2, max_length=8)


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    statement: str = Field(max_length=1800)
    evidence_ids: list[str] = Field(min_length=1, max_length=10)
    classification: Literal["verified", "hypothesis"]
    confidence: Literal["high", "medium", "low"]
    contradictory_evidence_ids: list[str] = Field(default_factory=list, max_length=10)


class Diagnosis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(max_length=2000)
    findings: list[Finding] = Field(default_factory=list, max_length=6)
    recommendations: list[str] = Field(min_length=1, max_length=5)
    limitations: list[str] = Field(default_factory=list, max_length=8)


class ChangeAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    primary_change_id: str | None
    confidence: Literal["high", "medium", "low"]
    alternative_change_ids: list[str] = Field(default_factory=list, max_length=2)
    contradictory_evidence_ids: list[str] = Field(default_factory=list, max_length=2)
    recommendations: list[str] = Field(min_length=1, max_length=3)
    limitations: list[str] = Field(default_factory=list, max_length=3)
