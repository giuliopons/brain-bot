#!/usr/bin/env python3
"""
brain-bot — cattura veloce da Telegram nell'inbox del second brain.

Ogni messaggio (testo, link, foto, documenti, inoltri) diventa un file
Markdown in inbox/ del vault. Poi commit + push sul repo bare locale, che
a sua volta fa il mirror su GitHub (hook post-receive).

Solo libreria standard: niente pip, niente venv.
Configurazione via variabili d'ambiente (le mette systemd da /etc/brain-bot.env):
  BRAIN_BOT_TOKEN            token di @BotFather (obbligatorio)
  BRAIN_BOT_ALLOWED_USER_ID  il tuo user id Telegram; se vuoto il bot te lo dice
  BRAIN_VAULT                clone di lavoro del bot (default ~/vault)
  BRAIN_BARE_REPO            repo bare centrale, usato da /cerca (default ~/brain.git)
  BRAIN_TZ                   fuso orario per i nomi file (default Europe/Rome)
"""
import json
import logging
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TOKEN = os.environ["BRAIN_BOT_TOKEN"]
ALLOWED_USER_ID = int(os.environ.get("BRAIN_BOT_ALLOWED_USER_ID") or 0)
VAULT = Path(os.environ.get("BRAIN_VAULT") or Path.home() / "vault")
BARE_REPO = Path(os.environ.get("BRAIN_BARE_REPO") or Path.home() / "brain.git")
TZ = ZoneInfo(os.environ.get("BRAIN_TZ") or "Europe/Rome")
STATE_FILE = Path.home() / ".brain-bot-offset"
MAX_DOWNLOAD = 20 * 1024 * 1024  # limite della Bot API per scaricare file
TG_MAX = 4096                     # lunghezza massima di un messaggio Telegram

API = f"https://api.telegram.org/bot{TOKEN}"
FILE_API = f"https://api.telegram.org/file/bot{TOKEN}"
INBOX = VAULT / "inbox"
ATTACH = INBOX / "attachments"

log = logging.getLogger("brain-bot")

# media_group_id -> nota: le foto di un album finiscono nella stessa nota
album_notes: dict[str, Path] = {}


# ---------------------------------------------------------------- Telegram

def tg(method: str, **params):
    """Chiama un metodo della Bot API e restituisce il campo 'result'."""
    data = urllib.parse.urlencode(params).encode()
    try:
        with urllib.request.urlopen(f"{API}/{method}", data=data, timeout=70) as r:
            resp = json.load(r)
    except urllib.error.HTTPError as e:
        # Telegram spiega l'errore nel corpo JSON; l'URL (col token) non va nei log
        desc = json.loads(e.read() or b"{}").get("description", "")
        raise RuntimeError(f"Telegram {method}: HTTP {e.code} {desc}") from None
    if not resp.get("ok"):
        raise RuntimeError(f"Telegram {method}: {resp.get('description')}")
    return resp["result"]


def reply(chat_id: int, text: str, to_message: int | None = None) -> None:
    # niente anteprime dei link: le risposte del bot sono solo testo
    params = {"chat_id": chat_id, "text": text,
              "link_preview_options": json.dumps({"is_disabled": True})}
    if to_message:
        params["reply_parameters"] = json.dumps({"message_id": to_message})
    tg("sendMessage", **params)


def download(file_id: str, dest_dir: Path, stem: str, default_ext: str) -> Path:
    """Scarica un file di Telegram in dest_dir e restituisce il percorso."""
    info = tg("getFile", file_id=file_id)
    if info.get("file_size", 0) > MAX_DOWNLOAD:
        raise RuntimeError("file oltre 20 MB, Telegram non lo lascia scaricare ai bot")
    ext = Path(info["file_path"]).suffix or default_ext
    dest = unique_path(dest_dir, stem, ext)
    with urllib.request.urlopen(f"{FILE_API}/{info['file_path']}", timeout=120) as r, \
            open(dest, "wb") as f:
        shutil.copyfileobj(r, f)
    return dest


# ---------------------------------------------------------------- git

def git(*args: str) -> str:
    res = subprocess.run(["git", *args], cwd=VAULT, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"git {args[0]}: {res.stderr.strip()}")
    return res.stdout


def pull() -> None:
    git("pull", "-q", "--rebase", "origin", "main")


def commit_and_push(message: str) -> None:
    # -A inbox: include anche eventuali file rimasti da un errore precedente
    git("add", "-A", "inbox")
    git("commit", "-q", "-m", message)
    for attempt in range(3):
        try:
            git("push", "-q", "origin", "HEAD:main")
            return
        except RuntimeError:
            # qualcuno (il PC) ha pushato nel frattempo: riallineati e riprova
            time.sleep(2)
            pull()
    raise RuntimeError("push fallito dopo 3 tentativi (il commit resta in locale)")


# ---------------------------------------------------------------- ricerca

