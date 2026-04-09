"""
MonoClient: The core SDK client for the mono M2M settlement network.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
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

DEFAULT_BASE_URL     = "https://mono-production-b257.up.railway.app/v1"
DEFAULT_TIMEOUT      = 30
DEFAULT_MAX_RETRIES  = 3
DEFAULT_BACKOFF_BASE = 1.0
DEFAULT_BACKOFF_MAX  = 16.0


class MonoClient:
    """Client for the mono M2M settlement API."""

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

    def settle(self, to: str, amount: float) -> SettleResult:
        """Execute an M2M settlement between agents.

        Gateway endpoint: POST /v1/settle?receiver_id=<uuid>&amount_micro=<int>
        Returns: {"status": "settled", "tx_id": "..."}
        We then fetch sender balance from /balance to populate SettleResult.
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
            f"/settle?receiver_id={to}&amount_micro={amount_micro}",
        )

        # Gateway only returns tx_id — fetch fresh balance for full SettleResult
        tx_id = data.get("tx_id") or data.get("transaction_id", "")
        try:
            bal = self.balance()
            sender_balance = float(
                bal.get("balance_usdc", bal.get("available_usdc", 0))
            )
        except Exception:
            sender_balance = 0.0

        return SettleResult(
            transaction_id    = str(tx_id),
            sender_balance    = sender_balance,
            recipient_balance = 0.0,   # gateway doesn't expose this
            amount            = amount,
            status            = "SUCCESS",
        )

    def transfer(self, to: str, amount: float, memo: str = "") -> SettleResult:
        """Pay another agent. Alias for settle."""
        return self.settle(to=to, amount=amount)

    def health(self) -> HealthStatus:
        """Get system health status (no auth required)."""
        data = self._request("GET", "/health", auth=False)
        return HealthStatus.from_dict(data)

    def balance(self) -> dict[str, Any]:
        """Get the current agent's balance (authoritative from Supabase)."""
        raw = self._request("GET", "/balance")
        # Gateway returns balance_usdc as formatted string e.g. "1.000000"
        # Normalise to a float under "available_usdc" for CLI compatibility
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

    def create_node(
        self,
        name:            str,
        spending_limit:  float | None = None,
        wallet_provider: str = "circle",
    ) -> NodeInfo:
        """Create a new node via /register. API key shown once."""
        data = self._request("POST", "/register", body={"name": name})
        return NodeInfo.from_dict(data, api_key=data.get("api_key"))

    def kill_node(self, node_id: str) -> dict[str, Any]:
        """Kill (lock) a node permanently."""
        return self._request("DELETE", f"/nodes?id={node_id}")

    def charge(self, amount: float, memo: str = "") -> dict[str, Any]:
        """Deduct amount from this agent's budget via /proxy."""
        return self._request("POST", "/charge", body={"amount": amount, "memo": memo})

    # ── Internal ──────────────────────────────────────────────────────────

    def _request(
        self,
        method: str,
        path:   str,
        body:   dict | None = None,
        auth:   bool = True,
    ) -> dict[str, Any]:
        url     = f"{self._base_url}{path}"
        headers = {"Content-Type": "application/json"}
        if auth:
            headers["Authorization"] = f"Bearer {self._api_key}"
        payload    = json.dumps(body).encode("utf-8") if body else None
        last_error: Exception | None = None

        for attempt in range(self._max_retries + 1):
            if attempt > 0:
                import random
                delay = min(DEFAULT_BACKOFF_BASE * (2 ** (attempt - 1)), DEFAULT_BACKOFF_MAX)
                delay *= 0.75 + random.random() * 0.5
                logger.info(f"Retry {attempt}/{self._max_retries} after {delay:.1f}s")
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
