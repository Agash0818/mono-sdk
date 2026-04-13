"""
MonoClient: The core SDK client for monospay.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from mono_sdk.errors import (
    MonoError,
    NetworkError,
    SystemHaltedError,
    raise_for_error,
)
from mono_sdk.models import HealthStatus, NodeInfo, SettleResult

logger = logging.getLogger("mono_sdk")

DEFAULT_BASE_URL     = "https://api.monospay.com/v1"
DEFAULT_TIMEOUT      = 30
DEFAULT_MAX_RETRIES  = 3
DEFAULT_BACKOFF_BASE = 1.0
DEFAULT_BACKOFF_MAX  = 16.0


class MonoClient:
    """Client for the monospay API."""

    def __init__(
        self,
        api_key:        str,
        base_url:       str   = DEFAULT_BASE_URL,
        timeout:        int   = DEFAULT_TIMEOUT,
        max_retries:    int   = DEFAULT_MAX_RETRIES,
        spending_limit: float | None = None,
    ):
        if not api_key or not api_key.startswith("mono_live_"):
            raise ValueError("API key must start with 'mono_live_'")

        self._api_key        = api_key
        self._base_url       = base_url.rstrip("/")
        self._timeout        = timeout
        self._max_retries    = max_retries
        self._spending_limit = spending_limit

    # ── Public API ────────────────────────────────────────────────────────

    def settle(self, to: str, amount: float, idempotency_key: str | None = None) -> SettleResult:
        """Send a payment between agents.

        `to` accepts agent name ("Agent 07") or UUID.
        """
        if self._spending_limit is not None and amount > self._spending_limit:
            from mono_sdk.errors import SpendingLimitExceededError
            raise SpendingLimitExceededError(
                message=f"Amount {amount} exceeds spending limit of {self._spending_limit} USDC",
                detail="Client-side pre-flight check.",
            )

        amount_micro = round(amount * 1_000_000)
        data = self._request(
            "POST",
            "/settle",
            body={"receiver_id": to, "amount_micro": amount_micro},
            extra_headers={"Idempotency-Key": idempotency_key} if idempotency_key else None,
        )
        return SettleResult.from_dict(data)

    def transfer(self, to: str, amount: float, memo: str = "", idempotency_key: str | None = None) -> SettleResult:
        """Pay another agent by name or UUID via dedicated /transfer endpoint."""
        if self._spending_limit is not None and amount > self._spending_limit:
            from mono_sdk.errors import SpendingLimitExceededError
            raise SpendingLimitExceededError(
                message=f"Amount {amount} exceeds spending limit of {self._spending_limit} USDC",
                detail="Client-side pre-flight check.",
            )

        amount_micro = round(amount * 1_000_000)
        data = self._request(
            "POST",
            "/transfer",
            body={"receiver_id": to, "amount_micro": amount_micro, "memo": memo},
            extra_headers={"Idempotency-Key": idempotency_key} if idempotency_key else None,
        )
        return SettleResult.from_dict(data)

    def health(self) -> HealthStatus:
        """Get system health status (no auth required)."""
        data = self._request("GET", "/health", auth=False)
        return HealthStatus.from_dict(data)

    def balance(self) -> dict[str, Any]:
        """Get the current agent's balance."""
        raw = self._request("GET", "/balance")
        if "balance_usdc" in raw:
            try:
                raw["available_usdc"] = float(str(raw["balance_usdc"]).replace(",", ""))
            except (ValueError, TypeError):
                pass
        return raw

    def list_nodes(self) -> list[NodeInfo]:
        """List all nodes owned by the authenticated user."""
        data = self._request("GET", "/nodes")
        return [NodeInfo.from_dict({"node": n}) for n in data.get("nodes", [])]

    def create_node(self, name: str, spending_limit: float | None = None, wallet_provider: str = "circle") -> NodeInfo:
        """Create a new node via /register."""
        data = self._request("POST", "/register", body={"name": name})
        return NodeInfo.from_dict(data, api_key=data.get("api_key"))

    def kill_node(self, node_id: str) -> dict[str, Any]:
        """Kill (lock) a node permanently."""
        return self._request("DELETE", f"/nodes?id={node_id}")

    def charge(self, amount: float, memo: str = "") -> dict[str, Any]:
        """Deduct amount from this agent's budget."""
        return self._request("POST", "/charge", body={"amount": amount, "memo": memo})

    def set_limits(self, spending_limit: float | None = None, daily_budget: float | None = None) -> dict[str, Any]:
        """Update spending limit and/or daily budget for this agent."""
        body: dict[str, Any] = {}
        if spending_limit is not None:
            body["spending_limit"] = spending_limit
        if daily_budget is not None:
            body["daily_budget"] = daily_budget
        return self._request("POST", "/limits", body=body)

    def inference(self, model: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Proxy an inference request through the mono gateway.

        `model` identifies the target service (e.g. "openai/gpt-4o").
        `payload` is forwarded as-is to the upstream provider.
        """
        return self._request("POST", "/proxy", body={"service": model, "payload": payload})

    def signed_transfer(
        self,
        to_wallet: str,
        amount: float,
        private_key: str,
        supabase_url: str = "https://vcearjwptzdijurqxyra.supabase.co",
        supabase_anon_key: str = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZjZWFyandwdHpkaWp1cnF4eXJhIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzM3Njk4MDcsImV4cCI6MjA4OTM0NTgwN30.F7AWQVq_Qq4zs8WPwRKbNsHgoibqRAC5UOFCB1a-tGI",
    ) -> dict[str, Any]:
        """Send a cryptographically signed transfer.

        Requires a private key — no API key can move funds.

        Args:
            to_wallet:   Recipient 0x wallet address.
            amount:      Amount in USDC (e.g. 1.50).
            private_key: Sender's hex private key (0x-prefixed or raw).
            supabase_url:      Override Supabase project URL.
            supabase_anon_key: Override Supabase anon key (for JWT auth on Edge Function).

        Returns:
            Dict with transaction_id, sender_new_balance, fee, etc.
        """
        try:
            from eth_account import Account
            from eth_account.messages import encode_defunct
        except ImportError:
            raise ImportError(
                "signed_transfer requires eth-account. Install with: "
                "pip install eth-account"
            )

        import uuid as uuid_lib
        import time as time_mod

        # Derive sender address from private key
        if not private_key.startswith("0x"):
            private_key = f"0x{private_key}"
        acct = Account.from_key(private_key)
        sender = acct.address.lower()
        receiver = to_wallet.strip().lower()

        # Build canonical message
        nonce = str(uuid_lib.uuid4())
        timestamp = int(time_mod.time() * 1000)  # epoch ms
        amount_fixed = f"{amount:.6f}"
        canonical = f"mono-transfer:{sender}:{receiver}:{amount_fixed}:{nonce}:{timestamp}"

        # Sign the canonical message
        msg = encode_defunct(text=canonical)
        signed = Account.sign_message(msg, private_key=private_key)
        signature = signed.signature.hex()
        if not signature.startswith("0x"):
            signature = f"0x{signature}"

        # POST to Edge Function
        url = f"{supabase_url}/functions/v1/transfer"
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
            "Authorization": f"Bearer {supabase_anon_key}",
            "apikey": supabase_anon_key,
        }
        payload = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                error_body = json.loads(e.read().decode("utf-8"))
            except Exception:
                error_body = {"error": f"HTTP {e.code}"}
            raise_for_error(e.code, error_body)
            return error_body  # unreachable, raise_for_error always raises

    def transactions(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        """Fetch transaction history for this agent."""
        data = self._request("GET", f"/transactions?limit={limit}&offset={offset}")
        return data.get("transactions", [])

    # ── Internal ──────────────────────────────────────────────────────────

    def _request(self, method: str, path: str, body: dict | None = None, auth: bool = True, extra_headers: dict[str, str] | None = None) -> dict[str, Any]:
        url     = f"{self._base_url}{path}"
        headers = {"Content-Type": "application/json"}
        if auth:
            headers["Authorization"] = f"Bearer {self._api_key}"
        if extra_headers:
            headers.update({k: v for k, v in extra_headers.items() if v})
        payload    = json.dumps(body).encode("utf-8") if body else None
        last_error: Exception | None = None

        for attempt in range(self._max_retries + 1):
            if attempt > 0:
                import random
                delay = min(DEFAULT_BACKOFF_BASE * (2 ** (attempt - 1)), DEFAULT_BACKOFF_MAX)
                delay *= 0.75 + random.random() * 0.5
                time.sleep(delay)

            try:
                req = urllib.request.Request(url, data=payload, headers=headers, method=method)
                with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                    resp_body = json.loads(resp.read().decode("utf-8"))
                    if resp_body.get("status") == "ERROR":
                        raise_for_error(resp.status, resp_body)
                    return resp_body

            except urllib.error.HTTPError as e:
                status_code = e.code
                try:
                    error_body = json.loads(e.read().decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    error_body = {"message": str(e), "code": "UNKNOWN"}
                if status_code == 503 and attempt < self._max_retries:
                    last_error = SystemHaltedError(message=error_body.get("message", "System halted"))
                    continue
                if status_code == 429 and attempt < self._max_retries:
                    last_error = MonoError(message="Rate limited", code="RATE_LIMIT", status_code=429)
                    continue
                raise_for_error(status_code, error_body)

            except urllib.error.URLError as e:
                last_error = NetworkError(message=f"Connection failed: {e.reason}")
                if attempt < self._max_retries:
                    continue
                raise last_error

            except OSError as e:
                last_error = NetworkError(message=f"OS error: {e}")
                if attempt < self._max_retries:
                    continue
                raise last_error

        if last_error:
            raise last_error
        raise MonoError("Request failed after all retries", code="RETRY_EXHAUSTED")

    def __repr__(self) -> str:
        masked = f"{self._api_key[:15]}...{self._api_key[-4:]}"
        return f"MonoClient(api_key='{masked}', base_url='{self._base_url}')"
