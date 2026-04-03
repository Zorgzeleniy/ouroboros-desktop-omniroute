"""Multi-model review — sends code/text to multiple LLMs for consensus review.

Also contains the unified pre-commit review gate: three models review staged
diffs against docs/CHECKLISTS.md before any repo_commit. Review always runs
before commit; enforcement is configurable between blocking and advisory.

BIBLE.md is automatically injected as constitutional context with top priority.
"""

import os
import json
import asyncio
import logging
import pathlib
from typing import List, Optional

from ouroboros.llm import LLMClient
from ouroboros.utils import utc_now_iso, run_cmd, append_jsonl
from ouroboros import config as _cfg
from ouroboros.tools.registry import ToolEntry, ToolContext

log = logging.getLogger(__name__)

MAX_MODELS = 10
CONCURRENCY_LIMIT = 5

_CONSTITUTIONAL_PREAMBLE = """\
## CONSTITUTIONAL CONTEXT — TOP PRIORITY

You are reviewing code for Ouroboros, a self-creating AI agent. The following
is its Constitution (BIBLE.md). **All recommendations you make MUST comply
with these principles.** If a potential improvement would violate any
principle, do NOT recommend it — flag the conflict instead.

Key principles to watch for:
- **P3 (LLM-First):** All decisions through the LLM. No hardcoded logic
  for behavior selection. If behavior can be described in a prompt, it goes
  in a prompt, not in code.
- **P5 (Minimalism):** Complexity is the enemy. Every line justifies its existence.
- **P0 (Agency):** Ouroboros is not a tool but a becoming personality.
- **P1 (Continuity):** BIBLE.md and identity.md are protected.
- **P2 (Self-Creation):** Fix the class, not the instance.

If you are unsure whether a recommendation complies with the Constitution,
err on the side of NOT recommending it and explain the tension.

---

"""


_CHECKLISTS_PATH = pathlib.Path(__file__).resolve().parent.parent.parent / "docs" / "CHECKLISTS.md"


def _load_bible() -> str:
    candidates = [
        pathlib.Path(__file__).resolve().parent.parent.parent / "BIBLE.md",
        pathlib.Path.cwd() / "BIBLE.md",
        pathlib.Path(os.environ.get("OUROBOROS_REPO_DIR", "")) / "BIBLE.md",
    ]
    for p in candidates:
        try:
            if p.is_file():
                return p.read_text(encoding="utf-8")
        except Exception:
            continue
    log.warning("BIBLE.md not found for review context")
    return ""


# ---------------------------------------------------------------------------
# Tool: multi_model_review (agent-callable)
# ---------------------------------------------------------------------------

def get_tools():
    return [
        ToolEntry(
            name="multi_model_review",
            schema={
                "name": "multi_model_review",
                "description": (
                    "Send code or text to multiple LLM models for review/consensus. "
                    "Each model reviews independently. Returns structured verdicts. "
                    "Choose diverse models yourself. Budget is tracked automatically. "
                    "BIBLE.md (Constitution) is automatically included as top-priority context."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "The code or text to review"},
                        "prompt": {"type": "string", "description": "Review instructions — what to check for."},
                        "models": {
                            "type": "array", "items": {"type": "string"},
                            "description": "OpenRouter model identifiers (e.g. 3 diverse models)",
                        },
                    },
                    "required": ["content", "prompt", "models"],
                },
            },
            handler=_handle_multi_model_review,
        )
    ]


def _handle_multi_model_review(ctx: ToolContext, content: str = "",
                                prompt: str = "", models: list = None) -> str:
    if models is None:
        models = []
    try:
        try:
            asyncio.get_running_loop()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                result = pool.submit(
                    asyncio.run,
                    _multi_model_review_async(content, prompt, models, ctx),
                ).result()
        except RuntimeError:
            result = asyncio.run(_multi_model_review_async(content, prompt, models, ctx))
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        log.error("Multi-model review failed: %s", e, exc_info=True)
        return json.dumps({"error": f"Review failed: {e}"}, ensure_ascii=False)


