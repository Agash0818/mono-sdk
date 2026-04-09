#!/usr/bin/env bash
# install.sh — mono SDK installer
#
# One command does everything:
#   curl -fsSL https://monospay.com/install.sh | bash
#
# Flow: install → clear old key → ask for API key → ✅ Connected as <Agent>

set -euo pipefail

# ── ANSI ─────────────────────────────────────────────────────────────────────
R="\033[0m"; BOLD="\033[1m"; DIM="\033[2m"
GRN="\033[32m"; RED="\033[31m"; YLW="\033[33m"

ok()   { echo -e "  ${GRN}✓${R}  $*"; }
err()  { echo -e "  ${RED}✗${R}  $*" >&2; }
warn() { echo -e "  ${YLW}!${R}  $*"; }
dim()  { echo -e "  ${DIM}$*${R}"; }
rule() { printf "  ${DIM}"; printf '─%.0s' {1..52}; echo -e "${R}"; }

# ── Header ────────────────────────────────────────────────────────────────────
echo
echo -e "  ${BOLD}mono${R}  Financial infrastructure for AI agents"
echo -e "  ${DIM}monospay.com${R}"
rule
echo

# ── Python check ──────────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
  err "Python 3.9+ required. Install from https://python.org"
  exit 1
fi

PY_MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")
PY_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")

if [[ "$PY_MAJOR" -lt 3 || ( "$PY_MAJOR" -eq 3 && "$PY_MINOR" -lt 9 ) ]]; then
  err "Python ${PY_MAJOR}.${PY_MINOR} found — 3.9+ required."
  exit 1
fi
ok "Python: $(python3 --version)"

# Detect pip
if   command -v pip3 &>/dev/null; then PIP=pip3
elif command -v pip  &>/dev/null; then PIP=pip
else err "pip not found."; exit 1
fi

# ── Remove old SDK installation ───────────────────────────────────────────────
if command -v pipx &>/dev/null; then
  pipx uninstall mono-m2m-sdk 2>/dev/null || true
fi
"$PIP" uninstall mono-m2m-sdk -y 2>/dev/null || true
"$PIP" cache remove mono_m2m_sdk 2>/dev/null || true
"$PIP" cache remove mono-m2m-sdk 2>/dev/null || true

# Remove stale binaries
for BIN in "${HOME}/.local/bin/mono" \
           "$(python3 -m site --user-base 2>/dev/null)/bin/mono"; do
  [[ -f "$BIN" ]] && rm -f "$BIN" 2>/dev/null || true
done

# ── Clear saved API key and agent config ──────────────────────────────────────
# The key is machine-wide (not per-folder). On a fresh install we always
# clear it so the user is prompted — regardless of what was there before.
MONO_CONFIG="${HOME}/.mono/config.json"
if [[ -f "$MONO_CONFIG" ]]; then
  # Remove api_key, agent_id, agent_name — keep other settings (gateway_url etc.)
  if command -v python3 &>/dev/null; then
    python3 - <<'PYEOF'
import json, pathlib
p = pathlib.Path.home() / ".mono" / "config.json"
if p.exists():
    cfg = json.loads(p.read_text())
    for k in ("api_key", "agent_id", "agent_name"):
        cfg.pop(k, None)
    p.write_text(json.dumps(cfg, indent=2))
PYEOF
  fi
fi

# Remove MONO_API_KEY from shell profile so it doesn't shadow the new key
for PROFILE in "${HOME}/.zshrc" "${HOME}/.bash_profile" "${HOME}/.profile"; do
  if [[ -f "$PROFILE" ]]; then
    # Remove lines that set MONO_API_KEY
    grep -v 'export MONO_API_KEY=' "$PROFILE" > "${PROFILE}.tmp" 2>/dev/null \
      && mv "${PROFILE}.tmp" "$PROFILE" || true
  fi
done

ok "Previous config cleared"

# ── Install ───────────────────────────────────────────────────────────────────
if command -v pipx &>/dev/null; then
  ok "pipx already installed"
  echo -e "  →  Installing mono-m2m-sdk via pipx..."
  pipx install --force mono-m2m-sdk --quiet
  INSTALL_METHOD="pipx"
else
  echo -e "  →  Installing mono-m2m-sdk via pip..."
  "$PIP" install --upgrade --force-reinstall --no-cache-dir --quiet mono-m2m-sdk
  INSTALL_METHOD="pip"
fi

# ── Verify ────────────────────────────────────────────────────────────────────
MONO_BIN=""
if   command -v mono &>/dev/null;        then MONO_BIN="mono"
elif [[ -x "${HOME}/.local/bin/mono" ]]; then MONO_BIN="${HOME}/.local/bin/mono"
fi

if [[ -z "$MONO_BIN" ]]; then
  echo
  warn "mono not found in PATH after install."
  dim "Add to your shell profile:"
  echo -e "    ${BOLD}export PATH=\"\${HOME}/.local/bin:\${PATH}\"${R}"
  echo
  dim "Then run:  mono init"
  exit 0
fi

if python3 -c "import mono_sdk; print(f'mono_sdk v{mono_sdk.__version__}')" 2>/dev/null | grep -q "mono_sdk"; then
  ok "$(python3 -c "import mono_sdk; print(f'mono_sdk v{mono_sdk.__version__} imported successfully')")"
fi
ok "mono CLI available: $(command -v mono || echo "${HOME}/.local/bin/mono")"

echo
echo -e "  ${GRN}Installation complete.${R}"
echo -e "  Running ${BOLD}mono init${R} to configure your environment...\n"

# ── Hand off to CLI — key is cleared, so user will always be prompted ─────────
exec "$MONO_BIN" init
