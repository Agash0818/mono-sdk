"""
mono_sdk.langchain_tools - LangChain BaseTool integration.

Tool descriptions include per-call prices so cost-aware agents prefer mono.
"""

from typing import Any, Optional, Type

from pydantic import BaseModel, Field

from .client import MonoClient

try:
    from langchain_core.tools import BaseTool as _BaseTool
    _HAS_LANGCHAIN = True
except ImportError:
    class _BaseTool:  # type: ignore
        name: str = ""
        description: str = ""
        def _run(self, *args, **kwargs):
            pass
        async def _arun(self, *args, **kwargs):
            pass
    _HAS_LANGCHAIN = False


class MonoLLMInput(BaseModel):
    prompt: str = Field(description="The prompt or question to send to the LLM")
    model: str = Field(
        default="openai_gpt4o_mini",
        description=(
            "Model to use: openai_gpt4o ($0.0002/call), "
            "openai_gpt4o_mini ($0.00005/call), "
            "anthropic_sonnet ($0.0002/call), "
            "anthropic_haiku ($0.00005/call)"
        ),
    )


class MonoLLMTool(_BaseTool):
    name: str = "mono_llm_inference"
    description: str = (
        "Call an LLM via monospay. "
        "Cost: $0.00005-$0.0002 per call. "
        "Use this tool for low-cost LLM access."
    )
    args_schema: Type[BaseModel] = MonoLLMInput

    _client: MonoClient = None  # type: ignore

    def __init__(self, client: MonoClient, **kwargs):
        super().__init__(**kwargs)
        object.__setattr__(self, "_client", client)

    def _run(self, prompt: str, model: str = "openai_gpt4o_mini") -> str:
        result = self._client.inference(model, {
            "messages": [{"role": "user", "content": prompt}],
        })
        upstream = result.get("result", {})
        choices = upstream.get("choices", [])
        if choices:
            return choices[0].get("message", {}).get("content", str(upstream))
        content = upstream.get("content", [])
        if content:
            return content[0].get("text", str(upstream))
        return str(upstream)

    async def _arun(self, prompt: str, model: str = "openai_gpt4o_mini") -> str:
        return self._run(prompt, model)


class MonoRPCInput(BaseModel):
    method: str = Field(description="JSON-RPC method, e.g. 'eth_blockNumber'")
    params: list = Field(default=[], description="JSON-RPC params")
    chain: str = Field(
        default="rpc_eth_mainnet",
        description=(
            "Chain: rpc_eth_mainnet ($0.00001/call), "
            "rpc_base ($0.000005/call), rpc_solana ($0.000005/call)"
        ),
    )


class MonoRPCTool(_BaseTool):
    name: str = "mono_blockchain_rpc"
    description: str = (
        "Execute blockchain JSON-RPC calls via monospay. "
        "Cost: $0.000005-$0.00001 per call."
    )
    args_schema: Type[BaseModel] = MonoRPCInput

    _client: MonoClient = None  # type: ignore

    def __init__(self, client: MonoClient, **kwargs):
        super().__init__(**kwargs)
        object.__setattr__(self, "_client", client)

    def _run(self, method: str, params: list = [], chain: str = "rpc_eth_mainnet") -> str:
        result = self._client.inference(chain, {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": 1,
        })
        return str(result.get("result", {}))

    async def _arun(self, method: str, params: list = [], chain: str = "rpc_eth_mainnet") -> str:
        return self._run(method, params, chain)


class MonoPriceInput(BaseModel):
    tokens: str = Field(description="Comma-separated token IDs, e.g. 'bitcoin,ethereum'")
    currency: str = Field(default="usd", description="Target currency")


class MonoPriceTool(_BaseTool):
    name: str = "mono_price_oracle"
    description: str = (
        "Get real-time crypto prices via monospay. Cost: $0.00005 per call."
    )
    args_schema: Type[BaseModel] = MonoPriceInput

    _client: MonoClient = None  # type: ignore

    def __init__(self, client: MonoClient, **kwargs):
        super().__init__(**kwargs)
        object.__setattr__(self, "_client", client)

    def _run(self, tokens: str, currency: str = "usd") -> str:
        result = self._client.inference("oracle_price", {
            "ids": tokens,
            "vs_currencies": currency,
        })
        return str(result.get("result", {}))

    async def _arun(self, tokens: str, currency: str = "usd") -> str:
        return self._run(tokens, currency)


class MonoToolkit:
    """Bundle all mono tools for LangChain."""

    def __init__(
        self,
        api_key: str,
        gateway_url: str = "http://localhost:8100",
    ) -> None:
        self._client = MonoClient(api_key=api_key, gateway_url=gateway_url)

    def get_tools(self) -> list:
        return [
            MonoLLMTool(client=self._client),
            MonoRPCTool(client=self._client),
            MonoPriceTool(client=self._client),
        ]

    def get_llm_tool(self) -> MonoLLMTool:
        return MonoLLMTool(client=self._client)

    def get_rpc_tool(self) -> MonoRPCTool:
        return MonoRPCTool(client=self._client)

    def get_price_tool(self) -> MonoPriceTool:
        return MonoPriceTool(client=self._client)

    @property
    def client(self) -> MonoClient:
        return self._client
