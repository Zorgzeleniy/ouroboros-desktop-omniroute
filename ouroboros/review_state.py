"""Durable state store for advisory pre-review runs.

Each advisory run is identified by a deterministic snapshot_hash built from:
  - the set of changed files and their content digests

State persists across task boundaries and restarts in
~/Ouroboros/data/state/advisory_review.json.

Public API:
  load_state(drive_root)        -> AdvisoryReviewState
  save_state(drive_root, state) -> None
  compute_snapshot_hash(repo_dir, commit_message, paths) -> str
  format_status_section(state)  -> str (for context injection)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import pathlib
import subprocess
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

_STATE_RELPATH = "state/advisory_review.json"
_MAX_RUN_HISTORY = 10  # Keep the last N runs in state


@dataclass
class AdvisoryRunRecord:
    """A single completed advisory pre-review run."""

    snapshot_hash: str
    commit_message: str
    status: str            # "fresh" | "stale" | "bypassed"
    ts: str                # ISO timestamp
    items: List[Dict[str, Any]] = field(default_factory=list)
    snapshot_summary: str = ""
    raw_result: str = ""
    bypass_reason: str = ""
    bypassed_by_task: str = ""


@dataclass
class AdvisoryReviewState:
    """Top-level state container."""

    runs: List[AdvisoryRunRecord] = field(default_factory=list)

    def latest(self) -> Optional[AdvisoryRunRecord]:
        """Return the most recent run, or None."""
        return self.runs[-1] if self.runs else None

    def find_by_hash(self, snapshot_hash: str) -> Optional[AdvisoryRunRecord]:
        """Return the most recent run matching snapshot_hash."""
        for run in reversed(self.runs):
            if run.snapshot_hash == snapshot_hash:
                return run
        return None

    def is_fresh(self, snapshot_hash: str) -> bool:
        """True iff there is a fresh (or bypassed) run matching snapshot_hash."""
        run = self.find_by_hash(snapshot_hash)
        return run is not None and run.status in ("fresh", "bypassed")

    def add_run(self, run: AdvisoryRunRecord) -> None:
        self.mark_all_stale_except(run.snapshot_hash)
        self.runs.append(run)
        if len(self.runs) > _MAX_RUN_HISTORY:
            self.runs = self.runs[-_MAX_RUN_HISTORY:]

    def mark_stale(self, snapshot_hash: str) -> None:
        """Mark all runs with this hash as stale."""
        for run in self.runs:
            if run.snapshot_hash == snapshot_hash:
                run.status = "stale"

    def mark_all_stale_except(self, snapshot_hash: str) -> None:
        """Mark all runs NOT matching snapshot_hash as stale."""
        for run in self.runs:
            if run.snapshot_hash != snapshot_hash and run.status == "fresh":
                run.status = "stale"


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def _record_from_dict(d: Dict[str, Any]) -> AdvisoryRunRecord:
    return AdvisoryRunRecord(
        snapshot_hash=str(d.get("snapshot_hash", "")),
        commit_message=str(d.get("commit_message", "")),
        status=str(d.get("status", "stale")),
        ts=str(d.get("ts", "")),
        items=list(d.get("items") or []),
        snapshot_summary=str(d.get("snapshot_summary", "")),
        raw_result=str(d.get("raw_result", "")),
        bypass_reason=str(d.get("bypass_reason", "")),
        bypassed_by_task=str(d.get("bypassed_by_task", "")),
    )


def load_state(drive_root: pathlib.Path) -> AdvisoryReviewState:
    """Load advisory review state from disk. Returns empty state on any error."""
    path = drive_root / _STATE_RELPATH
    try:
        if not path.exists():
            return AdvisoryReviewState()
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        runs = [_record_from_dict(r) for r in (data.get("runs") or [])]
        return AdvisoryReviewState(runs=runs)
    except Exception as e:
        log.warning("Failed to load advisory review state from %s: %s", path, e)
        return AdvisoryReviewState()


def save_state(drive_root: pathlib.Path, state: AdvisoryReviewState) -> None:
    """Persist advisory review state atomically."""
    path = drive_root / _STATE_RELPATH
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "runs": [asdict(r) for r in state.runs],
            "saved_at": _utc_now(),
        }
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    except Exception as e:
        log.warning("Failed to save advisory review state to %s: %s", path, e)


# ---------------------------------------------------------------------------
# Snapshot hash
# ---------------------------------------------------------------------------

_SNAPSHOT_EXCLUDE_PATHS = frozenset({
    # Exclude our own state file — it changes on every save and would
    # cause the hash to drift after advisory_pre_review stores its result.
    "state/advisory_review.json",
    # Also exclude lock files and temp files that change independently
    "state/queue_snapshot.json",
})


def compute_snapshot_hash(
    repo_dir: pathlib.Path,
    commit_message: str = "",
    paths: list[str] | None = None,
) -> str:
    """Build a deterministic hash for the current worktree snapshot.

    Hash inputs:
      - sorted list of (relpath, sha256_of_content) for changed files
        (excludes advisory state files that change independently)

    commit_message is accepted for backward compatibility but NOT included
    in the hash — the hash reflects code state only, making freshness less
    brittle when only the message changes.

    When *paths* is provided, only those files are considered instead of
    the full git status output.
    """
    changed_digests: List[tuple] = []

    if paths is not None:
        # Only consider the explicitly provided paths
        for relpath in paths:
            relpath = relpath.strip()
            if not relpath:
                continue
            if relpath in _SNAPSHOT_EXCLUDE_PATHS:
                continue
            file_path = repo_dir / relpath
            try:
                if file_path.is_file():
                    content = file_path.read_bytes()
                    digest = hashlib.sha256(content).hexdigest()[:16]
                else:
                    digest = "deleted"
                changed_digests.append((relpath, digest))
            except Exception:
                changed_digests.append((relpath, "unreadable"))
    else:
        # Get list of changed files (staged + unstaged) from git
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(repo_dir),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if not line.strip():
                        continue
                    # Format: "XY path" or "XY old -> new"
                    relpath = line[3:].strip().split(" -> ")[-1].strip()
                    if not relpath:
                        continue
                    if relpath in _SNAPSHOT_EXCLUDE_PATHS:
                        continue
                    file_path = repo_dir / relpath
                    try:
                        if file_path.is_file():
                            content = file_path.read_bytes()
                            digest = hashlib.sha256(content).hexdigest()[:16]
                        else:
                            digest = "deleted"
                        changed_digests.append((relpath, digest))
                    except Exception:
                        changed_digests.append((relpath, "unreadable"))
        except Exception as e:
            log.debug("compute_snapshot_hash: git status failed: %s", e)

    # Build hash from file content digests only
    h = hashlib.sha256()
    for relpath, digest in sorted(changed_digests):
        h.update(f"{relpath}:{digest}\n".encode())
    return h.hexdigest()[:32]


# ---------------------------------------------------------------------------
# Context injection
# ---------------------------------------------------------------------------

def format_status_section(state: AdvisoryReviewState) -> str:
    """Render a compact section for LLM context injection.

    Shows the last 3 runs with their status, hash, and key findings.
    """
    if not state.runs:
        return "## Advisory Pre-Review Status\n\nNo advisory runs recorded yet."

    lines = ["## Advisory Pre-Review Status"]
    for run in state.runs[-3:]:
        status_icon = {
            "fresh": "✅",
            "stale": "⚠️",
            "bypassed": "⏭️",
        }.get(run.status, "❓")

        ts_short = run.ts[:16] if len(run.ts) >= 16 else run.ts
        hash_short = run.snapshot_hash[:12]
        msg_short = run.commit_message[:60] + ("..." if len(run.commit_message) > 60 else "")

        lines.append(f"\n{status_icon} **{run.status.upper()}** | hash={hash_short} | {ts_short}")
        lines.append(f"   Commit: {msg_short}")

        if run.bypass_reason:
            lines.append(f"   Bypassed: {run.bypass_reason}")

        if run.snapshot_summary:
            lines.append(f"   Scope: {run.snapshot_summary}")

        findings = [i for i in (run.items or []) if isinstance(i, dict) and str(i.get("verdict", "")).upper() == "FAIL"]
        if findings:
            lines.append(f"   Findings ({len(findings)}):")
            for item in findings[:5]:
                sev = str(item.get("severity", "advisory")).upper()
                name = item.get("item", "?")
                reason = item.get("reason", "")[:120]
                lines.append(f"     [{sev}] {name}: {reason}")
            if len(findings) > 5:
                lines.append(f"     ... and {len(findings) - 5} more")
        elif run.status == "fresh":
            lines.append("   No findings.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utc_now() -> str:
    """ISO UTC timestamp."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
