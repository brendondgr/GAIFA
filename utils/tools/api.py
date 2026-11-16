"""Response models for the `tools` area (plan 13.1–13.2, 25.2): brief §11.7 `Tool`, `ToolIndexItem`,
`ToolCallResult`, `Approval`, `Grant`."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from utils.tools.approvals import ACTIONS

Risk = Literal["read", "write", "generate", "network", "execute", "destructive"]


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
    state: str = Field("on", description="Its mod's availability (capability-enablement 1.5): on, starts_on_use, off, not_set_up, "
                                         "cant_run, failed, broken, or off_by_mod (the mod said this tool is off)")
    turn_on: dict[str, Any] | None = Field(None, description="{tool, arguments, command}: what turns its mod on, when it isn't")
    group: str | None = Field(None, description="mcp-client 4.1: a group within its mod (mcp:<server>); the chat's tool groups use it, else the mod")


class Tool(ToolIndexItem):
    description: str
    parameters: dict[str, Any]
    ask: list[str]
    examples: list[dict[str, Any]]
    job: bool
    source: Literal["manifest", "tools_source", "hub"]
    grant_key: str | None = None
    view: dict[str, Any] | None = Field(None, description="Plan 46.1: how its result draws in Chat: {kind: table|bar|hbar|line|area|donut, rows, columns? | x, y}")


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
    fixes: list[dict[str, Any]] | None = Field(None, description="Plan 46.5: what fixes it: {label, tool, arguments} | {label, service, action} | {label, retry} | {label, command} | {label, setup, command}")
    log: list[str] | None = Field(None, description="Plan 46.5: the mod's log lines around the failure")
    state: str | None = Field(None, description="capability_unavailable: the mod's availability (not_set_up, off, cant_run, broken, off_by_mod)")
    service: str | None = Field(None, description="capability_unavailable, service_not_running: the mod it is about")
    turn_on: dict[str, Any] | None = Field(None, description="capability_unavailable: {tool, arguments, command} that turns the mod on")


class Grant(_Model):
    id: str
    tool: str = Field(description="A tool name glob")
    key: str | None = Field(None, description="What it covers: a host, a folder, a constant; null: every call of the tool")
    kind: str | None = Field(None, description="The tool's grant_key: url:host, arg:<name>, const:<x>; `folder` for a folder allowed in one chat (plan 34)")
    risk: str | None = None
    scope: Literal["thread", "always"]
    thread: str | None = None
    created_ts: float
    expires_ts: float | None = None
    note: str = ""
    used: int = 0
    last_used_ts: float | None = None


class Judged(_Model):
    """Auto mode (plan 30.3): the judge's verdict on a call, on its result or its card and in Settings → Agent."""
    verdict: Literal["allow", "ask", "refused"] = Field(description="refused: an ask in an unattended run (scheduled-tasks 2.1)")
    reason: str = ""
    source: str = Field("", description="rules | user (your command rules) | model | fail-closed")
    rule: str = ""
    ms: float | None = None
    model: str = ""
    summary: str = Field("", description="The command, URL or file, in one line")
    why: str | None = Field(None, description="The step row's words: Auto: ran (judged safe: …) or Auto: asked you (…)")
    refused: bool | None = Field(None, description="The judge asked, and the run was unattended, so the call was refused")


class JudgedCall(Judged):
    id: int
    ts: float
    tool: str
    thread: str | None = None
    call_id: str | None = None
    approval_id: str | None = None
    suggest: list[str] | None = Field(None, description="A command the judge's model asked about: allow rules that would "
                                      "cover it (Settings → Agent's \"Always allow\"; utils/tools/judge_user.py suggest)")


class JudgeStatus(_Model):
    available: bool = Field(description="The judge's model answers; Auto isn't offered while it doesn't")
    backend: str
    model: str
    detail: str = ""
    choices: list[str] = Field(default_factory=list, description="Models the backend offers that the judge could use (Settings → Agent)")
    fix: dict[str, Any] | None = Field(None, description="capability-enablement 3.6: when the decide mod isn't set up or is off, {kind, id, command}")


class CallLimits(_Model):
    """needs_approval for a tool with a preflight (plan 27.4): what the call would do."""
    action: Literal[ACTIONS] = Field(description="The decision table's word (approvals.ACTIONS); a mod's other word is shown as command")  # type: ignore[valid-type]
    folder: str | None = None
    level: str | None = None
    allow_bypass: bool | None = None
    key: str | None = Field(None, description="What \"allow in this chat\" covers (the folder, and a command's first word)")
    once: bool | None = Field(None, description="Asks every time: no grant buttons (host runs, commits, git remotes)")
    preview: dict[str, Any] | None = Field(None, description="{summary, diff} for an edit; {command, where, network, cwd, note?} for a run")
    path: str | None = None
    ask_folder: dict[str, Any] | None = Field(None, description="Plan 34: a folder outside the chat's environment the call asks to "
                                              "read: {path, level, max_level, capped?, environment: {id, name}}")


Mode = Literal["plan", "manual", "accept_edits", "auto", "bypass", "ask", "read_only"]


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
    live: dict[str, Any] | None = Field(None, description="A running job's live progress (plan 44.2): stage, stages, step, steps, eta_s, preview {url, seq, w, h}, lines, audio")
    job_id: str | None = None
    elapsed_s: float | None = None
    arguments: dict[str, Any] | None = None
    ask_fields: list[str] | None = None
    risk: Risk | None = None
    schema_: dict[str, Any] | None = Field(None, alias="schema")
    description: str | None = None
    filled: list[str] | None = None
    filled_by: dict[str, str] | None = None
    grant_key: str | None = None
    grant: Grant | None = None
    grant_id: str | None = Field(None, description="A grant ran the call (scheduled-tasks 2.1: a run's pre-allow)")
    why: str | None = Field(None, description="needs_approval: why it asks (the mode, a list, the risk)")
    limits: CallLimits | None = None
    judge: Judged | None = None


class CallRequest(_Model):
    arguments: dict[str, Any] = Field(default_factory=dict)
    origin: dict[str, Any] = Field(default_factory=dict, description="Who asks: {service, thread, …}; shown on the approval")
    mode: Mode = Field("manual", description="The chat's mode (plan 27.4); the old names ask and read_only map to manual and plan")


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
    filled: dict[str, str] | None = None
    edited: list[str] | None = None
    schema_: dict[str, Any] | None = Field(None, alias="schema")
    description: str | None = None
    grant_key: str | None = None


class Decision(_Model):
    approve: bool
    arguments: dict[str, Any] | None = Field(None, description="Edited arguments (the parameter card); they are what runs")
    reason: str | None = None
    remember: Literal["once", "thread", "always", "sites"] = Field("once", description="thread / always: also allow calls like "
                                                                   "this one (a grant); sites: a web tool on any site, in this chat")
    confirm: bool = Field(False, description="The second confirm an `always` grant for execute and destructive tools needs")
    grant_hours: float | None = Field(None, gt=0, description="The grant expires after this many hours (default: never)")


class ResultPage(_Model):
    call_id: str
    offset: int
    limit: int
    total: int
    text: str
