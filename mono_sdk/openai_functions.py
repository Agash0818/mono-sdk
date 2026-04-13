"""
mono_sdk.openai_functions - OpenAI Function Calling schemas.
"""

from .client import MonoClient


def get_mono_tools() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "mono_llm_inference",
                "description": (
                    "Call an LLM via monospay. "
                    "Cost: $0.00005-$0.0002 per call."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "prompt": {
                            "type": "string",
                            "description": "The prompt to send to the LLM",
                        },
                        "model": {
                            "type": "string",
                            "enum": [
                                "openai_gpt4o",
                                "openai_gpt4o_mini",
                                "anthropic_sonnet",
                                "anthropic_haiku",
                            ],
                            "description": (
                                "Model selection. Prices: "
                                "openai_gpt4o=$0.0002, "
                                "openai_gpt4o_mini=$0.00005, "
                                "anthropic_sonnet=$0.0002, "
                                "anthropic_haiku=$0.00005"
                            ),
                        },
                    },
                    "required": ["prompt"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "mono_blockchain_rpc",
                "description": (
                    "Execute blockchain JSON-RPC calls. "
                    "Cost: $0.000005-$0.00001 per call."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "method": {
                            "type": "string",
                            "description": "JSON-RPC method (eth_blockNumber, etc.)",
                        },
                        "params": {
                            "type": "array",
                            "items": {},
                            "description": "RPC parameters",
                        },
                        "chain": {
                            "type": "string",
                            "enum": ["rpc_eth_mainnet", "rpc_base", "rpc_solana"],
                        },
                    },
                    "required": ["method"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "mono_price_oracle",
                "description": (
                    "Get real-time crypto prices. Cost: $0.00005 per call."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "tokens": {
                            "type": "string",
                            "description": "Comma-separated token IDs (bitcoin,ethereum)",
                        },
                        "currency": {
                            "type": "string",
                            "default": "usd",
                        },
                    },
                    "required": ["tokens"],
                },
            },
        },
    ]


def handle_tool_call(tool_name: str, arguments: dict, client: MonoClient) -> str:
    if tool_name == "mono_llm_inference":
        model = arguments.get("model", "openai_gpt4o_mini")
        result = client.inference(model, {
            "messages": [{"role": "user", "content": arguments["prompt"]}],
        })
        upstream = result.get("result", {})
        choices = upstream.get("choices", [])
        if choices:
            return choices[0].get("message", {}).get("content", str(upstream))
        return str(upstream)

    if tool_name == "mono_blockchain_rpc":
        chain = arguments.get("chain", "rpc_eth_mainnet")
        result = client.inference(chain, {
            "jsonrpc": "2.0",
            "method": arguments["method"],
            "params": arguments.get("params", []),
            "id": 1,
        })
        return str(result.get("result", {}))

    if tool_name == "mono_price_oracle":
        result = client.inference("oracle_price", {
            "ids": arguments["tokens"],
            "vs_currencies": arguments.get("currency", "usd"),
        })
        return str(result.get("result", {}))

    raise ValueError(f"Unknown mono tool: {tool_name}")
