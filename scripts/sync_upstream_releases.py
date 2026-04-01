#!/usr/bin/env python3

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path


STABLE_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
RISCV_BRANCH_RE = re.compile(r"^(v(\d+)\.(\d+)\.(\d+)-riscv)$")


@dataclass(frozen=True, order=True)
class Version:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, value: str) -> "Version":
        match = STABLE_VERSION_RE.fullmatch(value.removeprefix("v"))
        if not match:
            raise ValueError(f"unsupported version format: {value}")
        return cls(*(int(part) for part in match.groups()))

    @property
    def tag(self) -> str:
        return f"v{self.major}.{self.minor}.{self.patch}"


@dataclass(frozen=True)
class ReleasePlan:
    target: Version
    previous_branch: str

    @property
    def base_branch(self) -> str:
        return f"{self.target.tag}-riscv"

    @property
    def head_branch(self) -> str:
        return f"ci/release-{self.target.tag}-riscv"


def log(message: str) -> None:
    print(message, flush=True)


def run(cmd: list[str], *, cwd: Path | None = None, capture: bool = False) -> str:
    log(f"Running: {' '.join(cmd)} (cwd={cwd})")
    result = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
    )
    return result.stdout if capture else ""


def github_request(
    repo: str,
    path: str,
    token: str,
    *,
    method: str = "GET",
    body: dict | None = None,
) -> object | None:
    url = f"https://api.github.com/repos/{repo}/{path.lstrip('/')}"
    data = None
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "electron-riscv-release-sync",
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API {method} {url} failed: {error.code} {detail}") from error

    if not payload:
        return None
    return json.loads(payload)


def fetch_stable_releases() -> list[Version]:
    request = urllib.request.Request(
        "https://releases.electronjs.org/releases.json",
        headers={"User-Agent": "electron-riscv-release-sync"},
    )
    with urllib.request.urlopen(request) as response:
        payload = json.load(response)

    releases: list[Version] = []
    seen: set[str] = set()
    for release in payload:
        version = release.get("version", "")
        if not STABLE_VERSION_RE.fullmatch(version):
            continue
        if version in seen:
            continue
        seen.add(version)
        releases.append(Version.parse(version))
    return releases


def list_source_branches(source_repo_url: str) -> dict[str, str]:
    output = run(["git", "ls-remote", "--heads", source_repo_url], capture=True)
    branches: dict[str, str] = {}
    for line in output.splitlines():
        sha, ref = line.split("\t", 1)
        prefix = "refs/heads/"
        if ref.startswith(prefix):
            branches[ref[len(prefix):]] = sha
    return branches


def latest_branches_by_major(branches: dict[str, str]) -> dict[int, str]:
    latest: dict[int, tuple[Version, str]] = {}
    for branch in branches:
        match = RISCV_BRANCH_RE.fullmatch(branch)
        if not match:
            continue
        version = Version(int(match.group(2)), int(match.group(3)), int(match.group(4)))
        current = latest.get(version.major)
        if current is None or version > current[0]:
            latest[version.major] = (version, branch)
    return {major: branch for major, (_, branch) in latest.items()}


def release_exists(repo: str, tag: str, token: str) -> bool:
    release = github_request(repo, f"releases/tags/{tag}", token)
    return release is not None


def find_existing_pr(repo: str, owner: str, base: str, head: str, token: str) -> dict | None:
    query = urllib.parse.urlencode(
        {
            "state": "all",
            "base": base,
            "head": f"{owner}:{head}",
            "per_page": 100,
        }
    )
    pulls = github_request(
        repo,
        f"pulls?{query}",
        token,
    )
    if not pulls:
        return None
    return pulls[0]


def clone_source_repo(source_repo_auth_url: str, tempdir: Path) -> Path:
    checkout_dir = tempdir / "electron"
    run(["git", "clone", "--filter=blob:none", source_repo_auth_url, str(checkout_dir)])
    run(["git", "remote", "add", "upstream", "https://github.com/electron/electron.git"], cwd=checkout_dir)
    run(["git", "config", "user.name", "github-actions[bot]"], cwd=checkout_dir)
    run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"], cwd=checkout_dir)
    return checkout_dir


def prepare_release_branch(plan: ReleasePlan, checkout_dir: Path) -> None:
    previous_tag = plan.previous_branch.removesuffix("-riscv")
    run(["git", "fetch", "origin", plan.previous_branch], cwd=checkout_dir)
    run(["git", "fetch", "upstream", f"refs/tags/{previous_tag}:refs/tags/{previous_tag}"], cwd=checkout_dir)
    run(["git", "fetch", "upstream", f"refs/tags/{plan.target.tag}:refs/tags/{plan.target.tag}"], cwd=checkout_dir)
    run(["git", "fetch", "origin", f"refs/heads/{plan.base_branch}:refs/remotes/origin/{plan.base_branch}"], cwd=checkout_dir)
    run(["git", "switch", "-C", plan.head_branch, f"origin/{plan.previous_branch}"], cwd=checkout_dir)
    run(["git", "merge-base", "--is-ancestor", previous_tag, "HEAD"], cwd=checkout_dir)
    run(["git", "rebase", "--onto", plan.target.tag, previous_tag], cwd=checkout_dir)
    run(["git", "push", "--force", "origin", f"HEAD:refs/heads/{plan.head_branch}"], cwd=checkout_dir)


