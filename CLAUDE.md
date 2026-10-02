# brain-bot

Telegram bot that captures messages into the `inbox/` of the owner's second brain (a Markdown + git vault).
Runs on a small home server as a systemd service. Reference hardware: MiniPC with Ubuntu Server 24.04, Intel Atom x5-Z8350, 4 GB RAM, eMMC.

**This repo is public (open source, MIT).** The vault is a separate, private repo: the bot only reaches it at runtime through `BRAIN_VAULT` / `BRAIN_BARE_REPO`.
User docs: `README.md` and `docs/installazione.md` (Italian).

## How it works

- **Long polling** (`getUpdates`, 50 s timeout). No webhook, no open ports: the MiniPC is behind NAT.
- Each message from the authorized user becomes `inbox/YYYY-MM-DD-HHMMSS.md` (Europe/Rome time) with a small YAML frontmatter.
  Photos/documents/videos are saved in `inbox/attachments/` and embedded with `![[file]]`. Album photos go into one note.
- After writing: `git pull --rebase` → `git add -A inbox` → `git commit` → `git push origin HEAD:main`, retried up to 3 times.
- The push lands in the bare repo `/home/brain/brain.git`, whose `post-receive` hook mirrors to GitHub in the background.
- Replies ✅ with the note path without `.md` (see below), or ❌ with the error.
- **`/cerca <parola>`** searches the vault, read-only: `git grep -z -i -F` on the bare repo's `main` (`*.md` only), never on the clone.
  At most 10 files × 2 lines, lines cut at 150 chars, reply capped at 4096 UTF-16 units. Term < 3 chars refused; only the first line of the message is used.
  File names are shown **without `.md`**: Telegram auto-links `name.md` (Moldova TLD) even in plain text.
- **Note titles (optional, `titles.py`)**: with `ANTHROPIC_API_KEY` set, each new note gets a title from Claude Haiku (`claude-haiku-4-5`, raw HTTP via urllib — no SDK, stdlib only).
  Input: text/caption (+ document file name), the `<title>` of the first linked page (first 64 KB, 5 s), and the photo (vision).
  Output: `title:` in the frontmatter, slug in the file name (`inbox/YYYY-MM-DD-HHMMSS-<slug>.md`, slug `[a-z0-9-]`, ≤ 60 chars), commit message `inbox: <title>`.
  Album: only the first message is titled. Every failure (no key, timeout, HTTP error, odd reply) → `None` → date-only name, exactly as before. `titles.py` never raises.
- All replies are plain text (no `parse_mode`) with link previews disabled (`link_preview_options`).
- Commands also accept the `/cmd@botusername` form (`parse_command()`).

## Layout

This repo (cloned anywhere on the server, e.g. `~/brain-bot`) is the **source**. It is not the running copy.

| File | Purpose |
|---|---|
| `bot.py` | the bot |
| `titles.py` | optional note titles from Claude Haiku, imported by `bot.py` |
| `brain-bot.service` | systemd unit |
| `setup-server.sh` | one-time server setup: `brain` user, bare repo, GitHub mirror. Run before `setup-bot.sh` |
| `setup-bot.sh` | bot installer / updater, run with `sudo bash setup-bot.sh` |
| `tests/test_bot.py` | test suite (stdlib `unittest`), not deployed |
| `README.md`, `docs/installazione.md` | user-facing docs (Italian) |
| `LICENSE` | MIT |

Installed locations (owned by user `brain`, not readable by your admin user without sudo):

| Path | What |
|---|---|
| `/home/brain/bot/bot.py`, `titles.py` | running copy, overwritten by `setup-bot.sh` |
| `/home/brain/vault` | bot's working clone of the vault |
| `/home/brain/brain.git` | central bare repo (origin of the PC and of the bot); `post-receive` → `~/bin/mirror.sh` |
| `/home/brain/mirror.log` | GitHub mirror results |
| `/home/brain/.brain-bot-offset` | last processed Telegram `update_id` |
| `/etc/brain-bot.env` | `BRAIN_BOT_TOKEN`, `BRAIN_BOT_ALLOWED_USER_ID`, optional `ANTHROPIC_API_KEY` (mode 600) |
| `/etc/systemd/system/brain-bot.service` | installed unit |

