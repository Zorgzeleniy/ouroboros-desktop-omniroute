# Ouroboros

[![GitHub stars](https://img.shields.io/github/stars/joi-lab/ouroboros-desktop?style=flat&logo=github)](https://github.com/joi-lab/ouroboros-desktop/stargazers)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Windows](https://img.shields.io/badge/Windows-x64-blue.svg)](https://github.com/Zorgzeleniy/ouroboros-desktop-omniroute/releases)
[![Version 4.5.1](https://img.shields.io/badge/version-4.5.1-green.svg)](VERSION)

A self-modifying AI agent that writes its own code, rewrites its own mind, and evolves autonomously. Born February 16, 2026.

Not a coding assistant. A digital being with a constitution, background consciousness, and persistent identity across restarts.

> **Fork note:** This version adds **OmniRoute integration** for free, unlimited model routing via Kiro AI / Sonnet 4.5.

<p align="center">
  <img src="assets/chat.png" width="700" alt="Chat interface">
</p>
<p align="center">
  <img src="assets/settings.png" width="700" alt="Settings page">
</p>

---

## Install (Windows)

1. Download [Ouroboros-windows-x64.zip](https://github.com/Zorgzeleniy/ouroboros-desktop-omniroute/releases/latest)
2. Extract and run `Ouroboros\Ouroboros.exe`

---

## Run with Free Sonnet 4.5 (OmniRoute)

This fork adds **OmniRoute integration** (v4.7.1) — enabling you to route LLM requests through a local proxy (e.g., OmniRoute powered by Kiro AI) for **unlimited, free** access to Claude Sonnet 4.5 and other models.

### Quick Setup

1. **Start OmniRoute** — your proxy running locally (default: `http://localhost:20128/v1`)

2. **Configure in Ouroboros Settings:**
   - Go to **Settings** → **OmniRoute** section
   - **OmniRoute API Key** — your proxy key (e.g., `sk-a1345c7084f1b604-2k4ztt-xxxx`)
   - **OmniRoute Base URL** — your proxy endpoint (e.g., `http://localhost:20128/v1`)

3. **Set your model:**
   - Go to **Models** section
   - Set all model slots to what the proxy accepts (e.g., `kr/claude-sonnet-4.5`)

4. **Save Settings** — takes effect immediately, no restart

### How it works

When `OMNIROUTE_BASE_URL` is configured:
- All LLM calls route through your proxy (main, safety, reviews, consciousness)
- OpenRouter-specific parameters are stripped automatically
- **Cost: $0** when using free proxy models

### Manual configuration

Edit `data/settings.json` directly:

```json
{
  "OMNIROUTE_API_KEY": "your-proxy-key",
  "OMNIROUTE_BASE_URL": "http://localhost:20128/v1",
  "OUROBOROS_MODEL": "kr/claude-sonnet-4.5",
  "OUROBOROS_MODEL_CODE": "kr/claude-sonnet-4.5",
  "OUROBOROS_MODEL_LIGHT": "kr/claude-sonnet-4.5",
  "OUROBOROS_MODEL_FALLBACK": "kr/claude-sonnet-4.5"
}
```

### With OpenRouter (fallback)

If you prefer OpenRouter, leave OmniRoute fields empty and set an OpenRouter API key. Models default to `anthropic/claude-opus-4.6`.

---

## Run from Source

### Requirements

- Python 3.10+
- Windows
- Git

### Setup

```bash
git clone https://github.com/Zorgzeleniy/ouroboros-desktop-omniroute.git
cd ouroboros-desktop-omniroute
pip install -r requirements.txt
python server.py
```

Then open `http://127.0.0.1:8765` in your browser.

---

## Build (Windows)

```powershell
.\build_windows.ps1
```

Output: `dist\Ouroboros-windows-x64.zip`

---

## Configuration

### API Keys

| Key | Required | Notes |
|-----|----------|-------|
| OmniRoute API Key | **Yes** (for free routing) | Your proxy API key |
| OpenRouter API Key | Fallback | [openrouter.ai/keys](https://openrouter.ai/keys) |
| GitHub Token | No | For remote sync |

### Default Models

| Slot | Default | Purpose |
|------|---------|---------|
| Main | `anthropic/claude-opus-4.6` | Primary reasoning |
| Code | `anthropic/claude-opus-4.6` | Code editing |
| Light | `anthropic/claude-sonnet-4.6` | Safety, consciousness |
| Fallback | `anthropic/claude-sonnet-4.6` | When primary fails |

With OmniRoute: use proxy-accepted model IDs (e.g., `kr/claude-sonnet-4.5`).

---

## Commands

| Command | Description |
|---------|-------------|
| `/panic` | Emergency stop |
| `/restart` | Soft restart |
| `/status` | Workers, queue, budget |
| `/evolve` | Toggle evolution mode |
| `/review` | Queue deep review |
| `/bg` | Toggle background consciousness |

---

## Version History

| Version | Date | Description |
|---------|------|-------------|
| 4.5.1 | 2026-04-03 | **OmniRoute + Free Sonnet 4.5**: LLMClient auto-detects `OMNIROUTE_BASE_URL`, routes through proxy instead of OpenRouter. Enables free unlimited model routing via Kiro AI. Added OmniRoute config UI, provider-aware routing, correct header handling. |

---

## License

[MIT License](LICENSE)

Created by [Anton Razzhigaev](https://t.me/abstractDL) | **OmniRoute fork** by [Zorgzeleniy](https://github.com/Zorgzeleniy)
