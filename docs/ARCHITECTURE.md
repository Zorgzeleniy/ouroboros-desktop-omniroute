# Ouroboros v4.6.0 — Architecture & Reference

This document describes every component, page, button, API endpoint, and data flow.
It is the single source of truth for how the system works. Keep it updated.

---

## 1. High-Level Architecture

```
User
  │
  ▼
launcher.py (PyWebView)       ← desktop window, immutable (bundle-only, not in git)
  │
  │  spawns subprocess
  ▼
server.py (Starlette+uvicorn) ← HTTP + WebSocket on localhost:8765
  │
  ├── web/                     ← Web UI (SPA with ES modules in web/modules/)
  │
  ├── supervisor/              ← Background thread inside server.py
  │   ├── message_bus.py       ← Queue-based message bus (LocalChatBridge)
  │   ├── workers.py           ← Multiprocessing worker pool (fork/spawn by platform)
  │   ├── state.py             ← Persistent state (state.json) with file locking
  │   ├── queue.py             ← Task queue management (PENDING/RUNNING lists)
  │   ├── events.py            ← Event dispatcher (worker→supervisor events)
  │   └── git_ops.py           ← Git operations (clone, checkout, rescue, rollback, push, credential helper)
  │
  └── ouroboros/               ← Agent core (runs inside worker processes)
      ├── config.py            ← SSOT: paths, settings defaults, load/save, PID lock
      ├── agent.py             ← Task orchestrator
      ├── agent_startup_checks.py ← Startup verification and health checks
      ├── agent_task_pipeline.py  ← Task execution pipeline orchestration
      ├── loop.py              ← High-level LLM tool loop
      ├── loop_llm_call.py     ← Single-round LLM call + usage accounting
      ├── loop_tool_execution.py ← Tool dispatch and tool-result handling
      ├── pricing.py           ← Model pricing, cost estimation, usage events
      ├── llm.py               ← OpenRouter API client
      ├── safety.py            ← Dual-layer LLM security supervisor
      ├── consciousness.py     ← Background thinking loop (with progress emission)
      ├── consolidator.py      ← Block-wise dialogue consolidation (dialogue_blocks.json)
      ├── memory.py            ← Scratchpad, identity, chat history
      ├── context.py           ← LLM context builder (public API for consciousness)
      ├── context_compaction.py ← Context trimming and summarization helpers
      ├── local_model.py       ← Local LLM lifecycle (llama-cpp-python)
      ├── local_model_api.py   ← Local model HTTP endpoints
      ├── local_model_autostart.py ← Local model startup helper
      ├── review.py            ← Code collection, complexity metrics, full-codebase review
      ├── owner_inject.py      ← Per-task user message mailbox (compat module name)
      ├── reflection.py        ← Execution reflection and pattern capture
      ├── server_runtime.py    ← Server startup and WebSocket liveness helpers
      ├── tool_policy.py       ← Tool access policy and gating
      ├── utils.py             ← Shared utilities
      ├── world_profiler.py    ← System profile generator (WORLD.md)
      ├── tools/               ← Auto-discovered tool plugins
      └── compat.py            ← Cross-platform process/path/locking helpers
```

### Two-process model

1. **launcher.py** — immutable outer shell (lives inside the `.app` bundle, not in the git repo). Never self-modifies. Handles:
   - PID lock (single instance)
   - Bootstrap: copies workspace to `~/Ouroboros/repo/` on first run
   - Core file sync: overwrites safety-critical files on every launch
   - Starts `server.py` as a subprocess via embedded Python
   - Shows PyWebView window pointed at `http://127.0.0.1:8765`
   - Monitors subprocess; restarts on exit code 42 (restart signal)
   - First-run wizard (PyWebView HTML page for API key entry)
   - **Graceful shutdown with orphan cleanup** (see Shutdown section below)

2. **server.py** — self-editable inner server. Can be modified by the agent.
   - Starlette app with HTTP API + WebSocket
   - Runs supervisor in a background thread
   - Supervisor manages worker pool, task queue, message routing
   - Local model lifecycle endpoints extracted to `ouroboros/local_model_api.py`

### Data layout (`~/Ouroboros/`)

