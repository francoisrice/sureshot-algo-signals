# Volatility Harvester

Sureshot Name: SiegeEngine
AlgoZoo Name: Anteater

- Long ETFs and Short their leveraged counterparts
- Harvest gains from Volatility Decay

- Paper trade to test returns

Entry: Buy and Hold - When the strategy is turned on, enter a position
Exit: Discretionary
Stop Loss: Close all positions if there is a drawdown of 5% or more below initial capital

## Implementation details

- Need to hold/pull state of positions persistently; When manually exiting, don't auto-reinvest
- 

## Hypotheses

- Strengths: Volatility over time (ex GLDM & SHNY, PLTR circa 2026, QQQ & TQQQ)
- Weakness: Strong and consistent Bullish or Bearish trends (ex. MU)

## Discovered results

Backtests (2026-08-28, $100k initial, entry on first trading day, held to end):

| Pair | Ratio | Window | Return | CAGR | Max DD | Sharpe |
|------|-------|--------|--------|------|--------|--------|
| GLDM/SHNY | 3:1 | 2026-01-01 → 2026-08-01 | +5.17% | 9.08% | 2.36% | 1.41 |
| GLDM/SHNY | 3:1 | 2026-01-01 → 2026-08-28 | +8.48% | 13.25% | 2.36% | 1.38 |
| PLTR/PLTU | 2:1 | 2026-01-01 → 2026-08-28 | +10.94% | 17.19% | 4.56% | 1.87 |
| USO/UCO | 2:1 | 2026-01-01 → 2026-08-28 | +18.48% | 29.58% | 12.44% | 1.60 |
| OILK/UCO | 2:1 | 2026-01-01 → 2026-08-28 | -5.59% (stopped out 2026-03-12) | -8.42% | 25.12% | 0.23 |

- Decay spread realized: SHNY fell 40.3% (to Aug 1) while GLDM fell 6.5% (3x would predict ~20%); PLTU fell 22.1% while PLTR rose 5.4% (2x would predict +10.7%). Profit ≈ spread × short-leg notional.
- Both legs finished profitable on the Aug 28 runs — decay kept the leveraged short down through the underlying's rally.
- Harvest is capped by the short leg's share of capital: cash-collateralized sizing puts 1/(factor+1) of capital in the short (25% at 3:1, 33% at 2:1), so return on total capital = spread × that fraction.
- PLTR/PLTU outperformed despite lower leverage: decay scales with volatility squared, and the 2:1 pair carries a larger short notional. Cost: ~2x the drawdown of the gold pair.
- Stop-loss (5% of entry capital) never triggered on the gold or PLTR pairs. It fired once, on OILK/UCO (2026-03-12, -$5,593.70) — daily checks overshot the -$5,000 line by ~12%, but cut what would have been a -$12.4k hold-to-end loss.
- USO/UCO survived oil's +88.5% rally (SPEC's stated worst case): UCO compounded to only +121.5% vs the +177% that 2x arithmetic predicts, so decay still won. Trend risk is real but chop can offset it.
- Hedge quality matters more than index-family logic: OILK rose only 45.1% while UCO rose ~107% over the same stretch (OILK's Balanced WTI index staggers contracts across the curve and lags front-month rallies), so the "1x" leg under-hedged the short and the pair ran net short into the rally. USO tracked UCO's underlying much more closely and is the better long leg.
- Metrics caveat: max drawdown / Sharpe come from an equity curve built on engine-local cash (never synced with API cash by design), which distorts levels for two-leg positions — trust Final Value / Total Return; treat DD and Sharpe as indicative only.