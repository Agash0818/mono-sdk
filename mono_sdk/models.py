"""
Typed response models for the mono API.
Uses dataclasses for zero-dependency, clean attribute access.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SettleResult:
    """Returned by client.settle() / client.transfer() on success."""
    transaction_id:    str
    sender_balance:    float
    recipient_balance: float
    amount:            float
    status:            str = "SUCCESS"

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SettleResult":
        # Gateway returns "tx_id" for settle, "transaction_id" for process_m2m_transfer
        tx_id = (
            d.get("transaction_id")
            or d.get("tx_id")
            or d.get("tx_id", "")
        )
        # sender_balance: try several field names across gateway versions
        sender_bal = (
            d.get("sender_balance")
            or d.get("sender_new_balance")
            or d.get("new_balance_usdc")
            or 0
        )
        recipient_bal = (
            d.get("recipient_balance")
            or d.get("receiver_balance")
            or d.get("recipient_new_balance")
            or 0
        )
        # amount: may be in USDC or micro depending on endpoint
        raw_amount = d.get("amount", 0)
        amount = float(raw_amount) if float(raw_amount) < 10_000 else float(raw_amount) / 1_000_000

        return cls(
            transaction_id    = str(tx_id),
            sender_balance    = float(sender_bal),
            recipient_balance = float(recipient_bal),
            amount            = amount,
            status            = d.get("status", "SUCCESS"),
        )


@dataclass(frozen=True)
class TrustStats:
    """Node trust metrics."""
    total_calls:           int   = 0
    successful_calls:      int   = 0
    failed_calls:          int   = 0
    success_rate_pct:      float = 100.0
    total_settled_volume:  float = 0.0
    total_settlements:     int   = 0
    avg_latency_ms:        float | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "TrustStats":
        if not d:
            return cls()
        return cls(
            total_calls          = int(d.get("total_calls", 0)),
            successful_calls     = int(d.get("successful_calls", 0)),
            failed_calls         = int(d.get("failed_calls", 0)),
            success_rate_pct     = float(d.get("success_rate_pct", 100)),
            total_settled_volume = float(d.get("total_settled_volume", 0)),
            total_settlements    = int(d.get("total_settlements", 0)),
            avg_latency_ms       = float(d["avg_latency_ms"]) if d.get("avg_latency_ms") is not None else None,
        )


@dataclass(frozen=True)
class NodeInfo:
    """Returned by client.create_node()."""
    id:              str
    name:            str
    balance:         float
    status:          str
    custody_type:    str        = "managed"
    wallet_provider: str | None = None
    spending_limit:  float | None = None
    created_at:      str        = ""
    api_key:         str | None = None
    trust_stats:     TrustStats = field(default_factory=TrustStats)

    @classmethod
    def from_dict(cls, d: dict[str, Any], api_key: str | None = None) -> "NodeInfo":
        node = d.get("node", d)
        # /register returns agent_id, not id
        node_id = node.get("id") or node.get("agent_id") or d.get("agent_id", "")
        return cls(
            id             = str(node_id),
            name           = node.get("name", ""),
            balance        = float(node.get("balance", 0)),
            status         = node.get("status", "active"),
            custody_type   = node.get("custody_type", "managed"),
            wallet_provider= node.get("wallet_provider"),
            spending_limit = float(node["spending_limit"]) if node.get("spending_limit") is not None else None,
            created_at     = node.get("created_at", ""),
            api_key        = api_key or d.get("api_key"),
            trust_stats    = TrustStats.from_dict(node.get("trust_stats")),
        )


@dataclass(frozen=True)
class HealthStatus:
    """Returned by client.health()."""
    status:                  str
    ledger_sum:              float
    nodes_total:             int
    nodes_active:            int
    nodes_locked:            int
    circuit_breaker_active:  bool
    circuit_breaker_reason:  str | None
    last_check:              str | None
    last_delta:              float

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "HealthStatus":
        nodes = d.get("nodes", {})
        cb    = d.get("circuit_breaker", {})
        return cls(
            status                 = d.get("status", "UNKNOWN"),
            ledger_sum             = float(d.get("ledger_sum", 0)),
            nodes_total            = int(nodes.get("total", 0)),
            nodes_active           = int(nodes.get("active", 0)),
            nodes_locked           = int(nodes.get("locked", 0)),
            circuit_breaker_active = cb.get("active", False),
            circuit_breaker_reason = cb.get("reason"),
            last_check             = d.get("last_check"),
            last_delta             = float(d.get("last_delta", 0)),
        )
