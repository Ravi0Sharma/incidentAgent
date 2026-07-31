import unittest

from webhook.views import render_revision_diff


class RevisionDiffRenderingTests(unittest.TestCase):
    def test_revision_diff_is_bounded_escaped_and_explains_reranking(self):
        page = render_revision_diff({
            "schema_version": "analysis-revision-diff/v1",
            "revision": 2,
            "previous_revision": 1,
            "evidence": {
                "added": ["metric-latency<script>alert(1)</script>"],
                "changed": ["log-timeout"],
                "removed": [],
                "unchanged": ["alert-1"],
            },
            "candidate_changes": [{
                "candidate_id": "candidate-timeout",
                "before": {
                    "rank": 2,
                    "confidence_label": "low",
                    "score": 35,
                    "event_ids": ["log-timeout"],
                    "title": "Timeout",
                    "raw_secret": "must-not-render",
                },
                "after": {
                    "rank": 1,
                    "confidence_label": "medium",
                    "score": 55,
                    "event_ids": ["log-timeout", "metric-latency"],
                    "title": "Timeout",
                },
            }],
            "unexpected_raw_payload": "must-not-render",
        })
        self.assertIn("What changed in analysis revision 2", page)
        self.assertIn("rank 2 → 1", page)
        self.assertIn("confidence low → medium", page)
        self.assertIn("uncalibrated score 35 → 55", page)
        self.assertIn("evidence +1", page)
        self.assertIn("metric-latency", page)
        self.assertIn("metric-latency&lt;script&gt;", page)
        self.assertNotIn("<script>", page)
        self.assertNotIn("must-not-render", page)

    def test_unknown_diff_schema_fails_closed(self):
        self.assertEqual(
            render_revision_diff({
                "schema_version": "invented/v9",
                "evidence": {"added": ["secret"]},
            }),
            "",
        )

    def test_initial_revision_is_explicit(self):
        page = render_revision_diff({
            "schema_version": "analysis-revision-diff/v1",
            "revision": 1,
            "previous_revision": None,
            "evidence": {
                "added": ["log-1"],
                "changed": [],
                "removed": [],
                "unchanged": [],
            },
            "candidate_changes": [],
        })
        self.assertIn("Initial analysis revision", page)
        self.assertIn("log-1", page)


if __name__ == "__main__":
    unittest.main()
