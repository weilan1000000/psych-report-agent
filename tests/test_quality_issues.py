from __future__ import annotations

import unittest

from report_pipeline.quality_issues import normalize_check_issues


class QualityIssueProtocolTests(unittest.TestCase):
    def test_normalizes_string_and_dictionary_issues(self):
        check = {
            "rule_issues": ["[major] 【注意稳定性】等级与原始分数不一致"],
            "llm_result": {
                "fabrication_risks": [
                    {
                        "section_id": "detailed_indicator_analysis",
                        "dimension": "注意稳定性",
                        "problem": "写入了输入未提供的课堂经历",
                        "current_excerpt": "孩子上课时从不走神",
                        "instruction": "改为条件化的结果解释",
                    }
                ]
            },
        }
        issues = normalize_check_issues(check)
        self.assertEqual(len(issues), 2)
        fabrication = next(item for item in issues if item["category"] == "fabrication_risk")
        self.assertEqual(fabrication["section_id"], "detailed_indicator_analysis")
        self.assertEqual(fabrication["metric"], "注意稳定性")
        self.assertEqual(fabrication["current_excerpt"], "孩子上课时从不走神")
        self.assertTrue(fabrication["auto_fixable"])
        self.assertTrue(fabrication["issue_id"].startswith("qi_"))

    def test_deduplicates_same_problem_across_checker_lists(self):
        text = "结果分析包含输入未提供的经历"
        check = {
            "rule_issues": [f"规则检查：{text}"],
            "llm_result": {"major_issues": [text], "fabrication_risks": [text]},
        }
        issues = normalize_check_issues(check)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["category"], "fabrication_risk")
        self.assertIn("rule_issues", issues[0]["sources"])
        self.assertIn("fabrication_risks", issues[0]["sources"])

    def test_extracts_metric_heading_and_severity(self):
        check = {
            "llm_result": {
                "minor_issues": ["【思维灵活性】连续使用机械句式“本项指标目前处于”"]
            }
        }
        issue = normalize_check_issues(check)[0]
        self.assertEqual(issue["metric"], "思维灵活性")
        self.assertEqual(issue["severity"], "minor")
        self.assertEqual(issue["category"], "writing_quality")


if __name__ == "__main__":
    unittest.main()
