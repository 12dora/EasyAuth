# Round 3.5 fix report — EasyAuth

## Verdict

**All 8 findings fixed.** Full suite green. Not pushed.

## Findings

| ID | Severity | Status | Commit | Notes |
|----|----------|--------|--------|-------|
| V-01 | major | **fixed** | `5073a85` | `takeover_expired_lease` gates `async_attention_required` **before** preempt: if `renewed_at` within `ASYNC_ATTENTION_POLL_INTERVAL_SECONDS` (30 min), return without fence burn / without `poll_async_action`. Outside gate still preempt+poll as fallback. Test: two recovery passes within 30 min → no `signed_hook_get`, fence/`next_fence` unchanged. |
| V-02 | major | **fixed** | `3b5cf88` | `except ApprovalActionError` re-fetch requires `status=REQUEST_STATUS_SUBMITTED`. Decided requests keep approver rows + `approval_routing_state=normal`. Test races approve-then-conflict. |
| V-03 | minor | **fixed** | `a793454` | `lifecycle_send_reminder_task` audits then **raises** `RuntimeError` when notify identity missing so eager outbox dispatch fails and event stays unpublished for retry. |
| V-04 | minor | **fixed** | `a793454` | Beat pin asserts `isinstance(daily, crontab)`, `hour=={9}`, `minute=={0}`, `CELERY_TIMEZONE=='Asia/Shanghai'`; fails if default is float 86400. |
| V-05 | minor | **fixed** | `1b4c83a` | Endpoint tests: console POST async-abandon done/failed → 200 + lease released; portal+console items with `HookCallError(412/423)` → HTTP 412/423 + `details.reason`. |
| V-06 | minor | **fixed** | `1b4c83a` | `map_handover_exception(..., details=)` accepts extras; portal/console 413 path passes `batch_progress`. Unit pin asserts details preserved. |
| V-07 | minor | **fixed** | `3b5cf88` | `replace_approval_rule_approvers` lazily memoises `resolve_assignee` on first matching rule; zero matches → no degraded audit. |
| V-08 | minor | **fixed** | `9aba1f5` | `resolve_manager_chain` returns `(user_ids, degraded)`; submission writes `no_active_manager` vs `chain_exhausted`. Updated unit + S14 tests; added genuine chain-walked-to-end case. |

## Commits (this round)

```
5073a85 fix(lifecycle): async_attention 租约恢复遵守 30 分钟轮询退避
3b5cf88 fix(access): 改派冲突仅对 submitted 进超管池，规则替换惰性解析
a793454 fix(tasks): 提醒缺身份时失败重试并钉扎 crontab 09:00
1b4c83a fix(api): 恢复 413 batch_progress 并补 async-abandon/items 端点测试
9aba1f5 fix(access): 区分 no_active_manager 与 chain_exhausted 路由原因
```

## Gates

```
docker run --rm -v "$PWD":/app -w /app -e DJANGO_DEBUG=1 \
  ghcr.io/astral-sh/uv:python3.12-bookworm-slim \
  bash -lc "uv run --frozen pytest tests -q && \
            uv run --frozen python manage.py check && \
            uv run --frozen python manage.py makemigrations --check --dry-run"
```

| Gate | Result |
|------|--------|
| `pytest tests -q` | **1492 passed, 9 skipped** in 282s |
| `manage.py check` | System check identified no issues |
| `makemigrations --check --dry-run` | No changes detected |

## Disputed

None.

## Residual debt (accepted, not in findings)

- `easyauth-lifecycle` notify identity still not provisioned; V-03 now fails loud and retries instead of consuming the outbox as success.
- Production non-eager Celery: outbox marks published on `send_task` enqueue; task-level raise relies on worker retries. Test settings use `CELERY_TASK_ALWAYS_EAGER` + `EAGER_PROPAGATES`, which is the path that keeps outbox unpublished.
