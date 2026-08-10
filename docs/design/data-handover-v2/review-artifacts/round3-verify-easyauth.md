# Verification findings — EasyAuth (verdict: fail)

## V-01 [major/confirmed] 30-minute async_attention_required backoff is defeated by the 60s lease-recovery beat

File: src/easyauth/tasks/lifecycle.py

The fix for a1c-beat-upgrade-conservation-05 only backs off the *poll* beat: `lifecycle_poll_async_actions_task` skips attention actions whose lease `renewed_at` is newer than ASYNC_ATTENTION_POLL_INTERVAL_SECONDS. But the same commit set changed `takeover_expired_lease` (handover.py:1974) to route ACTION_STATUS_ASYNC_ATTENTION_REQUIRED into `poll_async_action`, and `lifecycle_recover_expired_execution_leases_task` runs every 60s (settings/base.py:410) over every unreleased lease with `lease_expires_at <= now`. LEASE_TTL is 5 minutes (models.py:55) and nothing renews an attention lease between polls, so the cycle is: poll renews at T -> lease expires at T+5min -> recovery beat picks it up within 60s -> `preempt_expired_lease` allocates a *new fence* and renews -> `cas_update_owner` -> `poll_async_action` issues the signed status GET -> renews again. Net effect: a stuck (subject, app) is polled roughly every 5-6 minutes (~240/day instead of the specified 48/day) and burns 3+ fences per cycle instead of 2, and the poll beat's new attention branch becomes dead code because `renewed_at` is never older than 30 minutes. The mandated ASYNC_ATTENTION_POLL_INTERVAL cadence in 01 §7 is still not observable anywhere.

Suggested fix: In `takeover_expired_lease`, treat ASYNC_ATTENTION_REQUIRED as renew-only: `cas_update_owner(handle, new_owner=f"async:{batch.pk}", renew=True)` and return without calling `poll_async_action` (or apply the same `renewed_at + ASYNC_ATTENTION_POLL_INTERVAL_SECONDS` gate there). Add a test that expires an attention lease, runs the recovery beat twice within 30 minutes, and asserts no `signed_hook_get` call and no new fence.

## V-02 [major/plausible] ApprovalActionError fallback stamps superuser_pool on (and strips approvers from) already-decided access requests

File: src/easyauth/lifecycle/approvals.py

`reassign_access_request_approvers`'s new `except ApprovalActionError` branch re-fetches with `AccessRequest.objects.filter(pk=request_id).first()` — without the `status=REQUEST_STATUS_SUBMITTED` filter that `_reassign_one_access_request` uses — and unconditionally calls `_route_request_to_superuser_pool(...)`, which deletes the subject's approver row plus every non-active approver row and writes `approval_routing_state='superuser_pool'`, `routing_reason='no_active_manager'`. The most likely trigger is exactly the race the round-3 finding named: a concurrent approve/reject flips the request out of `submitted` between the unlocked scan at approvals.py:68-73 and the locked re-check inside `reassign_access_request` (kind='conflict'); legacy data with the applicant among the approvers (REASSIGN_APPLICANT_FORBIDDEN) triggers it deterministically. An approved/rejected request then carries `superuser_pool` forever, because the only reset lives in `reassign_access_request`, which refuses non-submitted requests — i.e. the exact 'permanently stuck in the pool' state a1c-reassign-adr36-05 was filed about, now created on decided rows, and it will show up in the new `approval_routing_state=superuser_pool` console filter and any '待认领计数'.

Suggested fix: Only route to the pool when the re-fetched request is still `status=submitted`; otherwise log/audit the conflict and move on without touching approver rows or routing state. Add a test that flips the request to `approved` before reassignment and asserts routing state stays `normal` and the approver rows are untouched.

## V-03 [minor/confirmed] Daily reminder is still consumed and dropped — send_reminder returns success without sending or failing the outbox event

File: src/easyauth/tasks/lifecycle.py

a1c-beat-upgrade-conservation-04 is reported fixed@34d5a6b, but `lifecycle_send_reminder_task` records a `lifecycle_reminder_recorded` audit row, logs a warning and returns 'recorded'. The outbox event is therefore marked `published`, and `last_reminded_on` was already advanced by the claim, so the reminder for that business date is never delivered and never retried — the ledger's suggested fix explicitly asked for the task to *fail the outbox event* (or to not advance `last_reminded_on`) precisely so the message is retried once the `easyauth-lifecycle` identity exists. The report discloses the identity as accepted debt, which is fair, but the finding itself is only converted from a silent drop to a logged drop, not fixed.

Suggested fix: Raise from `lifecycle_send_reminder_task` when the notify identity is missing so the outbox event stays unpublished and is retried after provisioning (or skip advancing `last_reminded_on` until an identity exists), and mark the finding partially-fixed rather than fixed.

## V-04 [minor/confirmed] Beat-schedule regression pin cannot fail: isinstance(daily, (float, crontab))

File: tests/unit/lifecycle/test_beat_shell.py

