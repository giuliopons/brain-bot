"""Test di brain-bot: solo stdlib, repo temporanei, niente rete.

Uso:  python3 -m unittest discover -s tests -v
"""
import importlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
USER = 42


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


if __name__ == "__main__":
    unittest.main()
