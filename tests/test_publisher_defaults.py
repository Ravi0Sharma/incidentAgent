"""Default publication behavior must stay local."""

import unittest
from unittest.mock import patch

from graph.nodes import publish as publish_node


class PublisherDefaultTests(unittest.TestCase):
    def test_default_output_stays_local_with_no_provider_calls(self):
        state = {
            "incident_id": "INC-LOCAL-OUTPUT",
            "severity": "SEV2",
            "alert": {"alertname": "Latency"},
            "postmortem_draft": "approved local draft",
        }
        with (
            patch.object(publish_node, "PUBLISH_EXTERNAL", False),
            patch.object(
                publish_node,
                "_write_html",
                return_value="output/INC-LOCAL-OUTPUT.html",
            ),
            patch.object(publish_node.slack, "publish") as slack,
            patch.object(publish_node.github, "create_postmortem") as github,
            patch.object(publish_node.jira, "create_postmortem") as jira,
        ):
            result = publish_node.publish(state)

        slack.assert_not_called()
        github.assert_not_called()
        jira.assert_not_called()
        self.assertEqual(result["postmortem_url"], "")
        self.assertEqual(
            result["postmortem_html_path"],
            "output/INC-LOCAL-OUTPUT.html",
        )


if __name__ == "__main__":
    unittest.main()
