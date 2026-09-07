# A bounded native experiment

From the repaired checkout, use Python3.12 and `uv sync --locked`.
The commands below assume already provisioned credentials; they do not perform account setup.

1. Inspect anonymous feed availability, then collect35 minutes so the30-minute history can warm up:

   ```bash
   uv run --locked btc5m doctor --duration 15
   uv run --locked btc5m observe --duration 2100 --runtime work/observe-35m/ledger.sqlite
   uv run --locked btc5m report --runtime work/observe-35m/ledger.sqlite
   ```

2. Copy `config/btc5m.toml` to `work/experiment.toml` and set only
   `risk.max_entries_per_day = 1`. Keep the USD5 spending target and USD10 loss allowances.
   Use a dedicated existing account with pUSD and the permissions described in the
   [operator guide](../README.md). Keep its existing CLOB credentials in a private file outside Git.

3. With explicit operator consent for funded trading, diagnose and run for40 minutes:

   ```bash
   uv run --locked btc5m doctor --account --env-file /absolute/private/btc5m.env
   uv run --locked btc5m run --execute --duration 2400 --shutdown-seconds 60 --config work/experiment.toml --env-file /absolute/private/btc5m.env
   ```

   A qualifying entry is not guaranteed after warm-up. Record raw eligibility, confirmation,
   actual order identity, final receipt, actual fee, balance changes and unresolved exposure.
   The cap persists per UTC day across restarts.

4. In a second terminal use the exact absolute journal path printed by the run:

   ```bash
   uv run --locked btc5m stop --runtime /absolute/common-root/.runtime/0xYOUR_WALLET/ledger.sqlite
   uv run --locked btc5m status --runtime /absolute/common-root/.runtime/0xYOUR_WALLET/ledger.sqlite
   uv run --locked btc5m report --records --runtime /absolute/common-root/.runtime/0xYOUR_WALLET/ledger.sqlite > work/experiment-report.json
   ```

   Stop and SIGTERM request a protected close. Exit2 requires inspection; it does not mean
   the wallet was liquidated. After the owner exits, `reconcile --env-file /absolute/private/btc5m.env`
   can apply venue-read-only evidence to the local journal without clearing stop or budgets.

Claimable winning tokens are noncash holdings. Use the official manual route for the same wallet,
retain the journal, and investigate post-claim balance differences; this version does not redeem
or automatically import claim receipts. See [manual claims and limitations](../README.md#stop-inspect-and-recover).
No funded action in this example was executed as development verification.
