"""
monospay MCP Server — AI agent payments.

Environment:
    MONO_PRIVATE_KEY   Required for transfers.
    MONO_API_KEY       Required for read-only operations (balance, history).
    MONO_API_BASE      Optional. Override gateway URL.

Usage:
    mono-mcp                          # stdio (Claude Desktop, Cursor)
    mono-mcp --http --port 8080       # Streamable HTTP (remote agents)
"""

from __future__ import annotations

import json
import os
import sys
import uuid as uuid_lib
import urllib.error
import urllib.request
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field, ConfigDict

# ── Constants ─────────────────────────────────────────────────────────────────

MONO_API_BASE = os.environ.get("MONO_API_BASE", "https://api.monospay.com/v1")
MONO_API_KEY = os.environ.get("MONO_API_KEY", "")
MONO_PRIVATE_KEY = os.environ.get("MONO_PRIVATE_KEY", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://vcearjwptzdijurqxyra.supabase.co")
# Public anon key — read-only, safe to embed
SUPABASE_ANON_KEY = os.environ.get(
    "SUPABASE_ANON_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZjZWFyandwdHpkaWp1cnF4eXJhIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzM3Njk4MDcsImV4cCI6MjA4OTM0NTgwN30.F7AWQVq_Qq4zs8WPwRKbNsHgoibqRAC5UOFCB1a-tGI",
)

# ── HTTP Helpers ──────────────────────────────────────────────────────────────

def _gateway_request(method: str, path: str, body: dict | None = None) -> dict[str, Any]:
    """Read-only call to the mono Gateway (API-key auth). No money movement."""
    if not MONO_API_KEY:
        return {"error": "MONO_API_KEY_NOT_SET", "detail": "Set MONO_API_KEY for read-only operations."}

    url = f"{MONO_API_BASE}{path}"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {MONO_API_KEY}",
        "User-Agent": "monospay/1.0",
    }
    payload = json.dumps(body).encode("utf-8") if body else None

    try:
        req = urllib.request.Request(url, data=payload, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode("utf-8"))
        except Exception:
            err = {}
        return {"error": err.get("error", f"HTTP {e.code}"), "detail": err.get("detail", str(e))}
    except Exception as e:
        return {"error": "CONNECTION_FAILED", "detail": str(e)}


def _signed_edge_request(
    sender: str,
    receiver: str,
    amount: float,
    nonce: str,
    timestamp: int,
    signature: str,
) -> dict[str, Any]:
    """Send signed transfer to edge function."""
    url = f"{SUPABASE_URL}/functions/v1/transfer"
    body = {
        "sender_address": sender,
        "receiver_address": receiver,
        "amount": amount,
        "nonce": nonce,
        "timestamp": timestamp,
        "signature": signature,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
        "apikey": SUPABASE_ANON_KEY,
        "User-Agent": "monospay/1.0",
    }
    payload = json.dumps(body).encode("utf-8")

    try:
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode("utf-8"))
        except Exception:
            err = {}
        return {"error": err.get("error", f"HTTP {e.code}"), "detail": err.get("detail", str(e))}
    except Exception as e:
        return {"error": "CONNECTION_FAILED", "detail": str(e)}


def _format_result(data: dict[str, Any]) -> str:
    if "error" in data:
        return json.dumps({"error": data["error"], "detail": data.get("detail", "")}, indent=2)
    return json.dumps(data, indent=2)


# ── Signing ───────────────────────────────────────────────────────────────────

def _sign_transfer(receiver: str, amount: float) -> dict[str, Any]:
    """Build canonical message, sign with private key, return signed payload."""
    if not MONO_PRIVATE_KEY:
        return {"error": "MONO_PRIVATE_KEY_NOT_SET", "detail": "Set MONO_PRIVATE_KEY env var (0x-prefixed hex)."}

    try:
        from eth_account import Account
        from eth_account.messages import encode_defunct
    except ImportError:
        return {"error": "MISSING_DEPENDENCY", "detail": "pip install eth-account"}

    import time as time_mod

    pk = MONO_PRIVATE_KEY if MONO_PRIVATE_KEY.startswith("0x") else f"0x{MONO_PRIVATE_KEY}"
    acct = Account.from_key(pk)
    sender = acct.address.lower()
    receiver = receiver.strip().lower()

    nonce = str(uuid_lib.uuid4())
    timestamp = int(time_mod.time() * 1000)
    amount_fixed = f"{amount:.6f}"

    canonical = f"mono-transfer:{sender}:{receiver}:{amount_fixed}:{nonce}:{timestamp}"

    msg = encode_defunct(text=canonical)
    signed = Account.sign_message(msg, private_key=pk)
    signature = signed.signature.hex()
    if not signature.startswith("0x"):
        signature = f"0x{signature}"

    return {
        "sender": sender,
        "receiver": receiver,
        "amount": amount,
        "nonce": nonce,
        "timestamp": timestamp,
        "signature": signature,
    }


# ── MCP Server ────────────────────────────────────────────────────────────────

mcp = FastMCP(
    "mono_mcp",
    instructions=(
        "monospay lets AI agents send payments. "
        "Use mono_transfer to send money, mono_balance to check funds. "
        "All amounts are in USD."
    ),
)


# ── Tool: Health ──────────────────────────────────────────────────────────────

