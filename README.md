# Contract Message Router

A Telegram message pipeline for extracting contract addresses, applying routing rules and retaining local history.

![review](https://img.shields.io/badge/review-private-374151) ![primary](https://img.shields.io/badge/primary-Python-2563EB) [![LinkedIn](https://img.shields.io/badge/LinkedIn-Douglas%20Silva-0A66C2?logo=linkedin&logoColor=white)](https://www.linkedin.com/in/douglas-silva-data-analyst/)

[Overview](#overview) · [Architecture](#architecture) · [Setup](#setup) · [Validation](#validation) · [Roadmap](#roadmap) · [Review notes](docs/REVIEW.md)

## Overview

- Configuration and extraction modules validate the routing inputs.
- History prevents duplicate message processing.
- Notification and optional wallet-guard modules are separate components.

**Technology:** Python · Telethon · SQLite · httpx · typed configuration · pytest

**Persistence and data:** SQLite stores history and wallet-guard-related operational state. Real sessions and wallet material are excluded.

## Architecture

```text
Configured message source → address extractor and routing policy → history/deduplication → configured destination
```

| Location | Review focus |
| --- | --- |
| [`src/token_forwarder`](src/token_forwarder) | Source/configuration inspected for scope and structure |
| [`src/wallet_guard`](src/wallet_guard) | Source/configuration inspected for scope and structure |
| [`tests/test_routing.py`](tests/test_routing.py) | Source/configuration inspected for scope and structure |
| [`tests/test_wallet_guard_broadcast.py`](tests/test_wallet_guard_broadcast.py) | Source/configuration inspected for scope and structure |
| [`pyproject.toml`](pyproject.toml) | Source/configuration inspected for scope and structure |

Internal package and module names are retained where changing them would affect imports or compatibility. This descriptive repository name does not imply a completed package/API migration.

## Setup

Read pyproject.toml and the src/ entrypoints. Use local example configuration; never copy a real .session file or private key into a review fixture.

Start from an isolated environment. Use `.env.example` when present and inspect the configuration loader: an example file is not necessarily loaded automatically. Runtime databases, real account sessions and private credentials are not bundled. Live integration prerequisites are separate from local tests.

## Validation

Static parsing checked 43 Python files and 0 strict JSON files. Python syntax errors: 0; JSON errors: 0. No functional test/build result is claimed for this preparation.

Available test scripts are inventoried in [the review notes](docs/REVIEW.md). Choose offline checks before operating any integration.

These results apply to the selected checks on the preparation copy. They do not establish deployment readiness, full coverage, live provider availability or measured performance. CI definitions, when present under `docs/ci-templates/`, are inactive review templates; no remote CI badge is claimed.

## Limits and current status

The selected folder also includes wallet-guard signing/execution code. The complete repository must not be described as universally read-only. No Telegram session, message send or wallet action was executed.

This private snapshot is for code and portfolio review. Generated runtime material and unreviewed binary assets may be excluded. [Review notes](docs/REVIEW.md) record preparation scope, findings and outstanding validation.

## Roadmap

- [ ] Split messaging from transaction-capable wallet-guard components.
- [ ] Run extractor/routing tests with isolated fixture configuration.
- [ ] Replace personal chat defaults with explicit example configuration.

## History and attribution

No recoverable original Git history was verified for this snapshot. Import and preparation commits use their actual current dates; filesystem timestamps are not treated as development dates.

No open-source license is granted by this preparation. A license and attribution review is required before public redistribution.

## Maintainer and feedback

Douglas de Oliveira Silva · [GitHub](https://github.com/qquante) · [LinkedIn](https://www.linkedin.com/in/douglas-silva-data-analyst/)

For this private review, report reproducible issues with a minimal fixture and the exact check output. Keep account data, credentials and generated sensitive reports out of issues and commits. Existing contribution guidelines apply where present.

**Topics:** `python`, `telegram`, `telethon`, `sqlite`, `automation`, `message-routing`
