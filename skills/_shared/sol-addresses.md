# sol-addresses.md

Canonical address constants. Imported wherever a SOL or wSOL address is needed; never inlined.

## Solana

| Use | Address |
|---|---|
| Native SOL (`onchainos swap --from`/`--to`) | `11111111111111111111111111111111` |
| Wrapped SOL (wSOL) (`onchainos market price`/`kline`/`price-info`/`ws price`) | `So11111111111111111111111111111111111111112` |

## EVM (X Layer and reference)

| Use | Address |
|---|---|
| Native (any EVM swap) | `0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee` |

EVM contract addresses MUST be all lowercase per the OKX reference repo.

## Rule

- Swaps: use native.
- Market data (price, kline, price-info, WebSocket subscriptions): use wrapped.

Both addresses are exported by `skills/_shared/state-schema.md` as enum constants for any Python
script that imports them; the script wrappers read them via simple string literals in code
referencing this file.
