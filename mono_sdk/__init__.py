"""
mono-sdk: The official Python SDK for the mono M2M settlement network.

Usage:
    from mono_sdk import MonoClient

    client = MonoClient(api_key="mono_live_xxxxx")
    result = client.settle(to="recipient_node_id", amount=0.50)
    print(result.transaction_id, result.sender_balance)
"""

from mono_sdk.client import MonoClient
from mono_sdk.errors import (
    MonoError,
    AuthenticationError,
    InsufficientBalanceError,
    NodeLockedError,
    RecipientNotFoundError,
    SpendingLimitExceededError,
    SystemHaltedError,
    RateLimitError,
    NetworkError,
)
from mono_sdk.models import (
    SettleResult,
    NodeInfo,
    HealthStatus,
    TrustStats,
)

__version__ = "0.4.7"

__all__ = [
    "MonoClient",
    "MonoError",
    "AuthenticationError",
    "InsufficientBalanceError",
    "NodeLockedError",
    "RecipientNotFoundError",
    "SpendingLimitExceededError",
    "SystemHaltedError",
    "RateLimitError",
    "NetworkError",
    "SettleResult",
    "NodeInfo",
    "HealthStatus",
    "TrustStats",
]
