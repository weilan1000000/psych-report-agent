from __future__ import annotations

from typing import Any, TypedDict


class ReportState(TypedDict, total=False):
    assessment_result: dict[str, Any]
    retrieval_result: dict[str, Any]
    writing_plan: dict[str, Any]
    detail_blocks: list[dict[str, str]] | None
    report: str
    check_result: dict[str, Any]
    passed: bool
    needs_polish: bool
    feedback: dict[str, Any] | None
    round_index: int
    repair_mode: str
    repair_note: str
    patch_failed: bool
    iterations: list[dict[str, Any]]
    approved_candidate: dict[str, Any] | None
    final_report: str
    final_check: dict[str, Any]
    next_step: str
    jump_finalize: bool
    immediate_approval: bool
    _pending_iteration: dict[str, Any] | None
    status: str
    approval_note: str
