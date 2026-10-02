# brain-bot

Un bot Telegram che salva tutto quello che gli mandi nell'`inbox/` del tuo **second brain**: un vault di note Markdown versionato con git, per esempio un vault di Obsidian.

Vedi un link, ti viene un'idea, fotografi una lavagna: lo mandi al bot dal telefono e un attimo dopo è una nota nel vault, già committata e sincronizzata. Poi, con calma, la sistemi dal PC.

```
📱 telefono ──► Telegram ──► brain-bot (sul tuo server di casa)
                                 │  scrive inbox/2026-10-02-153012.md
                                 │  git commit + push
                                 ▼
💻 PC  ◄── push / pull ──►  repo git centrale (sul server) ──► mirror su GitHub (privato)
```

- **Niente porte aperte, niente webhook.** Il bot usa il long polling: è lui a chiedere a Telegram se ci sono messaggi. Funziona dietro qualsiasi router, anche su un mini PC da pochi euro.
- **Niente dipendenze.** Un solo file Python, solo libreria standard: niente pip, niente venv.
- **Git come sincronizzazione.** Il server tiene il repo centrale del vault. PC e bot ci fanno push, e a ogni push il server fa una copia su GitHub.

## Cosa sa fare

| Mandi | Ottieni |
|---|---|
| testo, link | una nota in `inbox/`, con i link nascosti convertiti in `[testo](url)` |
| foto, documenti, video | il file in `inbox/attachments/`, incluso nella nota con `![[file]]` |
| album di foto | una sola nota con tutte le foto |
| messaggi inoltrati | la nota riporta da chi arriva (`forwarded_from`) |
| `/cerca parola` | le note che contengono quella parola, con le righe trovate |

Ogni nota ha un piccolo frontmatter:

```markdown
---
created: 2026-10-02T15:30
source: telegram
---

Il testo che hai mandato
```

Il bot risponde ✅ con il nome della nota (senza `.md`, così Telegram non lo trasforma in un link), o ❌ con l'errore.

## Il bot e il vault: due repo separate

Questa repo contiene **solo il codice** del bot, ed è pubblica. Il tuo vault è un'altra repo, **privata**, che resta tua: il bot non contiene nessuna nota e lo raggiunge solo quando gira sul server, attraverso il percorso che gli dai in configurazione. Chiunque può installare brain-bot e puntarlo sul proprio vault.

## Sicurezza

- Risponde **a un solo utente** (il tuo user id Telegram) e **solo in chat privata**. Ignora tutti gli altri senza rispondere.
- **Aggiunge soltanto** file in `inbox/`: non modifica e non cancella mai le note esistenti. Per questo non va mai in conflitto con quello che fai dal PC.
- Il repo centrale **rifiuta force push e cancellazioni** di branch: la storia del vault non si può riscrivere, né dal bot né per errore.
- Gira come utente dedicato `brain`, chiuso in una **sandbox systemd**: vede e scrive solo `/home/brain` e ha la memoria limitata a 150 MB.
- Il token del bot sta in `/etc/brain-bot.env` (leggibile solo da `brain`) e non finisce mai nei log.
- Telegram **non** cifra end-to-end le chat con i bot: quello che mandi passa dai server di Telegram. Tienine conto per i contenuti sensibili.

## Requisiti

- Un server Linux sempre acceso con systemd, con Python ≥ 3.10 e git.
  - Provato su Ubuntu Server 24.04, su un mini PC Intel Atom con 4 GB di RAM.
  - Dovrebbe funzionare anche su un **Raspberry Pi** con Raspberry Pi OS Bookworm o più recente (Python 3.11), ma non è ancora stato provato. Se lo installi su un Raspberry, fammi sapere com'è andata in un'issue.
- Un account Telegram.
- Un vault Markdown in git sul tuo PC.
- Una repo GitHub privata per la copia di backup del vault.

## Installazione

La guida passo-passo, dalla creazione del bot con @BotFather al primo messaggio salvato, è in **[docs/installazione.md](docs/installazione.md)**.

In breve:

```bash
git clone https://github.com/giuliopons/brain-bot.git ~/brain-bot && cd ~/brain-bot
sudo bash setup-server.sh <utente-github> "$(cat chiave_del_pc.pub)"   # utente, repo centrale, mirror
# … dal PC: push del vault sul server …
sudo bash setup-bot.sh                                                # chiede il token del bot
```

## Limiti attuali

- Le risposte del bot sono solo in italiano.
- I messaggi vocali non sono ancora supportati.
- Telegram lascia scaricare ai bot solo file fino a 20 MB.

## Sviluppo

```bash
python3 -m unittest discover -s tests -v    # test: solo libreria standard, niente rete
```

- [`CLAUDE.md`](CLAUDE.md): come è fatto il progetto e i vincoli da rispettare. Il progetto è sviluppato insieme a Claude Code.
- [`HANDOFF.md`](HANDOFF.md): le prossime funzioni in programma, per esempio il promemoria settimanale sulle note in inbox.

Segnalazioni e proposte sono benvenute nelle issue.

## Licenza

[MIT](LICENSE)
