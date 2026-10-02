"""Test di brain-bot: solo stdlib, repo temporanei, niente rete.

Uso:  python3 -m unittest discover -s tests -v
"""
import email.message
import importlib
import io
import json
import logging
import os
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
USER = 42
# never reach the real Claude API from tests, even if the key is in the shell
os.environ.pop("ANTHROPIC_API_KEY", None)
sys.path.insert(0, str(ROOT))
import titles  # noqa: E402


def run(*args, cwd):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


class CercaTest(unittest.TestCase):
    """/cerca: git grep sul repo bare."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls.tmp.name)
        work = tmp / "work"
        notes = {
            "projects/mail.md": "intro\nsincronizzo la posta con mbsync\naltro\n"
                            "mbsync -a ogni 5 minuti\nterza riga MBSYNC\n",
            "resources/email.md": "mbsync vs offlineimap\n",
            "strano/a b:c.md": "riga con mbsync\n",
            "altro.txt": "mbsync fuori dai .md\n",
            "trappola.md": "comando -rf pericoloso\nletterale a.b* qui\naxxb niente\n",
            "lunga.md": "zzlong " + "x" * 5000 + "\n",
        }
        for i in range(15):
            notes[f"molti/n{i:02}.md"] = "parolacomune\n" * 5
        for i in range(40):
            notes[f"enormi/{'d' * 80}{i:02}.md"] = ("parolaenorme " + "y" * 300 + "\n") * 3
        for rel, text in notes.items():
            f = work / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(text, encoding="utf-8")
        run("git", "init", "-q", "-b", "main", cwd=work)
        run("git", "add", ".", cwd=work)
        run("git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init", cwd=work)
        run("git", "clone", "-q", "--bare", str(work), str(tmp / "brain.git"), cwd=tmp)
        # the bot's working clone, used by the capture test
        run("git", "clone", "-q", str(tmp / "brain.git"), str(tmp / "vault"), cwd=tmp)
        run("git", "config", "user.name", "brain-bot", cwd=tmp / "vault")
        run("git", "config", "user.email", "bot@test", cwd=tmp / "vault")

        os.environ.update(BRAIN_BOT_TOKEN="x", BRAIN_BOT_ALLOWED_USER_ID=str(USER),
                          BRAIN_VAULT=str(tmp / "vault"), BRAIN_BARE_REPO=str(tmp / "brain.git"))
        sys.path.insert(0, str(ROOT))
        cls.bot = importlib.reload(importlib.import_module("bot"))
        cls.real_reply = cls.bot.reply

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.sent = []
        self.bot.reply = lambda chat_id, text, to_message=None: self.sent.append(text)

    def ask(self, text, user=USER):
        self.sent.clear()
        self.bot.handle({"message_id": 1, "date": 0, "text": text,
                         "chat": {"id": user, "type": "private"}, "from": {"id": user}})
        return self.sent

    def one(self, text):
        sent = self.ask(text)
        self.assertEqual(len(sent), 1)
        return sent[0]

    def test_match_piu_file(self):
        r = self.one("/cerca mbsync")
        self.assertTrue(r.startswith('🔎 "mbsync" — 3 file'))
        self.assertNotIn(".md\n", r)      # nomi file senza estensione: niente link
        self.assertIn("projects/mail\n  2: sincronizzo la posta con mbsync\n"
                      "  4: mbsync -a ogni 5 minuti", r)
        self.assertNotIn("MBSYNC", r)       # max 2 righe per file
        self.assertIn("resources/email\n  1: mbsync vs offlineimap", r)
        self.assertNotIn("altro.txt", r)    # solo *.md

    def test_percorso_con_due_punti_e_spazi(self):
        self.assertIn("strano/a b:c\n  1: riga con mbsync", self.one("/cerca mbsync"))

    def test_limite_dieci_file(self):
        r = self.one("/cerca parolacomune")
        self.assertIn("— 15 file", r)
        self.assertEqual(r.count("molti/"), 10)
        self.assertTrue(r.endswith("…e altri 5 file"))

    def test_nessun_risultato(self):
        self.assertEqual(self.one("/cerca inesistente"), 'Nessun risultato per "inesistente".')

    def test_trattino_iniziale(self):
        self.assertIn("trappola\n  1: comando -rf pericoloso", self.one("/cerca -rf"))

    def test_regex_letterale(self):
        r = self.one("/cerca a.b*")
        self.assertIn("2: letterale a.b* qui", r)
        self.assertNotIn("axxb", r)

    def test_riga_lunga_troncata(self):
        r = self.one("/cerca zzlong")
        line = r.splitlines()[-1]
        self.assertLessEqual(len(line), 160)
        self.assertTrue(line.endswith("…"))

    def test_risposta_entro_4096(self):
        r = self.one("/cerca parolaenorme")
        self.assertLessEqual(len(r.encode("utf-16-le")) // 2, 4096)
        self.assertIn("…e altri 30 file", r)
        self.assertLessEqual(len(self.bot.clip("😀" * 5000, 4096).encode("utf-16-le")) // 2, 4096)

    def test_comando_con_username(self):
        self.assertTrue(self.one("/cerca@mybot   mbsync  ").startswith('🔎 "mbsync"'))

    def test_uso_e_parola_corta(self):
        self.assertEqual(self.one("/cerca"), "Uso: /cerca parola")
        self.assertEqual(self.one("/cerca   "), "Uso: /cerca parola")
        self.assertIn("troppo corta", self.one("/cerca ab"))

    def test_solo_prima_riga(self):
        self.assertTrue(self.one("/cerca mbsync\nparolacomune").startswith('🔎 "mbsync" — 3 file'))

    def test_help_con_username(self):
        self.assertIn("/cerca", self.one("/help@mybot"))

    def test_utente_non_autorizzato(self):
        self.assertEqual(self.ask("/cerca mbsync", user=7), [])

    def test_cattura_risposta_senza_md(self):
        r = self.one("nota catturata nel test")
        self.assertRegex(r, r"^✅ inbox/\d{4}-\d{2}-\d{2}-\d{6}(-\d+)?$")
        note = Path(self.tmp.name) / "vault" / (r[2:] + ".md")
        self.assertIn("nota catturata nel test", note.read_text(encoding="utf-8"))

    def capture(self, msg_extra, date):
        self.sent.clear()
        msg = {"message_id": 1, "date": date,
               "chat": {"id": USER, "type": "private"}, "from": {"id": USER}, **msg_extra}
        self.bot.handle(msg)
        self.assertEqual(len(self.sent), 1)
        return self.sent[0]

    def with_titles(self, fake_title):
        """Enable titles with a fake make_title; returns the list of its calls."""
        calls = []
        def fake(text="", image=None, page=None):
            calls.append((text, image, page))
            return fake_title
        patches = {"enabled": lambda: True, "make_title": fake, "page_title": lambda url: "Pagina X"}
        old = {k: getattr(titles, k) for k in patches}
        for k, v in patches.items():
            setattr(titles, k, v)
        self.addCleanup(lambda: [setattr(titles, k, v) for k, v in old.items()])
        return calls

    def test_cattura_con_titolo(self):
        calls = self.with_titles("Ricetta: pane con lievito madre!")
        r = self.capture({"text": "farina, acqua, lievito madre"}, date=1000)
        self.assertEqual(r, "✅ inbox/1970-01-01-011640-ricetta-pane-con-lievito-madre")
        note = Path(self.tmp.name) / "vault" / (r[2:] + ".md")
        content = note.read_text(encoding="utf-8")
        self.assertTrue(content.startswith('---\ntitle: "Ricetta: pane con lievito madre!"\ncreated:'))
        self.assertEqual(calls, [("farina, acqua, lievito madre", None, None)])
        log = subprocess.run(["git", "log", "-1", "--format=%s"], cwd=Path(self.tmp.name) / "vault",
                             capture_output=True, text=True).stdout.strip()
        self.assertEqual(log, "inbox: Ricetta: pane con lievito madre!")

    def test_cattura_link_passa_titolo_pagina(self):
        calls = self.with_titles("Articolo interessante")
        self.capture({"text": "da leggere https://example.com/a"}, date=2000)
        self.assertEqual(calls, [("da leggere https://example.com/a", None, "Pagina X")])

    def test_cattura_titolo_fallito_solo_data(self):
        self.with_titles(None)
        self.assertEqual(self.capture({"text": "qualcosa"}, date=3000), "✅ inbox/1970-01-01-015000")

    def test_cattura_foto_e_album(self):
        calls = self.with_titles("Lavagna riunione")
        def fake_download(file_id, dest_dir, stem, ext):
            dest = self.bot.unique_path(dest_dir, stem, ext)
            dest.write_bytes(b"\xff\xd8fake jpeg")
            return dest
        old, self.bot.download = self.bot.download, fake_download
        self.addCleanup(setattr, self.bot, "download", old)
        photo = {"photo": [{"file_id": "a"}], "media_group_id": "g1"}
        r = self.capture(photo, date=4000)
        self.assertEqual(r, "✅ inbox/1970-01-01-020640-lavagna-riunione")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1].name, "1970-01-01-020640.jpg")  # the photo goes to Claude
        # second photo of the same album: same note, no new title request
        self.assertEqual(self.capture({**photo, "photo": [{"file_id": "b"}]}, date=4000), r)
        self.assertEqual(len(calls), 1)

    def test_reply_senza_anteprime(self):
        calls = []
        old = self.bot.tg
        self.bot.tg = lambda method, **params: calls.append((method, params))
        try:
            self.real_reply(USER, "vedi https://example.com")
        finally:
            self.bot.tg = old
        method, params = calls[0]
        self.assertEqual(method, "sendMessage")
        self.assertEqual(json.loads(params["link_preview_options"]), {"is_disabled": True})
        self.assertNotIn("parse_mode", params)

    def test_repo_mancante(self):
        old = self.bot.BARE_REPO
        self.bot.BARE_REPO = Path(self.tmp.name) / "manca.git"
        try:
            with self.assertRaises(RuntimeError):
                self.bot.search("mbsync")
        finally:
            self.bot.BARE_REPO = old


class FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, content_type="application/json"):
        super().__init__(body)
        self.headers = email.message.Message()
        self.headers["Content-Type"] = content_type


class TitlesTest(unittest.TestCase):
    """titles.py with a fake urlopen: no network."""

    def setUp(self):
        self.requests = []
        os.environ["ANTHROPIC_API_KEY"] = "sk-test-SEGRETA"
        self.addCleanup(os.environ.pop, "ANTHROPIC_API_KEY", None)
        old = titles.urlopen
        self.addCleanup(setattr, titles, "urlopen", old)

    def answer(self, result):
        """Make urlopen record the request and return (or raise) result."""
        def fake(req, timeout):
            self.requests.append(req)
            if isinstance(result, Exception):
                raise result
            return result
        titles.urlopen = fake

    def api_reply(self, text, stop="end_turn"):
        return FakeResponse(json.dumps({"stop_reason": stop,
                                        "content": [{"type": "text", "text": text}]}).encode())

    def test_slugify(self):
        self.assertEqual(titles.slugify("Ricetta: pane con lievito madre!"), "ricetta-pane-con-lievito-madre")
        self.assertEqual(titles.slugify("Perché è così? 🚀 Città"), "perche-e-cosi-citta")
        self.assertEqual(titles.slugify("🚀🚀"), "")
        long = titles.slugify("parola " * 30)
        self.assertLessEqual(len(long), 60)
        self.assertFalse(long.endswith("-"))
        self.assertTrue(set(long) <= set("abcdefghijklmnopqrstuvwxyz0123456789-"))
        self.assertEqual(titles.slugify("../../etc/passwd"), "etc-passwd")

    def test_clean_title(self):
        self.assertEqual(titles.clean_title('  "**Titolo**  in `due`\nrighe."  '), "Titolo in due righe")
        self.assertEqual(titles.clean_title('"Titolo su\ndue righe."'), "Titolo su due righe")
        self.assertEqual(titles.clean_title("# Titolo"), "Titolo")
        self.assertEqual(len(titles.clean_title("x" * 500)), 100)

    def test_first_url(self):
        self.assertEqual(titles.first_url("vedi [qui](https://a.it/x?y=1) e altro"), "https://a.it/x?y=1")
        self.assertIsNone(titles.first_url("niente link"))

    def test_make_title_request(self):
        self.answer(self.api_reply("Pane con lievito madre"))
        self.assertEqual(titles.make_title("ricetta del pane", page="Il pane"), "Pane con lievito madre")
        req = self.requests[0]
        self.assertEqual(req.full_url, "https://api.anthropic.com/v1/messages")
        self.assertEqual(req.get_header("X-api-key"), "sk-test-SEGRETA")
        self.assertEqual(req.get_header("Anthropic-version"), "2023-06-01")
        body = json.loads(req.data)
        self.assertEqual(body["model"], "claude-haiku-4-5")
        text = body["messages"][0]["content"][-1]["text"]
        self.assertIn("<content>\nricetta del pane\n</content>", text)
        self.assertIn("<linked_page_title>Il pane</linked_page_title>", text)

    def test_make_title_con_foto(self):
        with tempfile.TemporaryDirectory() as d:
            img = Path(d) / "f.jpg"
            img.write_bytes(b"\xff\xd8jpeg")
            self.answer(self.api_reply("Lavagna"))
            self.assertEqual(titles.make_title("", image=img), "Lavagna")
        blocks = json.loads(self.requests[0].data)["messages"][0]["content"]
        self.assertEqual(blocks[0]["type"], "image")
        self.assertEqual(blocks[0]["source"]["media_type"], "image/jpeg")
        self.assertEqual(blocks[1]["text"], "A photo with no text.")

    def test_make_title_senza_chiave_niente_chiamate(self):
        os.environ.pop("ANTHROPIC_API_KEY")
        self.answer(self.api_reply("x"))
        self.assertIsNone(titles.make_title("testo"))
        self.assertEqual(self.requests, [])

    def test_make_title_niente_da_descrivere(self):
        self.answer(self.api_reply("x"))
        self.assertIsNone(titles.make_title("   "))
        self.assertEqual(self.requests, [])

    def test_make_title_errori(self):
        err = urllib.error.HTTPError(titles.API_URL, 401, "Unauthorized", None,
                                     io.BytesIO(b'{"error": {"message": "invalid x-api-key"}}'))
        for result in (err, TimeoutError(), self.api_reply("x", stop="max_tokens"),
                       FakeResponse(b"non json"), self.api_reply("   ")):
            self.answer(result)
            with self.assertLogs("brain-bot.titles", logging.WARNING) as cm:
                # an empty reply logs nothing: the marker keeps assertLogs from failing
                logging.getLogger("brain-bot.titles").warning("marker")
                self.assertIsNone(titles.make_title("testo"))
            self.assertNotIn("SEGRETA", "\n".join(cm.output))

    def test_page_title(self):
        page = b"<html><head><title>\n  Caf&eacute; &amp; pane  </title></head></html>"
        self.answer(FakeResponse(page, "text/html; charset=utf-8"))
        self.assertEqual(titles.page_title("https://example.com"), "Café & pane")
        self.assertEqual(self.requests[0].get_header("User-agent"), titles.USER_AGENT)
        self.answer(FakeResponse(b"<html>senza titolo</html>", "text/html"))
        self.assertIsNone(titles.page_title("https://example.com"))
        self.answer(FakeResponse(b"%PDF", "application/pdf"))
        self.assertIsNone(titles.page_title("https://example.com/a.pdf"))
        self.answer(OSError("rete giu"))
        self.assertIsNone(titles.page_title("https://example.com"))
        self.assertIsNone(titles.page_title("file:///etc/passwd"))


if __name__ == "__main__":
    unittest.main()
