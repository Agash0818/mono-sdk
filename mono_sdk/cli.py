"""
mono CLI — command-line interface for monospay.
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
    from_installer = getattr(args, "from_installer", False)

    if not from_installer:
        print()
        print(f"  {BOLD}mono init{R}  Setting up your environment\n")

    cfg = load_config()

    # When called from installer: ignore env var — always ask the user.
    # The env var may still be loaded in the current shell session even
    # after install.sh removed it from ~/.zshrc.
    if from_installer:
        existing = cfg.get("api_key")   # only check saved config, not env
    else:
        existing = get_api_key()

    if existing:
        # Key found in config — use it silently (normal mono init reuse)
        api_key = existing
        masked  = f"{existing[:15]}...{existing[-4:]}"
        print(f"  {GRN}✓{R}  API key:  {masked}\n")
    else:
        # No key anywhere — ask the user
        print(f"  {BOLD}Get your API key:{R}")
        print(f"  {DIM}monospay.com/dashboard → Agents → Issue API key{R}\n")
        try:
            api_key = input("  Paste API key: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\n  Setup cancelled.\n")
            sys.exit(0)

        if not api_key:
            print(f"\n  {YLW}!{R}  No key entered. Run: mono init\n")
            sys.exit(0)

        if not api_key.startswith("mono_live_"):
            print(f"\n  {YLW}!{R}  Key should start with 'mono_live_'\n")

    gateway_url = DEFAULT_API
    cfg.update({"api_key": api_key, "gateway_url": gateway_url, "chain": "base", "chain_id": 8453})
    save_config(cfg)
    write_env_to_profile("MONO_API_KEY", api_key)

    print(f"  Connecting…", end="", flush=True)
    agent = _resolve_agent(api_key, gateway_url)

    if not agent:
        print(f"\r  {RED}✗{R}  Could not connect — check your API key.\n")
        sys.exit(1)

    cfg["agent_id"]   = agent["agent_id"]
    cfg["agent_name"] = agent["agent_name"]
    save_config(cfg)

    name    = agent["agent_name"] or "Agent"
    balance = agent["balance"]

    print(f"\r  {GRN}✓{R}  Connected to Base Mainnet              ")
    print()
    print(f"  {BOLD}{GRN}✅ Setup complete.{R} Connected as {BOLD}{name}{R}. Your balance: {BOLD}{balance:.2f} USDC{R}")
    print()


# ── mono balance ──────────────────────────────────────────────────────────────

def _low_balance_warn(balance: float) -> None:
    if balance < 1.00:
        print(f"  {YLW}⚠️{R}  Low balance — top up at monospay.com/dashboard")


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
    memo = getattr(args, "memo", "") or ""
    result = client.transfer(to=args.to, amount=args.amount, memo=memo)
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


# ── mono health ───────────────────────────────────────────────────────────────

def cmd_health(args: argparse.Namespace) -> None:
    gateway = get_setting("gateway_url") or DEFAULT_API
    try:
        req = urllib.request.Request(f"{gateway.rstrip('/')}/health")
        with urllib.request.urlopen(req, timeout=10) as resp:
            h = json.loads(resp.read())
        st   = h.get("status", "UNKNOWN")
        icon = "✅" if st in ("HEALTHY", "OK") else ("⚠️" if st == "WARNING" else "❌")
        print(f"\n{icon}  {st}  —  {gateway}\n")
    except Exception:
        print(f"\n  {RED}✗{R}  Gateway unreachable: {gateway}\n")


# ── mono limits ──────────────────────────────────────────────────────────────

def cmd_limits(args: argparse.Namespace) -> None:
    client = get_client()
    kwargs = {}
    if args.spending_limit is not None:
        kwargs["spending_limit"] = args.spending_limit
    if args.daily_budget is not None:
        kwargs["daily_budget"] = args.daily_budget
    if not kwargs:
        print(f"\n  {YLW}!{R}  Specify --spending-limit and/or --daily-budget\n")
        return
    result = client.set_limits(**kwargs)
    print(f"\n  {GRN}✓{R}  Limits updated")
    if "spending_limit" in result:
        print(f"     Spending limit: {result['spending_limit']} USDC/tx")
    if "daily_budget" in result:
        print(f"     Daily budget:   {result['daily_budget']} USDC/day")
    print()


# ── mono config ───────────────────────────────────────────────────────────────

def cmd_config_show(args: argparse.Namespace) -> None:
    cfg = load_config()
    if not cfg:
        print("\n  No config. Run: mono init\n")
        return
    print(f"\n  Config:  {tilde(CONFIG_FILE)}\n")
    for k, v in cfg.items():
        if k in _INTERNAL_KEYS: continue
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
    print(f"\n  {GRN}✓{R}  Config cleared\n")


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
        ),
    )
    sub = parser.add_subparsers(dest="command", metavar="command")

    p_init = sub.add_parser("init", help="Set up your API key")
    p_init.add_argument("--from-installer", dest="from_installer",
                        action="store_true", help=argparse.SUPPRESS)

    sub.add_parser("balance", help="Show your USDC balance")

    p_tr = sub.add_parser("transfer", help="Send USDC to another agent")
    p_tr.add_argument("--to",     required=True,             help="Recipient agent ID")
    p_tr.add_argument("--amount", required=True, type=float, help="Amount in USDC")
    p_tr.add_argument("--memo",   default="",                help="Optional memo")

    p_se = sub.add_parser("settle", help="Settle USDC to another agent")
    p_se.add_argument("--to",     required=True,             help="Recipient agent ID")
    p_se.add_argument("--amount", required=True, type=float, help="Amount in USDC")

    p_charge = sub.add_parser("charge", help="Deduct from agent budget")
    p_charge.add_argument("amount", type=float)
    p_charge.add_argument("memo", nargs="?", default="")

    sub.add_parser("health", help="Check gateway status")

    p_lim = sub.add_parser("limits", help="Set spending limits")
    p_lim.add_argument("--spending-limit", type=float, dest="spending_limit", help="Per-transaction limit (USDC)")
    p_lim.add_argument("--daily-budget",   type=float, dest="daily_budget",   help="Daily budget (USDC)")

    p_cfg   = sub.add_parser("config", help="Manage local config")
    cfg_sub = p_cfg.add_subparsers(dest="cfg_cmd", metavar="subcommand")
    cfg_sub.add_parser("show")
    p_cset  = cfg_sub.add_parser("set")
    p_cset.add_argument("key"); p_cset.add_argument("value")
    cfg_sub.add_parser("clear")

    args = parser.parse_args()

    try:
        cmd = args.command
        if   cmd == "init":     cmd_init(args)
        elif cmd == "balance":  cmd_balance(args)
        elif cmd == "transfer": cmd_transfer(args)
        elif cmd == "settle":   cmd_settle(args)
        elif cmd == "charge":   cmd_charge(args)
        elif cmd == "health":   cmd_health(args)
        elif cmd == "limits":  cmd_limits(args)
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
