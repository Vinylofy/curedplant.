import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ArchiveWorkflowTests(unittest.TestCase):
    def test_scheduled_catch_up_capacity_is_bounded_but_large_enough(self):
        workflow = (ROOT / ".github/workflows/database-archive-e-pilot.yml").read_text(encoding="utf-8")
        self.assertEqual(workflow.count("github.event_name == 'schedule' && '2000'"), 2)
        self.assertEqual(workflow.count("github.event_name == 'schedule' && '500' || inputs.batches"), 4)
        self.assertIn("--confirm-redundancy $env:CONFIRM_CLEANUP", workflow)
        self.assertIn("SINGLE_E_COPY_RISK_ACCEPTED", workflow)


if __name__ == "__main__":
    unittest.main()
