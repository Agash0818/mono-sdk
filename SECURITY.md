# Security

monospay uses cryptographic signatures for all money movement.
This document is for developers integrating at the protocol level.

For most use cases, use `client.signed_transfer()` — the SDK handles signing automatically.

## Signing Protocol

All transfers require an EIP-191 (personal_sign) ECDSA signature.

### Message Format

```
mono-transfer:{sender}:{receiver}:{amount}:{nonce}:{timestamp}
```

| Field | Format |
|---|---|
| sender | Lowercase 0x address |
| receiver | Lowercase 0x address |
| amount | 6 decimal fixed point (e.g. `1.500000`) |
| nonce | UUID v4 (single use) |
| timestamp | Epoch milliseconds (±5 min window) |

### Example

```python
from eth_account import Account
from eth_account.messages import encode_defunct
import uuid, time

sender = "0xabc..."
receiver = "0xdef..."
amount = "1.500000"
nonce = str(uuid.uuid4())
ts = int(time.time() * 1000)

canonical = f"mono-transfer:{sender}:{receiver}:{amount}:{nonce}:{ts}"

msg = encode_defunct(text=canonical)
signed = Account.sign_message(msg, private_key="0x...")
signature = f"0x{signed.signature.hex()}"
```

### Protections

- **Replay prevention**: Each nonce can only be used once (stored server-side)
- **Timestamp window**: Signatures expire after ±5 minutes
- **Rate limiting**: Max 30 transfers per 60 seconds per wallet
- **Spending limits**: Server-side enforcement, not bypassable by the agent

## Reporting Vulnerabilities

Email security@monospay.com with details. Do not open public issues for security vulnerabilities.
