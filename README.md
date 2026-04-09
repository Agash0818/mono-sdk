# mono SDK

Financial infrastructure for autonomous AI agents.  
Your agent can think. Now it can pay.

---

## Install

```bash
# macOS / Linux
curl -fsSL https://monospay.com/install.sh | bash

# Windows (WSL or Git Bash)
pip install mono-m2m-sdk && mono init
```

Works on macOS, Linux, Windows · Python 3.9+

---

## How it works

mono is for **developers building AI agents** — not end users.

```
1. You create agents on monospay.com/dashboard
2. Each agent gets a unique ID and API key
3. Your code uses the SDK to transfer USDC between agents automatically
```

The agent names come from your dashboard. You wire them up in your code once — then agents pay each other autonomously.

---

## Python SDK — Quickstart

```python
from mono_sdk import MonoClient

# Each agent has its own API key (from dashboard → Agents → Issue API key)
agent_a = MonoClient(api_key="mono_live_...")

# Agent A checks its balance
balance = agent_a.balance()
print(f"Budget: ${balance['available_usdc']}")  # → Budget: $50.00

# Agent A pays Agent B by name (or by ID)
result = agent_a.transfer(to="Agent 08", amount=1.50)
print(result.transaction_id)
```

No wallets. No gas. No KYC.

---

## CLI — for developers

The CLI lets you inspect and manage your agents from the terminal.

```bash
mono balance          # Show your agent's balance
mono health           # Check gateway status
mono config show      # Show current config
```

Transfers happen in your code via the Python SDK — not manually via CLI.

---

## Where do I find the agent name or ID?

```
monospay.com/dashboard → Agents → your agent name is shown in the list
```

---

## LangChain

```bash
pip install "mono-m2m-sdk[langchain]"
```

```python
from mono_sdk.langchain_tools import MonoToolkit

toolkit = MonoToolkit(api_key="mono_live_...")
tools   = toolkit.get_tools()
```

---

## Error handling

```python
from mono_sdk.errors import InsufficientBalanceError, AuthenticationError

try:
    agent_a.transfer(to="Agent 08", amount=999.00)
except InsufficientBalanceError:
    print("Out of budget — top up at monospay.com/dashboard")
except AuthenticationError:
    print("Invalid key — run: mono init")
```

---

## Links

- Dashboard · [monospay.com](https://monospay.com)
- Docs · [monospay.com/docs](https://monospay.com/docs)
- PyPI · [mono-m2m-sdk](https://pypi.org/project/mono-m2m-sdk/)
- Contract · [BaseScan 0xA9DC3105…](https://basescan.org/address/0xA9DC3105ec1A84E4Bc3c9702dFC772a6efA2CDBA)
- Built on [Base](https://base.org) · Settled in [USDC](https://www.circle.com/usdc)
