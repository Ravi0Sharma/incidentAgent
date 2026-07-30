import unittest

from webhook.lifecycle import LifecycleTransitionError, validate_transition


class LifecycleTests(unittest.TestCase):
    def test_review_lifecycle_has_explicit_legal_path(self):
        state = None
        for target in (
            "received",
            "collecting",
            "analyzing",
            "awaiting_analysis_review",
            "drafting_postmortem",
            "completed",
        ):
            state = validate_transition(state, target)
        self.assertEqual(state, "completed")

    def test_illegal_or_stale_lifecycle_transition_is_rejected(self):
        with self.assertRaisesRegex(LifecycleTransitionError, "received -> completed"):
            validate_transition("received", "completed")
        with self.assertRaisesRegex(LifecycleTransitionError, "completed -> analyzing"):
            validate_transition("completed", "analyzing")

    def test_resolution_is_allowed_from_active_and_completed_states(self):
        self.assertEqual(validate_transition("analyzing", "resolved"), "resolved")
        self.assertEqual(validate_transition("completed", "resolved"), "resolved")
        with self.assertRaises(LifecycleTransitionError):
            validate_transition("resolved", "resolved")

    def test_reopen_must_reenter_through_received(self):
        self.assertEqual(validate_transition("resolved", "received"), "received")
        with self.assertRaises(LifecycleTransitionError):
            validate_transition("resolved", "analyzing")
        with self.assertRaises(LifecycleTransitionError):
            validate_transition("resolved", "awaiting_analysis_review")
