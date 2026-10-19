# Contract Message Router

A Telegram message pipeline for extracting contract addresses, applying routing rules and retaining local history.

## Features

- Configuration and extraction modules validate the routing inputs.
- History prevents duplicate message processing.
- Notification and optional wallet-guard modules are separate components.

## Stack

Python · Telethon · SQLite · httpx · typed configuration · pytest

SQLite stores history and wallet-guard-related operational state. Real sessions and wallet material are excluded.

## Getting started

Read pyproject.toml and the src/ entrypoints. Use local example configuration; never copy a real .session file or private key into a review fixture.

## How it works

```text
Configured message source → address extractor and routing policy → history/deduplication → configured destination
```

## Current limitations

The selected folder also includes wallet-guard signing/execution code. The complete repository must not be described as universally read-only. No Telegram session, message send or wallet action was executed.

## License

No open-source license has been granted. Redistribution terms remain to be defined.
