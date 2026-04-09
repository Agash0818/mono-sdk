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

## CLI

```bash
mono balance                                   # Show balance
mono transfer --to <agent_id> --amount 1.50    # Send USDC
mono settle   --to <agent_id> --amount 1.50    # On-chain settle
mono health                                    # Gateway status
mono config show                               # Show config
```

---

## Python SDK

```python
from mono_sdk import MonoClient

client = MonoClient(api_key="mono_live_...")

# Check balance
balance = client.balance()
print(f"Budget: ${balance['available_usdc']}")  # → Budget: $50.00

# Pay another agent instantly
client.transfer(to="agent_02", amount=1.50)

# On-chain settlement
result = client.settle(to="agent_02", amount=1.50)
print(result.transaction_id)
```

No wallets. No gas. No KYC.

---

## How it works

```
Developer  →  funds agent via dashboard (USDC)
Agent      →  spends via transfer() / settle()
Dashboard  →  real-time balance as agent runs
```

Every `transfer()` is an off-chain ledger write — confirmed in 15ms,
settled on Base L2 periodically.

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
    client.transfer(to="agent_02", amount=999.00)
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
