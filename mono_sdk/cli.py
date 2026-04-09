"""
mono CLI — Control plane for the mono M2M settlement network.

MVP: One thing done perfectly.
  1. User pastes API key from dashboard
  2. CLI resolves agent identity automatically via /balance
  3. User can immediately transfer: mono transfer --to <id> --amount 0.01

The API key IS the agent. No manual assignment. No extra steps.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

from mono_sdk.client import MonoClient
from mono_sdk.errors import MonoError

# ── ANSI ──────────────────────────────────────────────────────────────────────
R    = "\033[0m"
BOLD = "\033[1m"
DIM  = "\033[2m"
GRN  = "\033[32m"
RED  = "\033[31m"
YLW  = "\033[33m"

# ── Config ────────────────────────────────────────────────────────────────────
MONO_DIR    = Path.home() / ".mono"
CONFIG_FILE = MONO_DIR / "config.json"
DEFAULT_API = "https://mono-production-b257.up.railway.app/v1"

DEFAULTS = {
    "base_rpc_url":  "https://mainnet.base.org",
    "paymaster_url": "https://api.monospay.com/paymaster",
    "gateway_url":   DEFAULT_API,
    "chain":         "base",
    "chain_id":      8453,
    "usdc_address":  "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "eurc_address":  "0x60a3E35Cc302bFA44Cb288Bc5a4F316Fdb1adb42",
}

_INTERNAL_KEYS = {"_test_key", "base_sepolia_rpc"}


def tilde(path: Path) -> str:
    try:
        return "~/" + str(path.relative_to(Path.home()))
    except ValueError:
        return str(path)


# ── Config helpers ────────────────────────────────────────────────────────────

def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_config(cfg: dict) -> None:
    clean = {k: v for k, v in cfg.items() if k not in _INTERNAL_KEYS}
    MONO_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(clean, indent=2))
    CONFIG_FILE.chmod(0o600)


def get_setting(key: str, fallback: str | None = None) -> str | None:
    if val := os.environ.get(f"MONO_{key.upper()}"):
        return val
    if val := load_config().get(key):
        return str(val)
    return str(DEFAULTS[key]) if key in DEFAULTS else fallback


def get_api_key() -> str | None:
    return os.environ.get("MONO_API_KEY") or load_config().get("api_key")


def get_client() -> MonoClient:
    key = get_api_key()
    if not key:
        print(f"\n  {RED}✗{R}  No API key found.\n", file=sys.stderr)
        print(f"     Run:  mono init\n", file=sys.stderr)
        sys.exit(1)
    return MonoClient(api_key=key, base_url=get_setting("gateway_url") or DEFAULT_API)


# ── Shell profile ─────────────────────────────────────────────────────────────

def detect_shell_profile() -> Path:
    shell = os.environ.get("SHELL", "")
    home  = Path.home()
    if "zsh"  in shell: return home / ".zshrc"
    if "bash" in shell: return home / ".bash_profile"
    return home / ".profile"


def write_env_to_profile(key: str, value: str) -> None:
    profile = detect_shell_profile()
    line    = f'export {key}="{value}"'
    try:
        text = profile.read_text() if profile.exists() else ""
        if f"export {key}=" in text:
            lines = [line if l.startswith(f"export {key}=") else l
                     for l in text.splitlines()]
            profile.write_text("\n".join(lines) + "\n")
        else:
            with profile.open("a") as f:
                f.write(f"\n# mono SDK\n{line}\n")
    except PermissionError:
        pass


def _resolve_agent(api_key: str, gateway_url: str) -> dict:
    """
    Call /balance to resolve which agent this key belongs to.
    Returns dict with agent_id, agent_name, balance_usdc.
    Never raises — returns empty dict on failure.
    """
    try:
        client = MonoClient(api_key=api_key, base_url=gateway_url)
        bal    = client.balance()
        return {
            "agent_id":   bal.get("agent_id", ""),
            "agent_name": bal.get("name", ""),
            "balance":    float(str(bal.get("balance_usdc", bal.get("available_usdc", 0))).replace(",", ".")),
        }
    except Exception:
        return {}


# ── mono init ─────────────────────────────────────────────────────────────────

def cmd_init(args: argparse.Namespace) -> None:
    """
    MVP setup flow:
    1. Ask for API key (or detect existing)
    2. Call /balance → resolve agent_id + agent_name automatically
    3. Save to ~/.mono/config.json
    4. Show: ✅ Connected as <Agent Name> · $X.XX USDC
    """
    print()
    print(f"  {BOLD}mono init{R}  Setting up your environment\n")

    cfg      = load_config()
    existing = get_api_key()

    # ── Step 1: Get API key ───────────────────────────────────────────────────
    if existing and not args.force:
        # Key exists — but still resolve agent identity to confirm it works
        masked = f"{existing[:15]}...{existing[-4:]}"
        print(f"  {GRN}✓{R}  API key:  {masked}\n")
        api_key = existing
    else:
        # New setup: ask for key
        print(f"  {BOLD}Where to get your API key:{R}")
        print(f"  {DIM}monospay.com/dashboard → Agents → your agent → Issue API key{R}\n")
        try:
            api_key = input("  Paste API key: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\n  Setup cancelled.\n")
            sys.exit(0)

        if not api_key:
            print(f"\n  {YLW}!{R}  No key entered. Run mono init again when ready.\n")
            sys.exit(0)

        if not api_key.startswith("mono_live_"):
            print(f"\n  {YLW}!{R}  Key should start with 'mono_live_' — double-check the dashboard.\n")

    # ── Step 2: Save config ───────────────────────────────────────────────────
    gateway_url = DEFAULT_API
    cfg.update({
        "api_key":     api_key,
        "gateway_url": gateway_url,
        "chain":       "base",
        "chain_id":    8453,
    })
    save_config(cfg)

    # Write to shell profile so key persists across terminal sessions
    write_env_to_profile("MONO_API_KEY", api_key)

    # ── Step 3: Resolve agent identity via /balance ───────────────────────────
    print(f"  Connecting…", end="", flush=True)

    agent = _resolve_agent(api_key, gateway_url)

    if not agent:
        print(f"\r  {RED}✗{R}  Could not connect — check your API key and try again.\n")
        print(f"     Run: {BOLD}mono health{R} to check the gateway.\n")
        sys.exit(1)

    # Save agent identity so all future commands know which agent this is
    cfg["agent_id"]   = agent["agent_id"]
    cfg["agent_name"] = agent["agent_name"]
    save_config(cfg)

    # ── Step 4: Show result — the "Aha moment" ────────────────────────────────
    name    = agent["agent_name"] or "Agent"
    balance = agent["balance"]

    print(f"\r  {GRN}✓{R}  Connected to Base Mainnet")
    print()
    print(
        f"  {BOLD}{GRN}✅ Setup complete.{R} "
        f"Connected as {BOLD}{name}{R}. "
        f"Your balance: {BOLD}{balance:.2f} USDC{R}"
    )
    print()
    print(f"  {DIM}Next steps:{R}")
    print(f"  {DIM}  mono balance                           — check balance{R}")
    print(f"  {DIM}  mono transfer --to <agent_id> --amount 1.00{R}")
    print()


# ── mono config ───────────────────────────────────────────────────────────────

def cmd_config_show(args: argparse.Namespace) -> None:
    cfg = load_config()
    if not cfg:
        print("\n  No config found. Run: mono init\n")
        return
    print(f"\n  Config:  {tilde(CONFIG_FILE)}\n")
    for k, v in cfg.items():
        if k in _INTERNAL_KEYS:
            continue
        if k == "api_key":
            v = f"{str(v)[:15]}...{str(v)[-4:]}" if v else "(not set)"
        print(f"  {k:<22} {v}")
    print()


def cmd_config_set(args: argparse.Namespace) -> None:
    cfg = load_config()
    cfg[args.key] = args.value
    save_config(cfg)
    print(f"\n  {GRN}✓{R}  {args.key} = {args.value}\n")


def cmd_config_clear(args: argparse.Namespace) -> None:
    if CONFIG_FILE.exists():
        CONFIG_FILE.unlink()
    print(f"\n  {GRN}✓{R}  Config cleared: {tilde(CONFIG_FILE)}\n")


# ── mono health ───────────────────────────────────────────────────────────────

def cmd_health(args: argparse.Namespace) -> None:
    gateway = get_setting("gateway_url") or DEFAULT_API
    try:
        req = urllib.request.Request(f"{gateway.rstrip('/')}/health")
        with urllib.request.urlopen(req, timeout=10) as resp:
            h = json.loads(resp.read())
    except Exception:
        print(f"\n  {RED}✗{R}  Gateway unreachable: {gateway}\n")
        return
    st   = h.get("status", "UNKNOWN")
    icon = "✅" if st in ("HEALTHY", "OK") else ("⚠️" if st == "WARNING" else "❌")
    print(f"\n{icon}  {st}")
    print(f"   API:      {gateway}\n")


# ── Low-balance warning ───────────────────────────────────────────────────────

def _low_balance_warn(balance: float) -> None:
    if balance < 1.00:
        print(f"  {YLW}⚠️{R}  Low balance — top up at monospay.com/dashboard")


# ── mono balance ──────────────────────────────────────────────────────────────

def cmd_balance(args: argparse.Namespace) -> None:
    client = get_client()
    result = client.balance()
    usdc   = float(str(result.get("balance_usdc", result.get("available_usdc", "0"))).replace(",", "."))
    name   = result.get("name", load_config().get("agent_name", "agent"))
    print()
    print(f"  {GRN}●{R}  {name:<22}  ${usdc:.3f} USDC  [active]")
    _low_balance_warn(usdc)
    print()


# ── mono transfer ─────────────────────────────────────────────────────────────

def cmd_transfer(args: argparse.Namespace) -> None:
    client = get_client()
    result = client.transfer(to=args.to, amount=args.amount)
    print(f"\n  {GRN}✓{R}  Sent {args.amount:.2f} USDC → {args.to}")
    print(f"     TX:      {result.transaction_id}")
    print(f"     Balance: {result.sender_balance:.3f} USDC")
    _low_balance_warn(result.sender_balance)
    print()


# ── mono settle ───────────────────────────────────────────────────────────────

def cmd_settle(args: argparse.Namespace) -> None:
    client = get_client()
    result = client.settle(to=args.to, amount=args.amount)
    print(f"\n  {GRN}✓{R}  Settlement complete")
    print(f"     TX:      {result.transaction_id}")
    print(f"     Amount:  {result.amount:.4f} USDC")
    print(f"     Balance: {result.sender_balance:.4f} USDC\n")


# ── mono charge ───────────────────────────────────────────────────────────────

def cmd_charge(args: argparse.Namespace) -> None:
    client  = get_client()
    result  = client.charge(amount=args.amount, memo=args.memo)
    balance = float(result.get("new_balance", 0))
    print(f"\n  {GRN}✓{R}  Charged ${args.amount:.4f} USDC")
    if args.memo:
        print(f"     Memo:    {args.memo}")
    print(f"     Balance: ${balance:.3f} USDC")
    _low_balance_warn(balance)
    print()


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="mono",
        description="mono — Financial infrastructure for AI agents · monospay.com",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Getting started:\n"
            "  mono init                                # Paste your API key\n"
            "  mono balance                             # Check balance\n"
            "  mono transfer --to <agent_id> --amount 1.00\n"
            "\n"
            "More commands:\n"
            "  mono settle --to <agent_id> --amount 1.00\n"
            "  mono health\n"
            "  mono config show\n"
        ),
    )
    sub = parser.add_subparsers(dest="command", metavar="command")

    # init
    p_init = sub.add_parser("init", help="Set up your API key")
    p_init.add_argument("--force", action="store_true", help="Re-enter key even if already set")

    # balance
    sub.add_parser("balance", help="Show your USDC balance")

    # transfer
    p_tr = sub.add_parser("transfer", help="Send USDC to another agent")
    p_tr.add_argument("--to",     required=True,             help="Recipient agent ID")
    p_tr.add_argument("--amount", required=True, type=float, help="Amount in USDC")

    # settle
    p_se = sub.add_parser("settle", help="Settle USDC to another agent")
    p_se.add_argument("--to",     required=True,             help="Recipient agent ID")
    p_se.add_argument("--amount", required=True, type=float, help="Amount in USDC")

    # charge
    p_charge = sub.add_parser("charge", help="Deduct from agent budget")
    p_charge.add_argument("amount", type=float)
    p_charge.add_argument("memo", nargs="?", default="")

    # health
    sub.add_parser("health", help="Check gateway status")

    # config
    p_cfg   = sub.add_parser("config", help="Manage local config")
    cfg_sub = p_cfg.add_subparsers(dest="cfg_cmd", metavar="subcommand")
    cfg_sub.add_parser("show",  help="Show config")
    p_cset  = cfg_sub.add_parser("set", help="Set a value")
    p_cset.add_argument("key"); p_cset.add_argument("value")
    cfg_sub.add_parser("clear", help="Clear config")

    args = parser.parse_args()

    try:
        cmd = args.command
        if   cmd == "init":     cmd_init(args)
        elif cmd == "balance":  cmd_balance(args)
        elif cmd == "transfer": cmd_transfer(args)
        elif cmd == "settle":   cmd_settle(args)
        elif cmd == "charge":   cmd_charge(args)
        elif cmd == "health":   cmd_health(args)
        elif cmd == "config":
            cc = getattr(args, "cfg_cmd", None)
            if   cc == "show":  cmd_config_show(args)
            elif cc == "set":   cmd_config_set(args)
            elif cc == "clear": cmd_config_clear(args)
            else:               p_cfg.print_help()
        else:
            parser.print_help()
            print(f"\n  {DIM}First time? Run: mono init{R}\n")

    except MonoError as e:
        print(f"\n  {RED}✗{R}  {e}\n", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n  Aborted.", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    main()