```
~/Ouroboros/
├── repo/              ← Agent's self-modifying git repository
│   ├── server.py      ← The running server (copied from workspace)
│   ├── ouroboros/      ← Agent core package
│   │   └── local_model_api.py  ← Local model API endpoints (extracted from server.py)
│   ├── supervisor/     ← Supervisor package
│   ├── web/            ← Web UI files
│   │   └── modules/    ← ES module pages (chat, dashboard, logs, etc.)
│   ├── docs/           ← Project documentation
│   │   ├── ARCHITECTURE.md ← This document
│   │   ├── DEVELOPMENT.md  ← Engineering handbook (naming, entity types, review protocol)
│   │   └── CHECKLISTS.md   ← Pre-commit review checklists (single source of truth)
│   └── prompts/        ← System prompts (SYSTEM.md, SAFETY.md, CONSCIOUSNESS.md)
├── data/
│   ├── settings.json   ← User settings (API keys, models, budget)
│   ├── state/
│   │   ├── state.json  ← Runtime state (spent_usd, session_id, branch, etc.)
│   │   └── queue_snapshot.json
│   ├── memory/
│   │   ├── identity.md     ← Agent's self-description (persistent)
│   │   ├── scratchpad.md   ← Working memory (auto-generated from scratchpad_blocks.json)
│   │   ├── scratchpad_blocks.json ← Append-block scratchpad (FIFO, max 10)
│   │   ├── dialogue_blocks.json ← Block-wise consolidated chat history
│   │   ├── dialogue_summary.md ← Legacy dialogue summary (auto-migrated to blocks)
│   │   ├── dialogue_meta.json  ← Consolidation metadata (offsets, counts)
│   │   ├── WORLD.md        ← System profile (generated on first run)
│   │   ├── knowledge/      ← Structured knowledge base files
│   │   ├── identity_journal.jsonl    ← Identity update journal
│   │   ├── scratchpad_journal.jsonl  ← Scratchpad block eviction journal
│   │   ├── knowledge_journal.jsonl   ← Knowledge write journal
│   │   ├── registry.md              ← Source-of-truth awareness map (what data the agent has vs doesn't have)
│   │   └── owner_mailbox/           ← Per-task user message files (compat path name)
│   ├── logs/
│   │   ├── chat.jsonl      ← Chat message log
│   │   ├── progress.jsonl  ← Progress/thinking messages (BG consciousness, tasks)
│   │   ├── events.jsonl    ← LLM rounds, task lifecycle, errors
│   │   ├── tools.jsonl     ← Tool call log with args/results
│   │   ├── supervisor.jsonl ← Supervisor-level events
│   │   └── task_reflections.jsonl ← Execution reflections (process memory)
│   └── archive/            ← Rotated logs, rescue snapshots
└── ouroboros.pid           ← PID lock file (platform lock — auto-released on crash)
```

---

## 2. Startup / Onboarding Flow

```
launcher.py main()
  │
  ├── acquire_pid_lock()        → Show "already running" if locked
  ├── check_git()               → Show "install git" wizard if missing
  ├── bootstrap_repo()          → Copy workspace to ~/Ouroboros/repo/ (first run)
  │                               OR sync core files (subsequent runs)
  ├── _run_first_run_wizard()   → Show API key wizard if no settings.json
  │                               (PyWebView HTML page with key + budget + model fields)
  │                               Saves to ~/Ouroboros/data/settings.json
  ├── agent_lifecycle_loop()    → Background thread: start/monitor server.py
  └── webview.start()           → Open PyWebView window at http://127.0.0.1:8765
```

### First-run wizard

Shown when `settings.json` does not exist or has no `OPENROUTER_API_KEY`.
Fields: OpenRouter API Key (required), Total Budget ($), Main Model.
On save: writes `settings.json`, closes wizard, proceeds to main app.

### Core file sync (`_sync_core_files`)

On every launch (not just first run), these files are copied from the workspace
bundle to `~/Ouroboros/repo/`, ensuring safety-critical code cannot be permanently
corrupted by agent self-modification:

- `prompts/SAFETY.md`
- `ouroboros/safety.py`
- `ouroboros/tools/registry.py`

---

## 3. Web UI Pages & Buttons

The web UI is a single-page app (`web/index.html` + `web/style.css` + ES modules).
`web/app.js` is the thin orchestrator (~90 lines) that imports from `web/modules/`:
- `ws.js` — WebSocket connection manager
- `utils.js` — shared utilities (markdown rendering, escapeHtml, matrix rain)
- `chat.js` — chat page with message rendering
- `dashboard.js` — dashboard with controls and polling
- `logs.js` — log viewer with category filters
- `files.js` — file browser, preview, uploads, and editor
- `evolution.js` — evolution chart (Chart.js)
- `settings.js` — settings form with local model management
- `costs.js` — cost breakdown tables
- `versions.js` — version management and rollback
- `about.js` — about page

Navigation is a left sidebar with 9 pages.

### 3.1 Chat

- **Status badge** (top-right): "Online" (green) / "Thinking..." (amber pulse) / "Reconnecting..." (red).
  Driven by WebSocket connection state and typing events.
- **Message input**: textarea + send button. Shift+Enter for newline, Enter to send.
- **Messages**: user bubbles (right, blue-tinted), assistant bubbles (left, crimson), and system-summary bubbles (left, amber). Non-user bubbles render markdown.
- **Timestamps**: smart relative formatting (today: "HH:MM", yesterday: "Yesterday, HH:MM", older: "Mon DD, HH:MM"). Shown on hover.
- **Progress messages**: background consciousness thinking shown as dimmed bubbles with 💬 prefix.
- **System summaries**: `direction="system"` entries from `chat.jsonl` are shown in the same timeline with a 📋 label instead of being hidden or treated as user text.
- **Typing indicator**: animated "thinking dots" bubble appears when the agent is processing.
- **Persistence**: chat history loaded from server on page load (`/api/chat/history`), survives app restarts. Fallback to sessionStorage.
- **Empty-chat init**: if neither server history nor sessionStorage has messages, the UI shows a transient assistant bubble: `Ouroboros has awakened`. This is visual-only and is not written to chat history.
- Messages sent via WebSocket `{type: "chat", content: text}`.
- Responses arrive via WebSocket `{type: "chat", role: "assistant", content: text, ts: "ISO"}`. On page-load history sync, `/api/chat/history` can also return `role: "system"` entries for internal summaries.
- Supports slash commands: `/status`, `/evolve`, `/review`, `/bg`, `/restart`, `/panic`.