a1c-beat-upgrade-conservation-07 was specifically 'registered as an 86400s float instead of crontab 09:00 Asia/Shanghai'. The new pin at test_beat_shell.py:142-144 asserts `isinstance(daily, (float, crontab))`, which is satisfied by the exact defect it is supposed to catch — reverting base.py to `float(os.environ.get(..., "86400"))` keeps the test green. No test asserts the hour/minute or CELERY_TIMEZONE either.

Suggested fix: With EASYAUTH_LIFECYCLE_DAILY_REMINDER_SECONDS unset, assert `isinstance(daily, crontab)` and that `daily.hour == {9}` / `daily.minute == {0}`, plus `settings.CELERY_TIMEZONE == 'Asia/Shanghai'`.

## V-05 [minor/confirmed] No endpoint-level test for async-abandon or items 412/423, as the ledger required

File: tests/unit/lifecycle/test_round3_blockers.py

Both blockers' suggested fixes asked for tests driving the HTTP endpoints. The new pins call the domain functions directly (`async_abandon_action`, `complete_data_phase`) and unit-test `map_handover_exception` in isolation; nothing exercises `console_handover_async_abandon` (payload -> domain -> `action_item` serialization, the layer that returned 500) or `portal_handover_items` / `console_handover_items` with a stubbed 412/423 hook. The whole reason both blockers shipped was that these endpoints had zero coverage, and they still do.

Suggested fix: Add an integration test that POSTs `/console/api/v1/lifecycle/handover-tasks/{id}/actions/{app_key}/async-abandon` for both `done` and `failed` asserting 200 + released lease, and a test that stubs the items hook to raise `HookCallError(status_code=412)` asserting HTTP 412 with `details.reason == 'snapshot_stale'` on both portal and console.

## V-06 [minor/confirmed] Portal 413 response lost details.batch_progress when HookCallError mapping moved into map_handover_exception

File: src/easyauth/portal/handover_api.py

`portal_handover_action_operation` previously answered a downstream 413 through its own `'413' in text` branch, which returned `reason_error('payload_too_large', details={'batch_progress': batch_progress(action)})` (still present at handover_api.py:566-573). Now `map_handover_exception` intercepts `HookCallError` by `status_code` first and returns a bare `reason_error('payload_too_large')`, so that branch is unreachable for the real 413 path (`signed_hook_post` -> `_parse_hook_response` raises HookCallError(413) -> `_execute_action` re-raises it) and the batch-progress detail silently disappears from the error envelope. 01 §6.1's 413 row says the response should carry `batch_progress`.

Suggested fix: Either keep the HookCallError 413 case in the handler (check `isinstance(error, HookCallError) and error.status_code == 413` before calling the mapper), or let `map_handover_exception` accept optional extra details and pass `batch_progress(action)` for 413.

## V-07 [minor/confirmed] replace_approval_rule_approvers now resolves the assignee unconditionally, adding a degraded-audit row even when no rule mentions the subject

File: src/easyauth/lifecycle/approvals.py

The a1c-reassign-adr36-07 fix hoisted `resolve_assignee(subject, start_level=0)` out of the per-rule loop to approvals.py:233 — but it now runs on *every* offboard 建单 and upgrade (`reassign_approvals_for_departed` -> `replace_approval_rule_approvers`), before the `subject_uid not in raw: continue` filter. For the common case (departing user is in zero approval rules) with a missing/stale DingTalkUserOrgContext, `resolve_assignee` writes a `handover_assignee_resolution_degraded` audit row (assignee.py:41/58/71), so 建单 now emits two rows where it previously emitted one — worsening the '审计表出现且仅出现一行' property §6.4 assigns to this event, which is the very thing the finding was about. It also costs an extra directory query per 建单.

Suggested fix: Resolve lazily: keep the single-resolution cache but compute it on the first matching rule (e.g. a small memoised closure), so no resolution happens when the subject appears in no rule.

## V-08 [minor/confirmed] routing_reason is still hard-coded to chain_exhausted on the submission path, and the new tests pin the fabricated value

File: src/easyauth/access_requests/services.py

a1c-reassign-adr36-04's second half ('the recorded routing_reason is fabricated; no_active_manager is never produced on this path') is not addressed: services.py:136 still writes `routing_reason = 'chain_exhausted'` for every superuser_pool submission, even though `active_manager_chain_user_ids` returns () both when the chain is genuinely walked to the end and when the directory context is missing/stale (`resolve_assignee(...).degraded`, which the lifecycle path at approvals.py maps to `no_active_manager`). Both new tests (tests/unit/access_requests/test_adr36_chain_exhausted.py:52 and tests/integration/portal/test_access_request_s14.py:349) assert `routing_reason == 'chain_exhausted'` for an applicant who has no DingTalk context at all, cementing the wrong enum value.

Suggested fix: Have `active_manager_chain_user_ids` (or a sibling) return the AssigneeResolution so services.py can write `no_active_manager` when `resolution.degraded` and `chain_exhausted` only when the chain was actually walked; update both tests to the correct value.
