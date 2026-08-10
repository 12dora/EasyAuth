# EasyProject round-3 findings fix report

**Branch**: `main` (not pushed)  
**Commits**:
- `2e21f60` fix(handover): 五元守恒 — assignee 重叠协作人只计 transferred
- `12fbaf0` fix(handover): 水位短事务推进、终态 412、重复 assignment 与 APPLY_FAILED 去重
- `c36e9bc` fix(openproject): 交接投影 worker claim/HTTP/终态拆事务
- `27731cc` test(handover): round-3 回归 — 9 类 execute、守恒与弱断言加固
- `27bcddd` style(handover): ruff format 与未用变量清理

**Frozen docs**: EasyAuth `docs/design/data-handover-v2/` — `00` §10.5, `05`, `08` §1.3/§2.2/§2.3

---

## 分片 ep-fix1-production（7）

| id | status |
|---|---|
| ep-fix1-production-01 | fixed@2e21f60 — M10/M19 assignee 桶固定 `(1,0)`；目标 collab 删除为不变量修复不进五元 |
| ep-fix1-production-02 | fixed@7ffa6da (pre-HEAD) — `now=` 已删；回归钉扎在 27731cc 九类 execute（含 `work_record_participant`） |
| ep-fix1-production-03 | fixed@12fbaf0 — `record()` 有 `handover_outbox_id` 时跳过 legacy 四元组 |
| ep-fix1-production-04 | fixed@12fbaf0 — `_lock_plan` 终态 → `SnapshotStaleError` (412) |
| ep-fix1-production-05 | fixed@12fbaf0 — preview/items 独立短写事务 `lock_or_create`+`advance` 后再 READ ONLY |
| ep-fix1-production-06 | fixed@c36e9bc — claim 短事务提交 → advisory lock + 无事务 HTTP → owner-CAS 终态 |
| ep-fix1-production-07 | fixed@12fbaf0 — assignments 重复 `asset_type` → 422 |

## 分片 ep-fix2-tests（14）

| id | status |
|---|---|
| ep-fix2-tests-01 | fixed@2e21f60+27731cc — 断言改为 `(1,0)`；真 execute 守恒 `sum==preview` |
| ep-fix2-tests-02 | fixed@27731cc — `test_execute_all_nine_asset_types_conservation` 经 `HandoverServiceV2.execute` 覆盖 9 类 |
| ep-fix2-tests-03 | fixed@27731cc — 真 PG preview→execute 守恒断言（assignee-was-collaborator 含） |
| ep-fix2-tests-04 | fixed@27731cc — 记录 FOR UPDATE SQL 表序，assert projects before tasks |
| ep-fix2-tests-05 | fixed@27731cc — M18 硬断言 skipped≥1 / B-side PENDING / SUPERSEDED |
| ep-fix2-tests-06 | fixed@27731cc — `test_collab_to_final_assignee_merged_pg`（+ recurrence 镜像） |
| ep-fix2-tests-07 | fixed@27731cc — 删 `or True`；同 task 不同 batch_id 真搬数据 |
| ep-fix2-tests-08 | fixed@27731cc — socket/httpx connect guard 于 execute 期间 |
| ep-fix2-tests-09 | fixed@27731cc — 事务中途 assert owner 已翻，再 `pytest.raises(TaskHandoverConflict)` |
| ep-fix2-tests-10 | fixed@27731cc — 真 PG `HandoverReadRepository.list_items` ≥7 条连续翻页 |
| ep-fix2-tests-11 | fixed@27731cc — `EXPECTED_TYPE_LABELS` 字面钉 05 §3.1 九中文名 |
| ep-fix2-tests-12 | fixed@27731cc — member→已是 OWNER：merged + role/元数据保留 |
| ep-fix2-tests-13 | fixed@27731cc — seed 注入 SqlTaskActivityWriter + enqueue；断言 activity actor NULL + outbox |
| ep-fix2-tests-14 | fixed@27731cc — SDK `read_bounded_body` 伪造 CL → BodyTooLargeError + 真超大 body 413 |

---

## Gates

| gate | result |
|---|---|
| `pytest tests/unit tests/integration tests/contract` (backend cwd) | **2285 passed**, 37 skipped (~21.5 min) |
| `scripts/check_permissions.py` | OK |
| `scripts/check_openapi.py` | OK |
| `scripts/check_migrations.py` | OK |
| `scripts/migration-smoke.sh` (venv) | PASS |
| `scripts/quality-gate.sh` full | **blocked on pre-existing ruff** (61 errors, none in this fix set; user rule: do not touch) |
| secret scan | pre-existing false-positives in docs/playwright/ops (untouched) |
| supply-chain config | PASS |

## Notes

- Vendored SDK not modified.
- No push.
- Disputed: none among the 21 EP findings; all confirmed and fixed (or already fixed at HEAD for -02 production code).