### 3.2 Files

- **Browser pane**: directory tree for the configured root, breadcrumb navigation, inline filter, refresh button,
  create-file/create-directory actions, clipboard-style copy/move/paste, and delete/download context menu.
- **Preview pane**: text preview/editor, image preview, binary-file placeholder, and drag-drop upload target.
- **Write safety**: unsaved text edits are guarded on folder switches, file switches, page navigation, and browser refresh.
- **Root policy**: localhost requests fall back to the current user's home directory when no root is configured.
  Network/Docker access requires an explicit `OUROBOROS_FILE_BROWSER_DEFAULT` directory.
- **Network policy**: non-loopback browser/API access is protected by `OUROBOROS_NETWORK_PASSWORD`.
  `/api/health` remains public for health checks; the rest of the app requires auth when the password is configured.
- **Bounds**: directory listings are capped, previews are bounded to a text/byte limit, and uploads reject oversized payloads.

### 3.3 Dashboard

- **Stat cards**: Uptime, Workers (alive/total + progress bar), Budget (spent/limit + bar), Branch@SHA.
- **Toggles**: Evolution Mode (on/off), Background Consciousness (on/off).
  Send `/evolve start|stop` and `/bg start|stop` via WebSocket command.
- **Buttons**:
  - **Force Review** → sends `/review` command. Queues a deep code review task.
  - **Restart Agent** → sends `/restart` command. Graceful restart (save state, kill workers, exit 42).
  - **Panic Stop** → sends `/panic` command (with confirm dialog). Kills all workers immediately.
- Dashboard polls `/api/state` every 3 seconds.

### 3.4 Settings

- **API Keys**: OpenRouter (required), OpenAI (optional, for web search), Anthropic (optional),
  OpenAI Base URL (optional), and Network Password (optional).
  Keys are displayed as masked values (e.g., `sk-or-v1...`).
  Only overwritten on save if user enters a new value (not containing `...`).
- **Models**: Main, Code, Light, Fallback.
- **Reasoning Effort**: Four separate dropdowns for task/chat, evolution, review, and consciousness.
  Backed by `OUROBOROS_EFFORT_TASK`, `OUROBOROS_EFFORT_EVOLUTION`, `OUROBOROS_EFFORT_REVIEW`,
  `OUROBOROS_EFFORT_CONSCIOUSNESS`. Loading falls back to legacy `OUROBOROS_INITIAL_REASONING_EFFORT`
  for task/chat when the new key is absent.
- **Review Models**: Comma-separated OpenRouter model IDs for pre-commit review.
  Backed by `OUROBOROS_REVIEW_MODELS`.
- **Review Enforcement**: `Advisory` or `Blocking` for pre-commit review behavior.
  Backed by `OUROBOROS_REVIEW_ENFORCEMENT`. Review always runs in both modes.
- **Runtime**: Max Workers, Budget ($), Tool Timeout, Soft/Hard Timeout.
- **GitHub**: Token + Repo (for remote sync).
- **Save Settings** button → POST `/api/settings`. Applies to env immediately.
  Budget changes take effect immediately; model/worker changes need restart.
- **Reset All Data** button (Danger Zone) → POST `/api/reset`.
  Deletes: state/, memory/, logs/, archive/, settings.json.
  Keeps: repo/ (agent code).
  Triggers server restart. On next launch, onboarding wizard appears.

### 3.5 Logs

- **Filter chips**: Tools, LLM, Errors, Tasks, System, Consciousness.
  Toggle on/off to filter log entries.
- **Clear** button: clears the in-memory log view (not files on disk).
- Log entries arrive via WebSocket `{type: "log", data: event}`.
- The page renders a live timeline: timestamp, category, phase badge, readable summary,
  metadata pills, and optional body text.
- Each row has a **Raw** toggle that expands the original JSON payload.
- New live-only timeline events cover task start, context building, LLM round start/finish,
  tool start/finish/timeout, and compact task heartbeats during long waits.
- Repeated startup/system events such as verification bursts are compacted in the UI.
- Max 500 entries in view (oldest removed).

### 3.6 Versions

- **Current branch + SHA** displayed at top.
- **Recent Commits** list with SHA, date, message, and "Restore" button.
- **Tags** list with tag name, date, message, and "Restore" button.
- **Restore** button → POST `/api/git/rollback` with target SHA/tag.
  Creates rescue snapshot, resets to target, restarts server.
- **Promote to Stable** button → POST `/api/git/promote`.
  Updates `ouroboros-stable` branch to match `ouroboros`.
