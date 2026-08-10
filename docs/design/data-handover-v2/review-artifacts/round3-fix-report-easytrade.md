# EasyTrade round-3 findings fix report

Branch: `main` (not pushed)  
Commits:

| SHA | Subject |
|---|---|
| `c39fe51f` | fix(authz): 交接 snapshot/动作/继承应收与未映射身份整改 |
| `0f07fae4` | fix(authz): 交接回执迁移保留历史并加 task_id 格式 CHECK |
| `51875cab` | test(authz): 补齐交接 v2 契约与 execute/items/锁序真实用例 |
| `6582914c` | test(backend): 业务日时区口径修复并同步交接 v2 现状 |

Gate: `BACKEND_TESTS='app/tests' make finish-check` → **exit 0**  
Tally: platform_tests **80 passed**; customs **290 passed**; app/tests **3542 passed**, **5 skipped**; ruff check/format OK; tsc OK; Playwright skipped (no FRONTEND_TESTS).

---

## 分片 et-registry-preview-items

| id | status |
|---|---|
| et-registry-preview-items-01 | fixed@c39fe51f |
| et-registry-preview-items-02 | fixed@c39fe51f |
| et-registry-preview-items-03 | fixed@51875cab |
| et-registry-preview-items-04 | fixed@51875cab |
| et-registry-preview-items-05 | fixed@c39fe51f |
| et-registry-preview-items-06 | fixed@c39fe51f |
| et-registry-preview-items-07 | fixed@c39fe51f |
| et-registry-preview-items-08 | fixed@c39fe51f |
| et-registry-preview-items-09 | fixed@c39fe51f |

## 分片 et-execute-locks-migration

| id | status |
|---|---|
| et-execute-locks-migration-01 | fixed@c39fe51f |
| et-execute-locks-migration-02 | fixed@c39fe51f |
| et-execute-locks-migration-03 | fixed@c39fe51f |
| et-execute-locks-migration-04 | fixed@0f07fae4 |
| et-execute-locks-migration-05 | fixed@51875cab |
| et-execute-locks-migration-06 | fixed@0f07fae4 |
| et-execute-locks-migration-07 | fixed@c39fe51f |
| et-execute-locks-migration-08 | fixed@51875cab |
| et-execute-locks-migration-09 | fixed@51875cab |
| et-execute-locks-migration-10 | fixed@c39fe51f |
| et-execute-locks-migration-11 | fixed@c39fe51f |

## 分片 et-test-quality

| id | status |
|---|---|
| et-test-quality-01 | fixed@51875cab |
| et-test-quality-02 | fixed@c39fe51f + fixed@51875cab |
| et-test-quality-03 | fixed@51875cab |
| et-test-quality-04 | fixed@c39fe51f + fixed@51875cab |
| et-test-quality-05 | fixed@51875cab |
| et-test-quality-06 | fixed@51875cab |
| et-test-quality-07 | fixed@51875cab |
| et-test-quality-08 | fixed@51875cab |
| et-test-quality-09 | fixed@51875cab |
| et-test-quality-10 | fixed@51875cab |
| et-test-quality-11 | fixed@51875cab |
| et-test-quality-12 | fixed@51875cab |

---

## Implementation notes

### Production

- `snapshot_token`: per-type `array_to_string(array_agg(expr ORDER BY id), E'\n')` then SHA-256[:32]; input tuple `(type|id|owner|status)` with NULL→`None`.
- `_validate_items_bounds`: non-str `q` → 422 (key absent → `""`).
- `_mark_receivable_materialize`: `action_to is None` treated as skip (type omitted from assignments).
- Actions: parse + `_validate_assignments` + `_apply_type` only `transfer|release|skip`.
- `on_handover_preview` unmapped → 409 `identity_unmapped` (same as items/execute).
- `try_replay_execute` before identity resolution on execute; `locked=True` continues without re-check.
- Route: `anyio.to_thread.run_sync(lifecycle_http_response)`; items cache/inflight under `threading.Lock`.
- Labels via `_clip(..., 120)`; receivable hint uses `receivable_open_amount`; order reassign uses header+line_items audit snapshot.
- Migration `0002`: no DELETE; abort if non-conforming `task_id`; CHECK on receipts + watermarks; models mirror CHECK.

### Tests

- Golden: live POST preview/items/execute; registry labels vs sample; override shape parseable.
- `test_easyauth_handover_items.py`: pagination, 422 bounds, total/unfiltered_total, hints, 412, cache, label clip.
- `test_easyauth_handover_execute.py`: invalid action, overrides, out-of-snapshot, inherited receivable materialize (absent + explicit skip), idempotent replay with deactivated receiver + DB counts, idempotency_conflict, stale_generation, duplicate asset_type, owner-column staleness 412.
- Predicates: positive/negative rows per type.
- Lock order: unit 409 recheck tests; PG dual-txn scoped to B's pid; reverse accepts only deadlock/timeout (not AssertionError substring "lock").
- Body limit + 409 shape in vendored SDK test.

### Incidental (finish-check)

- Fulfillment orderDate / sample deliveredAt used UTC day boundaries that fail under `TZ=Asia/Shanghai` near day edges; switched to `business_today()` / `now-1s`.

### Not disputed

No findings in the three EasyTrade shards were disputed; all were confirmed and fixed. Vendored SDK left untouched.
