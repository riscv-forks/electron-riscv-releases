import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.sync_upstream_releases import (
    ReleasePlan,
    Version,
    build_release_plans,
    dispatch_release_workflow,
    ensure_base_branch,
    prepare_release_branch,
    resolve_patch_source,
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
    def test_release_dispatches_the_pr_branch(self, request) -> None:
        plan = ReleasePlan(Version.parse("41.10.5"), "v41.10.4-riscv")

        dispatch_release_workflow(
            "riscv-forks/electron-riscv-releases",
            "release.yml",
            "token",
            plan,
            72,
            "riscv-forks/electron",
        )

        body = request.call_args.kwargs["body"]
        self.assertEqual(body["inputs"]["source_ref"], "ci/release-v41.10.5-riscv")
        self.assertEqual(body["inputs"]["source_pr_number"], "72")


class PrepareReleaseBranchTest(unittest.TestCase):
    def git(self, repo: Path, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        ).stdout.strip()

    def make_repositories(self, tempdir: Path) -> tuple[Path, Path, Path]:
        upstream = tempdir / "upstream"
        origin = tempdir / "origin.git"
        checkout = tempdir / "checkout"
        for repo in (upstream, checkout):
            self.git(tempdir, "init", str(repo))
            self.git(repo, "config", "user.name", "test")
            self.git(repo, "config", "user.email", "test@example.com")
        for version in ("1.0.0", "1.1.0", "1.2.0", "1.3.0"):
            (upstream / "version").write_text(f"{version}\n")
            self.git(upstream, "add", "version")
            self.git(upstream, "commit", "-m", f"v{version}")
            self.git(upstream, "tag", f"v{version}")
        self.git(tempdir, "init", "--bare", str(origin))
        for repo in (origin, upstream):
            self.git(repo, "config", "uploadpack.allowFilter", "true")
        self.git(checkout, "remote", "add", "origin", origin.as_uri())
        self.git(checkout, "remote", "add", "upstream", upstream.as_uri())
        return upstream, origin, checkout

    def test_rebase_preserves_fork_changes_after_failed_builds(self) -> None:
        for target in ("1.2.0", "1.3.0"):
            for latest_state in ("clean", "marker", "patched"):
                with self.subTest(target=target, latest_state=latest_state), tempfile.TemporaryDirectory() as name:
                    upstream, origin, checkout = self.make_repositories(Path(name))
                    self.git(upstream, "switch", "-c", "fork", "v1.0.0")
                    (upstream / "riscv.patch").write_text("fork changes\n")
                    self.git(upstream, "add", "riscv.patch")
                    self.git(upstream, "commit", "-m", "Add RISC-V support")
                    patched_commit = self.git(upstream, "rev-parse", "HEAD")
                    self.git(upstream, "push", str(origin), "HEAD:refs/heads/v1.0.0-riscv")
                    self.git(upstream, "push", str(origin), "v1.1.0:refs/heads/v1.1.0-riscv")
                    self.git(upstream, "switch", "--detach", "v1.2.0")
                    if latest_state == "marker":
                        self.git(upstream, "commit", "--allow-empty", "-m", "Automated rebase marker")
                    elif latest_state == "patched":
                        self.git(upstream, "cherry-pick", patched_commit)
                        (upstream / "riscv.patch").write_text("updated fork changes\n")
                        self.git(upstream, "commit", "-am", "Update RISC-V support")
                    self.git(upstream, "push", str(origin), "HEAD:refs/heads/v1.2.0-riscv")
                    branches = {
                        branch: self.git(origin, "rev-parse", f"refs/heads/{branch}")
                        for branch in ("v1.0.0-riscv", "v1.1.0-riscv", "v1.2.0-riscv")
                    }

                    plan = build_release_plans([Version.parse(target)], branches)[0]
                    plan = resolve_patch_source(plan, checkout, branches)
                    use_latest = target == "1.3.0" and latest_state == "patched"
                    self.assertEqual(plan.previous_branch, "v1.2.0-riscv" if use_latest else "v1.0.0-riscv")
                    ensure_base_branch(plan, checkout, branches)
                    prepare_release_branch(plan, checkout)

                    self.assertEqual(
                        self.git(origin, "show", f"{plan.head_branch}:riscv.patch"),
                        "updated fork changes" if use_latest else "fork changes",
                    )
                    self.assertEqual(self.git(origin, "show", f"{plan.head_branch}:version"), target)
                    self.assertEqual(
                        self.git(origin, "diff", "--name-only", plan.base_branch, plan.head_branch),
                        "riscv.patch",
                    )

    def test_no_patch_source_fails_before_pushing(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            upstream, origin, checkout = self.make_repositories(Path(name))
            self.git(upstream, "push", str(origin), "v1.0.0:refs/heads/v1.0.0-riscv")
            plan = ReleasePlan(Version.parse("1.1.0"), "v1.0.0-riscv")
            branches_before = self.git(origin, "show-ref", "--heads")

            with self.assertRaisesRegex(RuntimeError, "No fork changes found"):
                resolve_patch_source(plan, checkout, {"v1.0.0-riscv": "clean"})

            self.assertEqual(self.git(origin, "show-ref", "--heads"), branches_before)

    def test_empty_rebase_gets_marker_commit_and_pr_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir_name:
            tempdir = Path(tempdir_name)
            upstream = tempdir / "upstream"
            origin = tempdir / "origin.git"
            checkout = tempdir / "checkout"

            self.git(tempdir, "init", str(upstream))
            self.git(upstream, "config", "user.name", "test")
            self.git(upstream, "config", "user.email", "test@example.com")
            (upstream / "version").write_text("1.0.0\n")
            self.git(upstream, "add", "version")
            self.git(upstream, "commit", "-m", "v1.0.0")
            self.git(upstream, "tag", "v1.0.0")
            old_commit = self.git(upstream, "rev-parse", "HEAD")
            self.git(upstream, "switch", "-c", "fork")
            (upstream / "riscv.patch").write_text("fork changes\n")
            self.git(upstream, "add", "riscv.patch")
            self.git(upstream, "commit", "-m", "Add RISC-V support")
            fork_commit = self.git(upstream, "rev-parse", "HEAD")
            self.git(upstream, "switch", "--detach", old_commit)
            (upstream / "version").write_text("1.1.0\n")
            # The new upstream release incorporates all downstream changes.
            (upstream / "riscv.patch").write_text("fork changes\n")
            self.git(upstream, "add", "version", "riscv.patch")
            self.git(upstream, "commit", "-m", "v1.1.0")
            self.git(upstream, "tag", "v1.1.0")
            target_commit = self.git(upstream, "rev-parse", "HEAD")

            self.git(tempdir, "init", "--bare", str(origin))
            self.git(origin, "config", "uploadpack.allowFilter", "true")
            self.git(upstream, "config", "uploadpack.allowFilter", "true")
            self.git(upstream, "push", str(origin), f"{fork_commit}:refs/heads/v1.0.0-riscv")
            # Start with an incorrect target branch to verify that it is reset
            # to the exact upstream tag before the PR branch is prepared.
            self.git(upstream, "push", str(origin), f"{old_commit}:refs/heads/v1.1.0-riscv")

            self.git(tempdir, "init", str(checkout))
            self.git(checkout, "remote", "add", "origin", origin.as_uri())
            self.git(checkout, "remote", "add", "upstream", upstream.as_uri())
            self.git(checkout, "config", "user.name", "github-actions[bot]")
            self.git(checkout, "config", "user.email", "github-actions[bot]@users.noreply.github.com")

            plan = ReleasePlan(Version.parse("1.1.0"), "v1.0.0-riscv")
            branches = {
                "v1.0.0-riscv": fork_commit,
                "v1.1.0-riscv": old_commit,
            }
            plan = resolve_patch_source(plan, checkout, branches)
            ensure_base_branch(plan, checkout, branches)
            prepare_release_branch(plan, checkout)

            base_commit = self.git(origin, "rev-parse", "refs/heads/v1.1.0-riscv")
            head_commit = self.git(origin, "rev-parse", "refs/heads/ci/release-v1.1.0-riscv")
            self.assertEqual(base_commit, target_commit)
            self.assertEqual(self.git(checkout, "config", "--get", "remote.origin.promisor"), "true")
            self.assertEqual(self.git(checkout, "config", "--get", "remote.upstream.promisor"), "true")
            self.assertEqual(self.git(checkout, "rev-list", "--count", f"{target_commit}..{head_commit}"), "1")
            self.assertEqual(
                self.git(checkout, "log", "-1", "--format=%s", head_commit),
                "v1.1.0: record automated rebase from v1.0.0-riscv",
            )
            self.assertEqual(self.git(checkout, "diff", "--stat", target_commit, head_commit), "")


class ReleaseWorkflowTest(unittest.TestCase):
    def test_release_workflow_has_no_push_trigger(self) -> None:
        workflow = Path(__file__).parents[1] / ".github" / "workflows" / "release.yml"

        self.assertNotIn("\n  push:", workflow.read_text())


if __name__ == "__main__":
    unittest.main()
