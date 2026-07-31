# Daily 2160H margin-acceleration confirmation rejected

The sole preregistered candidate required the positive daily 2,160H endpoint-trend margin to also exceed its own 24-hour-lagged value. Each market was evaluated independently on public confirmed OKX SPOT 1H data, with next-open execution and exactly 5 bps one way.

| Market | Candidate net | B1 net | Candidate Sharpe | B1 Sharpe | Candidate DD | B1 DD | Turnover | B1 turnover | Edge/turn | B1 edge/turn | Folds | Years | Residual Sharpe |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC-USDT | 70.97% | 123.62% | 0.882 | 0.972 | -28.51% | -25.87% | 328 | 45 | 21.64 bps | 274.71 bps | 4/12 | 1/4 | -0.496 |
| ETH-USDT | 95.96% | 86.91% | 0.921 | 0.698 | -23.06% | -47.25% | 272 | 31 | 35.28 bps | 280.36 bps | 6/12 | 2/4 | -0.120 |

## Failure mechanism

BTC removed 7,392 B1 long hours, lost 52.65 percentage points of compounded OOS return, worsened drawdown, and increased turnover from 45 to 328. ETH improved aggregate return, Sharpe, and drawdown, but increased turnover from 31 to 272 and collapsed edge per turnover. The 24-hour slope condition repeatedly switched exposure inside otherwise persistent positive 2,160H regimes.

BTC achieved only 4/12 profitable folds and 1/4 profitable years; ETH achieved 6/12 and 2/4. Residual Sharpe was negative in both markets. Every paired dependence-aware lower bound was negative, and the common-index median lower bounds were negative for both annualised mean and Sharpe deltas.

```text
verdict = reject_daily_margin_acceleration_confirmation_family
result  = df73a87ea587212a30e31234df0d264ac95d5a5bfb08f951455a96958fa0819b
artifact = 8780233710
artifact_sha256 = 5f36d6756a287932302b2ee385621937ffb5f78251a629781467a16a341c2a02
```

No correction is training-authorised. The candidate is terminally rejected and may not be rescued by changing the slope horizon, threshold, cadence, timing, sizing, fee, or sample. No paper- or live-trading authorization results.
