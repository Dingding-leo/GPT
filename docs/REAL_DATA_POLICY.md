# Real-data-only execution policy

Executable research commands, CI research jobs, and persisted research artifacts must use external real-market data.

## Allowed

- public OKX market data downloaded by `run_okx_research.py`;
- explicit external timestamp/close CSV input supplied to `run_research.py`;
- immutable regression extracts of real exchange observations, provided their metadata records the provider, instrument, timeframe, timestamp boundary, source artifact or retrieval details, and SHA-256 provenance;
- mocked protocol rows used only to test parser and failure handling, where no performance result is produced.

## Not allowed

- generated price series as a fallback for a research command;
- synthetic smoke-test reports or artifacts;
- classifying, ranking, or presenting a strategy using generated market prices;
- silently substituting generated data when a provider or file is unavailable.

`run_research.py` therefore requires `--csv`, and the hourly workflow fails rather than replacing unavailable OKX data with generated observations.

Unit tests use a committed, hash-verified extract of completed OKX BTC-USDT daily closes. The live BTC-USDT and ETH-USDT research job remains separate so a provider outage cannot be mistaken for a deterministic unit-test failure, while an unavailable provider still blocks fresh research artifacts.
