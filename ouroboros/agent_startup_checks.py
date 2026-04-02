"""
Startup verification checks for the Ouroboros agent.

Runs on worker boot to detect uncommitted changes, version desync,
budget issues, and missing memory files.
Extracted from agent.py to keep the agent thin.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from typing import Any, Dict, Tuple

from ouroboros.utils import utc_now_iso, read_text, append_jsonl

log = logging.getLogger(__name__)


def _is_stable_release_tag(tag: str) -> bool:
    return bool(re.match(r"^\d+\.\d+\.\d+$", str(tag or "").strip()))


def _startup_auto_rescue_enabled(env: Any) -> bool:
    managed = getattr(env, "launcher_managed", None)
    if managed is None:
        managed = os.environ.get("OUROBOROS_MANAGED_BY_LAUNCHER", "")
    if isinstance(managed, bool):
        return managed
    return str(managed or "").strip() == "1"


def check_uncommitted_changes(env: Any) -> Tuple[dict, int]:
    """Check for uncommitted changes and attempt auto-rescue commit."""
    import re
    try:
        lock_path = env.repo_path(".git/index.lock")
        if lock_path.exists():
            try:
                lock_path.unlink()
                log.warning("Removed stale git index.lock")
            except OSError:
                pass

        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(env.repo_dir),
            capture_output=True, text=True, timeout=10, check=True
        )
        dirty_files = [l.strip() for l in result.stdout.strip().split('\n') if l.strip()]
        if dirty_files:
            auto_committed = False
            if not _startup_auto_rescue_enabled(env):
                log.warning(
                    "Uncommitted changes detected on startup; skipping auto-rescue commit "
                    "outside launcher-managed mode"
                )
                return {
                    "status": "warning",
                    "files": dirty_files[:20],
                    "auto_committed": auto_committed,
                    "auto_rescue_skipped": "not_launcher_managed",
                }, 1
            try:
                subprocess.run(["git", "add", "-u"], cwd=str(env.repo_dir),
                               capture_output=True, timeout=10)
                if not re.match(r'^[a-zA-Z0-9_/-]+$', str(getattr(env, "branch_dev", "ouroboros"))):
                    raise ValueError(f"Invalid branch name: {getattr(env, 'branch_dev', '')}")
                commit_result = subprocess.run(
                    ["git", "commit", "-m", "auto-rescue: uncommitted changes detected on startup"],
                    cwd=str(env.repo_dir), capture_output=True, text=True, timeout=30,
                )
                if commit_result.returncode == 0 and "nothing to commit" not in (commit_result.stdout or ""):
                    auto_committed = True
                    log.warning(f"Auto-rescued {len(dirty_files)} uncommitted files on startup")
                else:
                    log.info("Auto-rescue: nothing staged to commit (untracked files only or no changes)")
            except Exception as e:
                log.warning(f"Failed to auto-rescue uncommitted changes: {e}", exc_info=True)
            return {
                "status": "warning", "files": dirty_files[:20],
                "auto_committed": auto_committed,
            }, 1
        else:
            return {"status": "ok"}, 0
    except Exception as e:
        return {"status": "error", "error": str(e)}, 0


def check_version_sync(env: Any) -> Tuple[dict, int]:
    """Check VERSION file sync with git tags and pyproject.toml."""
    try:
        version_file = read_text(env.repo_path("VERSION")).strip()
        issue_count = 0
        result_data: Dict[str, Any] = {"version_file": version_file}

        pyproject_path = env.repo_path("pyproject.toml")
        pyproject_content = read_text(pyproject_path)
        match = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', pyproject_content, re.MULTILINE)
        if match:
            pyproject_version = match.group(1)
            result_data["pyproject_version"] = pyproject_version
            if version_file != pyproject_version:
                result_data["status"] = "warning"
                issue_count += 1

        try:
            readme_content = read_text(env.repo_path("README.md"))
            readme_match = (
                re.search(r'version-(\d+\.\d+\.\d+)', readme_content, re.IGNORECASE)
                or re.search(r'\*\*Version:\*\*\s*(\d+\.\d+\.\d+)', readme_content)
            )
            if readme_match:
                readme_version = readme_match.group(1)
                result_data["readme_version"] = readme_version
                if version_file != readme_version:
                    result_data["status"] = "warning"
                    issue_count += 1
        except Exception:
            log.debug("Failed to check README.md version", exc_info=True)

        try:
            arch_content = read_text(env.repo_path("docs/ARCHITECTURE.md"))
            arch_match = re.search(r'# Ouroboros v(\d+\.\d+\.\d+)', arch_content)
            if arch_match:
                arch_version = arch_match.group(1)
                result_data["architecture_version"] = arch_version
                if version_file != arch_version:
                    result_data["status"] = "warning"
                    issue_count += 1
        except Exception:
            log.debug("Failed to check ARCHITECTURE.md version", exc_info=True)

        result = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0"],
            cwd=str(env.repo_dir),
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            result_data["status"] = "warning"
            result_data["message"] = "no_tags"
            return result_data, issue_count
        else:
            latest_tag = result.stdout.strip().lstrip('v')
            result_data["latest_tag"] = latest_tag
            if _is_stable_release_tag(latest_tag) and version_file != latest_tag:
                result_data["status"] = "warning"
                issue_count += 1
            elif not _is_stable_release_tag(latest_tag):
                result_data["tag_sync"] = "ignored_non_release_tag"

        if issue_count == 0:
            result_data["status"] = "ok"

        return result_data, issue_count
    except Exception as e:
        return {"status": "error", "error": str(e)}, 0


def check_budget(env: Any) -> Tuple[dict, int]:
    """Check budget remaining with warning thresholds."""
    try:
        state_path = env.drive_path("state") / "state.json"
        state_data = json.loads(read_text(state_path))
        total_budget_str = os.environ.get("TOTAL_BUDGET", "")

        if not total_budget_str or float(total_budget_str) == 0:
            return {"status": "unconfigured"}, 0
        else:
            total_budget = float(total_budget_str)
            spent = float(state_data.get("spent_usd", 0))
            remaining = max(0, total_budget - spent)

            if remaining < 0.5:
                status = "emergency"
                issues = 1
            elif remaining < 2:
                status = "critical"
                issues = 1
            elif remaining < 5:
                status = "warning"
                issues = 0
            else:
                status = "ok"
                issues = 0

            return {
                "status": status,
                "remaining_usd": round(remaining, 2),
                "total_usd": total_budget,
                "spent_usd": round(spent, 2),
            }, issues
    except Exception as e:
        return {"status": "error", "error": str(e)}, 0


def verify_system_state(env: Any, git_sha: str) -> None:
    """Bible Principle 1: verify system state on every startup."""
    checks: Dict[str, Any] = {}
    issues = 0
    drive_logs = env.drive_path("logs")

    checks["uncommitted_changes"], issue_count = check_uncommitted_changes(env)
    issues += issue_count

    checks["version_sync"], issue_count = check_version_sync(env)
    issues += issue_count

    checks["budget"], issue_count = check_budget(env)
    issues += issue_count

    memory_dir = env.drive_path("memory")
    identity_path = memory_dir / "identity.md"
    scratchpad_path = memory_dir / "scratchpad.md"
    world_path = memory_dir / "WORLD.md"

    identity_ok = identity_path.exists() and identity_path.stat().st_size > 0
    scratchpad_ok = scratchpad_path.exists()
    world_ok = world_path.exists()

    checks["identity"] = {"exists": identity_path.exists(), "non_empty": identity_ok}
    checks["scratchpad"] = {"exists": scratchpad_ok}
    checks["world_profile"] = {"exists": world_ok}

    if not identity_ok:
        issues += 1
        log.warning("identity.md missing or empty — continuity at risk (Bible P1)")
    if not scratchpad_ok:
        issues += 1
        log.warning("scratchpad.md missing — working memory not available (Bible P1)")
    if not world_ok:
        issues += 1
        log.warning("WORLD.md missing — environment profile not available")

    configured_model = os.environ.get("OUROBOROS_MODEL", "")
    checks["model"] = {"configured": configured_model or "(not set)"}
    if not configured_model:
        issues += 1

    event = {
        "ts": utc_now_iso(),
        "type": "startup_verification",
        "checks": checks,
        "issues_count": issues,
        "git_sha": git_sha,
    }
    append_jsonl(drive_logs / "events.jsonl", event)

    if issues > 0:
        log.warning(f"Startup verification found {issues} issue(s): {checks}")


def inject_crash_report(env: Any) -> None:
    """If a crash report exists from a rollback, log it to events.

    The file is NOT deleted — it stays so that build_health_invariants()
    shows CRITICAL: RECENT CRASH ROLLBACK on every task until the issue
    is investigated and removed via run_shell (LLM-first, P3).
    """
    try:
        crash_path = env.drive_path("state") / "crash_report.json"
        if not crash_path.exists():
            return
        crash_data = json.loads(crash_path.read_text(encoding="utf-8"))
        append_jsonl(env.drive_path("logs") / "events.jsonl", {
            "ts": utc_now_iso(),
            "type": "crash_rollback_detected",
            "crash_data": crash_data,
        })
        log.warning("Crash rollback detected: %s", crash_data)
    except Exception:
        log.debug("Failed to process crash report", exc_info=True)


def verify_restart(env: Any, git_sha: str) -> None:
    """Best-effort restart verification."""
    try:
        pending_path = env.drive_path('state') / 'pending_restart_verify.json'
        claim_path = pending_path.with_name(f"pending_restart_verify.claimed.{os.getpid()}.json")
        try:
            os.rename(str(pending_path), str(claim_path))
        except (FileNotFoundError, Exception):
            return
        try:
            claim_data = json.loads(read_text(claim_path))
            expected_sha = str(claim_data.get("expected_sha", "")).strip()
            ok = bool(expected_sha and expected_sha == git_sha)
            append_jsonl(env.drive_path('logs') / 'events.jsonl', {
                'ts': utc_now_iso(), 'type': 'restart_verify',
                'pid': os.getpid(), 'ok': ok,
                'expected_sha': expected_sha, 'observed_sha': git_sha,
            })
        except Exception:
            log.debug("Failed to log restart verify event", exc_info=True)
            pass
        try:
            claim_path.unlink()
        except Exception:
            log.debug("Failed to delete restart verify claim file", exc_info=True)
            pass
    except Exception:
        log.debug("Restart verification failed", exc_info=True)
        pass
