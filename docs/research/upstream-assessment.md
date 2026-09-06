# What was real in the published repository

Reviewed upstream commit `1c9aa81ec64cdf62895b155ed64dc8e88c013102`, containing 15 tracked files.
The idea is a plausible trading experiment, but the published repository is an incomplete and
fragile wrapper around another trading project. Its code does not substantiate the promotional
returns or implement the full strategy described in the screenshots. The evidence does not
establish the author's motives, and GitHub popularity is not a trading record.

No obvious credential-exfiltration or wallet-draining destination was identified in the inspected
tracked source. That does not make running it with a funded wallet appropriate: missing components,
implicit execution, weak order accounting and broad environment access are concrete software risks.
The repaired branch's separate [dependency advisory check](../reviews/dependency-audit.md) covers
known package advisories, not a guarantee about all code or dependencies.

## Source findings

| Finding | What the source actually does | Consequence |
|---|---|---|
| Missing trading engine | The session script invokes a relative `src/live/pm_live_trade_runner.py`, which is absent from the tracked tree. [Invocation](https://github.com/Novals83/5min-btc-polymarket/blob/1c9aa81ec64cdf62895b155ed64dc8e88c013102/scripts/test_btc_5m_session_exit_sl.py#L225) | Cloning this repository is insufficient to place the intended orders. |
| The implemented entry differs from the narrative | The default threshold is 70c; candidates are the sides whose ask exceeds that threshold, with the higher ask selected. A minimum remaining-time check exists, but this path does not enforce a USD 70–100 BTC lead or entry near two minutes remaining. [Selection](https://github.com/Novals83/5min-btc-polymarket/blob/1c9aa81ec64cdf62895b155ed64dc8e88c013102/scripts/test_btc_5m_session_exit_sl.py#L424) | A claim about the screenshot strategy cannot be assigned to this implementation without the missing modifications. |
| Rich configuration is not the actual control surface | The YAML advertises hedge and risk settings, while the script defines its own profile dictionary and never loads that YAML. [Profiles](https://github.com/Novals83/5min-btc-polymarket/blob/1c9aa81ec64cdf62895b155ed64dc8e88c013102/scripts/test_btc_5m_session_exit_sl.py#L284), [advertised configuration](https://github.com/Novals83/5min-btc-polymarket/blob/1c9aa81ec64cdf62895b155ed64dc8e88c013102/config/btc_5m_profiles.yaml) | A setting's presence in documentation does not establish that the bot enforces it. |
| Stops already exist, but need execution repair | The monitor checks a percentage drop from entry and a pre-expiry time exit. The stop quote comes from its market-price helper, while later sales are delegated to the missing runner. [Monitor](https://github.com/Novals83/5min-btc-polymarket/blob/1c9aa81ec64cdf62895b155ed64dc8e88c013102/scripts/test_btc_5m_session_exit_sl.py#L485) | The correct assessment is of the actual exit policy and filled losses, not an assumption that every loser is held to zero. A trigger alone does not prove a fill. |
| An accepted/matched response substitutes for final accounting | Entry quantities come from the immediate response. The close loop can stop on a matched response, and the report can mark success merely because some proceeds are present. [Entry](https://github.com/Novals83/5min-btc-polymarket/blob/1c9aa81ec64cdf62895b155ed64dc8e88c013102/scripts/test_btc_5m_session_exit_sl.py#L452), [close report](https://github.com/Novals83/5min-btc-polymarket/blob/1c9aa81ec64cdf62895b155ed64dc8e88c013102/scripts/test_btc_5m_session_exit_sl.py#L640) | Partial fills, remaining shares, actual fees and ambiguous submissions can be misrepresented. |
| Aggressive fallback weakens exit-price protection | After unsuccessful immediate fills, the script can place resting orders and eventually use a 1c fallback when the bid read fails. [Fallback](https://github.com/Novals83/5min-btc-polymarket/blob/1c9aa81ec64cdf62895b155ed64dc8e88c013102/scripts/test_btc_5m_session_exit_sl.py#L585) | Missing market information can produce an extremely permissive sale price. |
| Shell start implicitly authorizes execution | The control wrapper inserts the execution flag and sources a separate project's environment file. Its stop command kills the process, escalating to SIGKILL. [Start](https://github.com/Novals83/5min-btc-polymarket/blob/1c9aa81ec64cdf62895b155ed64dc8e88c013102/scripts/btc5m_ctl.sh#L77), [stop](https://github.com/Novals83/5min-btc-polymarket/blob/1c9aa81ec64cdf62895b155ed64dc8e88c013102/scripts/btc5m_ctl.sh#L136) | Starting can trade unexpectedly; stopping the process does not liquidate its holdings. |
| Container access is broad and deployment incomplete | The compose file mounts a parent workspace by default, loads an external environment file and starts a sleeping Python image. [Compose](https://github.com/Novals83/5min-btc-polymarket/blob/1c9aa81ec64cdf62895b155ed64dc8e88c013102/docker-compose.yml) | It is not an isolated, self-contained deployment of the advertised strategy. |

The original imports the older `py_clob_client`. Public issue reports also describe the missing
runner and order-version/authentication trouble, but those reports alone are not reproduced
root-cause diagnoses. See the dated [trader evidence register](trader-sentiment.md).

## Why repairing it is reasonable

Buying a likely winner can have value if the executable price is favorable after costs. Stops
change the policy's winning and losing trade sizes. Neither a high price nor a stop proves an
advantage; neither establishes that the approach is useless. A small funded experiment can test
real execution without building a separate paper-trading platform.

The repair therefore makes the project self-contained, models the actual settlement reference,
replaces the fixed-dollar signal with a volatility/time-sensitive value candidate, retains a
modified momentum comparison, and makes order/fee/inventory state durable. The independently
reviewed design and implementation status are in [design](../design.md) and [progress](../progress.md).
The screenshot's claimed USD 250 to USD 13,000 result remains unverified; this work does not
promise to reproduce it.

Alpha-Sentry currently centers on equity research over a much longer horizon. Its research workflow
does not supply this venue's order execution, custody or settlement machinery. Keep the bot standalone
until both execution evidence and strategy results justify integration. Scientific and trader
evidence, selected changes and deferred alternatives are in [strategy decisions](strategy-decisions.md).
