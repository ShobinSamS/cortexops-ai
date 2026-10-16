from pydantic import BaseModel, Field
from app.schemas.contracts import Evidence


class ToolResult(BaseModel):
    source: str
    data: dict = Field(default_factory=dict)
    evidence: list[Evidence] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
