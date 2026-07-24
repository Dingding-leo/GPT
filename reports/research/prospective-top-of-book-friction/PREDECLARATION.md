# Prospective Top-of-Book Friction Predeclaration

## Hypothesis

A bounded prospective public-OKX quote collection can obtain twelve valid top-of-book observations for each of BTC-USDT and ETH-USDT, with zero unrecovered collection failures, while both markets satisfy all of the following preliminary paper-execution evidence thresholds:

- 95th-percentile one-way half-spread no greater than 2.5 bps;
- 95th-percentile books-request round trip no greater than 1.0 second;
- 95th-percentile server-time request round trip no greater than 1.0 second;
- every exchange-measured quote age no greater than 1,000 milliseconds;
- every absolute midpoint clock skew no greater than 5.0 seconds.

The economic rationale is that the canonical 5 bps one-way exchange fee leaves only 2.5 bps before the first 7.5 bps aggregate cost sensitivity. Half-spread is measured separately from the exchange fee and from still-unmeasured slippage, market impact and decision-to-order latency.

## Fixed design

- Provider: unauthenticated public OKX REST endpoints only.
- Instruments: BTC-USDT and ETH-USDT spot.
- Observations: 12 per instrument.
- Interval: 2 seconds between successful observations.
- Maximum attempts: 2 per scheduled observation.
- Books endpoint: `GET /api/v5/market/books?sz=1`.
- Exchange-time endpoint: `GET /api/v5/public/time`.
- Instrument endpoint: `GET /api/v5/public/instruments?instType=SPOT&instId=<instrument>`.
- Quote-age rejection bound: 1,000 milliseconds.
- Individual request hard bounds: 2 seconds.
- Absolute midpoint-clock-skew hard bound: 5 seconds.
- Candidate count: one joint BTC/ETH evidence candidate.

No account, credential, balance, position, order, leverage or fund endpoint is accessed. The experiment measures public quote spread and transport timing only. It does not estimate fills, slippage, impact, partial fills, rejected orders, strategy alpha or live eligibility.

## Canonical signature

`prospective-top-of-book-friction-v1|provider=OKX-public|markets=BTC-USDT,ETH-USDT|samples=12-per-market|interval=2s|max-attempts=2|metric=half-spread-bps,books-rtt,server-rtt,exchange-quote-age,midpoint-clock-skew|pass=p95-half-spread<=2.5bps,p95-books-rtt<=1s,p95-server-rtt<=1s,max-quote-age<=1000ms,max-abs-skew<=5s,zero-unrecovered-failures-in-both-markets|candidate-count=1`