- **Refresh** button → reloads commit/tag lists.

### 3.7 Costs

- **Total Spent / Total Calls / Top Model** stat cards at top.
- **Breakdown tables**: By Model, By API Key, By Model Category, By Task Category.
  Each row shows name, call count, cost, and a proportional bar.
- **Refresh** button reloads data from `/api/cost-breakdown`.
- Data auto-loads when the page becomes active (MutationObserver on class).

### 3.8 Evolution

- **Chart**: interactive Chart.js line graph showing code LOC, prompt sizes (BIBLE, SYSTEM),
  identity, scratchpad, and total memory growth across all git tags.
- **Dual Y-axes**: left axis for Lines of Code, right axis for Size (KB).
- **Tags table**: detailed breakdown per tag with all metrics.
- Data fetched from `/api/evolution-data` (cached 60s server-side).
- Chart.js bundled locally (`web/chart.umd.min.js`) — no CDN dependency.

### 3.9 About

- Logo (large, centered)
- "A self-creating AI agent" description
- Created by Anton Razzhigaev & Andrew Kaznacheev
- Links: @abstractDL (Telegram), GitHub repo
- "Joi Lab" footer

---

## 4. Server API Endpoints

If `OUROBOROS_NETWORK_PASSWORD` is configured, non-loopback HTTP/WebSocket access requires
authentication. `/api/health`, `/auth/login`, and `/auth/logout` remain reachable without an
existing session.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Serves `web/index.html` |
| GET | `/api/health` | `{status, version, runtime_version, app_version}` |
| GET | `/api/state` | Dashboard data: uptime, workers, budget, branch, etc. |
| GET | `/api/files/list` | Directory listing for Files tab root/path |
| GET | `/api/files/read` | File preview payload (text/image metadata/binary placeholder) |
| GET | `/api/files/content` | Raw file content response for image preview |
| GET | `/api/files/download` | Attachment download for a file |
| POST | `/api/files/write` | Create or overwrite a text file from Files editor |
| POST | `/api/files/mkdir` | Create a directory inside current Files path |
| POST | `/api/files/delete` | Delete a file/directory (root delete is rejected) |
| POST | `/api/files/transfer` | Copy or move files/directories within the Files root |
| POST | `/api/files/upload` | Multipart upload into current Files directory |
| GET | `/api/settings` | Current settings with masked API keys |
| POST | `/api/settings` | Update settings (partial update, only provided keys) |
| POST | `/api/command` | Send a slash command `{cmd: "/status"}` |
| POST | `/api/reset` | Delete all runtime data, restart for fresh onboarding |
| GET | `/api/git/log` | Recent commits + tags + current branch/sha |
| POST | `/api/git/rollback` | Rollback to a specific commit/tag `{target: "sha"}` |
| POST | `/api/git/promote` | Promote ouroboros → ouroboros-stable |
| GET | `/api/cost-breakdown` | Cost dashboard aggregation by model/key/category |
| POST | `/api/local-model/start` | Start/download local model server |
| POST | `/api/local-model/stop` | Stop local model server |
| GET | `/api/local-model/status` | Local model status and readiness |
| GET | `/api/evolution-data` | Evolution metrics per git tag (LOC, prompt sizes, memory) |
| GET | `/api/chat/history` | Merged chat + system summaries + progress messages (chronological, limit param) |
| POST | `/api/local-model/test` | Local model sanity test (chat + tool calling) |
| GET/POST | `/auth/login` | Password gate entrypoint for non-localhost browser/API access |
| GET/POST | `/auth/logout` | Clear auth cookie/session |
| WS | `/ws` | WebSocket: chat messages, commands, log streaming |
| GET | `/static/*` | Static files from `web/` directory (NoCacheStaticFiles wrapper forces revalidation) |

### WebSocket protocol

**Client → Server:**
- `{type: "chat", content: "text"}` — send chat message
- `{type: "command", cmd: "/status"}` — send slash command

**Server → Client:**
- `{type: "chat", role: "assistant", content: "text"}` — agent response
- `{type: "log", data: {type, ts, ...}}` — real-time log event
- `{type: "typing", action: "typing"}` — typing indicator (show animation)

---

## 5. Supervisor Loop

Runs in a background thread inside `server.py:_run_supervisor()`.

Each iteration (0.5s sleep):
1. `rotate_chat_log_if_needed()` — archive chat.jsonl if > 800KB
2. `ensure_workers_healthy()` — respawn dead workers, detect crash storms
3. Drain event queue (worker→supervisor events via multiprocessing.Queue)
4. `enforce_task_timeouts()` — soft/hard timeout handling
5. `enqueue_evolution_task_if_needed()` — auto-queue evolution if enabled
6. `assign_tasks()` — match pending tasks to free workers
7. `persist_queue_snapshot()` — save queue state for crash recovery
8. Poll `LocalChatBridge` inbox for user messages
9. Route messages: slash commands → supervisor handlers; text → agent

### Slash command handling (server.py main loop)

