# Installazione

Questa guida porta da zero a un bot funzionante: crei il bot su Telegram, prepari il server, colleghi il vault e mandi il primo messaggio. Ci vuole circa mezz'ora.

**Una installazione per server.** Gli script usano un utente fisso (`brain`) e percorsi fissi. Per installare brain-bot per un'altra persona serve un altro server: ognuno ha il suo bot, il suo vault e la sua repo GitHub.

## Panoramica

| Dove | Cosa | Passo |
|---|---|---|
| Telegram | crei il bot e ottieni il token | 1 |
| GitHub | crei una repo privata vuota per la copia del vault | 2 |
| Server | `setup-server.sh`: utente `brain`, repo centrale, mirror su GitHub | 3, 4 |
| PC | push del vault sul server | 5 |
| Server | `setup-bot.sh`: installa e avvia il bot | 6 |
| Telegram | scopri il tuo user id e autorizzi solo te | 7 |
| Anthropic | *facoltativo*: chiave API per i titoli automatici delle note | 9 |

Nei comandi:
- `<server>` è il nome o l'IP del server nella tua rete, per esempio `minipc.local` o `192.168.1.20`;
- `<utente-github>` è il tuo nome utente GitHub.

## 0. Prerequisiti

- **Server**: Linux con systemd (provato su Ubuntu Server 24.04), sempre acceso, connesso a internet, con accesso `sudo`. Python ≥ 3.10 e git: su Ubuntu ci sono già, altrimenti `sudo apt install python3 git`.
- **Raspberry Pi** (non ancora provato, ma non ci sono ostacoli noti): usa Raspberry Pi OS **Bookworm** o più recente, o Ubuntu Server per Raspberry. La vecchia Bullseye ha Python 3.9 e non basta: controlla con `python3 --version`. Anche un modello piccolo va bene, il bot usa poche decine di MB. Il vault però sta sulla scheda SD, quindi tieni attivo il mirror su GitHub come backup: le schede SD si rovinano più spesso dei dischi.
- **PC**: git e una chiave SSH. Se non ne hai una:
  ```bash
  ssh-keygen -t ed25519
  ```
  La chiave pubblica è in `~/.ssh/id_ed25519.pub`.
- **Telegram** sul telefono.

## 1. Crea il bot con @BotFather

