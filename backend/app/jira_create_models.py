from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class JiraFieldOption(BaseModel):
    label: str
    value: str
    disabled: bool = False
    selected: bool = False


class ParsedJiraField(BaseModel):
    id: str
    label: str
    required: bool = False
    type: Literal["text", "textarea", "select", "checkbox", "radio", "unsupported"] = "unsupported"
    options: list[JiraFieldOption] = Field(default_factory=list)
    description: str | None = None
    tab: str | None = None
    default_value: Any | None = None
    raw_field: dict[str, Any] = Field(default_factory=dict, exclude=True)


class JiraTabDefinition(BaseModel):
    id: str
    label: str
    position: int
    fields: list[str] = Field(default_factory=list)


class JiraProjectOption(BaseModel):
    id: str
    key: str
    name: str


class JiraIssueTypeOption(BaseModel):
    id: str
    name: str
    description: str | None = None


class JiraCreateMetadata(BaseModel):
    project_id: str
    issue_type_id: str
    project_key: str | None = None
    issue_type_name: str | None = None
    fields: dict[str, ParsedJiraField]
    sorted_tabs: list[JiraTabDefinition]


class CreateJiraMetadataRequest(BaseModel):
    project_id: str
    issue_type_id: str


class CreateJiraIssueRequest(BaseModel):
    project_id: str
    issue_type_id: str
    fields: dict[str, Any] = Field(default_factory=dict)


class CreateJiraIssueResponse(BaseModel):
    key: str
    id: str | None = None
    self_url: str | None = None


class MissingRequiredField(BaseModel):
    id: str
    label: str
    question: str


class CreateJiraAgentMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class CreateJiraAgentRequest(BaseModel):
    messages: list[CreateJiraAgentMessage]
    project_id: str
    issue_type_id: str
    project_label: str | None = None
    issue_type_label: str | None = None
    current_values: dict[str, Any] = Field(default_factory=dict)
    user_edited_field_ids: list[str] = Field(default_factory=list)


class CreateJiraAgentResponse(BaseModel):
    status: Literal["needs_information", "ready"]
    message: str
    fields: dict[str, Any] = Field(default_factory=dict)
    missing_required_fields: list[MissingRequiredField] = Field(default_factory=list)
