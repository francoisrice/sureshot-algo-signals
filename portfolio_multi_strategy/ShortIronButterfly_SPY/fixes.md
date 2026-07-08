# ShortIronButterfly_SPY Strategy Fixes

- Black-Scholes and options pricing logic should be handled externally to main.py . This should come from a library in SureshotSDK (i.e. options). Then use that library to get the option contract price, either the Live price from data-fetcher or the calculated Black-Scholes price.
- 