async def _query_model(llm_client: LLMClient, model: str, messages: list, semaphore):
    async with semaphore:
        try:
            msg, usage = await llm_client.chat_async(
                messages=messages,
                model=model,
                reasoning_effort="low",
                max_tokens=4096,
                temperature=0.2,
            )
            payload = {
                "choices": [{"message": {"content": msg.get("content") or ""}}],
                "usage": usage or {},
            }
            return model, payload, None
        except asyncio.TimeoutError:
            return model, "Error: Timeout after 120s", None
        except Exception as e:
            error_msg = str(e)[:200]
            return model, f"Error: {error_msg}", None


async def _multi_model_review_async(content: str, prompt: str,
                                     models: list, ctx: ToolContext):
    if not content:
        return {"error": "content is required"}
    if not prompt:
        return {"error": "prompt is required"}
    if not models:
        return {"error": "models list is required"}
    if not isinstance(models, list) or not all(isinstance(m, str) for m in models):
        return {"error": "models must be a list of strings"}
    if len(models) > MAX_MODELS:
        return {"error": f"Too many models ({len(models)}). Maximum is {MAX_MODELS}."}

    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        return {"error": "OPENROUTER_API_KEY not set"}

    bible_text = _load_bible()
    if bible_text:
        system_content = (
            _CONSTITUTIONAL_PREAMBLE
            + "### BIBLE.md (Full Text)\n\n" + bible_text
            + "\n\n---\n\n## REVIEW INSTRUCTIONS\n\n" + prompt
        )
    else:
        log.warning("Proceeding without BIBLE.md — constitutional compliance cannot be guaranteed")
        system_content = (
            _CONSTITUTIONAL_PREAMBLE
            + "(BIBLE.md could not be loaded)\n\n## REVIEW INSTRUCTIONS\n\n" + prompt
        )

    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": content},
    ]

    semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
    llm_client = LLMClient(api_key=api_key)
    tasks = [_query_model(llm_client, m, messages, semaphore) for m in models]
    results = await asyncio.gather(*tasks)

    review_results = []
    for model, result, headers_dict in results:
        review_result = _parse_model_response(model, result, headers_dict)
        _emit_usage_event(review_result, ctx)
        review_results.append(review_result)

    return {
        "model_count": len(models),
        "constitutional_context": bool(bible_text),
        "results": review_results,
    }


def _parse_model_response(model: str, result, headers_dict) -> dict:
    if isinstance(result, str):
        return {
            "model": model, "verdict": "ERROR", "text": result,
            "tokens_in": 0, "tokens_out": 0, "cost_estimate": 0.0,
        }
    try:
        choices = result.get("choices", [])
        if not choices:
            text = f"(no choices in response: {json.dumps(result)[:200]})"
            verdict = "ERROR"
        else:
            text = choices[0]["message"]["content"]
            verdict = "UNKNOWN"
            for line in text.split("\n")[:3]:
                line_upper = line.upper()
                if "PASS" in line_upper:
                    verdict = "PASS"
                    break
                elif "CONCERNS" in line_upper:
                    verdict = "CONCERNS"
                    break
                elif "FAIL" in line_upper:
                    verdict = "FAIL"
                    break
    except (KeyError, IndexError, TypeError):
        text = f"(unexpected response format: {json.dumps(result)[:200]})"
        verdict = "ERROR"

    usage = result.get("usage", {})
    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)
    cached_tokens = usage.get("cached_tokens", 0)
    cache_write_tokens = usage.get("cache_write_tokens", 0)

    cost = 0.0
    try:
        if "cost" in usage:
            cost = float(usage["cost"])
        elif "total_cost" in usage:
            cost = float(usage["total_cost"])
        elif headers_dict:
            for key, value in headers_dict.items():
                if key.lower() == "x-openrouter-cost":
                    cost = float(value)
                    break
    except (ValueError, TypeError, KeyError):
        pass

    return {
        "model": model, "verdict": verdict, "text": text,
        "tokens_in": prompt_tokens, "tokens_out": completion_tokens,
        "cached_tokens": cached_tokens, "cache_write_tokens": cache_write_tokens,
        "cost_estimate": cost,
    }


