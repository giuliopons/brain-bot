# HANDOFF — next features for brain-bot

Read `CLAUDE.md` first. Every feature must respect its hard constraints (public repo, stdlib only, sandbox, token never logged, bot never modifies notes).
Every user-visible change must also update `README.md` and `docs/installazione.md` (Italian).

---

## 1. ✅ DONE — `/cerca <parola>`

Implemented in `bot.py` (`search()`, `parse_command()`), tests in `tests/test_bot.py`. Deviations from the design below:
- `git grep` runs with **`-z`**: output is `main:<path>\0<n>\0<text>`, so paths containing `:` parse correctly (`split(":", 3)` would break).
- File names are shown **without `.md`** (`projects/mail`), because Telegram turns `mail.md` into a link (`.md` = Moldova TLD).
- `reply()` always sends `link_preview_options={"is_disabled": true}` (all replies, not only `/cerca`).
- Only the first line of the message is used as the term (with `-F` a newline would become a second pattern).
- `/help@botusername` now works too.

Deployed and working on the server.
The ✅ capture reply now also omits `.md`.

Optional follow-up: @BotFather → `/setcommands` → `cerca - cerca nel second brain` (owner will do it).

The original spec is kept below for reference.

### Original spec

**Goal:** from the phone, send `/cerca mbsync` and get back which notes mention it, with the matching lines.

#### Design decision: `git grep` on the bare repo (preferred) vs `ripgrep` on the clone

The original idea was `ripgrep` on the vault. Recommended instead: **`git grep` on `/home/brain/brain.git`**:
- the bare repo is always up to date (the PC and the bot push there), while `/home/brain/vault` lags until the next capture;
- it is read-only: no `git pull`, no `index.lock` contention with capture;
- no extra dependency (git is already there, ripgrep is not installed).

```python
subprocess.run(
    ["git", "-C", BARE_REPO, "grep", "-i", "-F", "-n", "-I", "--max-count", "2",
     "-e", term, "main", "--", "*.md"],
    capture_output=True, text=True, timeout=10,
)
```
Output lines look like `main:path/to/note.md:12:text`: `line.split(":", 3)`.
Exit code **1 = no matches** (not an error). Any other non-zero code → reply with an error.

Fallback if `git grep` proves too slow on the Atom: `rg -i -F -n --max-count 2 --glob '*.md' -- <term>` on `VAULT` after a `pull()` (requires `sudo apt install ripgrep`; `/usr/bin/rg` is readable inside the sandbox).

#### Behaviour

- Match `/cerca` and `/cerca@<botusername>`; the rest of the text is the search term (strip it).
- Empty term → reply with usage: `Uso: /cerca parola`.
- Term shorter than 3 characters → refuse (too many matches).
- **No shell**: pass argv as a list; the `-e term` form prevents a term starting with `-` from being read as an option.
- Group results by file. Show at most **10 files**, **2 lines per file**, each line trimmed to ~150 chars.
  If more files match: `…e altri N file`.
- Keep the whole reply under Telegram's **4096-char** limit (truncate defensively).
- No results → `Nessun risultato per "term".`
- Read-only: never commits, never writes.
- Authorization is already enforced at the top of `handle()`; keep the command below those checks.
- Add a constant `BARE_REPO = Path(os.environ.get("BRAIN_BARE_REPO") or Path.home() / "brain.git")`.
- Update the `/help` text.
- Optional: register commands with @BotFather → `/setcommands` (`cerca - cerca nel second brain`).

#### Suggested reply format
```
🔎 "mbsync" — 3 file
projects/mail.md
  12: sincronizzo la posta con mbsync
  40: mbsync -a ogni 5 minuti
resources/email.md
  7: mbsync vs offlineimap
```
Send as plain text (no `parse_mode`), so note content can't break Markdown/HTML parsing.

#### Tests to add
- match in several files, limit 10 files / 2 lines;
- no match (exit code 1) → friendly message;
- term with leading `-` (e.g. `/cerca -rf`) is treated as text;
- term with regex characters (`a.b*`) matched literally (`-F`);
- reply length ≤ 4096 with a huge result set;
- `/cerca@mybot term` parsed correctly.