Tutti i bot Telegram si creano parlando con [@BotFather](https://t.me/BotFather), il bot ufficiale di Telegram (ha la spunta blu).

1. Apri @BotFather e manda `/newbot`.
2. Ti chiede il **nome** visibile, per esempio `Second Brain`. Puoi cambiarlo quando vuoi.
3. Ti chiede lo **username**: deve essere unico e finire in `bot`, per esempio `mario_brain_bot`. Non si può cambiare.
4. Ti risponde con il **token**, una stringa tipo `123456789:AAH…`. Copialo e tienilo da parte per il passo 6.

> ⚠️ Il token è la password del bot: chi lo ha può leggere i messaggi che gli mandi. Non incollarlo in chat, in un'issue o in un file dentro una repo. Se pensi che sia trapelato, in @BotFather usa `/revoke`: ottieni un token nuovo e quello vecchio smette di funzionare (poi vedi "Cambiare il token" più sotto).

Impostazioni consigliate, sempre in @BotFather. Ogni comando ti chiede prima di scegliere il bot.

- `/setjoingroups` → **Disable**: nessuno potrà aggiungere il bot a un gruppo. Il bot lavora solo in chat privata.
- `/setcommands`: manda questo testo, così Telegram suggerisce i comandi quando scrivi `/`:
  ```
  cerca - cerca nel second brain
  help - come si usa
  ```
- Facoltativi:
  - `/setdescription`: il testo che si vede aprendo la chat vuota, per esempio "Mandami qualsiasi cosa: finisce nell'inbox del second brain.";
  - `/setuserpic`: l'immagine del bot.

## 2. Crea la repo GitHub per la copia del vault

Su GitHub crea una repo **privata** e **vuota**: niente README, niente licenza, niente `.gitignore`. Chiamala `brain`. Se vuoi un altro nome, ricordati di passarlo al passo 3 con `GH_REPO`.

Il server ci spingerà automaticamente una copia del vault a ogni push. Se hai già il vault su GitHub, puoi usare quella repo, purché abbia la stessa storia del vault sul PC.

## 3. Prepara il server

Sul server, con il tuo utente normale:

```bash
git clone https://github.com/giuliopons/brain-bot.git ~/brain-bot
cd ~/brain-bot
sudo bash setup-server.sh <utente-github> "$(cat id_ed25519.pub)"
```

Il secondo argomento è la **chiave pubblica del PC**, cioè il contenuto di `~/.ssh/id_ed25519.pub` del PC. Puoi copiarla sul server oppure incollarla direttamente tra virgolette. Se la repo GitHub non si chiama `brain`:

```bash
sudo GH_REPO=nome-repo bash setup-server.sh <utente-github> "ssh-ed25519 AAAA… mario@pc"
```

Lo script crea:
- l'utente di sistema `brain`, che può solo usare git: niente login interattivo;
- il repo centrale `/home/brain/brain.git`, che rifiuta force push e cancellazioni di branch;
- una chiave SSH dedicata (*deploy key*) per spingere su GitHub;
- il mirror su GitHub a ogni push, più un tentativo ogni ora se nel frattempo la rete era giù.

Si può rilanciare senza problemi: non rifà quello che esiste già.

## 4. Autorizza il server su GitHub

Alla fine `setup-server.sh` stampa una chiave che inizia con `ssh-ed25519`.

1. Su GitHub apri la repo del passo 2 → **Settings** → **Deploy keys** → **Add deploy key**.
2. Incolla la chiave, dalle un titolo (per esempio `server di casa`) e spunta **Allow write access**.
3. Verifica dal server:
   ```bash
   sudo -u brain -H ssh -T git@github-brain
   ```
   Deve rispondere `Hi <utente-github>/brain! You've successfully authenticated…`.

La deploy key vale solo per quella repo: anche se qualcuno la rubasse dal server, non avrebbe accesso al resto del tuo account GitHub.

## 5. Porta il vault sul server

Dal **PC**, nella cartella del vault.

**Se il vault è già una repo git:**

```bash
cd ~/vault
git branch -M main                          # il branch deve chiamarsi main
git remote add server brain@<server>:brain.git
git push -u server main
```

**Se il vault non è ancora in git:**

```bash
cd ~/vault
git init -b main
mkdir -p inbox && touch inbox/.gitkeep
git add -A && git commit -m "vault iniziale"
git remote add server brain@<server>:brain.git
git push -u server main
```

Il push fa partire anche la prima copia su GitHub. Controlla dal server:

```bash
sudo tail /home/brain/mirror.log            # deve esserci una riga "ok"
```

**Da qui in poi il PC lavora con il server, non con GitHub.** Il server è il repo centrale e GitHub è solo una copia: se fai push su GitHub direttamente dal PC, le due storie si separano e il mirror smette di funzionare. Se il remote `origin` del vault punta ancora a GitHub, rimuovilo o rinominalo, e usa il server come remote principale:

```bash
git remote remove origin                    # oppure: git remote rename origin github-vecchio
git remote rename server origin
```

## 6. Installa il bot

Sul server:

```bash
cd ~/brain-bot
sudo bash setup-bot.sh
```

Ti chiede il **token** del passo 1. Mentre lo incolli non vedi niente: è normale, così non resta sullo schermo né nella cronologia della shell.

Lo script:
- copia `bot.py` in `/home/brain/bot/`;
- crea il clone di lavoro del bot in `/home/brain/vault`;
- salva il token in `/etc/brain-bot.env`;
- installa e avvia il servizio `brain-bot`.

Se risponde `Il repo /home/brain/brain.git è vuoto`, non hai ancora fatto il passo 5.

## 7. Autorizza solo te

Per ora il bot non sa chi sei, e a chiunque gli scriva risponde solo con il suo user id.

1. Su Telegram cerca il tuo bot (`@mario_brain_bot`), aprilo e premi **Avvia**. Risponde:
   `Il tuo user id è 123456789.`
2. Sul server, metti quel numero nel file di configurazione:
   ```bash
   sudo nano /etc/brain-bot.env
   ```
   ```
   BRAIN_BOT_TOKEN=123456789:AAH…
   BRAIN_BOT_ALLOWED_USER_ID=123456789
   ```
3. Riavvia:
   ```bash
   sudo systemctl restart brain-bot
   ```

Da adesso il bot risponde solo a te, e solo in chat privata.

## 8. Prova

1. Manda al bot `prova dal telefono`. Risponde `✅ inbox/2026-10-02-153012`: è il nome della nota, senza `.md`.
2. Sul PC fai `git pull`: la nota è in `inbox/`.
3. Manda `/cerca prova`: il bot ti mostra la nota appena creata.

## 9. Titoli automatici con Claude (facoltativo)

Senza questo passo le note si chiamano con la sola data e ora (`2026-10-02-153012.md`). Con una chiave API di Anthropic, il bot chiede a Claude Haiku un titolo breve e lo aggiunge al nome (`2026-10-02-153012-ricetta-pane-lievito-madre.md`) e al frontmatter (`title:`).

Cosa viene inviato ad Anthropic: il testo che mandi, le foto e, per i link, il titolo della pagina, che il server legge scaricando i primi KB. Solo per i messaggi tuoi: quelli degli altri il bot li ignora prima di arrivare a questo punto.

1. Crea un account su [console.anthropic.com](https://console.anthropic.com), aggiungi un metodo di pagamento e crea una **API key** (Settings → API keys).
   Consigliato: in Settings → Limits imposta un **limite di spesa mensile** basso, per esempio 5 dollari. Un messaggio di testo costa meno di un decimo di centesimo, una foto circa due decimi.
2. Sul server, aggiungi la chiave al file di configurazione:
   ```bash
   sudo nano /etc/brain-bot.env
   ```
   ```
   ANTHROPIC_API_KEY=sk-ant-…
   ```
   Se c'è già la riga `#ANTHROPIC_API_KEY=`, togli il `#` e incolla la chiave dopo l'`=`.
3. Aggiorna e riavvia (serve `titles.py`, che `setup-bot.sh` installa insieme al bot):
   ```bash
   cd ~/brain-bot && git pull && sudo bash setup-bot.sh
   ```
4. Prova: manda `ricetta del pane con lievito madre`. La risposta deve essere tipo `✅ inbox/2026-10-02-153012-ricetta-pane-lievito-madre`.

Per disattivarli, togli la riga (o rimettici il `#` davanti) e fai `sudo systemctl restart brain-bot`.

> ⚠️ La chiave API è come il token del bot: non incollarla in chat, in un'issue o in un file dentro una repo. Se trapela, revocala dalla console di Anthropic e creane una nuova.

## Uso quotidiano dal PC

- Prima di lavorare sul vault fai `git pull`, dopo fai commit e `git push`. In Obsidian lo può fare in automatico il plugin *Obsidian Git*.
- Ogni tanto svuota `inbox/`: sposta le note dove servono, uniscile ad altre o cancellale. Le note in inbox le gestisci tu dal PC: il bot ne aggiunge di nuove ma non tocca mai quelle esistenti.
- Mai `git push --force`: il server lo rifiuta comunque.

## Gestione

```bash
systemctl status brain-bot                  # è attivo?
journalctl -u brain-bot -f                  # log in diretta
sudo tail /home/brain/mirror.log            # esito delle copie su GitHub
```

**Aggiornare brain-bot** a una nuova versione:

```bash
cd ~/brain-bot && git pull && sudo bash setup-bot.sh
```

Token, user id e vault restano dove sono.

**Cambiare il token**: in @BotFather `/revoke`, poi metti il nuovo valore in `BRAIN_BOT_TOKEN` dentro `/etc/brain-bot.env` e fai `sudo systemctl restart brain-bot`.

**Fuso orario**: i nomi delle note usano l'ora di Roma. Per cambiarla aggiungi `BRAIN_TZ=Europe/London` (o un altro fuso) in `/etc/brain-bot.env` e riavvia.

**Disinstallare il bot**, lasciando intatti il vault e il repo centrale:

```bash
sudo systemctl disable --now brain-bot
sudo rm /etc/systemd/system/brain-bot.service /etc/brain-bot.env
sudo systemctl daemon-reload
```

> L'utente `brain` e `/home/brain` contengono il repo centrale del vault. Non cancellarli se prima non hai verificato che PC e GitHub abbiano tutta la storia.

## Problemi frequenti

**Il bot non risponde.** Guarda `journalctl -u brain-bot -n 50`:
- `HTTP 401 Unauthorized`: il token è sbagliato o è stato revocato;
- `HTTP 409 Conflict`: un'altra copia del bot sta usando lo stesso token, per esempio una prova lasciata accesa sul PC. Fermala;
- `ignorato messaggio da user id …`: l'id in `/etc/brain-bot.env` non è il tuo. Ricontrolla il passo 7;
- nessun log: il servizio è fermo. Prova `sudo systemctl restart brain-bot` e poi `systemctl status brain-bot`.

**Le note non prendono il titolo** (nome con la sola data). Guarda `journalctl -u brain-bot -n 50 | grep titolo`:
- `titolo: Claude HTTP 401 …`: la chiave API è sbagliata o revocata;
- `titolo: Claude HTTP 400 …` che parla di credito: hai finito il credito o raggiunto il limite di spesa;
- `titolo: Claude non raggiungibile`: problema di rete o API lenta. Riprova più tardi;
- nessuna riga `titolo`: la chiave non è in `/etc/brain-bot.env`, oppure il bot non è stato riavviato dopo averla aggiunta.

La nota viene comunque salvata con la sola data: non si perde niente.

**Il bot risponde ❌ con un errore git.** Controlla lo stato del clone del bot:

```bash
sudo -u brain -H git -C /home/brain/vault status
```

Di solito il problema è un push rifiutato perché il repo centrale ha una storia diversa, per esempio dopo un force push tentato dal PC. Il bot riprova da solo 3 volte; il commit resta in locale e parte con il messaggio successivo.

**Il push dal PC viene rifiutato** (`non-fast-forward`): nel frattempo il bot ha aggiunto note. Fai `git pull --rebase` e poi di nuovo `git push`.

**`mirror.log` dice `ERRORE push GitHub`.** Le cause più comuni:
- la deploy key non ha **Allow write access**: rifai il passo 4;
- la repo GitHub non è vuota e ha una storia diversa dal vault.

Il server riprova ogni ora; per riprovare subito:

```bash
sudo -u brain -H /home/brain/bin/mirror.sh && sudo tail -3 /home/brain/mirror.log
```

**Una shell come utente `brain`**, per indagare:

```bash
sudo -u brain -H bash
```
