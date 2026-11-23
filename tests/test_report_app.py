from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_team import (
    RuleChecker,
    _compose_controlled_metric_block,
    _definition_for_report_stage,
    _detailed_indicator_role_issues,
    _detailed_indicator_duplicate_analysis_issues,
    _fallback_result_analysis,
    _metric_result_sentence,
    _result_analysis_policy,
    _suggestion_actionability_issues,
    build_runtime_agent_context,
    enrich_feedback_targets,
    normalize_report_contract,
    parse_report_json,
    report_reader_mode,
    resolve_report_stage,
    run_output_contract_checks,
    suggestion_categories_for_stage,
)
from quality_review import build_quality_review, render_quality_review_html
from report_app.server import (
    BatchJob,
    JobItem,
    JobManager,
    apply_stage_override,
    load_json_text,
    resolve_web_asset,
    sanitize_log,
    student_number_label,
)


class ReportAppTests(unittest.TestCase):
    def test_job_manager_persists_structured_human_feedback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = JobManager(Path(temp_dir))
            job_root = Path(temp_dir) / "job-1"
            item = JobItem(
                item_id="item-001",
                filename="student.json",
                status="review",
                review_summary={
                    "issues": [
                        {
                            "issue_id": "qi_123",
                            "category": "fabrication_risk",
                            "severity": "major",
                            "problem": "存在无依据经历",
                        }
                    ]
                },
            )
            manager.jobs["job-1"] = BatchJob(
                job_id="job-1",
                stage="elementary",
                created_at=0,
                root_dir=job_root,
                items=[item],
            )
            result = manager.submit_feedback(
                "job-1",
                "item-001",
                {
                    "reviewer": "审核员A",
                    "reviews": [
                        {
                            "issue_id": "qi_123",
                            "decision": "false_positive",
                            "note": "该行为来自输入背景",
                        }
                    ],
                },
            )
            self.assertTrue(result["ok"])
            self.assertEqual(result["feedback_summary"]["resolved_issue_count"], 1)
            self.assertTrue((job_root / "human_feedback.jsonl").exists())

    def test_student_number_uses_assessment_metadata_and_normalizes_suffix(self) -> None:
        self.assertEqual(
            student_number_label(
                {"assessment_metadata": {"source_student_id": "26"}}
            ),
            "26号",
        )
        self.assertEqual(
            student_number_label(
                {"assessment_metadata": {"source_student_id": "26号"}}
            ),
            "26号",
        )
        self.assertEqual(
            student_number_label(
                {"assessment_metadata": {"source_student_id": "legacy_demo_id"}}
            ),
            "",
        )

    def test_legacy_console_urls_resolve_to_current_web_assets(self) -> None:
        for path in (
            "/",
            "/index.html",
            "/report_app/web/index.html",
            "/web/index.html",
        ):
            target = resolve_web_asset(path)
            self.assertIsNotNone(target)
            self.assertEqual(target.name, "index.html")
            self.assertTrue(target.is_file())

        self.assertEqual(resolve_web_asset("/report_app/web/app.js").name, "app.js")
        self.assertEqual(resolve_web_asset("/web/styles.css").name, "styles.css")

    def sample(self) -> dict:
        return {
            "report_type": "青少年创新潜能与综合素质评估报告",
            "respondent_profile": {"age_group": "高中阶段"},
            "scores": {"注意稳定性": {"score": 80, "level": "常态区"}},
        }

    def test_ui_stage_override_has_priority_over_legacy_title(self) -> None:
        payload = apply_stage_override(self.sample(), "elementary")
        self.assertEqual(payload["school_stage"], "elementary")
        self.assertEqual(payload["respondent_profile"]["age_group"], "小学阶段")
        self.assertEqual(resolve_report_stage(payload), "elementary")

    def test_secondary_variants_route_explicitly(self) -> None:
        junior = apply_stage_override(self.sample(), "junior_high")
        senior = apply_stage_override(self.sample(), "senior_high")
        self.assertEqual(resolve_report_stage(junior), "junior_high")
        self.assertEqual(resolve_report_stage(senior), "senior_high")
        self.assertEqual(junior["audience"], "student")
        self.assertEqual(junior["respondent_profile"]["audience"], "student")
        self.assertEqual(report_reader_mode(junior), "student")

    def test_stage_runtime_contexts_are_isolated(self) -> None:
        elementary = build_runtime_agent_context(
            "generator",
            {"school_stage": "elementary"},
        )
        junior = build_runtime_agent_context(
            "generator",
            {"school_stage": "junior_high"},
        )
        self.assertIn("# report_text/references/humanized_parent_style.md", elementary)
        self.assertNotIn("# report_text/references/secondary_school_writing_style.md", elementary)
        self.assertIn("# report_text/references/secondary_school_writing_style.md", junior)
        self.assertIn("# report_text/references/secondary_school_support_advice.md", junior)
        self.assertIn("# report_text/references/teacher_annotation_universal_rules.md", elementary)
        self.assertIn("# report_text/references/teacher_annotation_universal_rules.md", junior)
        self.assertNotIn("# report_text/references/humanized_parent_style.md", junior)

    def test_secondary_contract_and_metric_voice_are_student_facing(self) -> None:
        assessment = {
            "school_stage": "junior_high",
            "audience": "parents",
            "report_type": "青少年综合素质评估报告",
        }
        normalized = normalize_report_contract(
            json.dumps(
                {
                    "audience": "parents",
                    "report_type": "青少年综合素质评估报告",
                    "sections": [
                        {
                            "section_id": "core_growth_portrait",
                            "title": "核心成长画像",
                            "body": "家长您好：孩子在任务中可以继续练习。",
                        }
                    ],
                    "parent_suggestions": [
                        {
                            "category": "自我成长与学习规划",
                            "scene": "孩子安排任务时",
                            "action": "孩子先写下一步。",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            assessment,
        )
        parsed, error = parse_report_json(normalized)
        self.assertFalse(error)
        self.assertEqual(parsed["audience"], "student")
        self.assertEqual(parsed["sections"][0]["body"], "你在任务中可以继续练习。")
        self.assertEqual(
            parsed["parent_suggestions"][0]["scene"],
            "你安排任务时",
        )
        self.assertEqual(
            parsed["parent_suggestions"][0]["action"],
            "你先写下一步。",
        )

        block = _compose_controlled_metric_block(
            {
                "dimension_name": "注意稳定性",
                "professional_label": "持续聚焦",
                "definition": "反映儿童在较长任务中维持注意的能力。",
                "level": "优势区",
                "rating_basis": "fixed_norm_20_80_raw_score",
            },
            "",
            "junior_high",
        )
        self.assertIn("反映你在较长任务中维持注意的能力", block)
        self.assertIn("你通常能较稳定地", block)
        self.assertNotIn("孩子较容易", block)

    def test_suggestion_categories_are_isolated_by_stage(self) -> None:
        self.assertEqual(
            suggestion_categories_for_stage({"school_stage": "elementary"}),
            {"学习与日常", "课外与探索", "亲子互动与沟通"},
        )
        self.assertEqual(
            suggestion_categories_for_stage({"school_stage": "junior_high"}),
            {"自我成长与学习规划", "兴趣探索与项目实践", "生涯启发与发展规划"},
        )

    def test_secondary_metric_fallbacks_are_metric_specific(self) -> None:
        analyses = [
            _fallback_result_analysis(
                {
                    "dimension_name": name,
                    "professional_label": name,
                    "level": "潜力区",
                },
                "junior_high",
            )
            for name in ("思维流畅性", "思维灵活性", "思维独创性")
        ]
        self.assertEqual(len(set(analyses)), 3)
        self.assertTrue(all("你" in analysis for analysis in analyses))
        self.assertIn("想法数量", analyses[0])
        self.assertIn("候选空间", analyses[0])
        self.assertFalse(
            any(
                cue in analysis
                for analysis in analyses
                for cue in ("写下", "本周", "下一次", "练习", "完成后")
            )
        )

    def test_secondary_interest_curiosity_is_deep_but_advice_free(self) -> None:
        analysis = _fallback_result_analysis(
            {
                "dimension_name": "兴趣好奇心",
                "professional_label": "新异刺激的探索取向",
                "level": "潜力区",
            },
            "junior_high",
        )
        self.assertIn("短暂注意发展为持续探索", analysis)
        self.assertIn("已有经验", analysis)
        self.assertNotIn("15分钟", analysis)
        self.assertNotIn("卡片", analysis)
        self.assertNotIn("下一次", analysis)

    def test_secondary_detail_role_checker_rejects_action_advice(self) -> None:
        mixed_role = {
            "sections": [
                {
                    "section_id": "detailed_indicator_analysis",
                    "body": (
                        "【兴趣好奇心】定义。"
                        "本项指标目前处于潜力区。"
                        "你可以继续探索新主题，慢慢找到适合自己的方向。"
                    ),
                }
            ]
        }
        issues = _detailed_indicator_role_issues(
            mixed_role,
            {"school_stage": "junior_high"},
        )
        self.assertEqual(len(issues), 1)
        self.assertIn("混入了行动建议", issues[0])
        self.assertIn("成长支持建议", issues[0])

    def test_secondary_interpretation_rules_do_not_change_elementary_metrics(self) -> None:
        elementary_policy = _result_analysis_policy(
            {"dimension_name": "兴趣好奇心", "level": "潜力区"},
            "elementary",
        )
        junior_policy = _result_analysis_policy(
            {"dimension_name": "兴趣好奇心", "level": "潜力区"},
            "junior_high",
        )
        self.assertEqual(
            elementary_policy["target_length"],
            "65-105 Chinese characters",
        )
        self.assertEqual(
            junior_policy["target_length"],
            "85-140 Chinese characters",
        )

        elementary_report = {
            "sections": [
                {
                    "section_id": "detailed_indicator_analysis",
                    "body": (
                        "【兴趣好奇心】定义。"
                        "本项指标目前处于潜力区。"
                        "孩子可以继续接触新主题并慢慢积累经验。"
                    ),
                }
            ]
        }
        self.assertEqual(
            _detailed_indicator_role_issues(
                elementary_report,
                {"school_stage": "elementary"},
            ),
            [],
        )

    def test_secondary_definition_removes_unexplained_academic_jargon(self) -> None:
        cases = {
            "反映儿童大脑神经信息加工速率与短时记忆编码效率。":
                "反映你接收新信息并形成初步记忆的效率。",
            "作为大脑的高级指挥官，负责安排多步骤任务。":
                "作为任务管理的综合能力，负责安排多步骤任务。",
            "指儿童为了消除信息盲区，不满足于事物表象，主动寻求深层原因与底层逻辑的内驱力。":
                "指你在信息还不完整时，愿意继续追问原因并寻找解释。",
        }
        for source, expected in cases.items():
            self.assertEqual(
                _definition_for_report_stage(source, "junior_high"),
                expected,
            )

    def test_rule_checker_rejects_unexplained_secondary_academic_jargon(self) -> None:
        report = (
            "写在前面。核心成长画像。详细指标分析。"
            "你目前可以在任务中尝试新方法。"
            "作为大脑的高级指挥官，这反映大脑神经信息加工速率。"
            "本报告不能替代医学诊断或专业咨询。"
        )
        issues = RuleChecker().run(report, {"school_stage": "junior_high"})
        joined = "\n".join(issues)
        self.assertIn("学生难以直接理解的学术化表达", joined)
        self.assertIn("[major]", joined)

    def test_fixed_norm_level_sentence_uses_reader_facing_wording(self) -> None:
        sentence = _metric_result_sentence(
            {
                "dimension_name": "思维流畅性",
                "level": "潜力区",
                "rating_basis": "fixed_norm_20_80_raw_score",
            }
        )
        self.assertEqual(sentence, "本项指标目前处于潜力区。")
        self.assertNotIn("按输入的量表解释", sentence)

    def test_vague_suggestion_is_rejected_and_concrete_step_passes(self) -> None:
        assessment = {"school_stage": "junior_high"}
        vague = {
            "parent_suggestions": [
                {
                    "action": "加强创新思维，提高探索能力。",
                    "first_step": "多进行相关练习。",
                }
            ]
        }
        self.assertGreaterEqual(
            len(_suggestion_actionability_issues(vague, assessment)),
            2,
        )
        concrete = {
            "parent_suggestions": [
                {
                    "action": "遇到开放题时，先写下三个不同方向，再按时间和效果筛选一个方案；完成后比较实际结果。",
                    "first_step": "本周选择一道开放题，完成一张三方案比较表；周末根据结果决定保留或调整方法。",
                }
            ]
        }
        self.assertEqual(
            _suggestion_actionability_issues(concrete, assessment),
            [],
        )

    def test_missing_suggestion_cards_are_a_major_contract_failure(self) -> None:
        report = json.dumps(
            {
                "audience": "student",
                "report_type": "青少年创新潜能与综合素质评估报告",
                "data_sketch": {},
                "sections": [],
                "parent_suggestions": [],
                "self_check": {},
            },
            ensure_ascii=False,
        )
        issues = run_output_contract_checks(
            report,
            {"school_stage": "junior_high"},
        )
        self.assertTrue(
            any(
                issue.startswith("[major] parent_suggestions 必须恰好为 3 条")
                for issue in issues
            )
        )

    def test_secondary_suggestion_requires_a_review_rule(self) -> None:
        assessment = {"school_stage": "junior_high"}
        no_review = {
            "parent_suggestions": [
                {
                    "action": "遇到开放题时，写下三个不同方向并筛选一个方案。",
                    "first_step": "本周完成一张三方案比较表并记录结果。",
                }
            ]
        }
        issues = _suggestion_actionability_issues(no_review, assessment)
        self.assertTrue(any("复核规则" in issue for issue in issues))

    def test_rule_checker_flags_teacher_reviewed_ai_hinges(self) -> None:
        report = (
            "这提示你需要行动。这不是能力不足，而是需要更多练习。"
            "按输入的量表解释，本项处于常态区。"
        )
        issues = RuleChecker().run(report, {"school_stage": "junior_high"})
        joined = "\n".join(issues)
        self.assertIn("不是……而是……", joined)
        self.assertIn("这提示/这说明", joined)
        self.assertIn("按输入的量表解释", joined)

    def test_duplicate_metric_result_analysis_is_a_major_issue(self) -> None:
        repeated = "在相关任务中，你可以先拆清要求，再完成后复盘一次。"
        report = {
            "sections": [
                {
                    "section_id": "detailed_indicator_analysis",
                    "body": (
                        "【思维流畅性】定义。本项得分满分，按本量表规则列为优势区。"
                        f"{repeated}\n\n"
                        "【思维灵活性】定义。按输入的量表解释，本项处于常态区。"
                        f"{repeated}"
                    ),
                }
            ]
        }
        issues = _detailed_indicator_duplicate_analysis_issues(report)
        self.assertEqual(len(issues), 1)
        self.assertIn("[major]", issues[0])
        self.assertIn("思维流畅性、思维灵活性", issues[0])

    def test_json_validation_requires_scores(self) -> None:
        with self.assertRaisesRegex(ValueError, "scores"):
            load_json_text("empty.json", json.dumps({"scores": {}}))
        with self.assertRaisesRegex(ValueError, "不是 JSON"):
            load_json_text("data.txt", json.dumps(self.sample()))

    def test_api_key_is_redacted_from_logs(self) -> None:
        key = "sk-test-secret-123456"
        cleaned = sanitize_log(f"request failed for {key}", key)
        self.assertNotIn(key, cleaned)
        self.assertIn("[REDACTED_API_KEY]", cleaned)

    def test_artifact_path_blocks_directory_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = JobManager(Path(temp_dir))
            job_root = Path(temp_dir) / "job-1"
            job_root.mkdir()
            result = job_root / "result.json"
            result.write_text("{}", encoding="utf-8")
            self.assertEqual(manager.artifact_path("job-1", "result.json"), result)
            self.assertIsNone(manager.artifact_path("job-1", "../outside.json"))

    def test_feedback_enrichment_targets_each_named_metric(self) -> None:
        feedback = {"priority": "major", "fix": []}
        assessment = {
            "scores": {
                "思维流畅性": {"score": 3, "level": "潜力区"},
                "思维灵活性": {"score": 3, "level": "潜力区"},
            }
        }
        check_result = {
            "llm_result": {
                "major_issues": [
                    "思维流畅性与思维灵活性的结果分析完全重复，未体现指标差异"
                ]
            }
        }
        enriched = enrich_feedback_targets(feedback, assessment, check_result)
        targets = {
            (item["section_id"], item["dimension"])
            for item in enriched["fix"]
        }
        self.assertIn(("detailed_indicator_analysis", "思维流畅性"), targets)
        self.assertIn(("detailed_indicator_analysis", "思维灵活性"), targets)
        self.assertIn("整份报告推倒重写", enriched["avoid"])

    def test_quality_review_explains_human_intervention(self) -> None:
        result = {
            "status": "needs_human_review",
            "iterations": [
                {
                    "round": 1,
                    "passed": False,
                    "feedback": {"fix": []},
                    "check_result": {
                        "llm_result": {
                            "total_score": 72,
                            "major_issues": ["结果分析包含输入未提供的经历"],
                        }
                    },
                },
                {
                    "round": 2,
                    "passed": False,
                    "check_result": {
                        "llm_result": {
                            "total_score": 78,
                            "major_issues": ["结果分析包含输入未提供的经历"],
                        }
                    },
                },
            ],
            "final_check": {
                "llm_result": {
                    "total_score": 78,
                    "major_issues": ["结果分析包含输入未提供的经历"],
                    "revision_instructions": ["删除无依据经历"],
                }
            },
        }
        review = build_quality_review(
            result,
            target_score=90,
            review_draft_rendered=True,
        )
        self.assertTrue(review["requires_human_review"])
        self.assertEqual(review["automatic_repair"]["round_count"], 2)
        self.assertIn("需要人工复核", review["headline"])
        self.assertEqual(len(review["issues"]), 1)
        self.assertEqual(review["issues"][0]["category"], "fabrication_risk")
        html = render_quality_review_html(review)
        self.assertIn("同事下一步怎么做", html)
        self.assertIn("结果分析包含输入未提供的经历", html)


if __name__ == "__main__":
    unittest.main()
