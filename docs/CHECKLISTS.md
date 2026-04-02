# Pre-Commit Review Checklists

Single source of truth for all automated review checklists (Bible P5: DRY).
Loaded by `ouroboros/tools/review.py` at review time and injected into the
multi-model review prompt.

When a new reviewable concern appears, add it here — not in prompts or docs.

### Review-exempt operations

The following tools create commits but are **exempt** from multi-model review
(Bible P8 explicit exception):

- `restore_to_head` — discards uncommitted changes (not a commit, no review needed)
- `revert_commit` — creates a mechanical inverse of an already-reviewed commit

Rationale: review gates on rollbacks create a paradox where reviewers block
the undo for missing tests/VERSION, trapping the agent with broken code.
These tools restore to already-reviewed states by definition.

---

## Repo Commit Checklist

Used by `repo_commit` and `repo_write_commit` for all changes to the
Ouroboros repository.

| # | item | what to check | severity when FAIL |
|---|------|---------------|--------------------|
| 1 | bible_compliance | Does the diff violate any BIBLE.md principle? | critical |
| 2 | development_compliance | Does it follow DEVELOPMENT.md patterns (naming, entity types, module structure)? | critical |
| 3 | secrets_check | Are secrets, API keys, .env files, credentials present in the diff? | critical |
| 4 | code_quality | Careful code review: bugs, logic errors, crashes, regressions, race conditions, resource leaks? | critical |
| 5 | security_issues | Security vulnerabilities: injection, path traversal, secret leakage, unsafe operations? | critical |
| 6 | tests_affected | Did code logic change without corresponding test changes? (PASS if only docs/config/memory changed, or if tests are present.) | critical |
| 7 | architecture_doc | New module, endpoint, or data flow added but ARCHITECTURE.md not updated? (Write "Not applicable" with PASS if no architectural change.) | critical |
| 8 | version_bump | Behavior changed but VERSION not updated? (PASS if no behavior change.) | critical |
| 9 | changelog_and_badge | VERSION bumped but README.md badge or changelog not updated? (PASS if VERSION not bumped.) | critical |
| 10 | tool_registration | New tool function added but not exported in get_tools()? (PASS if no new tool.) | critical |
| 11 | context_building | New data/memory files that should appear in LLM context (context.py) but don't? | advisory |
| 12 | knowledge_index | Knowledge base topics changed but memory/knowledge/index-full.md not updated? | advisory |
| 13 | self_consistency | Does this change affect behavior described in `BIBLE.md`, `prompts/`, `docs/`, or this checklist itself? Are all descriptions still accurate? **Includes**: version in `ARCHITECTURE.md` header matching `VERSION` file. | advisory |

### Severity rules

- Items 1-5 are always critical.
- Items 6-10 are conditionally critical: FAIL only when the condition applies.
  If the condition does not apply, write verdict PASS with a short reason
  (e.g. "Not applicable — no code logic change").
- Items 11-13 are advisory: FAIL produces a warning but does not block.

---

## Intent / Scope Review Checklist

Used by the supplemental blocking scope reviewer.
This reviewer checks completeness and forgotten touchpoints using richer context
than the diff-only triad.

| # | item | what to check | severity when FAIL |
|---|------|---------------|--------------------|
| 1 | intent_alignment | Does the staged change actually fulfill the intended transformation, not merely touch related files? | critical if the incompleteness is concrete and evidenced; otherwise advisory |
| 2 | forgotten_touchpoints | Are there specific coupled files, tests, prompts, docs, configs, or sibling paths that must also change? Name the exact file(s) or symbol(s). | critical if a required touchpoint is concretely omitted; otherwise advisory |
| 3 | cross_surface_consistency | If behavior changed, are adjacent surfaces still consistent: prompts, docs, comments, tool descriptions, automation, or user-visible workflow? | critical if a concrete stale surface leaves the repo internally inconsistent; otherwise advisory |
| 4 | regression_surface | Does wider repository context show a concrete sibling path, migration edge, or parallel flow that remains broken or incomplete after this change? | critical if it leaves a concrete broken/incomplete path; otherwise advisory |
| 5 | prompt_doc_sync | If prompts or docs are relevant to the changed behavior, are they still accurate and mutually consistent? | critical if a concrete prompt/doc artifact becomes false or stale; otherwise advisory |
| 6 | architecture_fit | Does the change solve the class of problem, or is it a narrow patch that leaves the underlying pattern unresolved? | advisory |

### Severity rules

- Any critical FAIL must cite a concrete file, symbol, prompt, doc, test, config, or sibling flow.
- If the reviewer cannot point to an exact touchpoint, the FAIL must be advisory, not critical.
- Scope affects only unchanged code outside the diff. The diff itself remains fully reviewable.
