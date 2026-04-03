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
