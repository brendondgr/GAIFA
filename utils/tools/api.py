"""Response models for the `tools` area (plan 13.1–13.2): brief §11.7 `Tool`, `ToolIndexItem`,
`ToolCallResult`, `Approval`."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Risk = Literal["read", "write", "generate", "destructive"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ToolIndexItem(_Model):
    name: str
    mod: str
    risk: Risk
    core: bool
    summary: str
    available: bool
    why: str | None = None


class Tool(ToolIndexItem):
    description: str
    parameters: dict[str, Any]
    ask: list[str]
    examples: list[dict[str, Any]]
    job: bool
    source: Literal["manifest", "tools_source", "hub"]


class ToolOutput(_Model):
    output_id: str
    ref: str
    kind: str
    title: str
    url: str
    preview: str | None = None
    summary: str
    prompt: str | None = None


class ToolErrorBody(_Model):
    code: str
    detail: str
    fix: str | None = None
    problems: list[dict[str, str]] | None = None


class ToolCallResult(_Model):
    status: Literal["needs_approval", "denied", "running", "done", "error", "cancelled"]
    tool: str | None
    call_id: str | None = None
    approval_id: str | None = None
    result: Any = None
    outputs: list[ToolOutput] | None = None
    error: ToolErrorBody | None = None
    progress: float | None = None
    note: str | None = None
    job_id: str | None = None
    elapsed_s: float | None = None
    arguments: dict[str, Any] | None = None
    ask_fields: list[str] | None = None
    risk: Risk | None = None
    schema_: dict[str, Any] | None = Field(None, alias="schema")
    description: str | None = None
    filled: list[str] | None = None


class CallRequest(_Model):
    arguments: dict[str, Any] = Field(default_factory=dict)
    origin: dict[str, Any] = Field(default_factory=dict, description="Who asks: {service, thread, …}; shown on the approval")
    mode: Literal["ask", "auto", "read_only"] = "ask"


class Approval(_Model):
    id: str
    tool: str
    arguments: dict[str, Any]
    final: dict[str, Any] | None = None
    ask_fields: list[str]
    risk: Risk
    origin: dict[str, Any]
    state: Literal["pending", "approved", "denied", "expired"]
    reason: str | None = None
    call_id: str | None = None
    created_ts: float
    decided_ts: float | None = None
    schema_: dict[str, Any] | None = Field(None, alias="schema")
    description: str | None = None


class Decision(_Model):
    approve: bool
    arguments: dict[str, Any] | None = Field(None, description="Edited arguments (the parameter card); they are what runs")
    reason: str | None = None


class ResultPage(_Model):
    call_id: str
    offset: int
    limit: int
    total: int
    text: str
