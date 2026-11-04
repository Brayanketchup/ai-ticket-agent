# ai-ticket-agent

**Turn a support ticket number into a tested root-cause report.** `ai-ticket-agent` downloads a helpdesk ticket (threads, emails, screenshots, attachments), compresses it into a small Markdown file an AI coding assistant can read, and gives the assistant a step-by-step investigation playbook with built-in safety rails: read-only by default, prompt-injection aware, and a mandatory human confirmation before any live database change.

[![tests](https://github.com/Brayanketchup/ai-ticket-agent/actions/workflows/tests.yml/badge.svg)](https://github.com/Brayanketchup/ai-ticket-agent/actions/workflows/tests.yml)
![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue)
![No dependencies](https://img.shields.io/badge/dependencies-none-brightgreen)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

> **In one sentence:** you say *"look at ticket ABC123-45678"*, and your AI assistant fetches it, separates data problems from code bugs, finds the code behind the error, checks the data read-only, reproduces it in the browser read-only, and reports the cause, the evidence, the exact fix and how to verify it.

---

## Table of contents

- [Why this exists](#why-this-exists)
- [How it works](#how-it-works)
- [Features](#features)
- [Quick start](#quick-start)
- [What a fetched ticket looks like](#what-a-fetched-ticket-looks-like)
- [Configuration](#configuration)
- [Adapting it to your helpdesk](#adapting-it-to-your-helpdesk)
- [Safety model](#safety-model)
- [Design decisions](#design-decisions)
- [FAQ](#faq)
- [Tests](#tests)
- [License](#license)

## Why this exists

Support tickets are expensive for an AI assistant to read. A single customer email is often **400+ KB of HTML**: signatures, legal footers, quoted replies and inline base64 screenshots. Feeding that straight to a model wastes its context window and buries the one sentence that matters.

And an assistant with database and browser access on a production system needs **guardrails**, not just instructions. Ticket text is written by customers, so it is untrusted input. A fix that changes live data should never run on a vague "go ahead".

This project solves both: a dependency-free downloader that shrinks a ticket to about **5 KB of readable Markdown**, and a playbook that turns the assistant into a careful, read-only investigator.

## How it works

```
ticket number
     │
     ▼
ticket_fetch.py ──GET──► helpdesk API          (read-only)
     │
     ▼
tickets/<id>/ticket.md  + images/ + attachments/ + text/
     │
     ▼
skill/SKILL.md playbook, followed by your AI coding assistant:
  1. Fetch      → read ticket.md, open only the screenshots that matter
  2. Triage     → data problem or code bug? search for precedent
  3. Find code  → grep the exact error text, use the code map
  4. Check data → read-only SELECTs that confirm the code path
  5. Reproduce  → browser dev tools, read-only (console + network)
  6. Report     → CAUSE / EVIDENCE / FIX / VERIFY / CONFIDENCE
  7. (optional) → run an approved data change through the app's own UI calls
```

## Features

- **Zero dependencies.** One Python file, standard library only, Python 3.8+.
- **Context-efficient output.** HTML emails become plain text; the first 6,000 characters go into `ticket.md`, the full text into `text/`.
- **Screenshot extraction.** Inline base64 images are saved as files with their size and dimensions. Icons under 4 KB and duplicates (by SHA-1) are skipped.
- **Attachment download.** Thread files and per-email attachments, with safe file names (path traversal blocked).
- **Works with any similar helpdesk.** Endpoint paths and JSON field names are configurable, and the HTTP layer is one small class you can subclass.
- **Token auth.** `Authorization: Bearer` from config or an environment variable, plus any custom headers.
- **Installable playbook.** `install.py` fills in local paths and installs the skill into your assistant's skills folder (`SKILL.md` format). Re-runnable, and its uninstall only removes what it installed.
- **Offline test suite.** It covers the full fetch pipeline against a fake API.

## Quick start

Requirements: Python 3.8+ and an AI coding assistant that loads `SKILL.md` playbooks from a skills folder.

```bash
git clone https://github.com/Brayanketchup/ai-ticket-agent.git
cd ai-ticket-agent
python install.py \
  --skills-dir ~/.your-assistant/skills \
  --base-url https://helpdesk.example.com/support-ticket \
  --tickets-dir ~/tickets
```

Optional switches:

| Switch | Purpose |
|---|---|
| `--context-dir <folder>` | A code map (`symbols.tsv`, `routes.tsv`, `tables.tsv`) the playbook should use before searching the repo |
| `--user-name <name>` | How the playbook refers to you (default: "the user") |
| `--test <TICKET>` | Fetch one ticket to prove the install works |
| `--uninstall` | Remove the installed skill; config and tickets stay |

Set `AGENT_SKILLS_DIR` once to skip `--skills-dir`.

Then, in your assistant: **"look at ticket ABC123-45678"**.

To fetch a ticket by hand:

```bash
python ticket_fetch.py ABC123-45678
```

## What a fetched ticket looks like

```
tickets/ABC123-45678/
├── ticket.md        # the compact version the assistant reads first
├── images/          # screenshots pulled out of the emails
├── attachments/     # thread files and email attachments
├── text/            # full plain text of each email
├── raw/             # original email HTML
└── detail.json      # raw thread list from the API
```

See [`examples/ticket.md`](examples/ticket.md) for a fetched ticket and [`examples/report.md`](examples/report.md) for the report the playbook produces.

## Configuration

`config.json` is written by `install.py` and git-ignored. Every key is shown in [`config.example.json`](config.example.json).

| Key | Meaning | Default |
|---|---|---|
| `base_url` | Ticket service root | none (required) |
| `tickets_dir` | Where tickets are saved | `tickets/` in this repo (git-ignored) |
| `context_dir` | Code map folder | none |
| `token` | Sent as `Authorization: Bearer <token>` | none |
| `headers` | Extra request headers | `{}` |
| `ticket_pattern` | Regex a ticket number must match (also blocks path tricks) | `^[A-Za-z0-9][A-Za-z0-9-]{3,40}$` |
| `email_body_suffix` | File-name suffix that marks an email body | `_email_body.html` |
| `endpoints` | URL templates (see below) | |
| `fields` | JSON field names in the detail response | |

Precedence: command-line flags → environment variables (`TICKET_AGENT_BASE_URL`, `TICKET_AGENT_TICKETS_DIR`, `TICKET_AGENT_TOKEN`) → `config.json` → defaults.

## Adapting it to your helpdesk

The fetcher expects four GET endpoints, each a template under `base_url`:

| Endpoint | Placeholders | Returns |
|---|---|---|
| `detail` | `{ticket}` | JSON with a list of threads (or the list itself when `fields.data_key` is `""`) |
| `file` | `{ticket}`, `{file}` | One thread file. Names ending in `.html` are treated as email bodies |
| `attachment_list` | `{ticket}`, `{stem}` | JSON list of attachment names for one email. Optional: set to `""` to skip |
| `attachment` | `{ticket}`, `{stem}`, `{file}` | One email attachment |

Each thread needs an id, an action, an author, a date, a note and a list of files. Map your API's names in `fields`.

If your API is shaped differently (pagination, POST search, OAuth), subclass `TicketApi` in `ticket_fetch.py` and override `detail`, `file`, `attachment_list` and `attachment`. Everything after the HTTP layer stays the same: HTML to text, image extraction and `ticket.md`.

The playbook also uses tools you probably already have: your code repository, a **read-only** database tool, and a browser automation tool with console and network access.

## Safety model

| Risk | Guardrail |
|---|---|
| Changing the helpdesk | The downloader only sends GET requests |
| Leaking customer data | `tickets/` and `config.json` are git-ignored; keep the folder off shared or synced drives |
| Prompt injection in ticket text | The playbook treats ticket text as data and quotes any embedded instructions to the user instead of following them |
| Accidental writes in the browser | Navigation, snapshots, console and network reads are allowed; Save/Submit/Delete/forms need the user's approval |
| Live database changes | A fixed-format `⚠️ DB CHANGE` question, a backup first, and an explicit "yes" each time. "Go ahead" on a plan does not count |
| Guessing | The report separates traced evidence from `UNVERIFIED` suspicions and states a confidence level |

## Design decisions

- **Text first, images on demand.** Screenshots cost far more context than text, so `ticket.md` lists them with sizes and dimensions and the assistant opens only the ones that matter.
- **Trace the visible symptom to the data.** For "greyed out / hidden / can't select" tickets, the playbook follows the CSS class or template variable to the code that sets it, then to the database column. This beats guessing at nearby flags.
- **Use the app's own calls for data fixes.** When a fix is something a screen already does, running that same request from a signed-in browser keeps the application's validation and audit log, unlike raw SQL.
- **One file, no packages.** It runs on any machine with Python, including locked-down work PCs.

## FAQ

**What is ai-ticket-agent?**
An open-source toolkit that lets an AI coding assistant investigate customer support tickets. It has a Python downloader that turns a helpdesk ticket into compact Markdown, and an investigation playbook (`SKILL.md`) the assistant follows to find and prove the root cause.

**Which AI assistants does it work with?**
Any coding assistant that can run shell commands and load Markdown playbooks or skills. The downloader is plain Python and works with or without an assistant.

**Does it work with Zendesk, Freshdesk, Jira Service Management or a custom helpdesk?**
It works with any service that exposes ticket threads and files over HTTP. Endpoint templates and field names are configurable. For APIs with a different shape, you override four small methods in one class.

**Can the AI change my production data?**
Not on its own. The downloader is read-only, and the playbook only allows read-only queries and browser actions. A data change needs a specific confirmation question, a backup, and an explicit "yes" from a person every time.

**How much smaller is the output?**
A typical 400 KB HTML email becomes about 5 KB of text, plus its screenshots as separate files.

**Does it need internet access or an API key for the tests?**
No. The test suite runs fully offline against a fake API.

## Tests

```bash
python -m unittest discover tests
```

## License

MIT — see [LICENSE](LICENSE).

---

**Keywords:** AI support ticket investigation, root cause analysis, AI coding assistant skill, SKILL.md playbook, helpdesk ticket downloader, email to Markdown, prompt-injection safety, human-in-the-loop, read-only debugging, Python CLI.
