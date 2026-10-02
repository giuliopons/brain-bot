#!/usr/bin/env bash
# Installa brain-bot sul server (dopo setup-server.sh).
# Uso:  sudo bash setup-bot.sh
# Rilanciabile: aggiorna bot.py, titles.py e il servizio, non tocca token né vault.
set -euo pipefail

U=brain
H=/home/$U
DIR="$(cd "$(dirname "$0")" && pwd)"
ENV=/etc/brain-bot.env
as_brain() { sudo -u "$U" -H "$@"; }

[ "$(id -u)" -eq 0 ] || { echo "Lancialo con sudo"; exit 1; }
id "$U" &>/dev/null || { echo "Utente $U mancante: lancia prima setup-server.sh"; exit 1; }
# The bot pulls main on every message: the vault must have been pushed at least once
as_brain git -C "$H/brain.git" rev-parse -q --verify main >/dev/null || {
  echo "Il repo $H/brain.git è vuoto: fai prima il push del vault dal PC (vedi docs/installazione.md)"; exit 1; }
python3 -c 'import sys; assert sys.version_info >= (3, 10)' || { echo "Serve Python >= 3.10"; exit 1; }

# 1. Codice
install -d -o root -g "$U" -m 750 "$H/bot"
install -o root -g "$U" -m 640 "$DIR/bot.py" "$H/bot/bot.py"
install -o root -g "$U" -m 640 "$DIR/titles.py" "$H/bot/titles.py"

# 2. Clone di lavoro del bot (scrive qui, poi push sul repo bare)
[ -d "$H/vault/.git" ] || as_brain git clone -q "$H/brain.git" "$H/vault"
as_brain git -C "$H/vault" config user.name "brain-bot"
as_brain git -C "$H/vault" config user.email "brain-bot@$(hostname)"
as_brain git -C "$H/vault" config pull.rebase true

# 3. Token (chiesto senza eco, non finisce nella history della shell)
if [ ! -f "$ENV" ]; then
  read -rsp "Token del bot (da @BotFather): " TOKEN; echo
  install -m 600 -o "$U" -g "$U" /dev/null "$ENV"
  # optional key for note titles (docs/installazione.md): uncomment and fill in
  printf 'BRAIN_BOT_TOKEN=%s\nBRAIN_BOT_ALLOWED_USER_ID=\n#ANTHROPIC_API_KEY=\n' "$TOKEN" > "$ENV"
fi

# 4. Servizio systemd
install -m 644 "$DIR/brain-bot.service" /etc/systemd/system/brain-bot.service
systemctl daemon-reload
systemctl enable -q brain-bot
systemctl restart brain-bot
sleep 2
systemctl --no-pager --lines=5 status brain-bot || true

echo
echo "✅ brain-bot attivo. Log in diretta:  journalctl -u brain-bot -f"
