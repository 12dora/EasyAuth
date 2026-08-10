# Fix2 report — EasyProject (Round 3.5 V-01…V-04)

Date: 2026-08-11  
Branch: `main` (not pushed)  
Commits this round:

| Commit | Subject |
|--------|---------|
| `013a514` | fix(openproject): 投影 worker 每实例 owner-CAS 与 pin 连接锁 |
| `8a60231` | test(openproject): 投影 worker 双实例 CAS/锁争用/耗尽集成 |
| `c329127` | test(handover): 钉住 M19 assignee 转交后 collab 删除 |
| `d4892fc` | test(handover): execute 终态 412 与审批锁 423 回归 |

## Findings

### V-01 — fixed@`013a514`

**Problem:** Module-level `_WORKER_OWNER = "handover-projection-worker"` made every instance share the same owner-CAS key; expired-claim preemption left the stale claimer’s terminal write matching.

**Fix:**
- `HandoverProjectionWorker.__init__` sets `self._owner = f"handover-projection-worker:{uuid4()}"`
- `_claim_batch`, `_cas_terminal`, and `_cas_requeue` all use `self._owner`
- Terminal CAS additionally requires `claim_expires_at IS NOT NULL AND claim_expires_at > now`

**Evidence:** Integration test phase 1 in `test_projection_worker.py` — after B reclaims, A’s `_cas_terminal(APPLIED)` leaves status=`CLAIMED` with B’s owner; B’s CAS then succeeds.

### V-02 — fixed@`013a514` + tests@`8a60231`

**Problem:** (1) Open transaction across HTTP after `pg_try_advisory_lock`; (2) zero tests for the worker rewrite.

**Fix:**
- `_with_task_lock` uses `engine.connect()` to **pin** one backend connection, acquires the session-scoped advisory lock, then `conn.commit()` so the connection is **not** idle-in-transaction during HTTP, while the lock remains on that connection until unlock.
- Note: a naive `session.commit()` after acquire would return the connection to the pool; another checkout of the same backend can re-enter the lock. Pinning matches the intent of 08 §1.3 / AGENTS invariant 4 without that hole.

**Tests** (`test_two_workers_stale_cas_lock_contention_and_exhaustion`):
1. Two instances, unique owners; stale terminal CAS no-op
2. Held task advisory lock → requeue with backoff, `gateway.calls == 0`
3. Exhaustion → exactly one `op_sync_conflicts` row with `handover_outbox_id`

### V-03 — fixed@`c329127`

**Problem:** M19 assignee-transfer test only asserted `(1,0)` counts; deleting `collab_of_new` no longer turned red.

**Fix:** After handover, assert `RecurringTemplateCollaboratorRow` for the template is empty (mirror M10’s `collabs == []`), including that `to_uid` is absent.

### V-04 — fixed@`d4892fc`

**Problem:** `_lock_plan` 409→412 (terminal → `SnapshotStaleError`) had no regression pin; old test name said 409.

**Fix:**
- New `test_execute_terminal_project_412_and_approval_lock_423`:
  - Direct `_lock_plan` on COMPLETED project → `SnapshotStaleError` matching `终态` (pins line 503; reverting to `HandoverConflictError` fails)
  - preview live project → flip COMPLETED → execute → `SnapshotStaleError` status_code 412
  - approval-locked project → `HandoverTemporarilyLockedError` status_code 423
- Renamed `test_approval_lock_423_vs_terminal_409` → `test_project_handover_approval_lock_vs_terminal_conflict` (M13 command path still correctly raises `ProjectHandoverConflict` for terminal; not the service 412 path)

## Gates

```text
backend/.venv/bin/python -m pytest tests/unit tests/integration tests/contract -q
→ 2287 passed, 37 skipped in 1274.18s

python3 scripts/check_permissions.py → OK
python3 scripts/check_openapi.py     → OK
python3 scripts/check_migrations.py  → OK
ruff check/format on touched files   → clean
```

## Final test tally

| Suite | Result |
|-------|--------|
| unit + integration + contract | **2287 passed**, 37 skipped |
| New worker integration | 1 test (3 scenarios) |
| M19 collab pin | existing test strengthened |
| execute 412/423 | 1 new test + 1 renamed |

## Not done / out of scope

- No push (per rules)
- Vendored SDK untouched
- Pre-existing ruff debt elsewhere untouched
- Full CF PATCH / redrive API still known debt (docs/design/09)
