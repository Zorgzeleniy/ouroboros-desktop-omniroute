"""
Ouroboros context builder.

Assembles LLM context from prompts, memory, logs, and runtime state.
Extracted from agent.py to keep the agent thin and focused.
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
import re
import sys
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from ouroboros.utils import (
    utc_now_iso, read_text, estimate_tokens, get_git_info,
)
from ouroboros.memory import Memory

log = logging.getLogger(__name__)


def build_user_content(task: Dict[str, Any]) -> Any:
    """Build user message content. Supports text + optional image."""
    text = task.get("text", "")
    image_b64 = task.get("image_base64")
    image_mime = task.get("image_mime", "image/jpeg")
    image_caption = task.get("image_caption", "")

    if not image_b64:
        # Return fallback text if both text and image are empty
        if not text:
            return "(empty message)"
        return text

    # Multipart content with text + image
    parts = []
    # Combine caption and text for the text part
    combined_text = ""
    if image_caption:
        combined_text = image_caption
    if text and text != image_caption:
        combined_text = (combined_text + "\n" + text).strip() if combined_text else text

    # Always include a text part when there's an image
    if not combined_text:
        combined_text = "Analyze the screenshot"

    parts.append({"type": "text", "text": combined_text})
    parts.append({
        "type": "image_url",
        "image_url": {"url": f"data:{image_mime};base64,{image_b64}"}
    })
    return parts


def build_runtime_section(env: Any, task: Dict[str, Any]) -> str:
    """Build the runtime context section (utc_now, repo_dir, drive_root, git_head, git_branch, task info, budget info)."""
    # --- Git context ---
    try:
        git_branch, git_sha = get_git_info(env.repo_dir)
    except Exception:
        log.debug("Failed to get git info for context", exc_info=True)
        git_branch, git_sha = "unknown", "unknown"

    # --- Budget calculation ---
    budget_info = None
    try:
        state_json = safe_read(env.drive_path("state/state.json"), fallback="{}")
        state_data = json.loads(state_json)
        spent_usd = float(state_data.get("spent_usd", 0))
        total_usd = float(os.environ.get("TOTAL_BUDGET", "1"))
        remaining_usd = total_usd - spent_usd
        budget_info = {"total_usd": total_usd, "spent_usd": spent_usd, "remaining_usd": remaining_usd}
    except Exception:
        log.debug("Failed to calculate budget info for context", exc_info=True)
        pass

    # --- Runtime context JSON ---
    _is_desktop = bool(os.environ.get("OUROBOROS_DESKTOP_MODE", ""))
    runtime_data = {
        "utc_now": utc_now_iso(),
        "repo_dir": str(env.repo_dir),
        "drive_root": str(env.drive_root),
        "git_head": git_sha,
        "git_branch": git_branch,
        "task": {"id": task.get("id"), "type": task.get("type")},
        "runtime_env": {
            "is_desktop": _is_desktop,
            "platform": sys.platform,
        },
    }
    if budget_info:
        runtime_data["budget"] = budget_info
    runtime_ctx = json.dumps(runtime_data, ensure_ascii=False, indent=2)
    return "## Runtime context\n\n" + runtime_ctx


_SECTION_BUDGETS = {
    "scratchpad": 90_000,
    "identity": 80_000,
    "registry": 30_000,
}


def _warn_if_over_budget(name: str, content: str) -> None:
    budget = _SECTION_BUDGETS.get(name)
    if budget and len(content) > budget:
        log.warning("Context section '%s' exceeds budget: %d chars > %d", name, len(content), budget)


def _parse_budget_chars(raw: str) -> Optional[int]:
    token = str(raw or "").strip().lower()
    token = token.replace("chars", "").replace("char", "").strip()
    token = token.replace(",", "").replace("_", "")
    if token.endswith("k"):
        try:
            return int(float(token[:-1]) * 1000)
        except ValueError:
            return None
    if token.isdigit():
        return int(token)
    return None


def _parse_file_size_budgets(dev_text: str) -> List[Tuple[str, int]]:
    budgets: List[Tuple[str, int]] = []
    in_section = False
    for line in dev_text.splitlines():
        if line.startswith("### File Size Budgets"):
            in_section = True
            continue
        if in_section and line.startswith("### "):
            break
        if not in_section or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        if cells[0].lower() in {"file", "path"} or set(cells[0]) == {"-"}:
            continue
        budget = _parse_budget_chars(cells[1])
        if budget:
            budgets.append((cells[0], budget))
    return budgets


def _iter_budget_paths(root: pathlib.Path, pattern: str) -> List[pathlib.Path]:
    if "*" in pattern or "?" in pattern or "[" in pattern:
        return sorted(p for p in root.glob(pattern) if p.is_file())
    path = root / pattern
    return [path] if path.exists() and path.is_file() else []


def _append_file_size_budget_checks(env: Any, checks: List[str]) -> None:
    try:
        repo_root = env.repo_dir if not isinstance(env, dict) else pathlib.Path(env["repo_dir"])
        drive_root = env.drive_root if not isinstance(env, dict) else pathlib.Path(env["drive_root"])
        dev_text = read_text(repo_root / "docs" / "DEVELOPMENT.md")
        seen: set[str] = set()
        for relpath, budget in _parse_file_size_budgets(dev_text):
            root = drive_root if relpath.startswith("memory/") else repo_root
            for fpath in _iter_budget_paths(root, relpath):
                resolved = str(fpath.resolve())
                if resolved in seen:
                    continue
                seen.add(resolved)
                size = fpath.stat().st_size
                label = str(fpath.relative_to(root)).replace("\\", "/")
                if size > budget:
                    checks.append(
                        f"WARNING: FILE SIZE BUDGET EXCEEDED — {label} is {size:,} chars "
                        f"(budget {budget:,}). Consolidate it or revise the budget in DEVELOPMENT.md."
                    )
                elif size >= int(budget * 0.9):
                    checks.append(
                        f"WARNING: FILE SIZE NEAR BUDGET — {label} is {size:,} chars "
                        f"({int(size * 100 / budget)}% of {budget:,}). Consider consolidation."
                    )
    except Exception:
        log.debug("Failed to append file size budget checks", exc_info=True)


def build_memory_sections(memory: Memory) -> List[str]:
    """Build scratchpad, identity, dialogue blocks, and registry sections."""
    sections = []

    scratchpad_raw = memory.load_scratchpad()
    _warn_if_over_budget("scratchpad", scratchpad_raw)
    sections.append("## Scratchpad\n\n" + scratchpad_raw)

    identity_raw = memory.load_identity()
    _warn_if_over_budget("identity", identity_raw)
    sections.append("## Identity\n\n" + identity_raw)

    try:
        from ouroboros.consolidator import migrate_dialogue_summary_to_blocks
        migrate_dialogue_summary_to_blocks(
            memory.drive_root / "memory" / "dialogue_summary.md",
            memory.drive_root / "memory" / "dialogue_blocks.json",
        )
    except Exception:
        pass

    dialogue_blocks = memory.load_dialogue_blocks()
    if dialogue_blocks:
        blocks_md = memory.format_blocks_as_markdown(dialogue_blocks)
        if blocks_md.strip():
            sections.append("## Dialogue History\n\n" + blocks_md)
    else:
        summary_path = memory.drive_root / "memory" / "dialogue_summary.md"
        if summary_path.exists():
            summary_text = read_text(summary_path)
            if summary_text.strip():
                sections.append("## Dialogue Summary\n\n" + summary_text)

    registry_path = memory.drive_root / "memory" / "registry.md"
    if registry_path.exists():
        registry_text = read_text(registry_path)
        if registry_text.strip():
            _warn_if_over_budget("registry", registry_text)
            sections.append("## Memory Registry\n\n" + registry_text)

    return sections


def _format_recent_reflections(entries: List[Dict[str, Any]], limit: int = 10) -> str:
    """Format recent execution reflections for dynamic context."""
    if not entries:
        return ""

    blocks: List[str] = []
    for entry in entries[-limit:]:
        ts_full = str(entry.get("ts", ""))
        ts = ts_full[:16] if len(ts_full) >= 16 else ts_full
        header_bits = [bit for bit in [
            ts,
            str(entry.get("task_type", "")).strip(),
            str(entry.get("task_id", "")).strip(),
        ] if bit]
        header = " | ".join(header_bits) or "unknown reflection"

        lines = [f"### {header}"]

        goal = str(entry.get("goal", "")).strip()
        if goal:
            lines.append(f"- Goal: {goal}")

        markers = [str(m).strip() for m in (entry.get("key_markers") or []) if str(m).strip()]
        if markers:
            lines.append(f"- Markers: {', '.join(markers)}")

        rounds = entry.get("rounds")
        if rounds not in (None, ""):
            lines.append(f"- Rounds: {rounds}")

        cost_usd = entry.get("cost_usd")
        if cost_usd not in (None, ""):
            lines.append(f"- Cost: ${cost_usd}")

        reflection = str(entry.get("reflection", "")).strip()
        if reflection:
            lines.append("")
            lines.append(reflection)

        blocks.append("\n".join(lines).strip())

    return "\n\n".join(blocks)


def build_recent_sections(memory: Memory, env: Any, task_id: str = "") -> List[str]:
    """Build recent dialogue and process-memory sections."""
    sections = []

    chat_summary = memory.summarize_chat(memory.read_jsonl_tail("chat.jsonl", 1000))
    if chat_summary:
        sections.append("## Recent chat\n\n" + chat_summary)

    progress_entries = memory.read_jsonl_tail("progress.jsonl", 200)
    if task_id:
        progress_entries = [e for e in progress_entries if str(e.get("task_id", "")).strip() == task_id]
    progress_summary = memory.summarize_progress(progress_entries, limit=50)
    if progress_summary:
        sections.append("## Recent progress\n\n" + progress_summary)

    tools_entries = memory.read_jsonl_tail("tools.jsonl", 200)
    if task_id:
        tools_entries = [e for e in tools_entries if str(e.get("task_id", "")).strip() == task_id]
    tools_summary = memory.summarize_tools(tools_entries)
    if tools_summary:
        sections.append("## Recent tools\n\n" + tools_summary)

    events_entries = memory.read_jsonl_tail("events.jsonl", 200)
    if task_id:
        events_entries = [e for e in events_entries if str(e.get("task_id", "")).strip() == task_id]
    events_summary = memory.summarize_events(events_entries)
    if events_summary:
        sections.append("## Recent events\n\n" + events_summary)

    supervisor_summary = memory.summarize_supervisor(memory.read_jsonl_tail("supervisor.jsonl", 200))
    if supervisor_summary:
        sections.append("## Supervisor\n\n" + supervisor_summary)

    reflections_entries = memory.read_jsonl_tail("task_reflections.jsonl", 20)
    reflections_text = _format_recent_reflections(reflections_entries, limit=10)
    if reflections_text:
        sections.append("## Execution reflections\n\n" + reflections_text)

    return sections


def _append_version_sync_checks(env: Any, checks: List[str]) -> None:
    try:
        ver_file = read_text(env.repo_path("VERSION")).strip()
        desync_parts = []

        pyproject = read_text(env.repo_path("pyproject.toml"))
        pyproject_ver = ""
        for line in pyproject.splitlines():
            if line.strip().startswith("version"):
                pyproject_ver = line.split("=", 1)[1].strip().strip('"').strip("'")
                break
        if ver_file and pyproject_ver and ver_file != pyproject_ver:
            desync_parts.append(f"pyproject.toml={pyproject_ver}")

        try:
            readme = read_text(env.repo_path("README.md"))
            readme_match = (
                re.search(r'version-(\d+\.\d+\.\d+)', readme, re.IGNORECASE)
                or re.search(r'\*\*Version:\*\*\s*(\d+\.\d+\.\d+)', readme)
            )
            if readme_match and readme_match.group(1) != ver_file:
                desync_parts.append(f"README={readme_match.group(1)}")
        except Exception:
            pass

        try:
            arch = read_text(env.repo_path("docs/ARCHITECTURE.md"))
            arch_match = re.search(r'# Ouroboros v(\d+\.\d+\.\d+)', arch)
            if arch_match and arch_match.group(1) != ver_file:
                desync_parts.append(f"ARCHITECTURE.md={arch_match.group(1)}")
        except Exception:
            pass

        if desync_parts:
            checks.append(f"CRITICAL: VERSION DESYNC — VERSION={ver_file}, {', '.join(desync_parts)}")
        elif ver_file:
            checks.append(f"OK: version sync ({ver_file})")
    except Exception:
        pass


def _append_budget_drift_checks(env: Any, checks: List[str]) -> None:
    try:
        state_json = read_text(env.drive_path("state/state.json"))
        state_data = json.loads(state_json)
        if state_data.get("budget_drift_alert"):
            drift_pct = state_data.get("budget_drift_pct", 0)
            our = state_data.get("spent_usd", 0)
            theirs = state_data.get("openrouter_total_usd", 0)
            checks.append(f"WARNING: BUDGET DRIFT {drift_pct:.1f}% — tracked=${our:.2f} vs OpenRouter=${theirs:.2f}")
        else:
            checks.append("OK: budget drift within tolerance")
    except Exception:
        pass


def _append_task_cost_checks(checks: List[str]) -> None:
    try:
        from supervisor.state import per_task_cost_summary
        costly = [t for t in per_task_cost_summary(5) if t["cost"] > 5.0]
        for t in costly:
            checks.append(
                f"WARNING: HIGH-COST TASK — task_id={t['task_id']} "
                f"cost=${t['cost']:.2f} rounds={t['rounds']}"
            )
        if not costly:
            checks.append("OK: no high-cost tasks (>$5)")
    except Exception:
        pass


def _append_memory_health_checks(env: Any, checks: List[str]) -> None:
    try:
        import time as _time
        identity_path = env.drive_path("memory/identity.md")
        if identity_path.exists():
            age_hours = (_time.time() - identity_path.stat().st_mtime) / 3600
            if age_hours > 8:
                checks.append(f"WARNING: STALE IDENTITY — identity.md last updated {age_hours:.0f}h ago")
            else:
                checks.append("OK: identity.md recent")
    except Exception:
        pass

    try:
        identity_content = read_text(env.drive_path("memory/identity.md"))
        if len(identity_content.strip()) < 200:
            checks.append(f"WARNING: THIN IDENTITY — identity.md is only {len(identity_content)} chars. Cognitive decay signal.")
    except Exception:
        pass

    try:
        scratchpad_content = read_text(env.drive_path("memory/scratchpad.md"))
        sp_len = len(scratchpad_content.strip())
        if sp_len < 50:
            checks.append("WARNING: EMPTY SCRATCHPAD — scratchpad is nearly empty. Memory loss signal.")
        elif sp_len > 50000:
            checks.append(f"WARNING: BLOATED SCRATCHPAD — {sp_len} chars. Extract durable insights to knowledge base.")
        else:
            checks.append(f"OK: scratchpad size ({sp_len} chars)")
    except Exception:
        pass


def _append_crash_rollback_checks(env: Any, checks: List[str]) -> None:
    try:
        crash_report = env.drive_path("state/crash_report.json")
        if crash_report.exists():
            crash_data = json.loads(crash_report.read_text(encoding="utf-8"))
            checks.append(
                f"CRITICAL: RECENT CRASH ROLLBACK — rolled back from "
                f"{crash_data.get('rolled_back_from', '?')[:12]} to tag "
                f"{crash_data.get('tag', '?')} at {crash_data.get('ts', '?')}"
            )
    except Exception:
        pass


def _append_prompt_runtime_drift_checks(env: Any, checks: List[str]) -> None:
    try:
        from ouroboros.consciousness import BackgroundConsciousness
        consciousness_md = safe_read(env.repo_path("prompts/CONSCIOUSNESS.md"))
        if not consciousness_md:
            return
        whitelist = BackgroundConsciousness._BG_TOOL_WHITELIST
        scan_text = re.sub(r'```.*?```', '', consciousness_md, flags=re.DOTALL)
        tool_prefixes = (
            "schedule_", "update_", "knowledge_", "browse_", "analyze_",
            "web_", "send_", "repo_", "data_", "chat_", "list_", "get_",
            "wait_", "set_", "memory_",
        )
        prompt_tool_refs = set()
        for match in re.finditer(r'\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b', scan_text):
            candidate = match.group(1)
            if candidate in whitelist or any(candidate.startswith(prefix) for prefix in tool_prefixes):
                prompt_tool_refs.add(candidate)
        phantom = prompt_tool_refs - whitelist
        if phantom:
            checks.append(
                f"WARNING: PROMPT-RUNTIME DRIFT — CONSCIOUSNESS.md references "
                f"tools not in BG whitelist: {', '.join(sorted(phantom))}"
            )
        else:
            checks.append("OK: prompt-runtime sync (no phantom tools)")
    except Exception:
        pass


def _scan_injected_message_hashes(path: pathlib.Path, msg_hash_to_tasks: Dict[str, set], type_field: str, type_value: str) -> None:
    if not path.exists():
        return
    import hashlib

    tail_bytes = 256_000
    file_size = path.stat().st_size
    with path.open("r", encoding="utf-8") as f:
        if file_size > tail_bytes:
            f.seek(file_size - tail_bytes)
            f.readline()
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if ev.get(type_field) != type_value:
                continue
            text = ev.get("text", "")
            if not text and "event_repr" in ev:
                event_repr = str(ev.get("event_repr", ""))
                text = (
                    event_repr[:200] + f" [...{len(event_repr) - 200} chars omitted]"
                    if len(event_repr) > 200 else event_repr
                )
            if not text:
                continue
            text_hash = hashlib.md5(text.encode()).hexdigest()[:12]
            tid = ev.get("task_id") or "unknown"
            msg_hash_to_tasks.setdefault(text_hash, set()).add(tid)


def _append_duplicate_processing_checks(env: Any, checks: List[str]) -> None:
    try:
        msg_hash_to_tasks: Dict[str, set] = {}
        _scan_injected_message_hashes(env.drive_path("logs/events.jsonl"), msg_hash_to_tasks, "type", "owner_message_injected")
        _scan_injected_message_hashes(
            env.drive_path("logs/supervisor.jsonl"),
            msg_hash_to_tasks,
            "event_type",
            "owner_message_injected",
        )
        dupes = {h: tids for h, tids in msg_hash_to_tasks.items() if len(tids) > 1}
        if dupes:
            checks.append(
                f"CRITICAL: DUPLICATE PROCESSING — {len(dupes)} message(s) "
                f"appeared in multiple tasks: {', '.join(str(sorted(tids)) for tids in dupes.values())}"
            )
        else:
            checks.append("OK: no duplicate message processing detected")
    except Exception:
        pass


def _append_cache_hit_rate_checks(env: Any, checks: List[str]) -> None:
    try:
        hit_rate = _compute_cache_hit_rate(env)
        if hit_rate is None:
            return
        if hit_rate < 0.30:
            checks.append(
                f"WARNING: LOW CACHE HIT RATE — {hit_rate:.0%} cached. "
                "Context structure may be degrading prompt caching efficiency."
            )
        elif hit_rate >= 0.50:
            checks.append(f"OK: cache hit rate ({hit_rate:.0%})")
        else:
            checks.append(f"INFO: cache hit rate moderate ({hit_rate:.0%})")
    except Exception:
        pass


def _append_provider_routing_health_checks(env: Any, checks: List[str]) -> None:
    try:
        events_path = env.drive_path("logs/events.jsonl")
        if not events_path.exists():
            return
        llm_error_models: Counter = Counter()
        local_overflow_models: Counter = Counter()
        file_size = events_path.stat().st_size
        tail_bytes = 256_000
        with events_path.open("r", encoding="utf-8") as f:
            if file_size > tail_bytes:
                f.seek(file_size - tail_bytes)
                f.readline()
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                evt_type = str(ev.get("type") or "")
                model = str(ev.get("model") or "unknown")
                if evt_type in {"llm_api_error", "review_model_error", "consciousness_llm_error", "provider_incomplete_response"}:
                    llm_error_models[model] += 1
                elif evt_type == "local_context_overflow":
                    local_overflow_models[model] += 1
        if llm_error_models:
            top = ", ".join(f"{model} x{count}" for model, count in llm_error_models.most_common(3))
            checks.append(
                f"WARNING: PROVIDER/ROUTING ERRORS — {sum(llm_error_models.values())} recent failures "
                f"({top}). Reliability or failover may need attention."
            )
        else:
            checks.append("OK: no recent provider/routing errors")
        if local_overflow_models:
            top = ", ".join(f"{model} x{count}" for model, count in local_overflow_models.most_common(3))
            checks.append(
                f"WARNING: LOCAL CONTEXT OVERFLOW — {sum(local_overflow_models.values())} recent overflow event(s) "
                f"({top}). Local context may need more compaction or a larger window."
            )
        else:
            checks.append("OK: no recent local context overflows")
    except Exception:
        pass


def _append_rescue_snapshot_checks(env: Any, checks: List[str]) -> None:
    try:
        import time as _time
        rescue_dir = env.drive_path("archive/rescue")
        if not rescue_dir.exists():
            return
        now = _time.time()
        recent = []
        for entry in sorted(rescue_dir.iterdir(), reverse=True):
            if not entry.is_dir():
                continue
            age_sec = now - entry.stat().st_mtime
            if age_sec < 7200:
                meta_path = entry / "rescue_meta.json"
                file_count = sum(1 for _ in entry.rglob("*") if _.is_file())
                age_str = f"{int(age_sec // 60)}m ago" if age_sec < 3600 else f"{age_sec / 3600:.1f}h ago"
                recent.append(f"{entry.name} ({age_str}, {file_count} files)")
            if len(recent) >= 3:
                break
        if recent:
            checks.append(
                f"WARNING: RESCUE SNAPSHOT AVAILABLE — {', '.join(recent)}. "
                "Uncommitted changes were saved before last restart. "
                "Use data_read to inspect archive/rescue/<dirname>/rescue_meta.json "
                "and changes.diff to decide if recovery is needed."
            )
    except Exception:
        pass


def build_health_invariants(env: Any) -> str:
    """Build health invariants section for LLM-first self-detection.

    Includes crash_report.json / CRASH ROLLBACK detection via helpers.
    """
    checks: List[str] = []
    _append_version_sync_checks(env, checks)
    _append_budget_drift_checks(env, checks)
    _append_task_cost_checks(checks)
    _append_memory_health_checks(env, checks)
    _append_crash_rollback_checks(env, checks)
    _append_prompt_runtime_drift_checks(env, checks)
    _append_duplicate_processing_checks(env, checks)
    _append_cache_hit_rate_checks(env, checks)
    _append_provider_routing_health_checks(env, checks)
    _append_rescue_snapshot_checks(env, checks)
    try:
        _append_file_size_budget_checks(env, checks)
    except Exception:
        pass
    if not checks:
        return ""
    return "## Health Invariants\n\n" + "\n".join(f"- {c}" for c in checks)


def _compute_cache_hit_rate(env: Any) -> Optional[float]:
    """Compute prompt cache hit rate from recent llm_round events."""
    events_path = env.drive_path("logs/events.jsonl")
    if not events_path.exists():
        return None
    total_prompt = total_cached = count = 0
    try:
        file_size = events_path.stat().st_size
        with events_path.open("r", encoding="utf-8") as f:
            if file_size > 256_000:
                f.seek(file_size - 256_000)
                f.readline()
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                    if ev.get("type") != "llm_round":
                        continue
                    usage = ev.get("usage", ev)
                    pt = int(usage.get("prompt_tokens", 0))
                    if pt > 0:
                        total_prompt += pt
                        total_cached += int(usage.get("cached_tokens", 0))
                        count += 1
                except (json.JSONDecodeError, ValueError, TypeError):
                    continue
    except Exception:
        return None
    if count < 5 or total_prompt == 0:
        return None
    return total_cached / total_prompt


def _build_registry_digest(env: Any) -> str:
    """Build a compact one-line-per-source digest from memory/registry.md.

    Returns a markdown table capped at 3000 chars, or empty string if
    the registry doesn't exist.
    """
    reg_path = env.drive_path("memory/registry.md")
    if not reg_path.exists():
        return ""
    try:
        text = reg_path.read_text(encoding="utf-8")
    except Exception:
        return ""

    rows: list = []
    current_id = ""
    fields: dict = {}
    for line in text.split("\n"):
        if line.startswith("### "):
            if current_id:
                rows.append(_registry_row(current_id, fields))
            current_id = line[4:].strip()
            fields = {}
        elif current_id and line.startswith("- **"):
            # Parse "- **Key:** value"
            m = re.match(r'^- \*\*(\w+):\*\*\s*(.*)', line)
            if m:
                fields[m.group(1).lower()] = m.group(2).strip()
    if current_id:
        rows.append(_registry_row(current_id, fields))

    if not rows:
        return ""

    header = "| source | path | updated | gaps |\n|---|---|---|---|"
    table = header + "\n" + "\n".join(rows)
    if len(table) > 3000:
        table = table[:2950] + "\n| ... | (truncated) | | |"
    return "## Memory Registry (what I know / don't know)\n\n" + table


def _registry_row(source_id: str, fields: dict) -> str:
    path = fields.get("path", "?")
    updated = fields.get("updated", "?")
    gaps = fields.get("gaps", "—")
    # Keep gaps short
    if len(gaps) > 60:
        gaps = gaps[:57] + f"... [{len(gaps) - 57} chars omitted]"
    return f"| {source_id} | {path} | {updated} | {gaps} |"


def build_llm_messages(
    env: Any,
    memory: Memory,
    task: Dict[str, Any],
    review_context_builder: Optional[Any] = None,
    soft_cap_tokens: int = 200_000,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Build the full LLM message context for a task.

    Returns (messages, cap_info) tuple.
    """
    task_type = str(task.get("type") or "user")
    base_prompt = safe_read(
        env.repo_path("prompts/SYSTEM.md"),
        fallback="You are Ouroboros. Your base prompt could not be loaded."
    )
    bible_md = safe_read(env.repo_path("BIBLE.md"))
    arch_md = safe_read(env.repo_path("docs/ARCHITECTURE.md"))
    dev_guide_md = safe_read(env.repo_path("docs/DEVELOPMENT.md"))
    readme_md = safe_read(env.repo_path("README.md"))
    checklists_md = safe_read(env.repo_path("docs/CHECKLISTS.md"))
    state_json = safe_read(env.drive_path("state/state.json"), fallback="{}")

    memory.ensure_files()

    static_text = (
        base_prompt + "\n\n"
        + "## BIBLE.md\n\n" + bible_md
    )
    if arch_md.strip():
        static_text += "\n\n## ARCHITECTURE.md\n\n" + arch_md
    if dev_guide_md.strip():
        static_text += "\n\n## DEVELOPMENT.md\n\n" + dev_guide_md
    if readme_md.strip():
        static_text += "\n\n## README.md\n\n" + readme_md
    if checklists_md.strip():
        static_text += "\n\n## CHECKLISTS.md\n\n" + checklists_md

    semi_stable_parts = []
    semi_stable_parts.extend(build_memory_sections(memory))

    kb_index_path = env.drive_path("memory/knowledge/index-full.md")
    if kb_index_path.exists():
        kb_index = kb_index_path.read_text(encoding="utf-8")
        if kb_index.strip():
            semi_stable_parts.append("## Knowledge base\n\n" + kb_index)

    patterns_path = env.drive_path("memory/knowledge/patterns.md")
    try:
        if patterns_path.exists():
            patterns_text = patterns_path.read_text(encoding="utf-8")
            if patterns_text.strip():
                semi_stable_parts.append(
                    "## Known error patterns (Pattern Register)\n\n" + patterns_text
                )
    except Exception:
        pass

    registry_digest = _build_registry_digest(env)
    if registry_digest:
        semi_stable_parts.append(registry_digest)

    semi_stable_text = "\n\n".join(semi_stable_parts)

    health_section = build_health_invariants(env)
    dynamic_parts = []
    if health_section:
        dynamic_parts.append(health_section)
    dynamic_parts.extend([
        "## Drive state\n\n" + state_json,
        build_runtime_section(env, task),
    ])

    dynamic_parts.extend(build_recent_sections(memory, env, task_id=task.get("id", "")))

    if str(task.get("type") or "") == "review" and review_context_builder is not None:
        try:
            review_ctx = review_context_builder()
            if review_ctx:
                dynamic_parts.append(review_ctx)
        except Exception:
            log.debug("Failed to build review context", exc_info=True)
            pass

    # Advisory pre-review status — helps agent see pending findings before committing
    try:
        from ouroboros.review_state import load_state, format_status_section
        advisory_state = load_state(pathlib.Path(env.drive_root))
        if advisory_state.runs:
            advisory_section = format_status_section(advisory_state)
            if advisory_section:
                dynamic_parts.append(advisory_section)
    except Exception:
        log.debug("Failed to build advisory review status section", exc_info=True)

    dynamic_text = "\n\n".join(dynamic_parts)

    messages: List[Dict[str, Any]] = [
        {
            "role": "system",
            "content": [
                {
                    "type": "text",
                    "text": static_text,
                    "cache_control": {"type": "ephemeral", "ttl": "1h"},
                },
                {
                    "type": "text",
                    "text": semi_stable_text,
                    "cache_control": {"type": "ephemeral"},
                },
                {
                    "type": "text",
                    "text": dynamic_text,
                },
            ],
        },
        {"role": "user", "content": build_user_content(task)},
    ]

    messages, cap_info = apply_message_token_soft_cap(messages, soft_cap_tokens)
    return messages, cap_info


