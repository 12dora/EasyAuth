# Fix2 report — EasyTrade verification findings V-01…V-07

**Verdict: all findings addressed. Gate green.**

## Findings

| ID | Severity | Result | Commit(s) |
|---|---|---|---|
| **V-01** | major | **fixed** | `eec7472b` (+ size/style follow-ups `4fb5de11` `3511e224` `a4764706`) |
| **V-02** | minor | **fixed** | `eec7472b` |
| **V-03** | minor | **fixed** | `2cfcd61e` (moved/compacted in `4fb5de11` → `test_easyauth_handover_snapshot_stale.py`) |
| **V-04** | minor | **fixed** | `2cfcd61e` |
| **V-05** | minor | **fixed** | `2cfcd61e` |
| **V-06** | minor | **fixed** | `2cfcd61e` |
| **V-07** | minor | **fixed** | `0b1b645f` (prod) + `2cfcd61e` (test) |

No findings disputed.

## What changed

### V-01 — Migration 0002 edited in place → follow-up 0003

- Kept rewritten `0002_handover_receipt_v2` (history-preserving + CHECK) for virgin installs.
- Added `0003_handover_task_id_check` which:
  - re-runs non-conforming `task_id` pre-check on receipts + watermarks
  - **idempotently** creates `ck_easyauth_handover_receipts_task_id_format` and `ck_easyauth_handover_generation_watermarks_task_id_format` (existence-guarded)
- Already-stamped old-0002 DBs converge on `alembic upgrade head` without replaying 0002 body.

### V-02 — Legacy v1 task_id abort with no cleanup path

- Kept abort (no silent whole-table DELETE).
- RuntimeError now includes sample ids + one-line cleanup SQL.
- Documented the same SQL in `docs/DEPLOYMENT.md` under「交接回执 task_id 清洗」.
- Same treatment in 0003.

### V-03 — Status-column snapshot_stale (membership unchanged)

- New test `test_snapshot_stale_on_status_column_change_membership_unchanged`:
  flips `Customer.status` ACTIVE↔INACTIVE (still in `_q_customer`), expects **412** `snapshot_stale`, **zero writes**.
- Lives in `backend/app/tests/test_easyauth_handover_snapshot_stale.py` (code-size gate).

### V-04 — Vacuous disjuncts

- Golden: `assert set(sample["summary"]) <= set(summary)` **and** `set(summary) == {s.type_key for s in HANDOVER_ASSETS}` as separate assertions.
- Items pagination: removed tautological `or set(seen) <= seeded | set(seen)`.

### V-05 — Body limit tests honest

- Forged Content-Length signed correctly → assert **exactly 413**.
- Chunked (no Content-Length) body over 256 KiB → **413**.
- Oversized with real CL still 413.

### V-06 — items 429 + multi-type hints + cache proof

- `test_items_concurrent_replay_returns_429`: slow-path monkeypatch + two threads → `{200, 429}`.
- `test_items_sequential_replay_uses_cache`: after first 200, mutate set membership; same body still 200 identical (cache); without cache would 412.
- `test_items_hints_nonempty_and_carry_business_fields`: seeds all 8 types, asserts non-empty hint + type-specific markers per §3.1.1.

### V-07 — `_parse_action` no silent skip on explicit falsy

```python
if raw is None:
    return "skip"
if not isinstance(raw, str) or raw not in VALID_ACTIONS:
    raise HandoverBusinessError(422, "invalid_action", ...)
```

- Test covers `""` default_action and empty override action → 422; owner unchanged.

## Constraint convergence proof

Throwaway container `easytrade_mig_proof` (`postgres:16-alpine` on `easytrade_internal` network). **Did not use the deployed compose DB for the experiment.**

Paths:

1. **virgin_path**: `alembic upgrade head` (0001→0002→0003)
2. **old0002_path**: `upgrade 0001` → apply **old** 0002 SQL (DELETE + columns + watermarks **without** CHECK) → `stamp 0002` → `upgrade head` (runs 0003)

`pg_constraint` dump (both paths identical):

```
easyauth_handover_generation_watermarks|ck_easyauth_handover_generation_watermarks_task_id_format|CHECK (((task_id)::text ~ '^[0-9]+:[0-9]+$'::text))
easyauth_handover_generation_watermarks|easyauth_handover_generation_watermarks_pkey|PRIMARY KEY (task_id)
easyauth_handover_receipts|ck_easyauth_handover_receipts_task_id_format|CHECK (((task_id)::text ~ '^[0-9]+:[0-9]+$'::text))
easyauth_handover_receipts|easyauth_handover_receipts_pkey|PRIMARY KEY (id)
easyauth_handover_receipts|uq_easyauth_handover_receipts_task_gen_batch|UNIQUE (task_id, generation, batch_id)
```

Result: **`CONVERGENCE_OK: pg_constraint identical and both CHECKs present`**

Container removed after proof (`docker rm -f easytrade_mig_proof`).

Note: normal backend restart during finish-check applied 0003 to the local compose DB (expected, idempotent CHECK add). That is the intended deploy-path convergence, not the scratch proof.

## Gate tally

```
BACKEND_TESTS='app/tests' make finish-check  → exit 0
```

| Step | Result |
|---|---|
| docker compose up -d --build + HTTP probe | backend/frontend ready |
| check-alembic-head | ok (head includes 0003) |
| ruff check | All checks passed |
| ruff format --check | 1228 files already formatted |
| platform_tests | **80 passed** |
| customs python style | ok |
| customs backend tests | **290 passed** |
| app/tests | **3544 passed, 5 skipped** |
| frontend tsc --noEmit | ok |
| Playwright | skipped (FRONTEND_TESTS unset) |

## Commits (not pushed)

```
a4764706 style(authz): ruff format 0002 count 查询
3511e224 style(authz): 折行 0002 清洗查询以过 ruff E501
4fb5de11 refactor(authz): 压交接迁移/用例体积以过 code-size 门禁
c9355883 style(authz): ruff format 交接迁移与 snapshot 用例
2cfcd61e test(authz): 补齐交接 v2 验证缺陷用例 V-03..V-07
0b1b645f fix(authz): 交接 action 显式非法值不得静默 skip
eec7472b fix(authz): 交接 task_id CHECK 收敛迁移 0003 与清洗文档
```

## Docs touched

- `docs/DEPLOYMENT.md` — task_id cleanup SQL + old-0002→0003 note
- `docs/CURRENT.md` — 0003 convergence + cleanup pointer

Vendored SDK: **not modified**.
