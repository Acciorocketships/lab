# Real memory compactor test artifacts

When you run `test_real_memory_compactor_shrinks_mythos_tier_a` with `LAB_RUN_REAL_MEMORY_COMPACTOR=1`, the test writes a timestamped directory under:

**`tests/artifacts/real_memory_compactor/<UTC>/`**

That folder is gitignored. Typical contents:

- `tier_a_before_fixture/` — copy of `tests/fixtures/mythosunwritten_tier_a/` (input snapshot)
- `tier_a_after/` — `.lab/state/*.md` after the real compactor run
- `worker_result.json` — full dict returned by `run_worker` (may be large)
- `stdout.txt` / `stderr.txt` — CLI streams
- `compactor_packet.md` / `worker_output.json` — episode artifacts when present
- `tier_a_sizes.json` — character counts before vs after
- `memory_compactor_system_prompt.txt` — prompt version used for the run
- `retention_checks.txt` — quick substring checks for high-signal fixture strings in `tier_a_after`

See `tests/test_pre_orchestrator_mythos_fixtures.py` for env vars (`LAB_REAL_WORKER_BACKEND`, `LAB_REAL_CURSOR_MODEL`, timeouts).
