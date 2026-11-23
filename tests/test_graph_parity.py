from __future__ import annotations

import copy
import os
import unittest
from unittest.mock import patch

import httpx
from openai import APIConnectionError

from agent_team import ReportOrchestrator


ASSESSMENT = {
    "report_type": "儿童创新潜能与综合素质评估报告",
    "respondent_profile": {"report_subject_label": "测X试", "age_group": "小学阶段"},
    "scores": {
        "注意稳定性": {
            "dimension_name": "注意稳定性",
            "score": 50,
            "level": "常态区",
            "direction": "higher_is_better",
        }
    },
}
RETRIEVAL = {"retrieval_summary": {"strategy": "test"}, "retrieved_standard_segments": []}
PLAN = {"metric_plans": [], "macro_plan": {}}
FEEDBACK = {"revision_goal": "fix", "priority": "major", "fix": []}


def transient_error() -> APIConnectionError:
    return APIConnectionError(
        request=httpx.Request("POST", "https://api.deepseek.com/chat/completions")
    )


class SequenceAgent:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)

    def run(self, *args, **kwargs):
        if not self.outcomes:
            raise AssertionError("scripted agent ran out of outcomes")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return copy.deepcopy(outcome)


class SequenceChecker(SequenceAgent):
    def passed(self, check_result):
        return bool(check_result.get("_passed"))


def check_result(passed: bool, score: int, minor=()):
    return {
        "_passed": passed,
        "rule_issues": [],
        "unsupported_issues": [],
        "llm_result": {
            "pass": passed,
            "total_score": score,
            "minor_issues": list(minor),
        },
    }


def run_scenario(implementation: str, spec: dict, **orchestrator_kwargs):
    orchestrator = ReportOrchestrator(client=None, **orchestrator_kwargs)
    orchestrator.retrieval_agent = SequenceAgent([RETRIEVAL])
    orchestrator.planner_agent = SequenceAgent([PLAN])
    orchestrator.metric_writer_agent = SequenceAgent(spec.get("metric_writer", [[]]))
    orchestrator.generator_agent = SequenceAgent(spec.get("generator", []))
    orchestrator.checker_agent = SequenceChecker(spec.get("checker", []))
    orchestrator.feedback_agent = SequenceAgent(spec.get("feedback", []))
    orchestrator.patch_agent = SequenceAgent(spec.get("patch", []))
    with patch.dict(os.environ, {"REPORT_ORCHESTRATOR_IMPL": implementation}):
        return orchestrator.run(copy.deepcopy(ASSESSMENT))


def assert_parity(test: unittest.TestCase, spec: dict, **kwargs):
    legacy = run_scenario("legacy", spec, **kwargs)
    graph = run_scenario("langgraph", spec, **kwargs)
    test.assertEqual(legacy, graph)
    return legacy


class GraphParityTests(unittest.TestCase):
    def test_round_one_approval(self):
        result = assert_parity(
            self,
            {"generator": ["report-v1"], "checker": [check_result(True, 92)]},
        )
        self.assertEqual(result["status"], "approved")
        self.assertNotIn("approval_note", result)

    def test_fail_feedback_patch_approve(self):
        result = assert_parity(
            self,
            {
                "generator": ["report-v1"],
                "checker": [check_result(False, 70), check_result(True, 90)],
                "feedback": [FEEDBACK],
                "patch": ["report-v2"],
            },
        )
        self.assertEqual(result["final_report"], "report-v2")
        self.assertEqual(result["iterations"][1]["repair_mode"], "targeted_patch")

    def test_bad_patch_recompose_fallback(self):
        result = assert_parity(
            self,
            {
                "generator": ["report-v1", "report-v2-recomposed"],
                "checker": [check_result(False, 70), check_result(True, 90)],
                "feedback": [FEEDBACK],
                "patch": [ValueError("invalid patch")],
            },
        )
        self.assertEqual(
            result["iterations"][1]["repair_mode"],
            "targeted_recompose_fallback",
        )

    def test_polish_regression_keeps_approved_candidate(self):
        result = assert_parity(
            self,
            {
                "generator": ["report-v1"],
                "checker": [check_result(True, 90), check_result(False, 60)],
                "feedback": [FEEDBACK],
                "patch": ["report-v2-worse"],
            },
            quality_target_score=95,
        )
        self.assertEqual(result["final_report"], "report-v1")
        self.assertIn("approval_note", result)

    def test_transient_after_approval_keeps_candidate(self):
        result = assert_parity(
            self,
            {
                "generator": ["report-v1"],
                "checker": [check_result(True, 90)],
                "feedback": [FEEDBACK],
                "patch": [transient_error()],
            },
            quality_target_score=95,
        )
        self.assertEqual(result["final_report"], "report-v1")
        self.assertIn("runtime_error", result["iterations"][-1])

    def test_round_one_transient_raises(self):
        for implementation in ("legacy", "langgraph"):
            with self.assertRaises(APIConnectionError):
                run_scenario(
                    implementation,
                    {"generator": [transient_error()], "checker": []},
                )

    def test_polish_feedback_transient_is_recorded(self):
        result = assert_parity(
            self,
            {
                "generator": ["report-v1"],
                "checker": [check_result(True, 90)],
                "feedback": [transient_error()],
            },
            quality_target_score=95,
        )
        self.assertIn("polish_runtime_error", result["iterations"][0])


if __name__ == "__main__":
    unittest.main()