| Command | Action |
|---------|--------|
| `/panic` | Kill workers (force), request restart exit |
| `/restart` | Save state, safe_restart (git), kill workers, exit 42 |
| `/review` | Queue a review task |
| `/evolve on\|off` | Toggle evolution mode in state, prune evolution tasks if off |
| `/bg start\|stop\|status` | Control background consciousness |
| `/status` | Send status text with budget breakdown |
| (anything else) | Route to agent via `handle_chat_direct()` |

---

## 6. Agent Core

### Task lifecycle

1. Message arrives → `handle_chat_direct(chat_id, text, image_data)`
2. Creates task dict `{id, type, chat_id, text}`
3. `OuroborosAgent.handle_task(task)` →
   a. Build context (`context.py`): system prompt + bible + identity + scratchpad + runtime info + Memory Registry digest
   b. `run_llm_loop()`: LLM call → tool execution → repeat until final text response
   c. Emit events: send_message, task_metrics, task_done
4. Events flow back to supervisor via event queue

### Tool execution (loop.py)

- Pricing/cost estimation logic extracted to `pricing.py` (model pricing table, cost estimation, API key inference, usage event emission)
- **Per-task cost cap**: Each task has a cost ceiling (default $5, env `OUROBOROS_PER_TASK_COST_USD`). When a task exceeds this, the LLM is asked to wrap up immediately. This prevents runaway evolution tasks that previously hit $10+.
- **`memory_tools.py`**: Provides `memory_map` (read the metacognitive registry of all data sources) and `memory_update_registry` (add/update entries). Part of the Memory Registry system (v3.16.0).
- **`tool_discovery.py`**: Provides `list_available_tools` (discover non-core tools) and `enable_tools` (activate extra tools for the current task). Enables dynamic tool set management.
- Core tools always available; extra tools discoverable via `list_available_tools`/`enable_tools`
- Read-only tools can run in parallel (ThreadPoolExecutor)
- Browser tools use thread-sticky executor (Playwright greenlet affinity)
- All tools have hard timeout (default 360s, per-tool overrides for browser/search/vision)
- Multi-layer safety: hardcoded sandbox (registry.py) → deterministic whitelist → LLM safety supervisor
- Tool results use explicit per-tool caps with visible truncation markers (`repo_read`/`data_read`/`knowledge_read`/`run_shell`: 80k, default: 15k chars). Cognitive reads (`memory/*`, prompts, BIBLE/docs, commit/review outputs) are exempt from silent clipping.
- Context compaction kicks in after round 8 (summarizes old tool results)

### Git tools (tools/git.py + tools/review.py + supervisor/git_ops.py)

- **`repo_write`** (v3.24.0): write file(s) to disk WITHOUT committing. Supports single-file
  (`path` + `content`) and multi-file (`files` array) modes. Preferred workflow:
  `repo_write` all files → `repo_commit` once with the full diff.
- **`repo_commit`**: stage + unified pre-commit review + commit + tests + auto-tag + auto-push.
  Includes `review_rebuttal` parameter for disputing reviewer feedback.
- **`repo_write_commit`**: legacy single-file write+commit (kept for compatibility).
  Also runs unified review before commit.
- **Unified pre-commit review** (v3.24.0): 3 models review staged diff against
  `docs/CHECKLISTS.md`. Review always runs before commit. `Blocking` mode keeps
  critical findings as hard gates; `Advisory` mode surfaces the same findings
  as warnings and lets the commit continue. Review history carried across
  blocking iterations. Quorum: at least 2 of 3 reviewers must succeed in
  blocking mode. Deterministic preflight catches VERSION/README mismatches
  before the expensive LLM call.
- **`pull_from_remote`**: fast-forward only pull from origin
- **`restore_to_head`**: discard uncommitted changes (review-exempt)
- **`revert_commit`**: create a revert commit for a specific SHA (review-exempt)
- **Auto-tag**: on VERSION change, creates annotated tag `v{VERSION}` after tests pass
- **Auto-push**: best-effort push to origin after successful commit (non-fatal)
- **Credential helper**: `git_ops.configure_remote()` stores credentials in repo-local
  `.git/credentials`. `migrate_remote_credentials()` migrates legacy token-in-URL origins.
  Both are wired at startup and on settings save.

### Safety system (safety.py + registry.py)

Multi-layer security:
1. **Hardcoded sandbox** (registry.py): deterministic blocks on safety-critical file writes, mutative git via shell, GitHub repo/auth commands. Runs BEFORE any LLM check.
2. **Deterministic whitelist** (safety.py): known-safe operations (read-only shell commands, repo writes already guarded by sandbox) skip LLM for speed.
3. **LLM Layer 1 (fast)**: Light model checks remaining tool calls for SAFE/SUSPICIOUS/DANGEROUS.
4. **LLM Layer 2 (deep)**: If flagged, heavy model re-evaluates with "are you sure?" nudge.
5. **Post-execution revert**: After claude_code_edit, modifications to safety-critical files are automatically reverted.
- Safety LLM calls now emit standard `llm_usage` events, so safety costs and failures appear in the same audit/health pipeline as other model calls.
`identity.md` is intentionally mutable (self-creation) and can be rewritten radically;
the constitutional guard is that the file itself must remain non-deletable.