---

## 2. Weekly reminder: "hai 14 note in inbox"

**Goal:** once a week, a Telegram message with the number of notes waiting in `inbox/`, to trigger the weekly review.

### Design

- **One-shot mode of the same script** (`bot.py --remind`) run by a **systemd timer**, not a thread in the long-running bot and not crontab: same env file, same sandbox, logs in the journal, `Persistent=true` catches runs missed while the MiniPC was off.
- Count from the **bare repo**, not from the clone (always current, no pull, no lock):
  ```
  git -C /home/brain/brain.git ls-tree --name-only main inbox/
  ```
  Count entries ending in `.md` (ignores `attachments/` and `.gitkeep`).
- Optionally include the age of the oldest note (the date is in the file name `YYYY-MM-DD-...`).
- Send to `chat_id = BRAIN_BOT_ALLOWED_USER_ID` (in a private chat, chat id = user id).
- **0 notes → send nothing** (no noise).
- `--remind` must not enter the polling loop and must not touch the offset file; it exits after sending (non-zero exit on failure, so `systemctl status` shows it).

### Message
```
📥 Hai 14 note in inbox (la più vecchia è di 9 giorni).
È il momento della revisione settimanale: integra, crea o cancella.
```
Singular form for 1 note: `Hai 1 nota in inbox`.

### Units (install them from `setup-bot.sh`)

`brain-bot-remind.service`
```ini
[Unit]
Description=brain-bot: promemoria settimanale inbox

[Service]
Type=oneshot
User=brain
Group=brain
EnvironmentFile=/etc/brain-bot.env
ExecStart=/usr/bin/python3 /home/brain/bot/bot.py --remind
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=tmpfs
BindPaths=/home/brain
PrivateTmp=true
```

`brain-bot-remind.timer`
```ini
[Unit]
Description=brain-bot: promemoria settimanale inbox (domenica 18:00)

[Timer]
OnCalendar=Sun *-*-* 18:00:00 Europe/Rome
Persistent=true

[Install]
WantedBy=timers.target
```
(`OnCalendar` with a timezone needs systemd ≥ 235; Ubuntu 24.04 ships 255.)

In `setup-bot.sh`: install both units, `systemctl daemon-reload`, `systemctl enable --now brain-bot-remind.timer`.
Document it in `README.md` (features) and `docs/installazione.md` (verify / operate sections).

### Verify
```bash
sudo systemctl start brain-bot-remind.service     # send now
systemctl list-timers brain-bot-remind.timer       # next run
journalctl -u brain-bot-remind -n 20
```

### Tests to add
- count with notes + attachments + `.gitkeep` → only `.md` counted;
- 0 notes → nothing sent;
- 1 note → singular text;
- oldest-note age computed from file names.

---

## 3. ✅ DONE — note titles from Claude Haiku

Implemented in `titles.py` (imported by `bot.py`), see `CLAUDE.md` → How it works. Owner's choices: file name = date + slug,
`title:` in the frontmatter, Claude sees text + linked page title + photos. Opt-in via `ANTHROPIC_API_KEY`.

To do by hand: create the API key (with a spend limit), add it to `/etc/brain-bot.env`, `sudo bash setup-bot.sh`, try text / link / photo.

Possible follow-ups:
- a one-sentence `summary:` in the frontmatter (same call, structured output with two fields);
- titles for images sent as documents, and for PDFs (document blocks);
- suggest a destination folder for the note (would help the weekly review, see §2).

---

## Also worth doing (small)

- Publish: the repo is ready for a public GitHub remote (README, LICENSE, install guide, personal data removed). Not pushed yet.
  Note: the first commit still contains the old, more personal versions of `CLAUDE.md`/`HANDOFF.md` (owner's decision to keep history as is).
- `setup-server.sh` makes the GitHub mirror mandatory. Possible improvement: make it optional (vault kept only on the server).
- Bot replies are Italian only. If non-Italian users show up, move the strings into one place before translating.
- `tests/test_bot.py` exists (covers `/cerca`). Still to move there: the ad-hoc capture tests described in `CLAUDE.md`.