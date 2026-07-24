import os
import subprocess
import textwrap
from pathlib import Path

import pytest

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW_ROOT = _REPOSITORY_ROOT / ".github/workflows"
_WORKFLOW_CHECKOUT_COUNTS = {
    "package-build.yml": 1,
    "hourly-research.yml": 1,
    "intraday-1h-research.yml": 2,
    "okx-1h-coverage.yml": 1,
}


def _verification_scripts(workflow_path: Path) -> list[str]:
    lines = workflow_path.read_text(encoding="utf-8").splitlines()
    scripts: list[str] = []
    for index, line in enumerate(lines):
        if line.strip() != "- name: Verify exact checked-out revision":
            continue

        run_index = next(
            candidate
            for candidate in range(index + 1, len(lines))
            if lines[candidate].strip() == "run: |"
        )
        run_indent = len(lines[run_index]) - len(lines[run_index].lstrip())
        body: list[str] = []
        for candidate in range(run_index + 1, len(lines)):
            body_line = lines[candidate]
            if body_line and len(body_line) - len(body_line.lstrip()) <= run_indent:
                break
            body.append(body_line)
        scripts.append(textwrap.dedent("\n".join(body)))

    return scripts


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        check=True,
        text=True,
    )
    return result.stdout.strip()


@pytest.mark.parametrize("workflow_name", sorted(_WORKFLOW_CHECKOUT_COUNTS))
def test_manual_dispatch_without_target_rejects_non_main_ref(
    tmp_path: Path, workflow_name: str
) -> None:
    scripts = _verification_scripts(_WORKFLOW_ROOT / workflow_name)
    assert len(scripts) == _WORKFLOW_CHECKOUT_COUNTS[workflow_name]

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "ci@example.invalid")
    _git(repo, "config", "user.name", "CI Test")
    _git(repo, "checkout", "-b", "main")
    (repo / "evidence.txt").write_text("main\n", encoding="utf-8")
    _git(repo, "add", "evidence.txt")
    _git(repo, "commit", "-m", "main")
    head_sha = _git(repo, "rev-parse", "HEAD")

    def run(
        script: str,
        github_ref: str,
        *,
        event_name: str = "workflow_dispatch",
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.update(
            {
                "EXPECTED_TESTED_SHA": head_sha,
                "REQUESTED_TARGET_SHA": "",
                "DISPATCH_REF_SHA": head_sha,
                "GITHUB_EVENT_NAME": event_name,
                "GITHUB_REF": github_ref,
            }
        )
        return subprocess.run(
            ["bash", "-c", script],
            cwd=repo,
            capture_output=True,
            check=False,
            env=env,
            text=True,
        )

    for script in scripts:
        exact_main = run(script, "refs/heads/main")
        assert exact_main.returncode == 0, exact_main.stderr

        pull_request = run(script, "refs/pull/531/merge", event_name="pull_request")
        assert pull_request.returncode == 0, pull_request.stderr

        lookalike = run(script, "refs/heads/main-shadow")
        assert lookalike.returncode != 0, (
            f"{workflow_name} accepted a manual dispatch from refs/heads/main-shadow "
            "when target_sha was omitted"
        )