### Background consciousness (consciousness.py)

- Daemon thread, sleeps between wakeups (interval controlled by LLM via `set_next_wakeup`)
- Loads full agent context: BIBLE, identity, scratchpad, knowledge base, drive state,
  health invariants, recent chat/progress/tools/events (same context as main agent)
- Owner messages are forwarded to background consciousness in full text (not first-100-char previews).
- Calls LLM with lightweight introspection prompt
- Has limited tool access (memory, messaging, scheduling, read-only)
- **Progress emission**: emits 💬 progress messages to UI via event queue + persists to `progress.jsonl`
- Pauses when regular task is running; deferred events queued and flushed on resume
- Budget-capped (default 10% of total)
- As of v3.16.1, CONSCIOUSNESS.md includes a concrete 7-item rotating maintenance checklist (dialogue consolidation, identity freshness, scratchpad freshness, knowledge gaps, process-memory freshness, tech radar, registry sync). One item is addressed per wakeup cycle.

### Block-wise dialogue consolidation (consolidator.py)

- Triggered after each task completion (non-blocking, runs in a daemon thread)
- Reads unprocessed entries from `chat.jsonl` in BLOCK_SIZE (100) message chunks
- Calls LLM (Gemini Flash) to create summary blocks stored in `dialogue_blocks.json`
- **Era compression**: when block count exceeds MAX_SUMMARY_BLOCKS (10), oldest blocks
  compressed into single "era summary" (30-40% of original length)
- **Auto-migration**: legacy `dialogue_summary.md` episodes auto-migrated to blocks
  on first consolidation run
- First-person narrative format ("I did...", "Anton asked...", "We decided...")
- Context reads blocks directly from `dialogue_blocks.json` instead of flat markdown

### Scratchpad auto-consolidation (consolidator.py)

- **Block-aware**: operates on `scratchpad_blocks.json` when blocks exist
- Triggered after each task when total block content exceeds 30,000 chars
- LLM extracts durable insights into knowledge base topics, compresses oldest blocks
- Falls back to flat-file mode for pre-migration scratchpads
- Writes knowledge files to `memory/knowledge/`, rebuilds `index-full.md`
- Uses platform-aware file locking to serialize concurrent calls
- Runs in a daemon thread (same pattern as dialogue consolidation)

### Execution reflection (reflection.py)

- Triggered at end of task when tool calls had errors or results contained
  blocking markers (`REVIEW_BLOCKED`, `TESTS_FAILED`, `COMMIT_BLOCKED`, etc.)
- Light LLM produces 150-250 word reflection capturing goal, errors, root cause, lessons
- Stored in `logs/task_reflections.jsonl`; last 20 entries loaded into dynamic context
- Pattern register: recurring error classes tracked in `memory/knowledge/patterns.md`
  via LLM, loaded into semi-stable context as "Known error patterns"
- Secondary reflection/pattern prompts use explicit truncation markers when compacted for prompt size; no silent clipping of these helper summaries.
- Runs synchronously (not in daemon thread) to avoid data loss on shutdown

### Crash report injection (agent.py)

- On startup, `_verify_system_state()` checks for `state/crash_report.json`
- If present, logs `crash_rollback_detected` event to `events.jsonl`
- File is NOT deleted — persists so `build_health_invariants()` surfaces
  CRITICAL: RECENT CRASH ROLLBACK on every task until the agent investigates

### Subtask lifecycle and trace summaries

- `schedule_task` now writes durable lifecycle states in `task_results/<id>.json`: `requested` → `scheduled` → `running` → terminal status (`completed`, `rejected_duplicate`, `failed`, etc.)
- Duplicate rejects are persisted explicitly, so `wait_for_task()` can report honest status instead of pretending the task is still running.
- Completed subtasks persist the full result text; parent tasks no longer see silently clipped child output.
- When a subtask completes, a compact trace summary is included alongside the full result.
- Parent tasks see tool call counts, error counts, and agent notes.
- Trace compaction remains explicit: max 4000 chars with visible omission markers, plus first/last 15 tool calls for long traces.

### Context building (context.py)

- As of v3.16.0, the Memory Registry digest (from `memory/registry.md`) is injected into every LLM context to enable source-of-truth awareness.
- As of v3.20.0, `patterns.md` (Pattern Register) is injected into semi-stable context, and execution reflections from `task_reflections.jsonl` are injected into dynamic context.
- As of v3.22.0, all docs are always in static context: BIBLE.md (180k), ARCHITECTURE.md (60k), DEVELOPMENT.md (30k), README.md (10k), CHECKLISTS.md (5k).
- `Health Invariants` are placed at the start of the dynamic context block, before drive state/runtime/recent sections, so warnings influence planning before the model reads the noisier tail sections.
- `build_recent_sections()` keeps recent dialogue broad, but task-scopes recent progress/tools/events when `task_id` is available.
- `build_health_invariants()` is split into focused helpers and now also surfaces recent provider/routing errors plus local context overflows.
- Local-model path no longer silently slices the live system prompt. It compacts non-core sections explicitly and raises an overflow error if core context still cannot fit.

