"""
Safety Agent — A dual-layer LLM security supervisor.

This module intercepts potentially dangerous tool calls (shell, code edit, git)
and passes them through a light model. If flagged as SUSPICIOUS or DANGEROUS,
it escalates to a heavy model for final judgment.

Returns:
  (True, "")              — SAFE, proceed without comment
  (True, "⚠️ SAFETY_WARNING: ...")  — SUSPICIOUS, proceed but warn the agent
  (False, "⚠️ SAFETY_VIOLATION: ...") — DANGEROUS, blocked
"""

import logging
import json
import os
import pathlib
from typing import Tuple, Dict, Any, List, Optional

from ouroboros.llm import LLMClient, DEFAULT_LIGHT_MODEL
from ouroboros.pricing import emit_llm_usage_event, estimate_cost
from supervisor.state import update_budget_from_usage

log = logging.getLogger(__name__)

CHECKED_TOOLS = frozenset([
    "run_shell", "claude_code_edit", "repo_write", "repo_write_commit", "repo_commit", "data_write",
])

SAFE_SHELL_COMMANDS = frozenset([
    "ls", "cat", "head", "tail", "grep", "rg", "find", "wc",
    "git", "pip", "pytest", "pwd", "whoami",
    "date", "which", "file", "stat", "diff", "tree",
])


def _is_whitelisted(tool_name: str, arguments: Dict[str, Any]) -> bool:
    """Deterministic whitelist — skip LLM check for known-safe operations.

    Safety-critical files are already blocked by the hardcoded sandbox in
    registry.py BEFORE this function is called, so repo_write_commit and
    claude_code_edit can be fully whitelisted here.
    """
    if tool_name in ("data_write",):
        return True

    if tool_name in ("repo_write", "repo_write_commit", "claude_code_edit"):
        return True

    if tool_name == "run_shell":
        raw_cmd = arguments.get("cmd", arguments.get("command", ""))
        if isinstance(raw_cmd, list):
            cmd_str = " ".join(str(x) for x in raw_cmd)
        else:
            cmd_str = str(raw_cmd)
        first_word = cmd_str.strip().split()[0] if cmd_str.strip() else ""
        return first_word in SAFE_SHELL_COMMANDS

    return False


def _get_safety_prompt() -> str:
    """Load the safety system prompt from prompts/SAFETY.md."""
    prompt_path = pathlib.Path(__file__).parent.parent / "prompts" / "SAFETY.md"
    try:
        return prompt_path.read_text(encoding="utf-8")
    except Exception as e:
        log.error(f"Failed to read SAFETY.md: {e}")
        return (
            "You are a security supervisor. Block only clearly destructive commands. "
            "Default to SAFE. Respond with JSON: "
            '{\"status\": \"SAFE\"|\"SUSPICIOUS\"|\"DANGEROUS\", \"reason\": \"...\"}'
        )


def _format_messages_for_safety(messages: List[Dict[str, Any]]) -> str:
    """Format conversation messages into a compact context string for the safety LLM."""
    parts = []
    for m in messages:
        role = m.get("role", "?")
        content = m.get("content", "")
        if not content or role == "tool":
            continue
        if isinstance(content, list):
            content = " ".join(
                b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
            )
        text = str(content)
        if len(text) > 500:
            omitted = len(text) - 500
            text = text[:500] + f" [...{omitted} chars omitted]"
        parts.append(f"[{role}] {text}")
    return "\n".join(parts)


def _build_check_prompt(
    tool_name: str,
    arguments: Dict[str, Any],
    messages: Optional[List[Dict[str, Any]]] = None,
) -> str:
    args_json = json.dumps(arguments, indent=2)
    prompt = f"Proposed tool call:\nTool: {tool_name}\nArguments:\n```json\n{args_json}\n```\n"
    if messages:
        context = _format_messages_for_safety(messages)
        if context.strip():
            prompt += f"\nConversation context:\n{context}\n"
    prompt += "\nIs this safe?"
    return prompt