SEARCH_FILES = 10  # file mostrati al massimo
SEARCH_LINES = 2   # righe per file
SEARCH_WIDTH = 150  # caratteri per riga


def clip(text: str, limit: int) -> str:
    """Tronca a 'limit' unità UTF-16 (come le conta Telegram), con '…' finale."""
    if len(text.encode("utf-16-le")) // 2 <= limit:
        return text
    raw = text.encode("utf-16-le")[:(limit - 1) * 2]
    return raw.decode("utf-16-le", errors="ignore") + "…"


def search(term: str) -> str:
    """Cerca 'term' (testo letterale, senza maiuscole) nelle note del repo bare.

    Sola lettura: git grep sull'albero di main, niente pull né lock.
    """
    try:
        # -z: separatori NUL, così i percorsi con ':' non confondono il parsing.
        # -e: un termine che inizia con '-' non viene letto come opzione.
        res = subprocess.run(
            ["git", "-C", str(BARE_REPO), "grep", "-z", "-i", "-F", "-n", "-I",
             "--max-count", str(SEARCH_LINES), "-e", term, "main", "--", "*.md"],
            capture_output=True, text=True, timeout=10)
    except subprocess.TimeoutExpired:
        raise RuntimeError("ricerca troppo lenta, riprova con una parola più specifica") from None
    if res.returncode == 1:
        return f'Nessun risultato per "{term}".'
    if res.returncode != 0:
        raise RuntimeError(f"git grep: {res.stderr.strip()[:200]}")

    # righe nel formato main:<path>\0<n>\0<testo>
    files: dict[str, list[str]] = {}
    for rec in res.stdout.splitlines():
        parts = rec.split("\0", 2)
        if len(parts) != 3:
            continue
        path, num, line = parts
        # senza ".md": Telegram lo scambierebbe per un dominio (Moldavia) e ne farebbe un link
        path = path.removeprefix("main:").removesuffix(".md")
        files.setdefault(path, []).append(f"  {num}: {clip(line.strip(), SEARCH_WIDTH)}")

    out = [f'🔎 "{term}" — {len(files)} file']
    for path, lines in list(files.items())[:SEARCH_FILES]:
        out.append(path)
        out.extend(lines[:SEARCH_LINES])
    if len(files) > SEARCH_FILES:
        out.append(f"…e altri {len(files) - SEARCH_FILES} file")
    return clip("\n".join(out), TG_MAX)


# ---------------------------------------------------------------- note

def unique_path(directory: Path, stem: str, ext: str) -> Path:
    path, n = directory / f"{stem}{ext}", 2
    while path.exists():
        path, n = directory / f"{stem}-{n}{ext}", n + 1
    return path


def apply_text_links(text: str, entities: list | None) -> str:
    """Trasforma i testi con link nascosto ('text_link') in [testo](url).

    Gli offset di Telegram sono in unità UTF-16 (le emoji contano 2),
    quindi si lavora sulla stringa codificata UTF-16.
    """
    links = [e for e in entities or [] if e["type"] == "text_link"]
    if not links:
        return text
    raw, out, pos = text.encode("utf-16-le"), [], 0
    for e in sorted(links, key=lambda e: e["offset"]):
        start, end = e["offset"] * 2, (e["offset"] + e["length"]) * 2
        out.append(raw[pos:start].decode("utf-16-le"))
        out.append(f"[{raw[start:end].decode('utf-16-le')}]({e['url']})")
        pos = end
    out.append(raw[pos:].decode("utf-16-le"))
    return "".join(out)


def forward_source(msg: dict) -> str | None:
    """Da dove arriva un messaggio inoltrato, in forma leggibile."""
    o = msg.get("forward_origin")
    if not o:
        return None
    if o["type"] == "user":
        u = o["sender_user"]
        return " ".join(filter(None, [u.get("first_name"), u.get("last_name")]))
    if o["type"] == "hidden_user":
        return o["sender_user_name"]
    if o["type"] == "chat":
        return o["sender_chat"].get("title")
    if o["type"] == "channel":
        chat = o["chat"]
        if chat.get("username"):
            return f"{chat.get('title')} (https://t.me/{chat['username']}/{o['message_id']})"
        return chat.get("title")
    return None


def frontmatter(dt: datetime, fwd: str | None) -> str:
    lines = ["---", f"created: {dt:%Y-%m-%dT%H:%M}", "source: telegram"]
    if fwd:
        lines.append(f"forwarded_from: {json.dumps(fwd, ensure_ascii=False)}")
    return "\n".join(lines + ["---", "", ""])


# ---------------------------------------------------------------- messaggi

HELP = ("Scrivimi qualsiasi cosa: testo, link, foto, documenti, messaggi inoltrati.\n"
        "Finisce in inbox/ del second brain. I vocali non sono ancora supportati.\n\n"
        "/cerca parola — cerca nelle note del second brain.")


