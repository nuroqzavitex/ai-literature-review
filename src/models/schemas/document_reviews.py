from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TextQuoteAnchor(StrictModel):
    exact: str = Field(min_length=1, max_length=20_000)
    prefix: str = Field(default="", max_length=64)
    suffix: str = Field(default="", max_length=64)


class DocumentAnnotation(StrictModel):
    annotation_id: str
    type: Literal["suggest", "warning", "verification"]
    anchor: TextQuoteAnchor
    aspect: str
    comment: str
    suggested_fix: str | None = None
    evidence: dict[str, Any] | None = None
    status: Literal["pending", "accepted", "rejected", "dismissed"]

    @model_validator(mode="after")
    def only_suggestions_offer_an_automatic_fix(self) -> DocumentAnnotation:
        if self.type != "suggest" and self.suggested_fix is not None:
            raise ValueError("only suggestion annotations can include suggested_fix")
        return self


class DocumentReviewResponse(StrictModel):
    review_id: str
    project_id: str
    filename: str
    title: str
    source_format: Literal["pdf", "tex", "tex_bundle"]
    extraction_method: Literal["llamaparse", "pypdf", "latex", "unknown"] = "unknown"
    source_file_available: bool = False
    content: str
    annotations: list[DocumentAnnotation]
    created_at: str
    updated_at: str


class DocumentContentUpdateRequest(StrictModel):
    content: str = Field(min_length=1, max_length=1_000_000)


class AnnotationActionRequest(StrictModel):
    action: Literal["accept", "reject", "dismiss"]


class SelectionRequest(StrictModel):
    selected_text: str = Field(min_length=1, max_length=10_000)
    prefix: str = Field(default="", max_length=32)
    suffix: str = Field(default="", max_length=32)
    instruction: str | None = Field(default=None, max_length=1_000)


class ApplyRewriteRequest(StrictModel):
    old_text: str = Field(min_length=1, max_length=10_000)
    new_text: str = Field(min_length=1, max_length=10_000)