def ensure_base_branch(plan: ReleasePlan, checkout_dir: Path, source_branches: dict[str, str]) -> None:
    if plan.base_branch in source_branches:
        return
    run(["git", "fetch", "upstream", f"refs/tags/{plan.target.tag}:refs/tags/{plan.target.tag}"], cwd=checkout_dir)
    run(["git", "switch", "-C", plan.base_branch, f"refs/tags/{plan.target.tag}"], cwd=checkout_dir)
    run(["git", "push", "-u", "origin", plan.base_branch], cwd=checkout_dir)


def create_pull_request(repo: str, head: str, base: str, token: str, previous_branch: str) -> dict:
    body = {
        "title": f"{base}: rebase from {previous_branch}",
        "head": head,
        "base": base,
        "body": (
            "Automated release preparation PR.\n\n"
            f"- Source patch branch: `{previous_branch}`\n"
            f"- Target stable branch: `{base}`\n"
        ),
        "maintainer_can_modify": True,
    }
    pull = github_request(repo, "pulls", token, method="POST", body=body)
    if not isinstance(pull, dict):
        raise RuntimeError("GitHub API returned an unexpected PR payload")
    return pull


def dispatch_release_workflow(
    repo: str,
    workflow: str,
    token: str,
    plan: ReleasePlan,
    pr_number: int,
    source_repo: str,
) -> None:
    body = {
        "ref": "main",
        "inputs": {
            "electron_tag": plan.target.tag,
            "source_ref": plan.head_branch,
            "source_pr_number": str(pr_number),
            "source_repo": source_repo,
        },
    }
    github_request(repo, f"actions/workflows/{workflow}/dispatches", token, method="POST", body=body)


def build_release_plans(releases: list[Version], latest_by_major: dict[int, str]) -> list[ReleasePlan]:
    plans: list[ReleasePlan] = []
    for release in releases:
        previous_branch = latest_by_major.get(release.major)
        if not previous_branch:
            continue
        previous_version = Version.parse(previous_branch.removesuffix("-riscv"))
        if release <= previous_version:
            continue
        plans.append(ReleasePlan(target=release, previous_branch=previous_branch))
    return plans


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Synchronize upstream Electron stable releases")
    parser.add_argument("--dry-run", action="store_true", help="show what would happen without pushing or opening PRs")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    github_token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    source_repo_token = os.environ.get("SOURCE_REPO_TOKEN")
    releases_repo = os.environ.get("RELEASES_REPO", "riscv-forks/electron-riscv-releases")
    source_repo = os.environ.get("SOURCE_REPO", "riscv-forks/electron")
    source_repo_url = os.environ.get("SOURCE_REPO_URL", f"https://github.com/{source_repo}.git")
    workflow = os.environ.get("RELEASE_WORKFLOW", "release.yml")

    if not github_token:
        raise RuntimeError("GITHUB_TOKEN or GH_TOKEN is required")
    if not args.dry_run and not source_repo_token:
        raise RuntimeError("SOURCE_REPO_TOKEN is required unless --dry-run is set")

    source_owner = source_repo.split("/", 1)[0]
    stable_releases = fetch_stable_releases()
    source_branches = list_source_branches(source_repo_url)
    latest_by_major = latest_branches_by_major(source_branches)
    plans = build_release_plans(stable_releases, latest_by_major)

    if not plans:
        log("No matching new stable releases found.")
        return 0

    failures: list[str] = []
    auth_url = f"https://x-access-token:{source_repo_token}@github.com/{source_repo}.git" if source_repo_token else source_repo_url

    for plan in plans:
        log(f"Evaluating {plan.target.tag} using {plan.previous_branch}")

        if release_exists(releases_repo, plan.target.tag, github_token):
            log(f"Skipping {plan.target.tag}: release already exists in {releases_repo}")
            continue

        existing_pr = find_existing_pr(source_repo, source_owner, plan.base_branch, plan.head_branch, github_token)
        if existing_pr:
            state = existing_pr.get("state", "unknown")
            url = existing_pr.get("html_url", "")
            log(f"Skipping {plan.target.tag}: PR already exists in state={state} {url}")
            continue

        if args.dry_run:
            log(
                f"Would create {plan.base_branch}, force-push {plan.head_branch}, open PR into {plan.base_branch}, "
                f"and dispatch {workflow}"
            )
            continue

        try:
            with tempfile.TemporaryDirectory(prefix="electron-riscv-release-") as tempdir_name:
                checkout_dir = clone_source_repo(auth_url, Path(tempdir_name))
                ensure_base_branch(plan, checkout_dir, source_branches)
                prepare_release_branch(plan, checkout_dir)
            pull = create_pull_request(source_repo, plan.head_branch, plan.base_branch, source_repo_token, plan.previous_branch)
            pr_number = int(pull["number"])
            dispatch_release_workflow(releases_repo, workflow, github_token, plan, pr_number, source_repo)
            log(f"Created PR #{pr_number} for {plan.target.tag}: {pull['html_url']}")
        except Exception as error:  # noqa: BLE001
            failures.append(f"{plan.target.tag}: {error}")

    if failures:
        log("Release synchronization failures:")
        for failure in failures:
            log(f"- {failure}")
        return 1

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:  # noqa: BLE001
        log(f"fatal: {error}")
        raise SystemExit(1)