def _emit_usage_event(review_result: dict, ctx: ToolContext) -> None:
    if ctx is None:
        return
    usage_event = {
        "type": "llm_usage", "ts": utc_now_iso(),
        "task_id": ctx.task_id if ctx.task_id else "",
        "model": review_result.get("model", ""),
        "usage": {
            "prompt_tokens": review_result["tokens_in"],
            "completion_tokens": review_result["tokens_out"],
            "cached_tokens": review_result.get("cached_tokens", 0),
            "cache_write_tokens": review_result.get("cache_write_tokens", 0),
            "cost": review_result["cost_estimate"],
        },
        "provider": "openrouter",
        "source": "review",
        "category": "review",
    }
    if ctx.event_queue is not None:
        try:
            ctx.event_queue.put_nowait(usage_event)
        except Exception:
            if hasattr(ctx, "pending_events"):
                ctx.pending_events.append(usage_event)
    elif hasattr(ctx, "pending_events"):
        ctx.pending_events.append(usage_event)


# ---------------------------------------------------------------------------
# Unified pre-commit review gate — used by git.py commit tools
# ---------------------------------------------------------------------------

def _load_checklist_section() -> str:
    """Load the Repo Commit Checklist from docs/CHECKLISTS.md (DRY, Bible P5).

    Raises FileNotFoundError or ValueError if missing or malformed — fail-closed.
    """
    try:
        text = _CHECKLISTS_PATH.read_text(encoding="utf-8")
    except Exception as e:
        raise FileNotFoundError(
            f"docs/CHECKLISTS.md not found at {_CHECKLISTS_PATH}: {e}"
        ) from e
    marker = "## Repo Commit Checklist"
    start = text.find(marker)
    if start == -1:
        raise ValueError(
            f"Section '{marker}' not found in docs/CHECKLISTS.md — "
            "file may be corrupted or reformatted"
        )
    return text[start:].strip()


_REVIEW_PREAMBLE = (
    "You are a pre-commit reviewer for Ouroboros, a self-modifying AI agent.\n"
    "Its Constitution is BIBLE.md. Its engineering handbook is DEVELOPMENT.md.\n"
)

_REVIEW_PROMPT_TEMPLATE = """\
{preamble}
You must review the staged diff and produce a JSON array.  Each element has
keys: "item", "verdict" (PASS or FAIL), "severity" (critical or advisory),
and "reason" (one-line explanation).

{checklist_section}

- Output ONLY a valid JSON array.  No markdown fences, no text outside the JSON.

## DEVELOPMENT.md

{dev_guide_text}

## Commit message

{commit_message}
{rebuttal_section}{review_history_section}
## Staged diff

{diff_text}

## Changed files

{changed_files}
"""


