# DEVELOPMENT.md — Development Principles & Module Guide

## What This File Is

This is Ouroboros's **engineering handbook** — the bridge between philosophy (BIBLE.md) and architecture (ARCHITECTURE.md).

**BIBLE.md** answers *why* and *what matters*.
**ARCHITECTURE.md** describes *what exists right now*.
**DEVELOPMENT.md** answers *how to build* — the concrete principles, patterns, and checklists for writing, modifying, and reviewing code in this project.

## Scope

- **Code style & structure:** naming, file layout, module boundaries, error handling patterns.
- **Module lifecycle:** how to create a new module, what it must include, how it integrates.
- **Review & commit protocol:** what happens before code lands — gates, checks, invariants.
- **Testing standards:** what gets tested, how, minimum expectations.
- **Prompt engineering:** standards for writing and modifying LLM prompts (SYSTEM.md, CONSCIOUSNESS.md, etc.).
- **Integration patterns:** how modules communicate, data flows, shared state.

## What It Is NOT

- Not philosophy — that's BIBLE.md.
- Not an architecture map — that's ARCHITECTURE.md.
- Not a changelog — that's README.md + git log.
- Not aspirational — every rule here must reflect current practice or an immediately enforced standard.

## Relationship to Other Documents

```
BIBLE.md (soul — principles, constraints, identity)
    ↓ informs
DEVELOPMENT.md (hands — how to build, concretely)
    ↓ produces
ARCHITECTURE.md (mirror — what currently exists)
```

Rules in this file must not contradict BIBLE.md.

---

## Naming Convention

### General Rules

- **Language:** All code identifiers, comments, docstrings, and commit messages are in English.
- **Style:** Python PEP 8. Modules and variables — `snake_case`. Classes — `PascalCase`. Constants — `UPPER_SNAKE_CASE`.
- **Self-explanatory names** over abbreviations. A name should tell you what the thing *does*, not just what it *is*. Derived from P4 (Authenticity).

### Entity Types

| Entity Type | Purpose | Naming Pattern | Contains Business Logic? | Example |
|-------------|---------|----------------|--------------------------|---------|
| **Gateway** | Thin adapter to an external API. Wraps third-party SDK/HTTP calls into clean Python functions. | `{Platform}Gateway` | No. Pure I/O — translate calls in, translate responses out. | `BrowserGateway` |
| **Service** | Orchestrates a domain concern. May use one or more Gateways, manage state, apply business rules. | `{Domain}Service` | Yes. Coordinates, decides, transforms. | — |
| **Tool** | An LLM-callable function exposed to the agent. Thin wrapper that connects the agent to a Gateway or Service. | `{verb}_{noun}` (snake_case function) | Minimal. Validates input, calls Gateway/Service, formats output. | `repo_read`, `browse_page`, `web_search` |

### Gateway Rules (recommended pattern, not enforced)

When adding a new external API integration, the recommended pattern is a **Gateway** class that isolates transport from business logic. Currently Ouroboros does not have a `gateways/` directory — most external calls live directly in tool modules (e.g. `llm.py`, `tools/search.py`). As the codebase grows, extract Gateways as needed.

When a Gateway exists, it should follow these guidelines:
- No business logic: no routing, no decisions. Just transport.
- Input/output: takes Python primitives, returns Python primitives.
- Error handling: translates platform-specific errors into consistent return values.
- Stateless where possible.

### Relationship Between Entities

```
LLM Agent
    |  calls
Tool (repo_read, web_search, browse_page)
    |  delegates to
Gateway or direct implementation
    |  calls
External API / filesystem / subprocess
```

Not every layer is required for every operation. Simple cases (e.g., `repo_read`) go Tool → filesystem directly.

---

## Module Size & Complexity

Derived from P5 (Minimalism): entire codebase fits in one context window.

- Module: ~1000 lines max.
- Method: <150 lines.
- Function parameters: <8.
- Net complexity growth per cycle approaches zero.
- If a feature is not used in the current cycle — it is premature.

---

## Review & Commit Protocol

Every commit through `repo_commit` or `repo_write_commit` passes a **unified
pre-commit review** — three models review the staged diff against
`docs/CHECKLISTS.md` before commit. Review enforcement is configurable:
`Blocking` preserves the current hard gate, while `Advisory` still runs the
same review but downgrades findings and review-phase failures to warnings.
See `ouroboros/tools/review.py` for implementation.

Preferred workflow for multi-file changes: `repo_write` all files first, then
`repo_commit` to stage, review, and commit everything in one diff.

The full pre-commit review checklists live in **`docs/CHECKLISTS.md`** —
the single source of truth (Bible P5: DRY).

This section defines what "DEVELOPMENT.md compliance" means in practice — it is the
detailed expansion of the `development_compliance` item in `docs/CHECKLISTS.md`.

### DEVELOPMENT.md Compliance Checklist

Before every commit, verify the following:

#### Naming Conventions
- [ ] Modules and variables use `snake_case`
- [ ] Classes use `PascalCase`
- [ ] Constants use `UPPER_SNAKE_CASE`
- [ ] Names are self-explanatory

#### Entity Type Rules
- [ ] **Gateway** (if present): contains ONLY transport. No business logic, no routing.
- [ ] **Tool** (`{verb}_{noun}`): thin LLM-callable wrapper. Validates input, formats output.

#### Module Size & Complexity
- [ ] Module fits in one context window (~1000 lines max)
- [ ] No method exceeds 150 lines
- [ ] No function has more than 8 parameters
- [ ] No gratuitous abstract layers (Bible P5)

#### Structural Rules
- [ ] New Tool? `get_tools()` exports it.
- [ ] New Gateway (if extracted)? Contains no business logic, only transport.
- [ ] New memory/data files? Should they appear in LLM context (`context.py`)?

---

*This section is the authoritative definition of "DEVELOPMENT.md compliance" referenced in the `development_compliance` item in `docs/CHECKLISTS.md`.*
