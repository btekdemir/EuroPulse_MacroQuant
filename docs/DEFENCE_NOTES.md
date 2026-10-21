# Defence notes: two sentences per method

Short answers for the interview. Every number here is on the dashboard; the full reasoning is in `DECISIONS.md` (the D-codes).

## The three questions most likely to come

**"Isn't four rounds on the same history a garden of forking paths?"**
Each round's rule was fixed and committed before it ran, and the ledger records every change (Dec 3.82% → 3.77% when round 4 was adopted). The model is now frozen: no round 5. From here on, the ledger's scores are the clean out-of-sample test.

**"Your December forecast equals the last print. Is the model just a random walk?"**
No. The 0.00 pp is two drivers cancelling: the base effect is −0.11 pp and momentum is +0.12 pp. Core is "no change in y/y" because that is what beat the benchmark; the gain comes from fuels (pump prices), food and the exact base-effect arithmetic.

**"Why did round 4 pass so narrowly?"**
p = 0.016 against a Holm threshold of 0.0167, so it is a pass, but a narrow one. Unlike round 2's candidates, which only gained after 2020, B1's gain is the same before and after 2020 (ratio about 0.79 in both), which makes it less likely to be a crisis accident. The idea came from an earlier finding on the same data (D44), so the page itself says the evidence is weaker than the p-value alone.

## Methods, two sentences each

- **RMSE ratio vs random walk (0.79 at 3 months):** our root-mean-squared error divided by that of "y/y stays where it is". Below 1 means we beat the benchmark that most inflation models fail to beat at short horizons.
- **Diebold–Mariano test:** tests whether the difference in squared errors between two forecasts is zero on average. Two-sided, on all origins since 2010.
- **Newey–West (h−1 lags):** three-month forecasts made a month apart overlap, so their errors are autocorrelated. Newey–West widens the variance to account for that.
- **HLN correction:** Harvey–Leybourne–Newbold adjusts the DM statistic for small samples and uses a t distribution. Without it the test rejects too often.
- **Holm correction:** when you run several tests, one passes by luck more often than 5%. Holm sorts the p-values and compares the smallest with 5%/k, the next with 5%/(k−1), and so on, which keeps the family-wide false-pass rate at 5%.
- **Pre-registration:** the candidates, the test and the pass rule were written and committed (git) before the results existed. That separates "we tested this" from "we kept what worked".
- **Bottom-up chain-link (Laspeyres):** six components forecast separately, then aggregated with the weights known at the forecast date, linked each December as Eurostat does. Contributions are exact, which is why we rebuild Eurostat's headline within 0.030 pp and its contributions within 0.009 pp.
- **Base effect:** the part of the y/y change that comes from last year's monthly moves dropping out of the 12-month window. It is known in advance, with no forecast involved.
- **Fan chart and calibration:** the bands come from the model's own past out-of-sample errors at each horizon. We check calibration by counting how often outcomes fell inside: in 2020–2023 the 68% band held too few, and the page says so.
- **Quantile (pinball) loss:** a score for a band rather than a point. It penalises outcomes outside each quantile in proportion to how far out they land. We used it to compare a fixed-width fan with a crisis-aware one (D28); the crisis-aware fan did not pass.
- **Chow test:** tests whether a regression's coefficients change at a known date (here January 2020). Energy-to-core pass-through rose by about 0.08 after it (p = 0.003).
- **QLR / sup-Wald (Andrews 1993):** the same test, run at every possible break date in the middle 70% of the sample, then taking the largest statistic. Andrews' critical values allow for having searched; 17.9 vs 8.68 says the pass-through is unstable.
- **Elasticity 0.31 (HAC s.e.):** the estimated pass-through used by the shock simulator, with standard errors robust to autocorrelation and heteroskedasticity. The simulator's assumptions (A1–A5) are always shown next to its results.
- **First-release check (D29):** scoring against the first published numbers instead of today's revised ones changes the ratios very little. The inputs are still today's vintage, so it is not a full real-time exercise, and the title says so.
- **Hash-chained ledger:** each recorded forecast stores the hash of the one before it. Editing, deleting or reordering any past entry breaks the chain, so the track record cannot be quietly rewritten.
- **The LLM:** it only fills a fixed scenario schema or answers from a fact sheet. Every number it writes is checked against that sheet before it is shown, and the simulator does the arithmetic.

## If asked what you would do next

Stop modelling and let the ledger score the forecasts as the prints arrive. Then add true real-time vintages (ECB SDW), so the backtest uses the data as it was known at each date.
