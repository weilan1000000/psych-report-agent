from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class QualityIssue(BaseModel):
    """Stable boundary object shared by Checker, Feedback and the review UI."""

    model_config = ConfigDict(extra="allow")

    issue_id: str
    severity: Literal["blocker", "major", "minor", "notice"]
    category: str
    sources: list[str] = Field(default_factory=list)
    section_id: str = ""
    metric: str = ""
    problem: str
    current_excerpt: str = ""
    evidence: str = ""
    expected: str = ""
    fix_instruction: str = ""
    confidence: float = 0.0
    auto_fixable: bool = False
    raw_text: str = ""