def _parse_review_json(raw: str) -> Optional[list]:
    """Best-effort extraction of a JSON array from model output."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, list):
            return obj
    except (json.JSONDecodeError, ValueError):
        pass
    start, end = text.find("["), text.rfind("]")
    if start != -1 and end > start:
        try:
            obj = json.loads(text[start:end + 1])
            if isinstance(obj, list):
                return obj
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def _preflight_check(commit_message: str, staged_files: str,
                     repo_dir) -> Optional[str]:
    """Deterministic pre-review sanity check — catches common mismatches
    before calling expensive LLM reviewers.
    """
    import re
    staged_set = set(f.strip() for f in staged_files.strip().splitlines() if f.strip())
    msg_lower = commit_message.lower()

    has_version_ref = bool(re.search(r'v?\d+\.\d+\.\d+', commit_message)) or "version" in msg_lower
    version_staged = "VERSION" in staged_set

    missing = []
    if has_version_ref and not version_staged:
        if any(f.endswith(('.py', '.md')) and f != 'VERSION' for f in staged_set):
            missing.append("VERSION")
    if version_staged and "README.md" not in staged_set:
        missing.append("README.md (badge + changelog)")

    if not missing:
        return None

    return (
        f"⚠️ PREFLIGHT_BLOCKED: Staged diff is incomplete — fix before review.\n"
        f"  Missing from staged: {', '.join(missing)}\n"
        f"  Currently staged: {', '.join(sorted(staged_set)) or '(none)'}\n\n"
        "Stage all related files together. Use repo_write for all files first,\n"
        "then repo_commit to stage and commit everything in one diff."
    )


def _build_review_history_section(history: list) -> str:
    if not history:
        return ""
    lines = ["## Previous review rounds\n"]
    for entry in history:
        lines.append(f"### Round {entry['attempt']}")
        lines.append(f"Commit message: \"{entry['commit_message']}\"")
        if entry.get("critical"):
            lines.append("CRITICAL findings:")
            for f in entry["critical"]:
                lines.append(f"- {f}")
        if entry.get("advisory"):
            lines.append("Advisory findings:")
            for f in entry["advisory"]:
                lines.append(f"- {f}")
        lines.append("")
    lines.append(
        "IMPORTANT: Focus on verifying whether previous CRITICAL findings "
        "were addressed. Do NOT rephrase previous findings as new ones. "
        "If a previous CRITICAL was fixed, verdict it PASS.\n"
    )
    return "\n".join(lines)


def _single_line(text: str) -> str:
    return " ".join(str(text or "").split())


def _append_review_warning(ctx: ToolContext, text: str) -> None:
    warning = _single_line(text)
    if warning:
        ctx._review_advisory.append(warning)


def _handle_review_block_or_warning(
    ctx: ToolContext,
    blocking_review: bool,
    blocked_msg: str,
    advisory_prefix: str,
) -> Optional[str]:
    """Either block immediately or downgrade to advisory warning."""
    if blocking_review:
        return blocked_msg
    _append_review_warning(ctx, advisory_prefix + blocked_msg)
    ctx._review_iteration_count = 0
    ctx._review_history = []
    return None


def _build_rebuttal_section(review_rebuttal: str) -> str:
    if not review_rebuttal:
        return ""
    return (
        "\n## Developer's rebuttal to previous review feedback\n\n"
        f"{review_rebuttal}\n\n"
        "Reconsider previous FAIL verdict(s) in light of this argument. "
        "If the argument is valid, change your verdict to PASS. "
        "If not, maintain FAIL and explain why.\n"
    )


def _load_dev_guide_text(repo_dir: pathlib.Path) -> str:
    dev_guide_path = repo_dir / "docs" / "DEVELOPMENT.md"
    try:
        if dev_guide_path.exists():
            return dev_guide_path.read_text(encoding="utf-8")
    except Exception:
        pass
    return ""


def _collect_review_findings(ctx: ToolContext, model_results: list) -> tuple[list[str], list[str], list[str]]:
    critical_fails: List[str] = []
    advisory_warns: List[str] = []
    errored_models: List[str] = []

    for mr in model_results:
        model_name = mr.get("model", "?")
        raw_text = str(mr.get("text", ""))
        verdict_upper = str(mr.get("verdict", "")).upper()

        if verdict_upper == "ERROR":
            errored_models.append(model_name)
            advisory_warns.append(
                f"[{model_name}] Model unavailable this round: {raw_text[:200]}"
            )
            try:
                append_jsonl(ctx.drive_logs() / "events.jsonl", {
                    "ts": utc_now_iso(), "type": "review_model_error",
                    "model": model_name, "error_preview": raw_text[:200],
                })
            except Exception:
                pass
            continue

        items = _parse_review_json(raw_text)
        if items is None:
            critical_fails.append(
                f"[{model_name}] Could not parse structured review output. "
                f"Raw preview: {raw_text[:300]}"
            )
            continue

        for item in items:
            if not isinstance(item, dict):
                continue
            item_verdict = str(item.get("verdict", "")).upper()
            severity = str(item.get("severity", "advisory")).lower()
            item_name = item.get("item", "?")
            reason = item.get("reason", "")
            if item_verdict != "FAIL":
                continue
            desc = f"[{model_name}] {item_name}: {reason}"
            if severity == "critical":
                critical_fails.append(desc)
            else:
                advisory_warns.append(desc)

    return critical_fails, advisory_warns, errored_models


def _build_critical_block_message(
    ctx: ToolContext,
    commit_message: str,
    critical_fails: List[str],
    advisory_warns: List[str],
    errored_note: str,
) -> str:
    ctx._review_history.append({
        "attempt": ctx._review_iteration_count,
        "commit_message": commit_message[:200],
        "critical": list(critical_fails),
        "advisory": list(advisory_warns),
    })

    iteration_note = f" (attempt {ctx._review_iteration_count})"

    soft_hint = ""
    if ctx._review_iteration_count >= 5:
        soft_hint = (
            "\n\nHint: You have attempted this commit 5+ times. Consider:\n"
            "- Breaking the change into smaller, independently reviewable commits\n"
            "- Using review_rebuttal to address specific reviewer concerns"
        )

    return (
        f"⚠️ REVIEW_BLOCKED{iteration_note}: Critical issues found by reviewers.\n"
        "Commit has NOT been created. Fix the issues and try again, or include a\n"
        "review_rebuttal argument explaining why you disagree.\n\n"
        + "\n".join(f"  CRITICAL: {f}" for f in critical_fails)
        + (
            "\n\nAdvisory warnings:\n"
            + "\n".join(f"  WARN: {w}" for w in advisory_warns)
            if advisory_warns else ""
        )
        + errored_note
        + soft_hint
    )


def _run_unified_review(ctx: ToolContext, commit_message: str,
                        review_rebuttal: str = "",
                        repo_dir=None) -> Optional[str]:
    """Unified pre-commit review: 3 models, structured JSON, consistent severity.

    Returns None if commit may proceed. In blocking mode returns a blocking
    error string when review rejects the commit.
    """
    target_repo = repo_dir or ctx.repo_dir
    ctx._review_iteration_count += 1
    review_enforcement = _cfg.get_review_enforcement()
    blocking_review = review_enforcement == "blocking"

    try:
        diff_text = run_cmd(["git", "diff", "--cached"], cwd=target_repo)
    except Exception:
        diff_text = "(failed to get staged diff)"

    if not diff_text.strip():
        return None

    try:
        changed = run_cmd(["git", "diff", "--cached", "--name-only"], cwd=target_repo)
    except Exception:
        changed = ""

    preflight_err = _preflight_check(commit_message, changed, target_repo)
    if preflight_err:
        result = _handle_review_block_or_warning(
            ctx, blocking_review, preflight_err,
            "Review enforcement=Advisory: preflight warning did not block commit. ",
        )
        if result is not None:
            return result

    rebuttal_section = _build_rebuttal_section(review_rebuttal)

    try:
        checklist_section = _load_checklist_section()
    except (FileNotFoundError, ValueError) as e:
        log.error("Checklist loading failed (fail-closed): %s", e)
        blocked_msg = (
            "⚠️ REVIEW_BLOCKED: Cannot load review checklist — commit cannot proceed.\n"
            f"Error: {e}\n"
            "Ensure docs/CHECKLISTS.md exists and contains the expected section headers."
        )
        return _handle_review_block_or_warning(
            ctx, blocking_review, blocked_msg,
            "Review enforcement=Advisory: review checklist failed to load; commit proceeding anyway. ",
        )

    dev_guide_text = _load_dev_guide_text(pathlib.Path(ctx.repo_dir))

    review_history_section = _build_review_history_section(ctx._review_history)

    prompt = _REVIEW_PROMPT_TEMPLATE.format(
        preamble=_REVIEW_PREAMBLE,
        checklist_section=checklist_section,
        dev_guide_text=dev_guide_text or "(DEVELOPMENT.md not found)",
        commit_message=commit_message[:500],
        rebuttal_section=rebuttal_section,
        review_history_section=review_history_section,
        diff_text=diff_text,
        changed_files=changed,
    )

    models = _cfg.get_review_models()

    try:
        result_json = _handle_multi_model_review(
            ctx,
            content="Review the staged diff and context provided in the instructions above.",
            prompt=prompt,
            models=models,
        )
        result = json.loads(result_json)
    except Exception as e:
        log.error("Unified review infrastructure failure: %s", e)
        blocked_msg = (
            "⚠️ REVIEW_BLOCKED: Review infrastructure failed — commit cannot proceed "
            "without a successful review.\n"
            f"Error: {e}\n"
            "Check OPENROUTER_API_KEY, network connectivity, and retry."
        )
        return _handle_review_block_or_warning(
            ctx, blocking_review, blocked_msg,
            "Review enforcement=Advisory: review infrastructure failure did not block commit. ",
        )

    if "error" in result:
        log.error("Review returned error: %s", result["error"])
        blocked_msg = (
            "⚠️ REVIEW_BLOCKED: Review service returned an error — commit cannot proceed "
            "without a successful review.\n"
            f"Error: {result['error']}\n"
            "Check OPENROUTER_API_KEY, network connectivity, and retry."
        )
        return _handle_review_block_or_warning(
            ctx, blocking_review, blocked_msg,
            "Review enforcement=Advisory: review service error did not block commit. ",
        )

    model_results = result.get("results", [])
    if not model_results:
        blocked_msg = (
            "⚠️ REVIEW_BLOCKED: Review returned no results from any model — "
            "commit cannot proceed without a successful review."
        )
        return _handle_review_block_or_warning(
            ctx, blocking_review, blocked_msg,
            "Review enforcement=Advisory: review returned no model results; commit proceeding anyway. ",
        )

    critical_fails, advisory_warns, errored_models = _collect_review_findings(ctx, model_results)

    models_total = len(model_results)

    # Quorum: at least 2 of N reviewers must succeed
    successful_reviewers = models_total - len(errored_models)
    if successful_reviewers < 2:
        blocked_msg = (
            f"⚠️ REVIEW_BLOCKED: Only {successful_reviewers} of {models_total} review "
            f"models responded successfully (minimum 2 required). "
            f"Unavailable: {', '.join(errored_models)}.\n"
            "Retry the commit — transient model failures usually resolve quickly."
        )
        return _handle_review_block_or_warning(
            ctx, blocking_review, blocked_msg,
            "Review enforcement=Advisory: review quorum failure did not block commit. ",
        )

    errored_note = ""
    if errored_models:
        errored_note = (
            f"\n\nNote: {len(errored_models)} of {models_total} review models "
            f"were unavailable ({', '.join(errored_models)}). "
            "Target is 3 working reviewers."
        )

    if critical_fails:
        if blocking_review:
            return _build_critical_block_message(
                ctx, commit_message, critical_fails, advisory_warns, errored_note,
            )

        _append_review_warning(
            ctx,
            "Review enforcement=Advisory: critical review findings did not block commit.",
        )
        for finding in critical_fails:
            _append_review_warning(ctx, f"CRITICAL (advisory mode): {finding}")
        for warning in advisory_warns:
            _append_review_warning(ctx, f"WARN: {warning}")
        if errored_note:
            _append_review_warning(ctx, errored_note)

    # All clear — reset iteration state
    ctx._review_iteration_count = 0
    ctx._review_history = []

    if errored_note:
        advisory_warns.append(errored_note.strip())
    if advisory_warns:
        ctx._review_advisory = advisory_warns
    return None
