#!/bin/bash
set -e

# Configure git identity if provided
if [ -n "$GIT_USER_NAME" ]; then
    git config --global user.name "$GIT_USER_NAME"
fi
if [ -n "$GIT_USER_EMAIL" ]; then
    git config --global user.email "$GIT_USER_EMAIL"
fi

# Configure GitHub CLI auth if token provided.
#
# We intentionally do NOT use `git config --global url.<token-URL>.insteadOf`
# here — that pattern embeds the token into every clone's .git/config as the
# origin remote, so `git remote -v` prints the token in cleartext and any
# command that dumps remote info leaks it. Instead we let `gh` register a
# credential helper; git fetches the token on demand and never persists it
# into repo configs or remote URLs.
if [ -n "$GITHUB_TOKEN" ]; then
    echo "$GITHUB_TOKEN" | gh auth login --with-token 2>/dev/null || true
    gh auth setup-git 2>/dev/null || true
fi

# Disable Codex built-in GitHub plugin — it uses the OpenAI OAuth user's
# personal GitHub account instead of GITHUB_TOKEN.  All git/gh operations
# should go through the bot's GITHUB_TOKEN set above.
mkdir -p "$HOME/.codex"
cat > "$HOME/.codex/config.toml" << 'TOML'
[plugins."github@openai-curated"]
enabled = false

# Disable built-in "apps" (codex_apps) — its GitHub tools use OpenAI OAuth
# which authenticates as the OAuth account owner, not the bot's GITHUB_TOKEN.
[features]
apps = false
TOML

# Run module setup (install deps, update AGENTS.md)
python3 -m src.module_setup || echo "Warning: module setup failed"

exec "$@"
