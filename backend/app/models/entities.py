from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class Identity:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class WorkspaceOwned:
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)


class User(Identity, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Workspace(Identity, Base):
    __tablename__ = "workspaces"
    name: Mapped[str] = mapped_column(String(100))
    settings: Mapped[dict] = mapped_column(JSON, default=dict)


class WorkspaceMember(Identity, WorkspaceOwned, Base):
    __tablename__ = "workspace_members"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16), default="analyst")
    __table_args__ = (UniqueConstraint("workspace_id", "user_id"), CheckConstraint("role IN ('owner','admin','analyst','viewer')"))


class RefreshToken(Identity, Base):
    __tablename__ = "refresh_tokens"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    family: Mapped[str] = mapped_column(String(36), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class Investigation(Identity, WorkspaceOwned, Base):
    __tablename__ = "investigations"
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(160))
    question: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    selected_sources: Mapped[list] = mapped_column(JSON, default=lambda: ["knowledge", "analytics", "github", "monitoring"])
    plan: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    job_id: Mapped[str | None] = mapped_column(String(100))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (CheckConstraint("status IN ('draft','queued','running','paused','completed','failed','cancelled','waiting_approval')"),)


class InvestigationStep(Identity, WorkspaceOwned, Base):
    __tablename__ = "investigation_steps"
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id", ondelete="CASCADE"), index=True)
    agent: Mapped[str] = mapped_column(String(40))
    position: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="pending")
    output: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (UniqueConstraint("investigation_id", "agent"),)


class AgentExecution(Identity, WorkspaceOwned, Base):
    __tablename__ = "agent_executions"
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id", ondelete="CASCADE"), index=True)
    agent: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(24), default="running")
    duration_ms: Mapped[float | None] = mapped_column(Float)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    llm_calls: Mapped[int] = mapped_column(Integer, default=0)
    llm_duration_ms: Mapped[float | None] = mapped_column(Float)
    error: Mapped[str | None] = mapped_column(Text)


class ToolExecution(Identity, WorkspaceOwned, Base):
    __tablename__ = "tool_executions"
    investigation_id: Mapped[str | None] = mapped_column(ForeignKey("investigations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    server: Mapped[str] = mapped_column(String(40))
    tool: Mapped[str] = mapped_column(String(100))
    arguments: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="running")
    duration_ms: Mapped[float | None] = mapped_column(Float)
    error: Mapped[str | None] = mapped_column(Text)


class Approval(Identity, WorkspaceOwned, Base):
    __tablename__ = "approvals"
    investigation_id: Mapped[str | None] = mapped_column(ForeignKey("investigations.id", ondelete="CASCADE"))
    requested_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    tool: Mapped[str] = mapped_column(String(100))
    server: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON)
    payload_hash: Mapped[str] = mapped_column(String(64))
    target: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="pending")
    decided_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (CheckConstraint("status IN ('pending','approved','rejected','executing','executed','failed','expired')"),)


class Document(Identity, WorkspaceOwned, Base):
    __tablename__ = "documents"
    uploaded_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    sha256: Mapped[str] = mapped_column(String(64))
    storage_path: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="queued")
    error: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (UniqueConstraint("workspace_id", "sha256"), CheckConstraint("status IN ('queued','processing','indexed','failed','deleting')"))


class DocumentChunk(Identity, WorkspaceOwned, Base):
    __tablename__ = "document_chunks"
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    page: Mapped[int] = mapped_column(Integer, default=1)
    section: Mapped[str] = mapped_column(String(255), default="")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (UniqueConstraint("document_id", "position"),)


class DataSource(Identity, WorkspaceOwned, Base):
    __tablename__ = "data_sources"
    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(40))
    mode: Mapped[str] = mapped_column(String(24), default="synthetic")
    configuration: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (UniqueConstraint("workspace_id", "kind"),)


class MCPServer(Identity, WorkspaceOwned, Base):
    __tablename__ = "mcp_servers"
    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(40))
    url: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(24), default="unknown")
    tools: Mapped[list] = mapped_column(JSON, default=list)
    allowed_tools: Mapped[list] = mapped_column(JSON, default=list)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("workspace_id", "kind"),)


