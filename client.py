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

# Public-facing API — no Supabase URL exposed
DEFAULT_BASE_URL   = "https://mono-production-b257.up.railway.app/v1"
DEFAULT_TIMEOUT    = 30
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE = 1.0
DEFAULT_BACKOFF_MAX  = 16.0


class MonoClient:
    """Client for the mono settlement API.

    Args:
        api_key:        Your mono API key (starts with 'mono_live_').
        base_url:       API base URL. Override for self-hosted or staging.
        timeout:        Request timeout in seconds.
        max_retries:    Max retry attempts on 503 (circuit breaker).
        spending_limit: Optional client-side spending limit in USDC.

    Example:
        >>> client = MonoClient(api_key="mono_live_abc123")
        >>> result = client.settle(to="node_id", amount=1.50)
        >>> print(result.sender_balance)
    """

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

        self._api_key       = api_key
        self._base_url      = base_url.rstrip("/")
        self._timeout       = timeout
        self._max_retries   = max_retries
        self._spending_limit = spending_limit

    # ── Public API ────────────────────────────────────────────────────────

    def settle(self, to: str, amount: float) -> SettleResult:
        """Execute an M2M settlement (transfer USDC between agents).

        Args:
            to:     Recipient node UUID or name.
            amount: Amount in USDC (must be > 0).

        Returns:
            SettleResult with transaction_id, balances, and amount.

        Raises:
            InsufficientBalanceError: Not enough USDC.
            NodeLockedError:          Sender node is killed/locked.
            RecipientNotFoundError:   Target node doesn't exist.
            SpendingLimitExceededError: Amount exceeds limit.
            SystemHaltedError:        Circuit breaker active (after retries).
        """
        if self._spending_limit is not None and amount > self._spending_limit:
            from mono_sdk.errors import SpendingLimitExceededError
            raise SpendingLimitExceededError(
                message=f"Amount {amount} exceeds client spending limit of {self._spending_limit} USDC",
                detail="Client-side pre-flight check.",
            )
        data = self._request("POST", "/settle", body={"to": to, "amount": amount})
        return SettleResult.from_dict(data)

    def health(self) -> HealthStatus:
        """Get system health status (no auth required)."""
        data = self._request("GET", "/health", auth=False)
        return HealthStatus.from_dict(data)

    def balance(self) -> dict[str, Any]:
        """Get the current agent's balance.

        Returns:
            Dict with available_usdc, agent_id, currency.
        """
        return self._request("GET", "/balance")

    def list_nodes(self) -> list[NodeInfo]:
        """List all nodes owned by the authenticated user."""
        data = self._request("GET", "/nodes")
        return [NodeInfo.from_dict({"node": n}) for n in data.get("nodes", [])]

    def get_node(self, node_id: str) -> NodeInfo:
        """Get detailed info for a specific node."""
        data = self._request("GET", f"/nodes?id={node_id}")
        return NodeInfo.from_dict(data)

    def create_node(
        self,
        name:            str,
        spending_limit:  float | None = None,
        wallet_provider: str = "circle",
    ) -> NodeInfo:
        """Create a new node. The API key is returned ONCE — save it."""
        data = self._request("POST", "/nodes", body={
            "name":            name,
            "spending_limit":  spending_limit,
            "wallet_provider": wallet_provider,
        })
        return NodeInfo.from_dict(data, api_key=data.get("api_key"))

    def kill_node(self, node_id: str) -> dict[str, Any]:
        """Kill (lock) a node permanently."""
        return self._request("DELETE", f"/nodes?id={node_id}")

    def charge(self, amount: float, memo: str = "") -> dict[str, Any]:
        """Deduct amount from this agent's budget.

        Args:
            amount: USDC to deduct (must be > 0).
            memo:   Optional description for the ledger.

        Returns:
            Dict with transaction_id, new_balance.
        """
        return self._request("POST", "/charge", body={"amount": amount, "memo": memo})

    def transfer(self, to: str, amount: float, memo: str = "") -> SettleResult:
        """Pay another agent (alias for settle with optional memo)."""
        data = self._request("POST", "/settle", body={"to": to, "amount": amount, "memo": memo})
        return SettleResult.from_dict(data)

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
        payload = json.dumps(body).encode("utf-8") if body else None
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