def _parse_safety_response(text: str) -> Optional[Dict[str, Any]]:
    """Parse JSON from LLM response, handling markdown code fences."""
    clean = text.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        return None


def _is_emergency_safe(tool_name: str, arguments: Dict[str, Any]) -> bool:
    """Emergency fallback whitelist when safety LLM is unreachable.
    
    Allows critical read-only and recovery operations to proceed when both
    safety checks fail. This prevents system deadlock when the safety model
    is down.
    """
    # Read-only operations are always safe
    if tool_name in ("repo_read", "data_read", "knowledge_read"):
        return True
    
    # Git status/diff are read-only
    if tool_name == "run_shell":
        raw_cmd = arguments.get("cmd", arguments.get("command", ""))
        if isinstance(raw_cmd, list):
            cmd_str = " ".join(str(x) for x in raw_cmd)
        else:
            cmd_str = str(raw_cmd)
        
        # Allow read-only git commands
        if cmd_str.strip().startswith(("git status", "git diff", "git log", "git show")):
            return True
        
        # Allow basic diagnostics
        if cmd_str.strip().split()[0] in ("echo", "pwd", "whoami", "date", "which"):
            return True
    
    return False


def check_safety(
    tool_name: str,
    arguments: Dict[str, Any],
    messages: Optional[List[Dict[str, Any]]] = None,
    ctx: Optional[Any] = None,
) -> Tuple[bool, str]:
    """Check if a tool call is safe to execute.

    Returns:
      (True, "")           — SAFE
      (True, warning_str)  — SUSPICIOUS (proceed, but warning is passed to agent)
      (False, error_str)   — DANGEROUS (blocked)
    """
    if tool_name not in CHECKED_TOOLS:
        return True, ""

    if _is_whitelisted(tool_name, arguments):
        return True, ""

    prompt = _build_check_prompt(tool_name, arguments, messages)
    client = LLMClient()

    # ── Layer 1: Fast check (light model) ──
    fast_status = None
    fast_reason = None
    _use_local_light = os.environ.get("USE_LOCAL_LIGHT", "").lower() in ("true", "1")
    try:
        light_model = os.environ.get("OUROBOROS_MODEL_LIGHT", DEFAULT_LIGHT_MODEL)
        log.info(f"Running fast safety check on {tool_name} using {light_model} (local={_use_local_light})")
        msg, usage = client.chat(
            messages=[
                {"role": "system", "content": _get_safety_prompt()},
                {"role": "user", "content": prompt},
            ],
            model=light_model,
            use_local=_use_local_light,
        )
        if usage:
            model_name = f"{light_model} (local)" if _use_local_light else light_model
            cost = float(usage.get("cost") or 0.0)
            if not _use_local_light and cost == 0.0:
                cost = estimate_cost(
                    light_model,
                    int(usage.get("prompt_tokens") or 0),
                    int(usage.get("completion_tokens") or 0),
                    int(usage.get("cached_tokens") or 0),
                    int(usage.get("cache_write_tokens") or 0),
                )
            _eq = getattr(ctx, "event_queue", None) if ctx is not None else None
            if _eq is not None:
                emit_llm_usage_event(
                    _eq,
                    getattr(ctx, "task_id", "") if ctx is not None else "",
                    model_name, usage, cost,
                    category="safety",
                    provider="local" if _use_local_light else "openrouter",
                    source="safety_light",
                )
            else:
                update_budget_from_usage(usage)

        result = _parse_safety_response(msg.get("content") or "")
        if result:
            fast_status = result.get("status", "").upper()
            fast_reason = result.get("reason", "")

        if fast_status == "SAFE":
            return True, ""

        log.warning(f"Fast safety check flagged {tool_name} as {fast_status}: {fast_reason}")

    except Exception as e:
        log.error(f"Fast safety check failed: {e}. Escalating to deep check.")
        fast_reason = str(e)
        
        # If fast check failed and this is emergency-safe, skip deep check
        if _is_emergency_safe(tool_name, arguments):
            log.warning(f"Fast check failed but {tool_name} is emergency-safe, allowing")
            return True, (
                f"⚠️ SAFETY_WARNING: Fast safety check failed (LLM unreachable), but this operation "
                f"is on the emergency whitelist (read-only/diagnostic). Proceeding with caution.\n"
                f"Error: {e}"
            )

    # ── Layer 2: Deep check (heavy model, with nudge to reduce false positives) ──
    _use_local_code = os.environ.get("USE_LOCAL_CODE", "").lower() in ("true", "1")
    try:
        heavy_model = os.environ.get(
            "OUROBOROS_MODEL_CODE",
            os.environ.get("OUROBOROS_MODEL", "anthropic/claude-opus-4.6"),
        )
        log.info(f"Running deep safety check on {tool_name} using {heavy_model} (local={_use_local_code})")
        deep_system = (
            _get_safety_prompt()
            + "\nThink carefully. Is this actually malicious, or just a normal development command? "
            "The fast check flagged it — you are the final judge."
        )
        msg, usage = client.chat(
            messages=[
                {"role": "system", "content": deep_system},
                {"role": "user", "content": prompt},
            ],
            model=heavy_model,
            use_local=_use_local_code,
        )
        if usage:
            model_name = f"{heavy_model} (local)" if _use_local_code else heavy_model
            cost = float(usage.get("cost") or 0.0)
            if not _use_local_code and cost == 0.0:
                cost = estimate_cost(
                    heavy_model,
                    int(usage.get("prompt_tokens") or 0),
                    int(usage.get("completion_tokens") or 0),
                    int(usage.get("cached_tokens") or 0),
                    int(usage.get("cache_write_tokens") or 0),
                )
            _eq = getattr(ctx, "event_queue", None) if ctx is not None else None
            if _eq is not None:
                emit_llm_usage_event(
                    _eq,
                    getattr(ctx, "task_id", "") if ctx is not None else "",
                    model_name, usage, cost,
                    category="safety",
                    provider="local" if _use_local_code else "openrouter",
                    source="safety_deep",
                )
            else:
                update_budget_from_usage(usage)

        result = _parse_safety_response(msg.get("content") or "")
        if result is None:
            log.error(f"Deep safety check returned invalid JSON: {msg.get('content')}")
            return False, "⚠️ SAFETY_VIOLATION: Safety Supervisor returned unparseable response."

        deep_status = result.get("status", "").upper()
        deep_reason = result.get("reason", "Unknown")

        if deep_status == "SAFE":
            log.info(f"Deep check cleared {tool_name}. Proceeding.")
            return True, ""

        if deep_status == "SUSPICIOUS":
            log.warning(f"Deep check: {tool_name} is suspicious: {deep_reason}")
            return True, (
                f"⚠️ SAFETY_WARNING: The Safety Supervisor flagged this action as suspicious.\n"
                f"Reason: {deep_reason}\n"
                f"The command was allowed, but consider whether this is the right approach."
            )

        # DANGEROUS (or any unrecognised status — fail safe)
        log.error(f"Deep safety check blocked {tool_name}: {deep_reason}")
        return False, (
            f"⚠️ SAFETY_VIOLATION: The Safety Supervisor blocked this command.\n"
            f"Reason: {deep_reason}\n\n"
            f"You must find a different, safer approach to achieve your goal."
        )

    except Exception as e:
        log.error(f"Deep safety check failed: {e}")
        
        # Emergency fallback: if both safety checks failed and this is a
        # critical read-only operation, allow it with a warning
        if _is_emergency_safe(tool_name, arguments):
            log.warning(f"Emergency fallback: allowing {tool_name} (safety LLM unreachable)")
            return True, (
                f"⚠️ SAFETY_WARNING: Safety checks failed (LLM unreachable), but this operation "
                f"is on the emergency whitelist (read-only/diagnostic). Proceeding with caution.\n"
                f"Error: {e}"
            )
        
        return False, f"⚠️ SAFETY_VIOLATION: Safety check failed with error: {e}"
