# Verification findings — EasyTrade (verdict: fail)

## V-01 [major/confirmed] Migration 0002 was edited in place: already-migrated databases stay at alembic head with neither CHECK constraint and never run the history-preserving path

File: /Users/konata/code/EasyTrade/backend/alembic/versions/0002_handover_receipt_v2_key.py

0f07fae4 rewrote the body of revision `0002_handover_receipt_v2` while keeping the same revision id. Any database that already applied the pre-fix 0002 (which started with `DELETE FROM easyauth_handover_receipts`) will never execute the rewritten version: alembic considers it up to date, so the two new `ck_..._task_id_format` CHECK constraints that 03 §3.8 mandates are silently absent and the destructive DELETE it already performed is not undone. This is not hypothetical — I inspected the running deployed instance's database (`docker compose exec postgres psql -U easytrade -d easytrade`): `python -m app.runtime_migration_guard` reports the DB at head, yet `pg_constraint` for `easyauth_handover_receipts` / `easyauth_handover_generation_watermarks` contains only the PK and `uq_easyauth_handover_receipts_task_gen_batch` — no CHECK constraints at all. The new migration only works on virgin databases (verified: the ephemeral `easytrade_gate_*_test` DBs created by scripts/run-backend-tests.sh do get them, which is why every test is green and the drift is invisible to the gate). Nothing in the deploy flow (migrate_with_lock / runtime_migration_guard) can detect a model-vs-DB constraint divergence, and the fix report marks et-execute-locks-migration-04/06 as `fixed@0f07fae4` without noting that already-migrated environments — including the one the pending §14 联调 / E2E checkpoints will run against — are unaffected by the fix.

Suggested fix: Add a follow-up revision `0003` that (a) re-runs the non-conforming `task_id` pre-check and (b) creates the two CHECK constraints with `IF NOT EXISTS`-style guards / try-drop-then-create, so databases already at 0002 converge. Alternatively, if the team's policy is to rebuild the pre-production database, say so explicitly in the commit/report and actually rebuild the deployed instance's DB before the §14 checkpoint — do not leave 'fixed' claimed while the live schema lacks the constraint.

## V-02 [minor/plausible] Migration abort predicate rejects the v1 receipt key format, so any DB carrying legacy receipts hard-fails container startup with no cleanup path

File: /Users/konata/code/EasyTrade/backend/alembic/versions/0002_handover_receipt_v2_key.py

The new pre-check raises `RuntimeError` when any row fails `task_id ~ '^[0-9]+:[0-9]+$'`. Handover v1 wrote `task_id = f"{task.id}:{app.app_key}"` (EasyAuth commit 34861cb, EasyTrade commit c7e89385 — e.g. `137:easytrade`), which I verified in Postgres does NOT match that regex. So on any environment that still holds v1 receipts, `alembic upgrade head` raises inside `upgrade()`; because backend/docker-entrypoint.sh runs `migrate_with_lock` (or the head guard) at start, the container refuses to boot, and neither the migration, the commit, nor docs/DEPLOYMENT.md provides a cleaning/archival step for those rows. The old behaviour (DELETE) at least completed; the new one converts data loss into an un-runnable migration. Impact is limited because the repo is pre-production (AGENTS.md §7) and the deployed DB currently holds 0 receipts (they were wiped by the pre-fix 0002), so this can only bite a third environment that skipped the old 0002 — hence 'plausible'.

Suggested fix: Handle legacy rows instead of aborting: either rewrite/park them (e.g. move `{task}:{app_key}` rows into an archive table or drop only the rows that cannot be narrowed, logging their ids) or keep the abort but ship a documented one-line cleanup query in docs/DEPLOYMENT.md and reference it in the RuntimeError message.

## V-03 [minor/confirmed] et-test-quality-09 reported fixed but the new staleness test still only exercises set membership

File: /Users/konata/code/EasyTrade/backend/app/tests/test_easyauth_handover_execute.py

`test_snapshot_stale_on_owner_column_change` (line 391) claims in its docstring '§3.5.1: id 集合不变但归属列变化 → 412', but it mutates `Customer.owner_user_id` to a third user. `_q_customer` filters on `Customer.owner_user_id == from_user_id`, so the row leaves the departing user's result set entirely — the id set changes, exactly the case the original finding said was already covered. A `snapshot_token` that hashed only `f"{type}|{id}"` (dropping owner and status from the tuple) still passes this test and every other test in the suite. The genuinely uncovered case is the status column, which for `customer` is NOT part of the predicate: flipping `Customer.status` between two non-DELETED values keeps membership while changing the digest. The report lists et-test-quality-09 as `fixed@51875cab`; it is not.

Suggested fix: Add a case that changes `Customer.status` (a value not filtered by `_q_customer`) between preview and execute/items and asserts 412 `snapshot_stale` with zero writes, so the owner/status components of the digest are actually pinned.

## V-04 [minor/confirmed] Two new assertions are vacuous because of always-true disjuncts, including the golden execute-vs-sample comparison

