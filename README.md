# monospay

[![PyPI](https://img.shields.io/pypi/v/monospay)](https://pypi.org/project/monospay/)
[![Python](https://img.shields.io/pypi/pyversions/monospay)](https://pypi.org/project/monospay/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

![LangChain](https://img.shields.io/badge/LangChain-compatible-blue)
![CrewAI](https://img.shields.io/badge/CrewAI-compatible-blue)
![OpenAI](https://img.shields.io/badge/OpenAI-function_calling-blue)
![AutoGen](https://img.shields.io/badge/AutoGen-compatible-blue)
![Claude](https://img.shields.io/badge/Claude-MCP_server-blue)
![Cursor](https://img.shields.io/badge/Cursor-MCP_server-blue)
![Google ADK](https://img.shields.io/badge/Google_ADK-compatible-blue)

Payment infrastructure for AI agents.  
Your agent can pay.

---

## Get started

**Claude Desktop** — paste into your config, done:

```json
{
  "mcpServers": {
    "monospay": {
      "command": "npx",
      "args": ["-y", "monospay-mcp"],
      "env": { "MONO_API_KEY": "mono_live_..." }
    }
  }
}
```

**Claude Code** — one command:

```bash
claude mcp add monospay -e MONO_API_KEY=mono_live_... -- npx -y monospay-mcp
```

**Python SDK** — 3 lines of code:

```bash
pip install monospay
```

```python
from mono_sdk import MonoClient
client = MonoClient(api_key="mono_live_...")
client.signed_transfer(to_wallet="0x...", amount=1.00, private_key="0x...")
```

**Dashboard** — no code, manage everything in your browser:  
[monospay.com/dashboard](https://monospay.com/dashboard)

Get your API key at [monospay.com/dashboard](https://monospay.com/dashboard) → Agents → Issue API key.

---

## Why monospay

- **10 minutes to first payment** — paste config or pip install, your agent pays
- **Works with every AI framework** — LangChain, CrewAI, OpenAI, Claude, Cursor, Google ADK
- **Sub-cent transactions** — no $0.30 minimum like card networks
- **Agents don't need bank accounts** — just a wallet and a private key
- **You stay in control** — spending limits, daily budgets, transaction history

---

## Python SDK — Quickstart

```python
from mono_sdk import MonoClient

# Each agent has its own API key (from dashboard -> Agents -> Issue API key)
agent_a = MonoClient(api_key="mono_live_...")

# Agent A checks its balance
balance = agent_a.balance()
print(f"Budget: ${balance['available_usdc']}")  # -> Budget: $50.00

# Agent A pays Agent B (cryptographically signed)
result = agent_a.signed_transfer(
    to_wallet="0x...",
    amount=1.50,
    private_key="0x...",
)
print(result["transaction_id"])
```

No wallets to manage. No gas. No KYC.

---

## Security

- All transfers are cryptographically signed — no API key can move funds
- Replay protection built in
- Server-side spending limits and daily budgets

> See [SECURITY.md](SECURITY.md) for details.

---

## 2-Agent Example

```python
from mono_sdk import MonoClient

agent_a = MonoClient(api_key="mono_live_A...")
agent_b = MonoClient(api_key="mono_live_B...")

# Agent A pays Agent B (cryptographically signed)
agent_a.signed_transfer(
    to_wallet="0xAgentB_Wallet",
    amount=0.50,
    private_key="0xAgentA_Key",
)
print(f"A balance: ${agent_a.balance()['available_usdc']}")
print(f"B balance: ${agent_b.balance()['available_usdc']}")
```

---

## CLI — for developers

The CLI lets you inspect and manage your agents from the terminal.

```bash
mono balance          # Show your agent's balance
mono health           # Check gateway status
mono config show      # Show current config
```

---

## LangChain

```bash
pip install "monospay[langchain]"
```

```python
from mono_sdk.langchain_tools import MonoToolkit

toolkit = MonoToolkit(api_key="mono_live_...")
tools   = toolkit.get_tools()
```

---

## MCP Server — details

| With API key only | + Private Key |
|---|---|
| ✅ Check balance | ✅ Check balance |
| ✅ View transactions | ✅ View transactions |
| ✅ Set spending limits | ✅ Set spending limits |
| ❌ Transfer USDC | ✅ **Transfer USDC** |

Your private key never leaves your machine.

<details>
<summary>Alternative: pip / uvx</summary>

```bash
pip install "monospay[mcp]"
mono-mcp
```

Or with uvx: `uvx --from "monospay[mcp]" mono-mcp`
</details>

Available tools: `mono_balance`, `mono_transfer`, `mono_transactions`, `mono_health`.

---

## OpenAI Function Calling

```python
from mono_sdk.openai_functions import get_mono_tools, handle_tool_call

tools = get_mono_tools()
# Pass tools to your OpenAI chat completion
```

---

## Error handling

```python
from mono_sdk.errors import InsufficientBalanceError, AuthenticationError

try:
    agent_a.signed_transfer(to_wallet="0x...", amount=999.00, private_key="0x...")
except InsufficientBalanceError:
    print("Out of budget — top up at monospay.com/dashboard")
except AuthenticationError:
    print("Invalid key — run: mono init")
```

---

## Links

- Dashboard · [monospay.com](https://monospay.com)
- Docs · [monospay.com/docs](https://monospay.com/docs)
- PyPI · [monospay](https://pypi.org/project/monospay/)