def apply_message_token_soft_cap(
    messages: List[Dict[str, Any]],
    soft_cap_tokens: int,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Estimate context size without silently trimming cognitive artifacts."""
    def _estimate_message_tokens(msg: Dict[str, Any]) -> int:
        content = msg.get("content", "")
        if isinstance(content, list):
            total = sum(estimate_tokens(str(b.get("text", "")))
                        for b in content if isinstance(b, dict) and b.get("type") == "text")
            return total + 6
        return estimate_tokens(str(content)) + 6

    estimated = sum(_estimate_message_tokens(m) for m in messages)
    info: Dict[str, Any] = {
        "estimated_tokens_before": estimated,
        "estimated_tokens_after": estimated,
        "soft_cap_tokens": soft_cap_tokens,
        "trimmed_sections": [],
    }
    if soft_cap_tokens > 0 and estimated > soft_cap_tokens:
        info["trimmed_sections"].append("disabled_no_silent_truncation")
    return messages, info


from ouroboros.context_compaction import (
    _COMPACTION_PROTECTED_TOOLS,
    compact_tool_history,
    compact_tool_history_llm,
)


def safe_read(path: pathlib.Path, fallback: str = "") -> str:
    """Read a file, returning fallback if it doesn't exist or errors."""
    try:
        if path.exists():
            return read_text(path)
    except Exception:
        log.debug(f"Failed to read file {path} in safe_read", exc_info=True)
        pass
    return fallback
