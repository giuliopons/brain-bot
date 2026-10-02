#!/usr/bin/env bash
# Prepares the server that hosts the second brain's central git repo (Ubuntu/Debian).
# Run it before setup-bot.sh.
# Usage:
#   sudo bash setup-server.sh <github-user> "<laptop SSH public key>"
# Example:
#   sudo bash setup-server.sh <github-user> "$(cat ~/.ssh/id_ed25519.pub)"
#
# Creates:
#  - system user `brain` with git-shell (no interactive login)
#  - bare repo /home/brain/brain.git (branch main, no force push, no deletions)
#  - GitHub deploy key + async mirror on every push + hourly retry cron
# Idempotent: safe to run again.
# GH_REPO (env) is the GitHub repo name for the mirror, default "brain".
set -euo pipefail

GH_USER="${1:?Manca utente GitHub}"
LAPTOP_PUBKEY="${2:?Manca chiave pubblica del portatile}"
GH_REPO="${GH_REPO:-brain}"

U=brain
H=/home/$U
REPO=$H/brain.git
as_brain() { sudo -u "$U" -H "$@"; }

[ "$(id -u)" -eq 0 ] || { echo "Lancialo con sudo"; exit 1; }
command -v git >/dev/null || apt-get install -y git

# 1. Dedicated user, separate from your own account
grep -qx /usr/bin/git-shell /etc/shells || echo /usr/bin/git-shell >> /etc/shells
id "$U" &>/dev/null || useradd --create-home --shell /usr/bin/git-shell "$U"
chmod 750 "$H"

# 2. Laptop access: git only, no tunnels or pty
install -d -m 700 -o "$U" -g "$U" "$H/.ssh" "$H/bin"
AK=$H/.ssh/authorized_keys
touch "$AK"
KEYBODY=$(awk '{print $2}' <<<"$LAPTOP_PUBKEY")
grep -q "$KEYBODY" "$AK" || \
  echo "no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-pty $LAPTOP_PUBKEY" >> "$AK"
chown "$U:$U" "$AK"; chmod 600 "$AK"

# 3. GitHub deploy key (used ONLY for this repo)
DK=$H/.ssh/github_deploy
[ -f "$DK" ] || as_brain ssh-keygen -q -t ed25519 -N "" -C "brain-mirror@$(hostname)" -f "$DK"
cat > "$H/.ssh/config" <<EOF
Host github-brain
  HostName github.com
  User git
  IdentityFile $DK
  IdentitiesOnly yes
EOF
touch "$H/.ssh/known_hosts"
grep -q "^github.com " "$H/.ssh/known_hosts" || \
  { ssh-keyscan -t ed25519 github.com >> "$H/.ssh/known_hosts" 2>/dev/null || echo "⚠️  ssh-keyscan fallito: rilancia più tardi"; }
chown "$U:$U" "$H/.ssh/config" "$H/.ssh/known_hosts"; chmod 600 "$H/.ssh/config"

# 4. Bare repo
[ -d "$REPO" ] || as_brain git init -q --bare -b main "$REPO"
as_brain git -C "$REPO" config receive.denyNonFastForwards true
as_brain git -C "$REPO" config receive.denyDeletes true
as_brain git -C "$REPO" remote get-url github &>/dev/null || \
  as_brain git -C "$REPO" remote add github "git@github-brain:$GH_USER/$GH_REPO.git"

# 5. Mirror to GitHub (never force push)
cat > "$H/bin/mirror.sh" <<'EOF'
#!/bin/sh
# Pushes branches and tags of the bare repo to GitHub. Called by the hook and by cron.
LOG=$HOME/mirror.log
exec 9>"$HOME/.mirror.lock"
flock -w 120 9 || exit 0
cd "$HOME/brain.git" || exit 1
if git push --quiet github 'refs/heads/*:refs/heads/*' 'refs/tags/*:refs/tags/*' >>"$LOG" 2>&1; then
  echo "$(date -Is) ok" >>"$LOG"
else
  echo "$(date -Is) ERRORE push GitHub" >>"$LOG"
fi
tail -n 300 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
EOF
cat > "$REPO/hooks/post-receive" <<'EOF'
#!/bin/sh
# Mirror in background: the push from the laptop does not wait for GitHub.
nohup "$HOME/bin/mirror.sh" >/dev/null 2>&1 &
EOF
chown "$U:$U" "$H/bin/mirror.sh" "$REPO/hooks/post-receive"
chmod 750 "$H/bin/mirror.sh" "$REPO/hooks/post-receive"

# 6. Recovery cron: if a mirror failed (network down), retry every hour
( crontab -u "$U" -l 2>/dev/null | grep -v mirror.sh || true; \
  echo "17 * * * * HOME=$H $H/bin/mirror.sh" ) | crontab -u "$U" -

echo
echo "✅ Remote pronto: $U@$(hostname):brain.git"
echo
echo "👉 Aggiungi questa DEPLOY KEY su GitHub → repo $GH_USER/$GH_REPO → Settings → Deploy keys"
echo "   (spunta 'Allow write access'):"
echo
cat "$DK.pub"
echo
echo "Poi verifica con:  sudo -u $U -H ssh -T git@github-brain"