File: /Users/konata/code/EasyTrade/backend/app/tests/contract/test_handover_v2_golden.py

In `test_live_execute_summary_keys_match_sample` (line ~117) the assertion is `assert set(summary) == set(sample["summary"]) or set(summary) == {s.type_key for s in HANDOVER_ASSETS}`. `execute_response.json` only carries 3 of the 8 types (customer / order_in_transit / inquiry_open), so the first disjunct is always false and the second — the implementation's summary is built as `{spec.type_key: ...}` over `HANDOVER_ASSETS` — is always true. The sample side of this 'golden' comparison can therefore never fail, which is the same class of defect et-test-quality-01 was raised for (the rest of the file is genuinely fixed: preview (type,label) and the items key set are compared live against the samples). The same pattern appears at /Users/konata/code/EasyTrade/backend/app/tests/test_easyauth_handover_items.py:47, `assert seeded.issubset(set(seen)) or set(seen) <= seeded | set(seen)` — the right-hand side is a tautology (line 49 happens to make the real assertion).

Suggested fix: Assert the frozen sample subset explicitly, e.g. `assert set(sample['summary']) <= set(summary)` plus `set(summary) == {s.type_key for s in HANDOVER_ASSETS}` as two separate assertions; delete the tautological disjunct at items test line 47.

## V-05 [minor/confirmed] Forged Content-Length assertion accepts the signature-failure status, and the §4-mandated chunked-over-limit case is still missing

File: /Users/konata/code/EasyTrade/backend/app/tests/test_easyauth_vendored_sdk.py

`test_handover_route_enforces_body_limit_and_business_error_shape` sends the forged-Content-Length request with `X-EasyAuth-Signature: 00` and asserts `forged.status_code in {400, 403, 413, 422}`. An unsigned request returns 403 from the SDK kernel regardless of whether `read_bounded_body`'s Content-Length pre-rejection exists, so this branch cannot detect a regression back to `await request.body()`; only the genuinely oversized-body case (asserted strictly as 413) has teeth. 03 §4 requires both 伪造 Content-Length and chunked 超限 to be covered; there is still no chunked (no Content-Length) over-limit case anywhere in app/tests. The report marks et-test-quality-11 as fixed.

Suggested fix: Sign the forged-Content-Length request correctly and assert exactly 413 (pre-rejection must happen before signature verification, or assert whichever status the SDK actually defines), and add a chunked/streaming body over 256 KiB asserting 413.

## V-06 [minor/confirmed] items single-flight/429 remains unverified and per-type hint assertions cover only `customer`

File: /Users/konata/code/EasyTrade/backend/app/tests/test_easyauth_handover_items.py

et-execute-locks-migration-11 was fixed in production code (the route now dispatches through `anyio.to_thread.run_sync`, so the `429 rate_limited` branch is reachable), but no test exercises it: `grep` for 429/inflight/concurrent/Thread over the new items test file returns nothing. `test_items_sequential_replay_uses_cache` only asserts `r1.json() == r2.json()`, which holds identically with the cache removed, so neither half of §3.5/§5's '连续与并发重放' requirement is actually pinned. Separately, §3.1.1 requires per-type hint assertions ('验收用例须逐类断言非空且含上表要素'); the new `test_items_hints_nonempty_and_carry_business_fields` only drives `asset_type=customer`, so 7 of the 8 `_render_*` hint implementations are still never reached through items (the 500 guard in `items_handover_v2` would fire in production instead of in a test).

Suggested fix: Add a concurrent-replay test (two threads posting the identical signed body, asserting one 200 and one 429 `rate_limited`), assert cache identity via a monkeypatched counter or by mutating the DB and showing the cached body is unchanged, and loop the hint assertions over all 8 asset types with one seeded row each.

## V-07 [minor/confirmed] `_parse_action` still silently maps falsy action values to `skip`, and the test deliberately excludes that case

File: /Users/konata/code/EasyTrade/backend/app/api/v1/easyauth_lifecycle_handlers.py

`_parse_action` does `action = str(raw or "skip")` before the enum check, so `""`, `0`, `false` and `[]` are all coerced to `skip` rather than rejected. Absent keys legitimately mean skip (contract §10.5 semantics 4), but an explicitly malformed value being turned into 保持原状 is precisely what 03 §3.6 step 2 forbids ('下游仍应做防御性校验…不得静默改成保持原状'). The new test acknowledges the hole and steps around it: test_easyauth_handover_execute.py:41-43 iterates `("Transfer", "keep", "DELETE", "")` and `continue`s on `""` with the comment 'empty becomes skip via or "skip"'. The residual risk is small (skip is the non-destructive direction, unlike the release bug that et-execute-locks-migration-01 fixed), but the finding's requirement is not fully met.

Suggested fix: Only default when the key is absent: `raw = payload.get(field, None); action = "skip" if raw is None else raw` then require `isinstance(raw, str) and action in VALID_ACTIONS`, else 422 `invalid_action`; re-enable the `""` case in the test.