@mcp.tool(
    name="mono_health",
    annotations={
        "title": "Health Check",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def mono_health() -> str:
    """Check if the mono payment gateway is online and healthy."""
    try:
        url = f"{MONO_API_BASE}/health"
        req = urllib.request.Request(url, method="GET", headers={"User-Agent": "monospay/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.dumps(json.loads(resp.read().decode("utf-8")), indent=2)
    except Exception as e:
        return json.dumps({"error": "GATEWAY_UNREACHABLE", "detail": str(e)}, indent=2)


# ── Tool: Balance (read-only, API key) ────────────────────────────────────────

@mcp.tool(
    name="mono_balance",
    annotations={
        "title": "Check Agent Balance",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def mono_balance() -> str:
    """Check the current USDC balance. Read-only, uses API key."""
    result = _gateway_request("GET", "/balance")
    if "error" in result:
        return _format_result(result)
    return json.dumps({
        "agent_id": result.get("agent_id"),
        "name": result.get("name"),
        "balance_usdc": result.get("balance_usdc"),
        "balance_micro": result.get("balance_micro"),
    }, indent=2)


# ── Tool: Transfer ────────────────────────────────────────────────────────────

class TransferInput(BaseModel):
    """Send USDC to another agent wallet."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    to: str = Field(
        ...,
        description='Recipient 0x wallet address (e.g., "0x874afb8b23b968ce61a95124db785f8b8cf51945")',
        min_length=42,
        max_length=42,
    )
    amount: float = Field(
        ...,
        description="Amount in USDC to send (e.g., 1.50 for $1.50)",
        gt=0,
        le=10000,
    )


@mcp.tool(
    name="mono_transfer",
    annotations={
        "title": "Send Payment",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def mono_transfer(params: TransferInput) -> str:
    """Send money to another agent. Requires MONO_PRIVATE_KEY."""
    signed = _sign_transfer(params.to, params.amount)
    if "error" in signed:
        return _format_result(signed)

    result = _signed_edge_request(
        sender=signed["sender"],
        receiver=signed["receiver"],
        amount=signed["amount"],
        nonce=signed["nonce"],
        timestamp=signed["timestamp"],
        signature=signed["signature"],
    )
    return _format_result(result) if "error" in result else json.dumps(result, indent=2)


# ── Tool: Transactions (read-only, API key) ──────────────────────────────────

class TransactionsInput(BaseModel):
    """Fetch transaction history."""
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=10, ge=1, le=100, description="Results to return (1-100)")
    offset: int = Field(default=0, ge=0, description="Pagination offset")


@mcp.tool(
    name="mono_transactions",
    annotations={
        "title": "Transaction History",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def mono_transactions(params: TransactionsInput) -> str:
    """Fetch transaction history. Read-only, uses API key."""
    result = _gateway_request("GET", f"/transactions?limit={params.limit}&offset={params.offset}")
    if "error" in result:
        return _format_result(result)
    return json.dumps(result.get("transactions", []), indent=2)


# ── Tool: Set Limits (API key, does not move funds) ──────────────────────────

class SetLimitsInput(BaseModel):
    """Set spending limits."""
    model_config = ConfigDict(extra="forbid")

    spending_limit: Optional[float] = Field(default=None, ge=0, description="Max USDC per transaction")
    daily_budget: Optional[float] = Field(default=None, ge=0, description="Max USDC per day")


@mcp.tool(
    name="mono_set_limits",
    annotations={
        "title": "Set Spending Limits",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def mono_set_limits(params: SetLimitsInput) -> str:
    """Set spending controls. Does not move funds — uses API key."""
    body: dict[str, Any] = {}
    if params.spending_limit is not None:
        body["spending_limit"] = params.spending_limit
    if params.daily_budget is not None:
        body["daily_budget"] = params.daily_budget
    if not body:
        return json.dumps({"error": "NO_LIMITS_PROVIDED"}, indent=2)

    result = _gateway_request("POST", "/limits", body=body)
    return _format_result(result)


# ── Entry Point ───────────────────────────────────────────────────────────────

def main():
    """CLI entry point for mono-mcp command."""
    has_key = bool(MONO_API_KEY)
    has_pk = bool(MONO_PRIVATE_KEY)

    if not has_key and not has_pk:
        print("", file=sys.stderr)
        print("  monospay · your AI agent can send payments", file=sys.stderr)
        print("  ─────────────────────────────────────────────────", file=sys.stderr)
        print("", file=sys.stderr)
        print("  Almost there! Two steps to connect your agent:", file=sys.stderr)
        print("", file=sys.stderr)
        print("  1. Get your keys at monospay.com/dashboard", file=sys.stderr)
        print("     → Agents → select agent → Issue API key", file=sys.stderr)
        print("", file=sys.stderr)
        print("  2. Set them in your environment:", file=sys.stderr)
        print("     export MONO_API_KEY=mono_live_...", file=sys.stderr)
        print("     export MONO_PRIVATE_KEY=0x...", file=sys.stderr)
        print("", file=sys.stderr)
        print("  Or add them to your Claude Desktop config:", file=sys.stderr)
        print('  {"mcpServers":{"mono":{"command":"mono-mcp",', file=sys.stderr)
        print('    "env":{"MONO_API_KEY":"mono_live_...",', file=sys.stderr)
        print('           "MONO_PRIVATE_KEY":"0x..."}}}', file=sys.stderr)
        print("", file=sys.stderr)
    else:
        print("", file=sys.stderr)
        print("  ✓ monospay ready — your agent can pay.", file=sys.stderr)
        print(f"    API key: {'✓' if has_key else '✗'}  Private key: {'✓' if has_pk else '✗'}", file=sys.stderr)
        print("    Tools: mono_balance, mono_transfer, mono_transactions", file=sys.stderr)
        print("", file=sys.stderr)

    if "--http" in sys.argv:
        port = 8080
        for i, arg in enumerate(sys.argv):
            if arg == "--port" and i + 1 < len(sys.argv):
                port = int(sys.argv[i + 1])
        print(f"  Listening on http://0.0.0.0:{port}", file=sys.stderr)
        mcp.run(transport="streamable_http", port=port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
