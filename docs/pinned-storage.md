# Compressed journals for pinned paper studies

`scripts/pinned_storage_launcher.py` lets an existing paper study read compressed
journals while keeping its original strategy and replay code. It runs the original
checkout's `btc5m lab run` entry point using that checkout's Python environment.
It does not import the current trading package, change a study manifest, override
`implementation_id()`, compact files, or start funded trading.

This is a storage compatibility layer. Existing execution limitations and data
quality flags remain part of the original study. Using the adapter does not make
old results equivalent to results produced by a corrected replay engine.

## Launch contract

Use the pinned checkout's `.venv/bin/python` with `-I`. Python's isolated mode
ignores the current directory and `PYTHONPATH` when finding packages. Supply the
full Git commit and the independently recorded SHA-256 of the approved standalone
`storage.py`. SHA-256 is a fingerprint of the file's exact bytes; an unexpected
change causes startup to fail before that module is executed.

```sh
"$PINNED_CHECKOUT/.venv/bin/python" -I \
  "$ADAPTER_CHECKOUT/scripts/pinned_storage_launcher.py" \
  --checkout "$PINNED_CHECKOUT" \
  --commit "$PINNED_FULL_COMMIT" \
  --storage-module "$ADAPTER_CHECKOUT/src/btc5m/storage.py" \
  --storage-sha256 "$APPROVED_STORAGE_SHA256" \
  --runtime "$EXISTING_STUDY_ROOT" \
  --source "$EXISTING_CAPTURE_SQLITE" \
  --config "$EXISTING_PAPER_TOML" \
  --verify-only
```

`--verify-only` checks identities without running the worker or writing adapter
provenance. For the actual worker command, replace `--verify-only` with
`--continuous`. Without either option it processes the available tape once.
The launcher accepts an explicit TOML configuration file and checks its policy
fingerprint against the existing manifest. It never loads a repository `.env`.

The verification checks:

- The expected Git commit, package source bytes, `pyproject.toml`, and `uv.lock`.
  Modified or extra package source files and source symlinks are rejected.
- The original `SEMANTIC_FILES` definition and the original implementation hash,
  both before package import and through the pinned implementation itself.
- The Python environment and the imported `btc5m` package paths.
- The existing study's implementation, configuration, source path, and tape identity.
- The explicit decoder fingerprint, before executing its verified bytes.

Installed dependency names and versions are recorded. This is not a security
sandbox or a byte-level integrity check of every installed dependency. The
approved checkout and its environment must remain unchanged while the worker runs.

## Connection handling and recorded provenance

The old replay workers replace their original `Ledger` connection with a SQLite
connection using `NestedConnection`, a class that keeps nested transactions
atomic. The launcher wraps `sqlite3.connect` so every connection registers the
compressed-event reader. All connection arguments, including that custom class,
are passed through unchanged. The wrapper is removed when the worker returns.

The existing `study.json`, implementation hash, variants, and account history
remain unchanged. Separate records describe the storage adapter:

- `storage-adapters/<fingerprint>.json` records the launcher and decoder paths and
  byte fingerprints, original checkout and source fingerprints, study identity,
  configuration, interpreter, installed dependency versions, and initial cursor.
  A cursor is the last source event the study processed. The record is written and
  synchronized to disk before being installed atomically; existing records must
  match exactly.
- `storage-adapter-runs.jsonl` records each launch, its adapter fingerprint, start
  and final cursors, and success or failure. Each record is synchronized to disk.
  A process killed without cleanup can leave an unmatched start record; it must
  not be interpreted as a successful finish.
- `storage-adapter.lock` prevents two launcher processes for the same study. The
  pinned study's existing writer locks still apply as well.

The launcher records a nonzero return from the old CLI as a failed run. Decoder
corruption remains a visible failure; it is never converted into missing events
or a successful replay.

Journal conversion and periodic compression belong to the separate storage
maintenance mechanism described in [storage.md](storage.md). Stop a writer before
replacing its database file, retain a verified source during conversion, and
resume through a decoder-aware reader. Unmodified external SQLite programs need
`register_event_reader(connection)` to query compressed `events.data`.

## Verification on the actual older workers

On 2026-09-08 the same synthetic, frozen two-market source was replayed through
both actual pinned checkouts, using each checkout's own Python environment:

| Checkout | Git commit | Original implementation | Fills after continuation |
| --- | --- | --- | ---: |
| `experiment-lab` | `edbd829ae3b4cc10f91daa555c2fd3fdec72ba58` | `58903589303f3dbc9e65a1471c47b53e673c680721943bb6f52dc8cc3047d6ef` | 2 |
| `order-flow` | `de70bf6734b05991b9e10df98bc0a8cb4b4f1b9f` | `7033a2d3aeb8c246289fd30607b207b3c6b03e72a47a83be082b1eb4a3df66b9` | 4 |

Each test started from a durable checkpoint containing one acknowledged but
unfilled order. Identical copies continued through the original uncompressed CLI
and through the launcher with compressed journals. They produced identical fill
sides, quantities, prices, fees and timestamps; order states; account cash and P&L;
position quantities and costs; round flags; replay cursors; and portfolio results.
Random identifiers for newly created orders were excluded from comparison.
A subsequent complete entry and stop exit occurred in both older implementations.

The oldest worker cancels an order pending across process restart with
`PAPER_EXECUTION_GAP`; the later worker fills it. Both baseline and adapter runs
preserved their respective behavior. This explains the different fill counts and
is not a storage effect. Restarting the completed compressed study added no fills
or financial changes and preserved the original manifest. Corrupting a compressed
chunk caused both pinned workers to fail with exit code 2.

Focused regression tests also cover custom connection classes, nested rollback,
read-only reconnection, exact event decoding, subsequent event IDs, repeated
provenance registration with installed dependencies, source/config/tape identity
rejection, decoder fingerprint rejection, and visible corruption. The 25 launcher
and storage tests passed together. Scratch actual-checkout comparisons are local
verification artifacts, not an additional runtime dependency or a profit test.

## Corrected studies must have separate identities

Continuing an old study through this adapter preserves its old replay behavior,
including known execution limitations. New corrected experiments should use a
new dated study root, a frozen comparison shortlist, and the corrected engine's
own implementation hash. Their cash, samples, and result labels must remain
separate from the old cohort, while old results stay available for inspection.

The dashboard currently has fixed roots for the directional and order-flow labs.
Displaying historical and corrected cohorts together needs an explicit mapping
of study roots and implementation labels. Repointing a root and presenting the
new cohort as uninterrupted old results would be misleading. The original six
paper portfolios and their history can remain in their existing root.

If an old cohort is closed with its existing stop request, that closure may force
exits. Record the cutoff and closure reason; do not describe those exits as the
strategy's ordinary trading decisions. The launcher itself neither closes old
cohorts nor creates new ones.
