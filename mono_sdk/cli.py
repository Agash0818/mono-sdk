"""
mono CLI: Command-line interface for the mono settlement network.

Commands:
    mono init                          Zero-config setup wizard
    mono health                        Check system health
    mono settle --to <id> --amount 0.5 Execute a settlement
    mono status                        Show fleet status and balances
    mono nodes list/create/kill        Manage agent nodes
    mono config show/set/clear         Manage local configuration
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any

from mono_sdk.client import MonoClient
from mono_sdk.errors import MonoError

# ── Config file location ──────────────────────────────────────────────────────
MONO_DIR    = Path.home() / ".mono"
CONFIG_FILE = MONO_DIR / "config.json"
DEFAULT_API = "https://mono-production-b257.up.railway.app/v1"

# ── Default provider settings (zero-config out of the box) ───────────────────
DEFAULTS = {
    "base_rpc_url":       "https://mainnet.base.org",
    "base_sepolia_rpc":   "https://sepolia.base.org",
    "paymaster_url":      "https://api.monospay.com/paymaster",
    "gateway_url":        DEFAULT_API,
    "chain":              "base",
    "chain_id":           8453,
    "usdc_address":       "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "eurc_address":       "0x60a3E35Cc302bFA44Cb288Bc5a4F316Fdb1adb42",
}

# ── Config helpers ────────────────────────────────────────────────────────────

def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_config(cfg: dict) -> None:
    MONO_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
    CONFIG_FILE.chmod(0o600)  # owner-read only (contains API key)


def get_setting(key: str, fallback: str | None = None) -> str | None:
    """Resolution order: env var → config file → default."""
    env_key = f"MONO_{key.upper()}"
    if val := os.environ.get(env_key):
        return val
    cfg = load_config()
    if val := cfg.get(key):
        return val
    if key in DEFAULTS:
        return str(DEFAULTS[key])
    return fallback


def get_api_key() -> str | None:
    return get_setting("api_key") or os.environ.get("MONO_API_KEY")


def get_client() -> MonoClient:
    api_key = get_api_key()
    if not api_key:
        print("\n  ✗  No API key found.\n", file=sys.stderr)
        print("     Run:  mono init\n", file=sys.stderr)
        sys.exit(1)
    return MonoClient(
        api_key=api_key,
        base_url=get_setting("gateway_url") or DEFAULT_API,
    )


# ── Shell profile helpers ──────────────────────────────────────────────────────

def detect_shell_profile() -> Path:
    shell = os.environ.get("SHELL", "")
    home  = Path.home()
    if   "zsh"  in shell: return home / ".zshrc"
    elif "bash" in shell: return home / ".bash_profile"
    else:                 return home / ".profile"


def write_env_to_profile(key: str, value: str) -> None:
    """Idempotently write export KEY=value to shell profile."""
    profile = detect_shell_profile()
    line    = f'export {key}="{value}"'
    try:
        text = profile.read_text() if profile.exists() else ""
        if f"export {key}=" in text:
            # Replace existing
            lines = text.splitlines()
            lines = [line if l.startswith(f"export {key}=") else l for l in lines]
            profile.write_text("\n".join(lines) + "\n")
        else:
            with profile.open("a") as f:
                f.write(f"\n# mono SDK\n{line}\n")
    except PermissionError:
        pass  # Non-fatal — config file has the value


def test_connection(api_key: str, gateway_url: str) -> bool:
    """Quick health check against the API."""
    try:
        req = urllib.request.Request(
            f"{gateway_url.rstrip('/')}/health",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
            return data.get("status") in ("HEALTHY", "OK", "ok")
    except urllib.error.HTTPError as e:
        return e.code < 500  # 401/404 = connected, just wrong key
    except Exception:
        return False


# ── mono init ─────────────────────────────────────────────────────────────────

def cmd_init(args: argparse.Namespace) -> None:
    """Zero-config setup wizard. All defaults pre-set — only API key needed."""
    print()
    print("  \033[1mmono init\033[0m  Setting up your environment\n")

    cfg = load_config()

    # ── Step 1: API key ────────────────────────────────────────────────────────
    existing_key = get_api_key()

    if existing_key and not args.force:
        masked = f"{existing_key[:15]}...{existing_key[-4:]}"
        print(f"  \033[32m✓\033[0m  API key:  {masked}  (already configured)\n")
        api_key = existing_key
    else:
        print("  Get your API key at: \033[1mhttps://monospay.com/dashboard\033[0m\n")
        print("  \033[2mPaste it below and press Enter.\033[0m")
        try:
            api_key = input("  MONO_API_KEY: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\n  Setup cancelled.\n")
            sys.exit(0)

        if not api_key:
            print("\n  \033[33m!\033[0m  Skipped — set MONO_API_KEY later.\n")
            api_key = ""
        elif not api_key.startswith("mono_live_"):
            print("\n  \033[33m!\033[0m  Warning: key should start with 'mono_live_'\n")

    # ── Step 2: Provider settings — all pre-configured, no user input needed ──
    print()
    print("  Configuring provider settings...\n")

    # Detect environment
    is_cloud = any([
        os.environ.get("GITHUB_ACTIONS"),
        os.environ.get("CI"),
        os.environ.get("RAILWAY_ENVIRONMENT"),
        os.environ.get("FLY_APP_NAME"),
        os.environ.get("RENDER"),
        os.environ.get("HEROKU_APP_NAME"),
        not sys.stdin.isatty() and not existing_key,
    ])

    chain       = "base"
    chain_id    = 8453
    rpc_url     = DEFAULTS["base_rpc_url"]
    paymaster   = DEFAULTS["paymaster_url"]
    gateway_url = DEFAULT_API

    # Apply to config
    cfg.update({
        "gateway_url":    gateway_url,
        "base_rpc_url":   rpc_url,
        "paymaster_url":  paymaster,
        "chain":          chain,
        "chain_id":       chain_id,
        "usdc_address":   DEFAULTS["usdc_address"],
        "eurc_address":   DEFAULTS["eurc_address"],
    })
    if api_key:
        cfg["api_key"] = api_key

    save_config(cfg)

    print(f"  \033[32m✓\033[0m  Network:   Base Mainnet (chain ID {chain_id})")
    print(f"  \033[32m✓\033[0m  RPC:       {rpc_url}")
    print(f"  \033[32m✓\033[0m  Paymaster: {paymaster}  (gas sponsored)")
    print(f"  \033[32m✓\033[0m  USDC:      {DEFAULTS['usdc_address']}")
    print(f"  \033[32m✓\033[0m  Config:    {CONFIG_FILE}")

    # ── Step 3: Write to shell profile ────────────────────────────────────────
    print()
    if api_key:
        write_env_to_profile("MONO_API_KEY", api_key)
        print(f"  \033[32m✓\033[0m  MONO_API_KEY written to {detect_shell_profile()}")
    write_env_to_profile("MONO_GATEWAY_URL", gateway_url)

    # ── Step 4: Connection test ────────────────────────────────────────────────
    print()
    if api_key:
        print("  Testing connection...", end="", flush=True)
        ok = test_connection(api_key, gateway_url)
        if ok:
            print(f"\r  \033[32m✓\033[0m  Connected to monospay.com")
        else:
            print(f"\r  \033[33m!\033[0m  Could not connect — check your API key or network")

    # ── Step 5: Done ──────────────────────────────────────────────────────────
    print()
    print("  \033[1m\033[32mAll set.\033[0m\n")
    print("  Quick start:\n")
    print("  \033[2m  from mono_sdk import MonoClient\033[0m")
    print("  \033[2m  client = MonoClient(api_key=\"...\")\033[0m")
    print("  \033[2m  client.health()\033[0m")
    print()
    if is_cloud:
        print("  Cloud/CI detected. Set MONO_API_KEY as an environment secret.\n")
    else:
        print("  Restart your terminal, or run:")
        print(f"  \033[1m  source {detect_shell_profile()}\033[0m\n")


# ── mono config ───────────────────────────────────────────────────────────────

def cmd_config_show(args: argparse.Namespace) -> None:
    cfg = load_config()
    if not cfg:
        print("\n  No config found. Run: mono init\n")
        return
    print(f"\n  Config file: {CONFIG_FILE}\n")
    for k, v in cfg.items():
        if k == "api_key":
            v = f"{str(v)[:15]}...{str(v)[-4:]}" if v else "(not set)"
        print(f"  {k:<22} {v}")
    print()


def cmd_config_set(args: argparse.Namespace) -> None:
    cfg = load_config()
    cfg[args.key] = args.value
    save_config(cfg)
    print(f"\n  \033[32m✓\033[0m  {args.key} = {args.value}\n")


def cmd_config_clear(args: argparse.Namespace) -> None:
    if CONFIG_FILE.exists():
        CONFIG_FILE.unlink()
    print(f"\n  \033[32m✓\033[0m  Config cleared: {CONFIG_FILE}\n")


# ── mono health ───────────────────────────────────────────────────────────────

def cmd_health(args: argparse.Namespace) -> None:
    gateway = get_setting("gateway_url") or DEFAULT_API
    try:
        req = urllib.request.Request(f"{gateway.rstrip('/')}/health")
        with urllib.request.urlopen(req, timeout=10) as resp:
            h = json.loads(resp.read())
    except Exception:
        client = get_client()
        hs = client.health()
        h = {
            "status": hs.status, "ledger_sum": hs.ledger_sum,
            "nodes": {"active": hs.nodes_active, "total": hs.nodes_total},
            "circuit_breaker": {"active": hs.circuit_breaker_active},
        }

    st  = h.get("status", "UNKNOWN")
    icon = "✅" if st in ("HEALTHY", "OK") else ("⚠️" if st == "WARNING" else "❌")
    cb   = h.get("circuit_breaker", {})
    nd   = h.get("nodes", {})

    print(f"\n{icon}  {st}")
    print(f"   Ledger:   {float(h.get('ledger_sum', 0)):.2f} USDC")
    print(f"   Nodes:    {nd.get('active', '?')}/{nd.get('total', '?')} active")
    print(f"   Breaker:  {'ACTIVE ⚠️' if cb.get('active') else 'OFF'}")
    print(f"   API:      {gateway}\n")


# ── Low-balance warning ───────────────────────────────────────────────────────

def _low_balance_warn(balance: float) -> None:
    if balance < 1.00:
        print(f"  \033[33m⚠️\033[0m  Low balance — top up at monospay.com/dashboard")


# ── mono charge ───────────────────────────────────────────────────────────────

def cmd_charge(args: argparse.Namespace) -> None:
    client = get_client()
    result = client.charge(amount=args.amount, memo=args.memo)
    balance = float(result.get("new_balance", 0))
    print(f"\n  \033[32m✓\033[0m  Charged ${args.amount:.4f} USDC")
    if args.memo:
        print(f"     Memo:    {args.memo}")
    print(f"     Balance: ${balance:.3f} USDC")
    _low_balance_warn(balance)
    print()


# ── mono pay ──────────────────────────────────────────────────────────────────

def cmd_pay(args: argparse.Namespace) -> None:
    client = get_client()
    result = client.transfer(to=args.agent, amount=args.amount)
    print(f"\n  \033[32m✓\033[0m  Paid ${args.amount:.2f} USDC → {args.agent}")
    print(f"     TX:      {result.transaction_id}")
    print(f"     Balance: ${result.sender_balance:.3f} USDC")
    _low_balance_warn(result.sender_balance)
    print()


# ── mono balance ──────────────────────────────────────────────────────────────

def cmd_balance(args: argparse.Namespace) -> None:
    client = get_client()
    nodes  = client.list_nodes()
    print()
    for n in nodes:
        icon = "\033[32m●\033[0m" if n.status == "active" else "\033[31m○\033[0m"
        print(f"  {icon}  {n.name:<22}  ${n.balance:.3f} USDC  [{n.status}]")
    print()


# ── mono settle ───────────────────────────────────────────────────────────────

def cmd_settle(args: argparse.Namespace) -> None:
    client = get_client()
    result = client.settle(to=args.to, amount=args.amount)
    print(f"\n\033[32m✓\033[0m  Settlement complete")
    print(f"   TX:            {result.transaction_id}")
    print(f"   Amount:        {result.amount:.4f} USDC")
    print(f"   Your balance:  {result.sender_balance:.4f} USDC\n")


# ── mono status ───────────────────────────────────────────────────────────────

def cmd_status(args: argparse.Namespace) -> None:
    client = get_client()
    nodes  = client.list_nodes()
    total  = sum(n.balance for n in nodes)
    active = sum(1 for n in nodes if n.status == "active")

    print(f"\n  Fleet: {len(nodes)} nodes  ·  {active} active  ·  {total:.2f} USDC total\n")
    for n in nodes:
        icon  = "\033[32m●\033[0m" if n.status == "active" else "\033[31m○\033[0m"
        limit = f"  (cap: ${n.spending_limit:.2f})" if n.spending_limit else ""
        print(f"  {icon}  {n.name:<20}  {n.balance:>10.4f} USDC  [{n.status}]{limit}")
    print()


# ── mono nodes ────────────────────────────────────────────────────────────────

def cmd_nodes_create(args: argparse.Namespace) -> None:
    client = get_client()
    node   = client.create_node(name=args.name, spending_limit=args.limit)
    print(f"\n\033[32m✓\033[0m  Node created")
    print(f"   ID:    {node.id}")
    print(f"   Name:  {node.name}")
    if node.api_key:
        print(f"\n\033[33m!\033[0m  API key (shown ONCE — copy now):")
        print(f"   {node.api_key}\n")


def cmd_nodes_kill(args: argparse.Namespace) -> None:
    client = get_client()
    client.kill_node(args.id)
    print(f"\n\033[32m✓\033[0m  Node {args.id} killed\n")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="mono",
        description="mono SDK CLI — monospay.com",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  mono init                       # First-time setup (run this first)\n"
            "  mono balance                    # Show your balance\n"
            "  mono charge 0.003 'gpt-4o call' # Deduct from budget\n"
            "  mono pay agent_02 1.50          # Pay another agent\n"
            "  mono health                     # Check system status\n"
            "  mono status                     # Show your node fleet\n"
            "  mono settle --to agent_02 --amount 1.50\n"
            "  mono config show                # Show current config\n"
        ),
    )

    sub = parser.add_subparsers(dest="command", metavar="command")

    # init
    p_init = sub.add_parser("init", help="Zero-config setup wizard")
    p_init.add_argument("--force", action="store_true", help="Re-run even if already configured")

    # balance
    sub.add_parser("balance", help="Show your balance")

    # charge
    p_charge = sub.add_parser("charge", help="Deduct from your agent's budget")
    p_charge.add_argument("amount", type=float, help="Amount in USDC")
    p_charge.add_argument("memo", nargs="?", default="", help="Optional memo")

    # pay
    p_pay = sub.add_parser("pay", help="Pay another agent (alias for settle)")
    p_pay.add_argument("agent", help="Recipient node ID")
    p_pay.add_argument("amount", type=float, help="Amount in USDC")

    # health
    sub.add_parser("health", help="Check system health (no auth required)")

    # status
    sub.add_parser("status", help="Show node fleet and balances")

    # settle
    p_settle = sub.add_parser("settle", help="Execute a USDC settlement")
    p_settle.add_argument("--to",     required=True,  help="Recipient node ID")
    p_settle.add_argument("--amount", required=True, type=float, help="Amount in USDC")

    # nodes
    p_nodes   = sub.add_parser("nodes", help="Manage agent nodes")
    nodes_sub = p_nodes.add_subparsers(dest="nodes_cmd", metavar="subcommand")

    nodes_sub.add_parser("list", help="List all nodes")

    p_create = nodes_sub.add_parser("create", help="Create a new node")
    p_create.add_argument("--name",  required=True, help="Node name")
    p_create.add_argument("--limit", type=float, default=None, help="Spending cap (USDC)")

    p_kill = nodes_sub.add_parser("kill", help="Kill a node permanently")
    p_kill.add_argument("--id", required=True, help="Node ID")

    # config
    p_cfg     = sub.add_parser("config", help="Manage configuration")
    cfg_sub   = p_cfg.add_subparsers(dest="cfg_cmd", metavar="subcommand")
    cfg_sub.add_parser("show",  help="Show current config")
    p_cset = cfg_sub.add_parser("set", help="Set a config value")
    p_cset.add_argument("key");  p_cset.add_argument("value")
    cfg_sub.add_parser("clear", help="Delete config file")

    args = parser.parse_args()

    try:
        cmd = args.command
        if cmd == "init":
            cmd_init(args)
        elif cmd == "balance":
            cmd_balance(args)
        elif cmd == "charge":
            cmd_charge(args)
        elif cmd == "pay":
            cmd_pay(args)
        elif cmd == "health":
            cmd_health(args)
        elif cmd == "status":
            cmd_status(args)
        elif cmd == "settle":
            cmd_settle(args)
        elif cmd == "nodes":
            nc = getattr(args, "nodes_cmd", None)
            if   nc == "list":   cmd_status(args)
            elif nc == "create": cmd_nodes_create(args)
            elif nc == "kill":   cmd_nodes_kill(args)
            else:                p_nodes.print_help()
        elif cmd == "config":
            cc = getattr(args, "cfg_cmd", None)
            if   cc == "show":  cmd_config_show(args)
            elif cc == "set":   cmd_config_set(args)
            elif cc == "clear": cmd_config_clear(args)
            else:               p_cfg.print_help()
        else:
            parser.print_help()
            print("\n  \033[2mFirst time? Run: mono init\033[0m\n")

    except MonoError as e:
        print(f"\n  \033[31m✗\033[0m  {e}\n", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n  Aborted.", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    main()