### Deep review (review.py)

- As of v3.16.1, the review task includes an explicit Constitution (BIBLE.md) compliance mandate as the highest-priority review criterion.
- Full-codebase review for 1M-context models: all text files loaded without truncation
- Dry-run size estimation before loading (avoids OOM on huge repos)
- Fallback to chunked previews if codebase exceeds 600K token budget
- Security: skips sensitive files (.env, .pem, credentials.json, etc.)
- Per-file cap: 1MB
- Multi-model review now uses the shared async `LLMClient` OpenRouter path instead of raw one-off HTTP calls, so provider routing, Anthropic parameter requirements, usage normalization, and cache metadata are aligned with the rest of the runtime.

---

## 7. Configuration (ouroboros/config.py)

Single source of truth for:
- **Paths**: HOME, APP_ROOT, REPO_DIR, DATA_DIR, SETTINGS_PATH, PID_FILE, PORT_FILE
- **Constants**: RESTART_EXIT_CODE (42), AGENT_SERVER_PORT (8765)
- **Settings defaults**: all model names, budget, timeouts, worker count
- **Functions**: `load_settings()`, `save_settings()`,
  `apply_settings_to_env()`, `acquire_pid_lock()`, `release_pid_lock()`

Settings file: `~/Ouroboros/data/settings.json`. File-locked for concurrent access.

### Default settings

| Key | Default | Description |
|-----|---------|-------------|
| OPENROUTER_API_KEY | "" | Required. Main LLM API key |
| OPENAI_API_KEY | "" | Optional. For web_search tool |
| OPENAI_BASE_URL | "" | Optional. Base URL for OpenAI-compatible web search backend |
| ANTHROPIC_API_KEY | "" | Optional. For Claude Code CLI |
| OUROBOROS_NETWORK_PASSWORD | "" | Optional on localhost, required for non-loopback access |
| OUROBOROS_MODEL | anthropic/claude-opus-4.6 | Main reasoning model |
| OUROBOROS_MODEL_CODE | anthropic/claude-opus-4.6 | Code editing model |
| OUROBOROS_MODEL_LIGHT | anthropic/claude-sonnet-4.6 | Fast/cheap model (safety, consciousness) |
| OUROBOROS_MODEL_FALLBACK | anthropic/claude-sonnet-4.6 | Fallback when primary fails |
| CLAUDE_CODE_MODEL | opus | Anthropic model for Claude Code CLI (sonnet, opus, or full name) |
| OUROBOROS_MAX_WORKERS | 5 | Worker process pool size |
| TOTAL_BUDGET | 10.0 | Total budget in USD |
| OUROBOROS_WEBSEARCH_MODEL | gpt-5.2 | OpenAI model for web_search tool |
| OUROBOROS_REVIEW_MODELS | openai/gpt-5.4,google/gemini-3.1-pro-preview,anthropic/claude-opus-4.6 | Comma-separated OpenRouter model IDs for pre-commit review (min 2 for quorum) |
| OUROBOROS_REVIEW_ENFORCEMENT | blocking | Pre-commit review enforcement: `advisory` or `blocking` |
| OUROBOROS_EFFORT_TASK | medium | Reasoning effort for task/chat: none, low, medium, high |
| OUROBOROS_EFFORT_EVOLUTION | high | Reasoning effort for evolution tasks |
| OUROBOROS_EFFORT_REVIEW | medium | Reasoning effort for review tasks |
| OUROBOROS_EFFORT_CONSCIOUSNESS | low | Reasoning effort for background consciousness |
| OUROBOROS_SOFT_TIMEOUT_SEC | 600 | Soft timeout warning (10 min) |
| OUROBOROS_HARD_TIMEOUT_SEC | 1800 | Hard timeout kill (30 min) |
| LOCAL_MODEL_SOURCE | "" | HuggingFace repo for local model |
| LOCAL_MODEL_FILENAME | "" | GGUF filename within repo |
| LOCAL_MODEL_CONTEXT_LENGTH | 16384 | Context window for local model |
| LOCAL_MODEL_N_GPU_LAYERS | 0 | GPU layers (-1=all, 0=CPU/mmap) |
| USE_LOCAL_MAIN | false | Route main model to local server |
| USE_LOCAL_CODE | false | Route code model to local server |
| USE_LOCAL_LIGHT | false | Route light model to local server |
| USE_LOCAL_FALLBACK | false | Route fallback model to local server |
| OUROBOROS_BG_MAX_ROUNDS | 5 | Max LLM rounds per consciousness cycle |
| OUROBOROS_BG_WAKEUP_MIN | 30 | Min wakeup interval (seconds) |
| OUROBOROS_BG_WAKEUP_MAX | 7200 | Max wakeup interval (seconds) |
| OUROBOROS_EVO_COST_THRESHOLD | 0.10 | Min cost per evolution cycle |
| LOCAL_MODEL_PORT | 8766 | Port for local llama-cpp server |
| LOCAL_MODEL_CHAT_FORMAT | "" | Chat format for local model (`""` = auto-detect) |
| GITHUB_TOKEN | "" | Optional. GitHub PAT for remote sync |
| GITHUB_REPO | "" | Optional. GitHub repo (owner/name) for sync |
| OUROBOROS_FILE_BROWSER_DEFAULT | "" | Explicit Files tab root. Required for Docker/non-localhost Files access |

