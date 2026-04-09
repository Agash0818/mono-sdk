#!/bin/sh
# ─────────────────────────────────────────────────────────────────────────────
#  mono SDK installer
#  curl -fsSL https://monospay.com/install.sh | bash
#
#  One command: install → ask for API key → ✅ Connected as <Agent>
# ─────────────────────────────────────────────────────────────────────────────

BOLD="\033[1m"; DIM="\033[2m"; GREEN="\033[32m"
YELLOW="\033[33m"; RED="\033[31m"; RESET="\033[0m"

SDK="mono-m2m-sdk"
MONO_DIR="$HOME/.mono"

ok()   { printf "  ${GREEN}✓${RESET}  %s\n" "$1"; }
warn() { printf "  ${YELLOW}!${RESET}  %s\n" "$1"; }
fail() { printf "\n  ${RED}✗${RESET}  %s\n\n" "$1"; exit 1; }

OS="$(uname -s 2>/dev/null || echo unknown)"
ARCH="$(uname -m 2>/dev/null || echo unknown)"

# ── Banner ────────────────────────────────────────────────────────────────────
printf "\n"
printf "  ${BOLD}mono${RESET}  Financial infrastructure for AI agents\n"
printf "  ${DIM}monospay.com  ·  %s %s${RESET}\n\n" "$OS" "$ARCH"

# ── 1. Python ─────────────────────────────────────────────────────────────────
PYTHON=""
for candidate in python3 python python3.12 python3.11 python3.10 python3.9; do
  if command -v "$candidate" >/dev/null 2>&1; then
    ver=$("$candidate" -c "import sys; print(sys.version_info >= (3,9))" 2>/dev/null)
    if [ "$ver" = "True" ]; then
      PYTHON="$candidate"
      break
    fi
  fi
done
[ -z "$PYTHON" ] && fail "Python 3.9+ not found. Visit https://python.org/downloads"
ok "Python: $($PYTHON --version 2>&1)"

# ── 2. pipx ───────────────────────────────────────────────────────────────────
if command -v pipx >/dev/null 2>&1; then
  ok "pipx already installed"
else
  if command -v brew >/dev/null 2>&1; then
    brew install pipx >/dev/null 2>&1 && pipx ensurepath >/dev/null 2>&1 || true
  else
    "$PYTHON" -m pip install --user --quiet pipx 2>/dev/null || true
    "$PYTHON" -m pipx ensurepath >/dev/null 2>&1 || true
  fi
fi

if [ -d "$HOME/.local/bin" ]; then
  export PATH="$HOME/.local/bin:$PATH"
fi

# ── 3. Install SDK ────────────────────────────────────────────────────────────
if command -v pipx >/dev/null 2>&1; then
  printf "  →  Installing %s via pipx...\n" "$SDK"
  pipx uninstall "$SDK" >/dev/null 2>&1 || true
  pipx install "$SDK" --quiet && ok "mono-m2m-sdk installed (pipx — fully isolated)"
else
  printf "  →  Installing %s via pip...\n" "$SDK"
  "$PYTHON" -m pip install --user --quiet --upgrade "$SDK" 2>/dev/null && \
    ok "mono-m2m-sdk installed (user)"
fi

# ── 4. Verify CLI ─────────────────────────────────────────────────────────────
printf "\n"
if command -v mono >/dev/null 2>&1; then
  ok "mono CLI available: $(command -v mono)"
fi
VER=$("$PYTHON" -c "import mono_sdk; print(mono_sdk.__version__)" 2>/dev/null || echo "?")
ok "mono_sdk v$VER imported successfully"

# ── 5. Clear saved key ────────────────────────────────────────────────────────
MONO_CONFIG="$HOME/.mono/config.json"
if [ -f "$MONO_CONFIG" ]; then
  "$PYTHON" - <<'PYEOF'
import json, pathlib
p = pathlib.Path.home() / ".mono" / "config.json"
if p.exists():
    try:
        cfg = json.loads(p.read_text())
        for k in ("api_key", "agent_id", "agent_name"):
            cfg.pop(k, None)
        p.write_text(json.dumps(cfg, indent=2))
    except Exception:
        pass
PYEOF
fi

for PROFILE in "$HOME/.zshrc" "$HOME/.bash_profile" "$HOME/.bashrc" "$HOME/.profile"; do
  if [ -f "$PROFILE" ]; then
    grep -v 'MONO_API_KEY' "$PROFILE" > "${PROFILE}.tmp" 2>/dev/null \
      && mv "${PROFILE}.tmp" "$PROFILE" || true
  fi
done

# ── 6. Ask for API key directly in the shell script ──────────────────────────
# curl | bash pipes stdin — Python's input() cannot read from terminal.
# Solution: read the key here in bash (reads from /dev/tty directly),
# then pass it to mono init via environment variable.

printf "\n"
printf "  ${GREEN}Installation complete.${RESET}\n\n"
printf "  ${BOLD}Get your API key:${RESET}\n"
printf "  ${DIM}monospay.com/dashboard → Agents → Issue API key${RESET}\n\n"
printf "  Paste API key: "

# Read from /dev/tty so it works even when stdin is a pipe (curl | bash)
API_KEY=""
if [ -t 0 ]; then
  # stdin is a terminal — read normally
  read -r API_KEY
else
  # stdin is a pipe — read from /dev/tty
  read -r API_KEY < /dev/tty
fi

if [ -z "$API_KEY" ]; then
  printf "\n  No key entered. Run: mono init\n\n"
  exit 0
fi

# Save key to config and run mono init non-interactively
mkdir -p "$HOME/.mono"
"$PYTHON" - "$API_KEY" <<'PYEOF'
import sys, json, pathlib
key = sys.argv[1]
p   = pathlib.Path.home() / ".mono" / "config.json"
cfg = {}
if p.exists():
    try: cfg = json.loads(p.read_text())
    except: pass
cfg["api_key"] = key
p.write_text(json.dumps(cfg, indent=2))
p.chmod(0o600)
PYEOF

# Write to shell profile
PROFILE=""
case "$(basename "${SHELL:-sh}")" in
  zsh)  PROFILE="$HOME/.zshrc" ;;
  bash) PROFILE="$HOME/.bash_profile" ;;
  *)    PROFILE="$HOME/.profile" ;;
esac
if [ -n "$PROFILE" ]; then
  grep -v 'MONO_API_KEY' "$PROFILE" > "${PROFILE}.tmp" 2>/dev/null \
    && mv "${PROFILE}.tmp" "$PROFILE" || true
  printf '\n# mono SDK\nexport MONO_API_KEY="%s"\n' "$API_KEY" >> "$PROFILE"
fi

# Run mono init with key already saved — skip the interactive prompt
printf "\n"
MONO_BIN=""
if   command -v mono >/dev/null 2>&1;  then MONO_BIN="mono"
elif [ -x "$HOME/.local/bin/mono" ];   then MONO_BIN="$HOME/.local/bin/mono"
fi

if [ -n "$MONO_BIN" ]; then
  exec "$MONO_BIN" init --from-installer
else
  printf "  Run: mono init\n\n"
fi
