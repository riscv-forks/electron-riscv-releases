import unittest
from unittest.mock import patch

from scripts.sync_upstream_releases import (
    ReleasePlan,
    Version,
    build_release_plans,
    dispatch_release_workflow,
    release_workflow_was_dispatched,
)


class BuildReleasePlansTest(unittest.TestCase):
    def test_new_release_uses_latest_branch_for_major(self) -> None:
        branches = {
            "v41.10.4-riscv": "old",
            "v43.3.0-riscv": "latest",
        }

        plans = build_release_plans([Version.parse("43.4.0")], branches)

        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0].target, Version.parse("43.4.0"))
        self.assertEqual(plans[0].previous_branch, "v43.3.0-riscv")

    def test_partially_created_target_branch_is_retried(self) -> None:
        branches = {
            "v43.3.0-riscv": "patched",
            "v43.4.0-riscv": "clean-target",
        }

        plans = build_release_plans([Version.parse("43.4.0")], branches)

        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0].previous_branch, "v43.3.0-riscv")

    def test_older_releases_are_not_retried(self) -> None:
        branches = {
            "v43.3.0-riscv": "old",
            "v43.4.0-riscv": "latest",
        }

        plans = build_release_plans([Version.parse("43.3.0")], branches)

        self.assertEqual(plans, [])

    @patch("scripts.sync_upstream_releases.github_request")
    def test_dispatched_release_is_recognized_by_run_title(self, request) -> None:
        request.return_value = {
            "workflow_runs": [
                {"display_title": "Release Electron v41.10.5 for RISC-V"},
            ]
        }

        self.assertTrue(
            release_workflow_was_dispatched(
                "riscv-forks/electron-riscv-releases",
                "release.yml",
                "v41.10.5",
                "token",
            )
        )
        self.assertFalse(
            release_workflow_was_dispatched(
                "riscv-forks/electron-riscv-releases",
                "release.yml",
                "v43.4.0",
                "token",
            )
        )

    @patch("scripts.sync_upstream_releases.github_request")
    def test_release_without_patch_commits_dispatches_the_base_branch(self, request) -> None:
        plan = ReleasePlan(Version.parse("41.10.5"), "v41.10.4-riscv")

        dispatch_release_workflow(
            "riscv-forks/electron-riscv-releases",
            "release.yml",
            "token",
            plan,
            None,
            "riscv-forks/electron",
            plan.base_branch,
        )

        body = request.call_args.kwargs["body"]
        self.assertEqual(body["inputs"]["source_ref"], "v41.10.5-riscv")
        self.assertEqual(body["inputs"]["source_pr_number"], "")


if __name__ == "__main__":
    unittest.main()