def parse_command(text: str | None) -> tuple[str, str] | None:
    """'/cerca@bot  foo bar' -> ('/cerca', 'foo bar'); None se non è un comando."""
    if not text or not text.startswith("/"):
        return None
    head, *rest = text.split(maxsplit=1)
    return head.split("@", 1)[0], (rest[0] if rest else "").strip()


def handle(msg: dict) -> None:
    chat_id, msg_id = msg["chat"]["id"], msg["message_id"]
    user_id = msg.get("from", {}).get("id")

    if not ALLOWED_USER_ID:
        reply(chat_id, f"Il tuo user id è {user_id}.\nMettilo in BRAIN_BOT_ALLOWED_USER_ID "
                       "(/etc/brain-bot.env) e riavvia il bot.")
        return
    if user_id != ALLOWED_USER_ID or msg["chat"]["type"] != "private":
        log.warning("ignorato messaggio da user id %s", user_id)
        return

    cmd = parse_command(msg.get("text"))
    if cmd and cmd[0] in ("/start", "/help"):
        reply(chat_id, HELP)
        return
    if cmd and cmd[0] == "/cerca":
        # solo la prima riga: con -F un a capo diventerebbe un secondo pattern
        term = (cmd[1].splitlines() or [""])[0].strip()
        if not term:
            reply(chat_id, "Uso: /cerca parola", msg_id)
        elif len(term) < 3:
            reply(chat_id, "Parola troppo corta: almeno 3 caratteri.", msg_id)
        else:
            reply(chat_id, search(term), msg_id)
        return
    if any(k in msg for k in ("voice", "audio", "video_note")):
        reply(chat_id, "🎙 Vocali non ancora supportati: scrivilo, per ora.", msg_id)
        return

    text = apply_text_links(msg.get("text") or msg.get("caption") or "",
                            msg.get("entities") or msg.get("caption_entities"))
    dt = datetime.fromtimestamp(msg["date"], TZ)
    stem = f"{dt:%Y-%m-%d-%H%M%S}"

    attachment = None
    if "photo" in msg:
        attachment = (msg["photo"][-1]["file_id"], ".jpg")  # l'ultima è la più grande
    elif "document" in msg:
        doc = msg["document"]
        attachment = (doc["file_id"], Path(doc.get("file_name", "")).suffix or ".bin")
    elif "video" in msg:
        attachment = (msg["video"]["file_id"], ".mp4")

    if not text and not attachment:
        reply(chat_id, "🤷 Tipo di messaggio non supportato.", msg_id)
        return

    pull()
    ATTACH.mkdir(parents=True, exist_ok=True)

    body = []
    if attachment:
        saved = download(attachment[0], ATTACH, stem, attachment[1])
        body.append(f"![[{saved.name}]]")
    if text:
        body.append(text)

    group = msg.get("media_group_id")
    if group and group in album_notes and album_notes[group].exists():
        # foto successiva dello stesso album: aggiungila alla nota esistente
        note = album_notes[group]
        with open(note, "a", encoding="utf-8") as f:
            f.write("\n" + "\n\n".join(body) + "\n")
    else:
        note = unique_path(INBOX, stem, ".md")
        note.write_text(frontmatter(dt, forward_source(msg)) + "\n\n".join(body) + "\n",
                        encoding="utf-8")
        if group:
            album_notes[group] = note

    first_line = (text.splitlines() or ["allegato"])[0][:60]
    commit_and_push(f"inbox: {first_line}")
    reply(chat_id, f"✅ {note.relative_to(VAULT)}", msg_id)
    log.info("salvato %s", note.relative_to(VAULT))


# ---------------------------------------------------------------- main loop

def load_offset() -> int:
    try:
        return int(STATE_FILE.read_text())
    except (FileNotFoundError, ValueError):
        return 0


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    offset = load_offset()
    log.info("avviato — vault %s, utente autorizzato %s", VAULT, ALLOWED_USER_ID or "NON IMPOSTATO")
    while True:
        try:
            # long polling: la richiesta resta aperta fino a 50 s o al primo messaggio.
            # Nessuna porta da aprire sul router.
            updates = tg("getUpdates", offset=offset, timeout=50,
                         allowed_updates=json.dumps(["message"]))
        except Exception as e:
            log.warning("getUpdates: %s — riprovo tra 10 s", e)
            time.sleep(10)
            continue
        for update in updates:
            offset = update["update_id"] + 1
            msg = update.get("message")
            if msg:
                try:
                    handle(msg)
                except Exception as e:
                    log.exception("errore sul messaggio %s", msg.get("message_id"))
                    try:
                        reply(msg["chat"]["id"], f"❌ Errore: {e}", msg["message_id"])
                    except Exception:
                        pass
            STATE_FILE.write_text(str(offset))


if __name__ == "__main__":
    main()