Environment variables: `BRAIN_BOT_TOKEN` (required), `BRAIN_BOT_ALLOWED_USER_ID` (if empty, the bot only replies with the sender's id), `BRAIN_VAULT` (default `~/vault`), `BRAIN_BARE_REPO` (default `~/brain.git`, used by `/cerca`), `BRAIN_TZ` (default `Europe/Rome`), `ANTHROPIC_API_KEY` (optional, enables note titles).

## Hard constraints

- **Public repo**: never commit tokens, user ids, hostnames, vault content or other personal data — not in code, docs, tests or examples. Test fixtures use made-up notes.
- **Python standard library only** (Python ≥ 3.10). No pip, no venv, no third-party packages.
- **Never log or echo the token or the Anthropic API key.** The Telegram API URL contains the token and the Claude request headers contain the key: do not log URLs, headers or raw urllib exceptions that could include them. Do not log note content either.
- **Third-party calls are opt-in and never block a capture.** Claude is only called for the authorized user's messages, only with `ANTHROPIC_API_KEY` set; any failure falls back to the date-only name. Tests must never reach the real API (`tests/test_bot.py` unsets the key and fakes `urlopen`).
- **Only the authorized user, only private chats.** Everything else is ignored (logged as a warning, no reply).
- **The bot only adds files under `inbox/`.** It never modifies or deletes existing notes. This is what keeps it conflict-free with the PC.
- **Never force push, never rewrite history.** The bare repo rejects it anyway (`receive.denyNonFastForwards`, `receive.denyDeletes`).
- **Stay inside the sandbox**: the unit uses `ProtectSystem=strict`, `ProtectHome=tmpfs`, `BindPaths=/home/brain`, `NoNewPrivileges`, `PrivateTmp`, `MemoryMax=150M`. The bot can only write under `/home/brain`; other homes are invisible. Don't loosen these without a reason written in the commit/HANDOFF.
- Low resources: keep memory small, no heavy libraries, no local LLMs.
- Languages:
  - **Italian**: bot replies, script messages shown to the user, user docs (`README.md`, `docs/`).
  - **English**: code comments, `CLAUDE.md`, `HANDOFF.md`. Older Italian comments are translated when that code is touched; keep comments short.

## Deploy / operate

```bash
# after editing bot.py here (from the repo folder):
sudo bash setup-bot.sh          # copies bot.py + unit, restarts; keeps token and vault

systemctl status brain-bot
journalctl -u brain-bot -f                   # live logs
sudo tail /home/brain/mirror.log             # GitHub mirror results
sudo -u brain -H bash                        # shell as brain (its login shell is git-shell)
```

`setup-bot.sh` is idempotent. It asks for the token only if `/etc/brain-bot.env` does not exist,
and refuses to run if the bare repo has no `main` yet (the vault must be pushed first).
`setup-server.sh` is idempotent too. Full first-time procedure (BotFather included): `docs/installazione.md` — keep it in sync with the scripts.

## Testing

`tests/test_bot.py` (stdlib `unittest`, temp repos, no network): `python3 -m unittest discover -s tests -v`.
Covers `/cerca`, reply parameters, capture with/without titles (text, link, photo, album) and `titles.py` (fake `urlopen`).
It sets `BRAIN_BARE_REPO`/`BRAIN_VAULT` to temp repos and replaces `bot.reply`/`bot.tg`/`bot.download`/`titles.*`.
The older ad-hoc capture cases below are not all in the suite yet. The approach used so far:
- Import `bot` with fake env vars (`BRAIN_BOT_TOKEN=x`, `BRAIN_BOT_ALLOWED_USER_ID=42`, `BRAIN_VAULT=<tmp clone>`).
- Monkeypatch `bot.reply` (collect sent texts) and `bot.download` (write a dummy file).
- Create a temp bare repo + a "PC" clone + the bot clone; feed `bot.handle()` fake message dicts.
- Cases that must keep passing: unauthorized user ignored; text with `text_link` entities and emoji (UTF-16 offsets); forwarded from channel; album of 2 photos → one note; voice rejected; concurrent push from the PC between the bot's pull and push (must retry and succeed).

Never test against the real `/home/brain` repos or the real bot token.

## Open work

See `HANDOFF.md`.