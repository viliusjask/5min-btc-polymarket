# Dependency advisory check

2026-09-06. Queried the OSV package/version API for all **44 public registry packages in
uv.lock**, including development dependencies, plus the pinned **hatchling 1.27.0** build
backend. No account information was sent. The check does not inspect arbitrary package
behavior, prove absence of malware, or cover unspecified isolated-build transitive versions.
See the [OSV batch API contract](https://google.github.io/osv.dev/post-v1-querybatch/).

The initial lock produced one affected package: **pytest 8.4.2**, the development test runner.
GHSA-6w46-j5rx-g56g and PYSEC-2026-1845 are aliases of **CVE-2025-71176**, concerning local
temporary-directory handling on UNIX. This is distinct from the bot's trading process. The
official pytest 9.0.3 release identifies the fix; the development pin was updated to that
version and the lock regenerated. Runtime versions were unchanged.
[Official release and fix](https://github.com/pytest-dev/pytest/releases/tag/9.0.3),
[OSV advisory and affected range](https://osv.dev/vulnerability/GHSA-6w46-j5rx-g56g).

The second complete 45-query batch returned **no advisory matches and no pagination tokens**.
This states what the database returned at the query time, not that every dependency is safe.
The exact UTC timestamps, package list and unmodified API responses remain in the ignored
`work/dependency-osv-check.json` and `work/dependency-osv-check-after.json` files. The scratch
`work/dependency-osv-check.py` repeats the lookup from the current lock and build requirement.

| Evidence | SHA-256 of uv.lock |
|---|---|
| Before pytest update | 8bb18707e69c1fb6fa3730a7726655f13b7ced61836a4a0a4d33e15a341801af |
| After pytest update | c78dd3a9894e6eba7a996079dbe624e00404651c00c06711338e72ac81af2666 |

`uv sync --locked` and `uv lock --check` passed after the change. The full suite under the patched test runner passed: **301 tests in 15.54 seconds**.
The exact console output is retained in `work/pytest-security-upgrade-tests.txt`.