---

## 8. Git Branching Model

- **ouroboros** — development branch. Agent commits here.
- **ouroboros-stable** — promoted stable version. Updated via "Promote to Stable" button.
- **main** — protected branch. Agent never touches it.

`safe_restart()` does `git checkout -f ouroboros` + `git reset --hard` on the repo.
Uncommitted changes are rescued to `~/Ouroboros/data/archive/rescue/` before reset.

---

## 9. Shutdown & Process Cleanup

**Requirement: closing the window (X button or Cmd+Q) MUST leave zero orphan
processes. No zombies, no workers lingering in background.**

### 9.1 Normal Shutdown (window close)

```
1. _shutdown_event.set()           ← signal lifecycle loop to exit
2. stop_agent()
   a. SIGTERM → server.py          ← server runs its lifespan shutdown:
      │                                kill_workers(force=True) → SIGTERM+SIGKILL all workers
      │                                then server exits cleanly
   b. wait 10s for exit
   c. if still alive → SIGKILL     ← hard kill (workers may orphan)
3. _kill_orphaned_children()        ← SAFETY NET
   a. _kill_stale_on_port(8765)    ← lsof port, SIGKILL any survivors
   b. multiprocessing.active_children() → SIGKILL each
4. release_pid_lock()               ← delete ~/Ouroboros/ouroboros.pid
```

This three-layer approach (graceful → force-kill server → sweep port/children)
guarantees no orphans even if the server hangs or workers resist SIGTERM.

### 9.2 Panic Stop (`/panic` command or Panic Stop button)

**Panic is a full emergency stop. Not a restart — a complete shutdown.**

The panic sequence (in `server.py:_execute_panic_stop()`):

```
1. consciousness.stop()             ← stop background consciousness thread
2. Save state: evolution_mode_enabled=False, bg_consciousness_enabled=False
3. Write ~/Ouroboros/data/state/panic_stop.flag
4. LocalModelManager.stop_server()   ← kill local model server if running
5. kill_all_tracked_subprocesses()   ← os.killpg(SIGKILL) every tracked
   │                                    subprocess process group (claude CLI,
   │                                    shell commands, and ALL their children)
6. kill_workers(force=True)          ← SIGTERM+SIGKILL all multiprocessing workers
7. os._exit(99)                      ← immediate hard exit, kills daemon threads
```

Launcher handles exit code 99:

```
7. Launcher detects exit_code == PANIC_EXIT_CODE (99)
8. _shutdown_event.set()
9. Kill orphaned children (port sweep + multiprocessing sweep)
10. _webview_window.destroy()        ← closes PyWebView, app exits
```

On next manual launch:

```
11. auto_resume_after_restart() checks for panic_stop.flag
12. Flag found → skip auto-resume, delete flag
13. Agent waits for user interaction (no automatic work)
```

### 9.3 Subprocess Process Group Management

All subprocesses spawned by agent tools (`run_shell`, `claude_code_edit`)
use `start_new_session=True` (via `_tracked_subprocess_run()` in
`ouroboros/tools/shell.py`). This creates a separate process group for each
subprocess and all its children.

On panic or timeout, the entire process tree is killed via
`os.killpg(pgid, SIGKILL)` — no orphans possible, even for deeply nested
subprocess trees (e.g., Claude CLI spawning node processes).

Active subprocesses are tracked in a thread-safe global set and cleaned up
automatically on completion or via `kill_all_tracked_subprocesses()` on panic.

---

## 10. Key Invariants

1. **Never delete BIBLE.md. Never physically delete `identity.md` file.**
   (`identity.md` content is intentionally mutable and may be radically rewritten.)
2. **VERSION == pyproject.toml version == latest git tag == README version == ARCHITECTURE.md header version**
3. **Config SSOT**: all settings defaults and paths live in `ouroboros/config.py`
4. **Message bus SSOT**: all messaging goes through `supervisor/message_bus.py`
5. **State locking**: `state.json` uses file locks for concurrent read-modify-write
6. **Budget tracking**: per-LLM-call cost events with model/key/category breakdown
7. **Core file sync**: safety-critical files are overwritten from bundle on every launch
8. **Zero orphans on close**: shutdown MUST kill all child processes (see Section 9)
9. **Panic MUST kill everything**: all processes (workers, subprocesses, subprocess
   trees, consciousness, evolution) are killed and the application exits completely.
   No agent code may prevent or delay panic. See BIBLE.md Emergency Stop Invariant.
10. **Architecture documentation**: `docs/ARCHITECTURE.md` must be kept in sync with
    the codebase. Every structural change (new module, new API endpoint, new data file,
    new UI page) must be reflected here. This is the single source of truth for how
    the system works.
