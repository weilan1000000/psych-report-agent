from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from report_app.feedback_store import FeedbackStore


class FeedbackStoreTests(unittest.TestCase):
    def test_appends_redacted_feedback_and_builds_summary(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = FeedbackStore(Path(temp_dir))
            event = store.append(
                job_id="job-1",
                item_id="item-001",
                filename="student.json",
                stage="junior_high",
                issue={"issue_id": "qi_123", "problem": "存在无依据经历"},
                decision="manual_revision",
                note="删除这一句，key=sk-test-secret-123456",
                replacement_text="改为条件化表达",
                reviewer="审核员A",
            )
            self.assertNotIn("sk-test-secret", str(event))
            events = store.load()
            self.assertEqual(len(events), 1)
            summary = store.summary(item_id="item-001", issue_ids=["qi_123"])
            self.assertEqual(summary["decision_counts"]["manual_revision"], 1)
            self.assertEqual(summary["resolved_issue_count"], 1)
            self.assertEqual(summary["unresolved_issue_count"], 0)

    def test_rejects_unknown_decision(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = FeedbackStore(Path(temp_dir))
            with self.assertRaisesRegex(ValueError, "decision"):
                store.append(
                    job_id="job-1",
                    item_id="item-001",
                    filename="student.json",
                    stage="elementary",
                    issue={"issue_id": "qi_123", "problem": "test"},
                    decision="delete_everything",
                )


if __name__ == "__main__":
    unittest.main()