class Report(Identity, WorkspaceOwned, Base):
    __tablename__ = "reports"
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id", ondelete="CASCADE"), unique=True)
    title: Mapped[str] = mapped_column(String(160))
    content: Mapped[dict] = mapped_column(JSON)
    markdown: Mapped[str] = mapped_column(Text)


class AuditLog(Identity, WorkspaceOwned, Base):
    __tablename__ = "audit_logs"
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(100), index=True)
    resource_type: Mapped[str] = mapped_column(String(50))
    resource_id: Mapped[str | None] = mapped_column(String(100))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class ModelConfiguration(Identity, WorkspaceOwned, Base):
    __tablename__ = "model_configurations"
    model: Mapped[str] = mapped_column(String(100), default="qwen3:1.7b")
    context_window: Mapped[int] = mapped_column(Integer, default=4096)
    temperature: Mapped[float] = mapped_column(Float, default=0)
    __table_args__ = (UniqueConstraint("workspace_id"),)


class InvestigationEvent(Identity, WorkspaceOwned, Base):
    __tablename__ = "investigation_events"
    sequence: Mapped[int] = mapped_column(Integer)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(50))
    agent: Mapped[str | None] = mapped_column(String(40))
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (UniqueConstraint("investigation_id", "sequence"),)


class ModelObservation(Identity, WorkspaceOwned, Base):
    __tablename__ = "model_observations"
    version: Mapped[str] = mapped_column(String(40), index=True)
    category: Mapped[str] = mapped_column(String(40))
    correct: Mapped[bool] = mapped_column(Boolean)
    confidence: Mapped[float] = mapped_column(Float)
    latency_ms: Mapped[float] = mapped_column(Float)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)


class Deployment(Identity, WorkspaceOwned, Base):
    __tablename__ = "deployments"
    version: Mapped[str] = mapped_column(String(40))
    service: Mapped[str] = mapped_column(String(100))
    commit_sha: Mapped[str] = mapped_column(String(40))
    deployed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    configuration: Mapped[dict] = mapped_column(JSON, default=dict)


class RepositoryChange(Identity, WorkspaceOwned, Base):
    __tablename__ = "repository_changes"
    repository: Mapped[str] = mapped_column(String(160))
    sha: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text)
    files: Mapped[list] = mapped_column(JSON)
    diff: Mapped[str] = mapped_column(Text)
    committed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ApplicationLog(Identity, WorkspaceOwned, Base):
    __tablename__ = "application_logs"
    service: Mapped[str] = mapped_column(String(100))
    version: Mapped[str] = mapped_column(String(40), index=True)
    level: Mapped[str] = mapped_column(String(16))
    message: Mapped[str] = mapped_column(Text)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)


class Incident(Identity, WorkspaceOwned, Base):
    __tablename__ = "incidents"
    title: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(16), default="medium")
    status: Mapped[str] = mapped_column(String(24), default="open")
    service: Mapped[str] = mapped_column(String(100), default="document-verification")
    external_url: Mapped[str | None] = mapped_column(Text)
    approval_id: Mapped[str | None] = mapped_column(ForeignKey("approvals.id"), unique=True)


class GraphEntity(Identity, WorkspaceOwned, Base):
    __tablename__ = "graph_entities"
    label: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(40))
    source_id: Mapped[str] = mapped_column(String(100))
    properties: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (UniqueConstraint("workspace_id", "kind", "source_id"),)


class GraphRelationship(Identity, WorkspaceOwned, Base):
    __tablename__ = "graph_relationships"
    source_id: Mapped[str] = mapped_column(ForeignKey("graph_entities.id", ondelete="CASCADE"))
    target_id: Mapped[str] = mapped_column(ForeignKey("graph_entities.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(40))
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (UniqueConstraint("workspace_id", "source_id", "target_id", "kind"),)


Index("ix_observations_workspace_version", ModelObservation.workspace_id, ModelObservation.version)


class BackgroundJob(Identity, WorkspaceOwned, Base):
    __tablename__ = "background_jobs"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(24), default="queued")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
