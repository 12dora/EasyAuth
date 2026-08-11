# 数据交接 v2 · 第四轮 codex 全量复审 findings（round4）

> 2026-08-11 上午，codex gpt-5.6-sol(high) 22 分片独立复审（前三轮之后的盲区扫描）。

## 分片 ea-approvals-adr36 — 5 条 (blocker 0 / major 4 / minor 1)

**Shard summary**: The manager-chain walker itself correctly handles finite cycles, self references, inactive users, local administrators, malformed entries, and tenant-scoped DingTalk IDs. However, submission routing bypasses those guarantees through a legacy fallback and resolves the chain twice. Offboarding reassignment also contains unlocked read-modify-write windows that can mutate decided requests or discard concurrent approver changes. Approval-rule replacement has the same lost-update risk.

### [ea-approvals-adr36-01] MAJOR (confirmed) Legacy manager fallback bypasses the frozen supervisor-chain policy

- **File**: `src/easyauth/access_requests/submission_validation.py:222`
- **Description**: When `resolve_assignee()` reports missing, stale, or exhausted `manager_chain`, `resolve_manager_chain()` falls back to `UserMirror.manager_userid`. It first interprets that DingTalk-oriented value as a globally unique Authentik ID without tenant scoping and does not exclude `local-admin:` users or the applicant. For example, with stale directory context and a still-active former direct manager in `manager_userid`, a MANAGED_USERS request is routed normally to that stale manager instead of entering `superuser_pool`; an Authentik-ID collision can even select a user from another tenant. This violates ADR-002 §36 and `01-easyauth-backend.md` §3, which require resolution exclusively through the tenant-scoped `manager_chain` and require unavailable/stale directory data to route to the pool.
- **Suggested fix**: Remove the `manager_userid` fallback. Use the single `resolve_assignee()` result directly and preserve its `degraded` classification.

### [ea-approvals-adr36-02] MAJOR (confirmed) Pool routing can rewrite an already-decided request

- **File**: `src/easyauth/lifecycle/approvals.py:192`
- **Description**: The no-replacement path calls `_route_request_to_superuser_pool()` without locking or rechecking the AccessRequest row. Concrete race: offboarding reads a submitted request whose only approver is the departing subject; that approver concurrently approves it; offboarding then deletes the approver row and updates only `approval_routing_state` and `routing_reason` from its stale object. The resulting approved request is permanently marked `superuser_pool`, its approver history is removed, and a misleading handover audit event is written. The exception fallback at lines 88-99 has the same check-then-mutate window. This violates `01-easyauth-backend.md` §4.5.1, which strictly forbids changing approved or otherwise decided requests.
- **Suggested fix**: Lock the AccessRequest before reading approvers, recheck `status == submitted` under that lock, and perform row deletion, routing-state update, and audit insertion in the same transaction.

### [ea-approvals-adr36-03] MAJOR (confirmed) Stale approver snapshots can silently discard concurrent reassignment

- **File**: `src/easyauth/lifecycle/approvals.py:122`
- **Description**: The complete approver set is read before `reassign_access_request()` acquires the request lock. If the initial set is `[departed, finance]`, an administrator can concurrently change it to `[departed, finance, legal]`; offboarding subsequently obtains the lock but submits its stale computed set `[finance, new_manager]`, and the whole-set replacement deletes `legal`. This silently cancels a valid approval responsibility and violates the complete-set preservation requirement in `01-easyauth-backend.md` §4.5.1.
- **Suggested fix**: Acquire the AccessRequest row lock first, then read and transform its current approver rows while holding that lock. Expose a locked replacement helper if necessary so validation, replacement, routing-state changes, and audits share one transaction.

### [ea-approvals-adr36-04] MAJOR (confirmed) Approval-rule replacement can overwrite concurrent rule edits

- **File**: `src/easyauth/lifecycle/approvals.py:247`
- **Description**: Active ApprovalRule objects are loaded without row locks and their JSON approver lists are later saved wholesale. If a rule starts as `[departed, finance]`, an administrator concurrently adds `legal`, and offboarding then saves its stale `[finance, new_manager]`, the administrator's approver is silently lost. This violates `01-easyauth-backend.md` §4.5.2, which requires replacing only the departing subject while preserving the rest of the rule.
- **Suggested fix**: Select matching ApprovalRule rows with `select_for_update()` inside the offboarding transaction and recompute each replacement from the locked current list.

### [ea-approvals-adr36-05] MINOR (confirmed) One degraded submission writes the resolution audit event twice

- **File**: `src/easyauth/access_requests/services.py:109`
- **Description**: For every MANAGED_USERS submission, `validate_submission_scope()` resolves the manager chain through `_validate_managed_users_approver()`, and `_submit_access_request()` resolves it again at lines 121-124. With missing or stale directory context and an empty submitted approver list, both calls invoke `resolve_assignee()` and each inserts `handover_assignee_resolution_degraded`; the successful request therefore produces two indistinguishable audit rows for one routing decision. A directory update between the calls can also make validation and persisted routing use different chain snapshots. This violates the single resolution-and-audit behavior specified by `01-easyauth-backend.md` §3 and the routing decision in ADR-002 §36.
- **Suggested fix**: Resolve once inside the submission transaction, pass the immutable result into scope validation, and reuse it when selecting approvers and persisting routing state.

## 分片 ea-beat-tasks — 2 条 (blocker 0 / major 2 / minor 0)

**Shard summary**: The four lifecycle beat jobs are registered with the required intervals, and the daily job defaults to 09:00 in Asia/Shanghai. Async polling includes both pending and attention-required actions and preserves the lease at the polling cap. Two confirmed defects remain: notification failures are consumed without retry, and the daily reminder scan silently omits every eligible task after the first 200.

### [ea-beat-tasks-01] MAJOR (confirmed) Missing notify identity consumes the reminder permanently instead of retrying

- **File**: `src/easyauth/tasks/lifecycle.py:119`
- **Description**: The reminder task raises RuntimeError when the easyauth-lifecycle identity is absent, but it has no autoretry or explicit self.retry configuration. The outbox dispatcher marks its event published as soon as current_app.send_task returns; the later worker exception therefore does not return the outbox event to pending, and Celery consumes the failed invocation without another attempt. For an identity outage followed by identity provisioning, the original reminder is never delivered despite the function claiming it was deferred. This violates 01-easyauth-backend.md §7, which requires missing identity to warn without silently losing the message and requires notification network effects to remain recoverable through the outbox path.
- **Suggested fix**: Give the reminder task a durable, backoff-based retry path for the missing-identity condition, with retries continuing until provisioning succeeds, or persist a separate delivery state that the dispatcher can reclaim. Add an integration test that dispatches through the real outbox boundary, observes the worker failure, provisions the identity, and verifies eventual delivery.

### [ea-beat-tasks-02] MAJOR (confirmed) Daily reminder processing is permanently capped at 200 eligible tasks per run

- **File**: `src/easyauth/tasks/lifecycle.py:178`
- **Description**: The only daily invocation materializes qs[:200] and never loops for another batch. With 201 eligible open tasks at 09:00, at least one receives no reminder that business day; because the query has no ordering and the first 200 become eligible again on the next business date, a stable PostgreSQL scan can repeatedly select the same rows and starve later tasks indefinitely. Concurrent beat instances also materialize the same unlocked slice, so they do not reliably extend coverage. This violates 01-easyauth-backend.md §7, which requires reminders for all unfinished assigned tasks and specifies select_for_update(skip_locked=True) batched claiming with an atomic conditional update.
- **Suggested fix**: Drain eligible rows in repeated bounded transactions using select_for_update(skip_locked=True), retaining the conditional last_reminded_on update and same-transaction outbox insert, until no eligible rows remain.

## 分片 ea-console-api — 8 条 (blocker 1 / major 5 / minor 2)

**Shard summary**: All reviewed console handlers invoke `require_superuser()` before resource lookup, and the `errors/raw` and `async-abandon` routes are correctly registered before the dynamic operation route. However, async manual resolution can silently skip planned batches and has a fence-ownership race that permits duplicate summary application. The raw-error pipeline neither preserves the contracted downstream fields nor reliably redacts and byte-truncates stored diagnostics. Capability resync can silently no-op, cannot reuse protected-descriptor credentials, and emits incorrectly attributed audit records.

### [ea-console-api-01] BLOCKER (confirmed) Manual async completion silently skips remaining batches

- **File**: `src/easyauth/lifecycle/handover.py:1020`
- **Description**: For an `async_attention_required` action whose current batch is non-final, `async_abandon_action(outcome="done")` forcibly changes `batch.is_final` to true before calling `complete_data_phase()`. Example: batch 1 of a three-batch 413 plan returns 202 and reaches attention; an administrator confirms batch 1 completed, but the helper marks the whole action and plan done, runs grant transfer, and leaves batches 2 and 3 unprocessed. This violates frozen 01 §5.5, which requires non-final batches to return the action to `previewed`, and §6.3's requirement to resolve through the real `complete_data_phase()` semantics.
- **Suggested fix**: Preserve the batch's immutable `is_final` value. Resolve the confirmed batch through `complete_data_phase()` and let its existing non-final path advance batch progress, release the lease, and return the action to `previewed`.

### [ea-console-api-02] MAJOR (confirmed) Concurrent async-abandon calls can double-apply the manual summary

- **File**: `src/easyauth/lifecycle/handover.py:1026`
- **Description**: The initial transaction leaves the action in `async_attention_required` and does not claim the sentinel lease under a new owner/fence. Two concurrent `done` requests can therefore both pass validation, reconstruct the same live lease handle, and each commit transaction A of `complete_data_phase()`, where `_merge_result_summary()` adds the same counts. One request later releases the lease and the other returns a CAS conflict, but the duplicated counts have already committed. A poller can cause the same partial-commit race by claiming the sentinel between the preliminary transaction and completion. This violates 01 §6.3's requirement that manual resolution and release be protected by one fence ownership/CAS protocol.
- **Suggested fix**: While holding the action and lease locks, CAS-claim the sentinel to a unique manual-resolution owner and fence, and record an in-progress resolution state or token. Require that exact handle throughout completion so concurrent manual requests and pollers fail before any summary mutation.

### [ea-console-api-03] MAJOR (confirmed) Raw errors are stored without the required redaction or UTF-8 byte limit

- **File**: `src/easyauth/lifecycle/handover.py:495`
- **Description**: Grant-transfer and several other failure paths assign `str(error)[:2000]` directly to `last_error_raw`; the console endpoint then returns that value verbatim. If an exception contains a token, URL credential, DSN, email, sub, or dtuid, it is persisted in the business table and exposed to console readers and backups. The slice is also by Unicode code points, so 2,000 multibyte characters can substantially exceed the frozen 2,000-byte limit. This violates contract 00 §10.6 and 01 §6.3, which require a redacted projection and UTF-8 byte truncation before storage.
- **Suggested fix**: Route every `last_error` and `last_error_raw` assignment through one redactor covering the mandated secret and identity patterns, then truncate safely to 200 and 2,000 UTF-8 bytes respectively.

### [ea-console-api-04] MAJOR (confirmed) Non-2xx response bodies are discarded before whitelist projection

- **File**: `src/easyauth/webhooks/hooks.py:134`
- **Description**: `_parse_hook_response()` raises `HookCallError` for every non-2xx status before decoding the response body. Consequently, a downstream 400 such as `{"error":{"code":"timestamp_out_of_range","message":"expired","traceId":"t1"}}` reaches `_finish_delivery_failure()` with no payload, and both normal and raw console errors contain only a generic HTTP message. This violates 00 §10.6's `code`/`message`/`traceId` whitelist contract and the 01 §6.3 `errors/raw` endpoint contract.
- **Suggested fix**: Return status, location, and a bounded parsed/raw response representation for allowed error statuses. Build `last_error` from the three whitelisted keys and `last_error_raw` from the separately redacted, byte-truncated projection.

### [ea-console-api-05] MAJOR (confirmed) Capability resync silently skips capability reconciliation for an unchanged manifest

- **File**: `src/easyauth/applications/manifest_import.py:70`
- **Description**: The console resync endpoint calls `sync_app_manifest()`, which returns immediately when the fetched manifest version and hash equal the latest imported version. That bypasses `apply_permission_template()` and therefore `sync_handover_capability_from_manifest()`. For example, after a valid `handover.v2` manifest was imported, an administrator can declare the app `none`; pressing resync against the unchanged valid descriptor reports success but leaves the app as `none` and performs no blocked-action reconciliation. This violates 01 §5.2 and §6.3, where manual resync must re-evaluate descriptor capability state.
- **Suggested fix**: Separate capability synchronization from permission-template version insertion. Even when the permission manifest is already current, parse its lifecycle section and atomically run capability synchronization/reconciliation.

### [ea-console-api-06] MAJOR (confirmed) Manual resync drops the descriptor credential

- **File**: `src/easyauth/admin_console/handover_v2_api.py:860`
- **Description**: The endpoint derives an origin from webhook configuration and unconditionally calls `_fetch_descriptor(base_url, None)`. An app whose well-known descriptor requires the bearer credential supported by the existing pull path will always return 401/403, so the documented resync button cannot synchronize it. This violates 01 §5.2 and §6.3, which require reuse of the existing descriptor pull path with its base URL and credentials.
- **Suggested fix**: Persist/reference the app's descriptor pull configuration and invoke the shared authenticated repull service instead of reconstructing an unauthenticated request from webhook URLs.

### [ea-console-api-07] MINOR (confirmed) Manual async-resolution audit omits the asserted result and generation

- **File**: `src/easyauth/lifecycle/handover.py:1057`
- **Description**: After a manual `done`, `handover_action_executed` records only `app_key`, `manual_resolution`, and `reason`; it omits the supplied summary, generation, and assignment/result summary. Thus an administrator can assert concrete transfer counts that affect `result_summary`, while the append-only audit record cannot reconstruct what was asserted. This violates 01 §6.4 and frozen contract 00 §12, which require generation, assignment summary, and result summary for `handover_action_executed`.
- **Suggested fix**: Include generation and the bounded/redacted manual result and assignment summaries in the event metadata, and write the audit record as part of the successful resolution transaction boundary.

### [ea-console-api-08] MINOR (confirmed) Console capability-sync audit events are misclassified as system actors

- **File**: `src/easyauth/applications/handover_capability.py:50`
- **Description**: The console endpoint passes the administrator's actor ID into capability synchronization, but `handover_capability_conflict` and `handover_action_unblocked` hard-code `actor_type="system"`. When an administrator triggers resync and it detects a conflict or unblocks tasks, actor-type queries attribute the operation to automation despite retaining the administrator's ID. This violates 01 §6.4's rule that console entry points record `actor_type="admin"`.
- **Suggested fix**: Pass an explicit actor type through the manifest/capability synchronization service and use `admin` for console resync, while retaining `system` for scheduled or system-initiated synchronization.

## 分片 ea-e2e-harness — 2 条 (blocker 0 / major 2 / minor 0)

**Shard summary**: The seed command is correctly gated by Django DEBUG and creates the handover task through ensure_handover_task; grant creation also uses the real grant service. The downstream stub delegates request authentication to the vendored lifecycle kernel, which verifies signatures and timestamps before dispatch. No production credential is committed; the fixed shared key is confined to the loopback E2E fixture. However, the full-stack test is skipped by default, and even when enabled it can pass without proving that the documented two overrides reached the downstream application.

### [ea-e2e-harness-01] MAJOR (confirmed) The only handover full-stack test is skipped unless an undocumented opt-in variable is set

- **File**: `frontend/e2e-fullstack/handover-self-service.spec.ts:18`
- **Description**: The describe block skips whenever EASYAUTH_HANDOVER_E2E is absent or not exactly "1", while playwright.fullstack.config.ts does not set that variable. A normal invocation of this dedicated full-stack configuration therefore starts the real services but reports the sole documented handover scenario as skipped, allowing missing or broken EasyAuth v2 endpoints to remain green. This violates 02-easyauth-frontend.md §9, which assigns this spec coverage of the manager portal -> open task -> change two items -> execute -> done flow, as well as the honesty requirement that an unavailable real backend must fail rather than be hidden.
- **Suggested fix**: Remove the skip gate now that the v2 backend is part of the program, or make the dedicated full-stack configuration unconditionally enable the test and fail explicitly if the required real endpoints are unavailable.

### [ea-e2e-harness-02] MAJOR (confirmed) Lost or malformed assignments are converted into a successful conserved result

- **File**: `scripts/e2e_handover_downstream.py:91`
- **Description**: on_execute silently replaces a missing/non-list assignments value with an empty list and ignores malformed rows, unknown asset types, invalid overrides, and missing transfer recipients. It then reports all three previewed assets as skipped, which satisfies EasyAuth's summary-conservation check and lets the task reach done. Combined with the spec asserting only one generic override marker and the final "已交接" text at frontend/e2e-fullstack/handover-self-service.spec.ts:86, a regression that drops one or both overrides—or even the entire assignments payload—can pass despite not executing the documented two-item reassignment. This violates 02-easyauth-frontend.md §9's exact E2E flow and the project's honesty/fail-fast rules.
- **Suggested fix**: Make the stub reject malformed or incomplete execute payloads and validate the expected document assignment semantics, including the transfer recipient and exactly two skip overrides. Also assert the resulting summary counts (one transferred and two skipped) or expose/assert the received assignments so the browser test proves the documented operation reached downstream.

## 分片 ea-execute-conservation — 7 条 (blocker 0 / major 5 / minor 2)

**Shard summary**: The normal synchronous path preserves data-before-grant ordering, validates conservation before marking data complete, and releases the lease on ordinary 200 and handled failure responses. However, recovery after Phase A is not idempotent and can silently double the persisted aggregate summary. Several exceptional paths can strand leases or leave batch records inconsistent with a completed action. The 413 plan lifecycle also permits mid-plan intent changes and can deadlock permanently when a later planned batch is still oversized.

### [ea-execute-conservation-01] MAJOR (confirmed) Recovery after Phase A double-counts the batch summary

- **File**: `src/easyauth/lifecycle/handover.py:444`
- **Description**: Phase A unconditionally calls `_merge_result_summary`, even when the same batch already has `data_completed_at`. If Phase A commits for a final batch and the worker crashes before Phase B or C, expired-lease recovery replays the immutable request; the downstream idempotently returns the original summary, and `complete_data_phase` adds those counters to `action.result_summary` a second time. The action can then finish with silently inflated totals, violating `00-overview-and-contract.md` §10.5's requirement that the displayed total be the sum of each batch exactly once and §10.5.1.1's durable, idempotent phase-resumption contract.
- **Suggested fix**: Make Phase A idempotent per batch: when `batch.data_completed_at` is already set, do not merge its summary again. Persist a per-batch accepted summary or another durable merge marker and only add it during the first DATA_COMPLETED transition.

### [ea-execute-conservation-02] MAJOR (confirmed) A malformed 202 response permanently strands the active lease

- **File**: `src/easyauth/lifecycle/handover.py:1363`
- **Description**: `_ensure_accepted_location` runs before the transaction that records the 202 and transfers the lease to the async sentinel. A downstream response of HTTP 202 without `Location` therefore raises immediately while the delivery and batch remain `sent`/`executing`, the action remains `executing`, and the lease remains active under the sender. Expired-lease recovery replays the request and reaches the same unhandled path, so the action cannot converge. This violates `00-overview-and-contract.md` §10.5's 202 contract and `01-easyauth-backend.md` §2.4.2's requirement that every outcome either transfer or release the lease under the fence CAS.
- **Suggested fix**: Treat 202 without `Location` as a terminal delivery failure through the same fenced failure transaction used for other invalid responses, updating delivery/batch/action and releasing the lease.

### [ea-execute-conservation-03] MAJOR (confirmed) A later 413 in an active plan rolls back terminal bookkeeping and lease release

- **File**: `src/easyauth/lifecycle/handover.py:2068`
- **Description**: When a planned batch returns 413 after at least one prior batch completed, `_ensure_batch_plan_on_413` leaves the existing active plan intact because `completed_batches > 0`, then attempts to create another active plan for the same action and generation. The conditional unique constraint rejects that insert, rolling back `_finish_delivery_failure`, including the delivery failure record, action transition, batch transition, and lease release. For example, a final batch containing all retained `skip` overrides may remain oversized after earlier transfer batches succeeded; every recovery replay returns 413 and repeats the same failure. This violates `01-easyauth-backend.md` §2.4.1.1's unshardable-413 behavior and §2.4.2's terminal lease-release invariant.
- **Suggested fix**: Detect 413 while `completed_batches > 0` as the documented unshardable-plan failure: retain the existing plan, record the oversized batch failure, return the action to an operable state with the prescribed guidance, and release the lease without creating another active plan.

### [ea-execute-conservation-04] MAJOR (confirmed) The frozen 413 assignment plan can be changed after partial execution

- **File**: `src/easyauth/lifecycle/handover.py:158`
- **Description**: After a non-final batch succeeds, its lease is released and its batch is `done`, so `action_execution_in_flight` returns false. `update_grant_receiver` then permits changing `grant_receiver`, resets the action to `pending`, and increments `confirm_version`, even though the active plan has `completed_batches > 0`. Moreover, the stored `assignment_hash` excludes `grant_receiver` and is never validated by execute. Thus an offboarding plan can move some data under one confirmed intent and transfer grants to a newly substituted receiver in the final batch, violating `01-easyauth-backend.md` §2.4.1.1's frozen-plan and assignment-hash rules.
- **Suggested fix**: Reject assignment and grant-receiver mutations whenever an active plan has completed batches. Include `grant_receiver` and the remaining canonical assignment intent in `assignment_hash`, and validate it before creating every planned batch.

### [ea-execute-conservation-05] MAJOR (confirmed) Grant-only retry completes the action but leaves the final batch failed

- **File**: `src/easyauth/lifecycle/handover.py:1151`
- **Description**: When Phase B fails after the final batch data marker commits, retry correctly skips the webhook and retries grants. On success it marks the action `done` and releases the lease, but never changes the failed final batch to `done` or calls `_complete_active_plan`. In a 413 plan this yields a completed action/task whose batch progress remains incomplete and whose final immutable batch ledger still says `failed`. This violates `01-easyauth-backend.md` §5.5's prescribed Phase C transition and `00-overview-and-contract.md` §10.5.1.1's idempotent resume semantics.
- **Suggested fix**: In the grant-only success transaction, lock the marked final batch, transition it to `done`, complete any active plan, then mark the action done and release the lease under the same fence.

### [ea-execute-conservation-06] MINOR (confirmed) Aggregated summaries are hidden while a multi-batch plan is in progress

- **File**: `src/easyauth/lifecycle/api_payloads.py:327`
- **Description**: A successful non-final batch persists its counters in `action.result_summary`, but intentionally leaves `action.status='previewed'` and `action.data_completed_at=NULL`. `aggregated_summary` returns `None` for exactly that state, so after batch 1 of N the API exposes progress but hides the accumulated result. This violates `00-overview-and-contract.md` §10.5, which requires the UI total during batching to be the per-field sum of completed batch summaries.
- **Suggested fix**: Return a nonempty persisted `result_summary` for partially completed active plans; do not gate it on final action status or the action-level final-batch marker.

### [ea-execute-conservation-07] MINOR (confirmed) Conservation validation accepts summaries that are not the frozen five-tuple

- **File**: `src/easyauth/lifecycle/handover.py:829`
- **Description**: Each counter is read with `row.get(field, 0)`, so omitted fields are silently treated as zero; Python booleans also pass the `isinstance(val, int)` check. For a preview count of 9, `{"transferred": 9}` or `{"transferred": 9, "failed": false}` is accepted and the action can become done without the downstream having supplied the required five counters. This violates `00-overview-and-contract.md` §10.5, which freezes the response as exactly `transferred`, `released`, `skipped`, `merged`, and `failed`, with nonnegative integer counts.
- **Suggested fix**: Require the row key set to equal the frozen five-field set and validate each value with `type(value) is int` and `value >= 0`.

## 分片 ea-fe-allocator — 5 条 (blocker 0 / major 5 / minor 0)

**Shard summary**: The reason extractor correctly reads `details.reason`, and every reason-specific branch in the allocator corresponds to a backend-emitted reason. Pagination uses the requested 50-item page size and the filtered `total` consistently. However, the allocator has multiple confirmed draft-loss and stale-state defects that can silently preserve, remove, or execute assignments contrary to the visible UI. The 412 teardown also fails to invalidate cached items and overrides, allowing prior-snapshot data to reappear after re-preview.

### [ea-fe-allocator-01] MAJOR (confirmed) Incomplete type-level transfer can execute the previous server assignment

- **File**: `frontend/src/features/handover/AssetAllocator.tsx:81`
- **Description**: Selecting `transfer` without a receiver, or clearing an existing receiver, only changes `localTypes` and returns without PATCHing, without calling `onActionUpdated`, and without marking the allocator busy. For example, if the server default is `skip`, the user can select transfer, leave the receiver empty, and immediately execute; the server validly executes the still-persisted `skip` assignment although the allocator shows transfer. Clearing an existing Bob receiver similarly leaves Bob persisted and executable. This violates 02 §6.1, which requires every type-level action or receiver change to be persisted immediately, requires a transfer receiver, and requires execution to stay disabled while the change is unresolved.
- **Suggested fix**: Treat the receiver-less transfer state as an explicit invalid draft: propagate it through `onBusyChange` or a validity callback so execution is disabled, and either prevent receiver clearing or restore the persisted value until a valid receiver can be PATCHed.

### [ea-fe-allocator-02] MAJOR (confirmed) Deleting an override is undone after changing page or search

- **File**: `frontend/src/features/handover/AssetAllocator.tsx:440`
- **Description**: Reverting an override to the type default deletes it from `drafts`, but leaves it in `fullOverrides`. If the user then navigates or searches so that the asset is no longer in `pageIds`, `fromOtherPages` reintroduces the original override and the PUT silently preserves it. Thus an override on page 1 that the user removed is resurrected when saving from page 2. This violates 02 §6.2's requirements that reverting to the default removes the override and that PUT submits the intended complete replacement collection.
- **Suggested fix**: Use one canonical full draft collection, or retain explicit deletion tombstones/dirty state across page and search changes; never infer that an absent draft should be restored from `fullOverrides`.

### [ea-fe-allocator-03] MAJOR (confirmed) Receiver-less transfer drafts are silently converted into override deletion

- **File**: `frontend/src/features/handover/AssetAllocator.tsx:450`
- **Description**: The save path silently filters out every transfer override without a receiver instead of rejecting the draft. If an existing per-item transfer override is cleared and Save is clicked, the entry is omitted from the complete-replacement PUT, so the server deletes it and the item unexpectedly falls back to the type default. A newly selected transfer is likewise reported through a successful PUT while never being saved. This violates 02 §6.1's required transfer receiver, 02 §6.2's complete-set save semantics, and the `receiver_required` contract in 01 §6.1.
- **Suggested fix**: Validate the complete draft set before PUT, disable Save or show an explicit receiver error while any transfer lacks a receiver, and never silently filter user-authored entries.

### [ea-fe-allocator-04] MAJOR (confirmed) Snapshot-stale cleanup leaves reusable React Query data behind

- **File**: `frontend/src/features/handover/AssetAllocator.tsx:323`
- **Description**: The 412 branches clear component state but do not remove or invalidate the items/overrides queries, whose keys contain neither generation nor snapshot identity. After the action is re-previewed with the same task/app/type, React Query can immediately supply the previous snapshot's cached overrides and items while background refetching; `canSubmit` also ignores `isFetching`, so the old complete set can be submitted before canonical data arrives. Moreover, refresh is delegated to an optional callback, so a consumer that omits it never performs the contract-required detail reload. This violates 02 §5.2's requirement to immediately clear that action's local items/overrides/confirmation state and reload details after `412 snapshot_stale`.
- **Suggested fix**: Centralize 412 handling: remove all affected items and overrides queries, reset the expanded allocator state, and require or internally perform the detail refresh. Include generation/snapshot identity in query keys or prevent submission until fresh post-preview queries complete.

### [ea-fe-allocator-05] MAJOR (confirmed) Edits remain enabled during PUT and are overwritten by the post-save refetch

- **File**: `frontend/src/features/handover/AssetAllocator.tsx:562`
- **Description**: While `saveMutation` is pending, the Save button is disabled but each item action and receiver control is disabled only by `readOnly`. A user can therefore make another edit after the request body has been captured. The PUT commits the earlier snapshot, and the success invalidation reloads that server snapshot into `drafts`, silently erasing the edit made during the request. This breaks the local override-set and explicit whole-replacement save behavior required by 02 §6.2.
- **Suggested fix**: Disable all item editors while the PUT is pending, or maintain a draft revision and rebase edits made after the submitted revision onto the returned canonical collection.

## 分片 ea-fe-panels — 5 条 (blocker 1 / major 2 / minor 2)

**Shard summary**: All nine backend action statuses have explicit panel branches, including the corrected async_attention_required behavior. The reassign flow keeps receiver selection in the detail view, and pre-offboard creation correctly uses a stable idempotency key and surfaces open_task_exists. However, the action panel still has an irreversible grant-receiver race, incomplete stale-snapshot cleanup, and an unprotected batch-preview submission path. Done summaries and confirm-version conflict recovery also violate the frozen rendering and recovery contract.

### [ea-fe-panels-01] BLOCKER (confirmed) Execute can race a pending grant-receiver update and transfer permissions to the old recipient

- **File**: `frontend/src/features/handover/HandoverActionPanel.tsx:297`
- **Description**: Selecting a new grant receiver starts grantReceiverMutation, but the execute button is not disabled by grantReceiverMutation.isPending. If the user immediately confirms execution and execute reaches the server before the PATCH, the old confirm_version is still valid and execution begins with the old or null grant receiver; the later PATCH is then rejected because execution is in flight. This creates an irreversible permission handover that contradicts the user's visible selection and violates §4's confirm_version invariant and §5.2's irreversible-execution confirmation contract.
- **Suggested fix**: Introduce an action-wide mutation lock: disable preview, execute, allocator edits, and confirmation while the grant-receiver PATCH is pending, and disable the receiver picker while any allocator mutation is pending. Only enable execute after the updated action and confirm_version have been applied.

### [ea-fe-panels-02] MAJOR (confirmed) 412 recovery leaves stale item and override state mounted

- **File**: `frontend/src/features/handover/HandoverActionPanel.tsx:523`
- **Description**: When execute or preview returns snapshot_stale, handleActionError only closes the confirmation, shows a banner, and requests a task refresh. It does not clear the action's cached item queries, expanded allocator, drafts, or override state; because the allocator remains mounted under the same query keys, stale items and unsaved assignments can survive the refresh and be shown or submitted after re-preview. This violates §5.2's 412 requirement to immediately clear local items, overrides, and confirmation state before reloading.
- **Suggested fix**: Reset or remount the allocator for the affected action and remove/invalidate its item and override queries before refreshing. Do not allow re-preview or editing until the fresh action has replaced the stale state.

### [ea-fe-panels-03] MAJOR (confirmed) Next-batch preview allows concurrent submissions and stale confirm-version overwrite

- **File**: `frontend/src/features/handover/HandoverActionPanel.tsx:281`
- **Description**: The next-batch button invokes previewMutation but has neither loading={previewMutation.isPending} nor a disabled check for that mutation. A double click, or clicking it while the adjacent re-preview is pending, sends concurrent previews; because every successful preview increments confirm_version, out-of-order responses can replace a newer action with an older version and then open confirmation for a token the server has already superseded. Execution consequently fails with 409 instead of advancing the batch, violating §5.2's preview-then-execute batch flow and the §4 confirm_version contract.
- **Suggested fix**: Disable every preview trigger while previewMutation is pending, render the next-batch button from allowed_actions, and open confirmation only for the single preview response whose updated action has been installed.

### [ea-fe-panels-04] MINOR (confirmed) Done summaries can be blank and permanently hide required zero-valued fields

- **File**: `frontend/src/features/handover/HandoverActionPanel.tsx:315`
- **Description**: A done action with summary=null renders no completion body, and summary={} renders an empty list. For a non-empty summary where merged and failed are both zero, both fields are omitted permanently with no disclosure control. This violates §5.2's done-state requirement to render the five-field per-type summary and its explicit rule that zero merged/failed fields may be collapsed but must not be hidden.
- **Suggested fix**: Render an explicit empty-summary state for null or empty summaries, and always expose all five fields—either directly or through a real expandable summary control.

### [ea-fe-panels-05] MINOR (confirmed) 409 confirm-version recovery re-enables confirmation before fresh state arrives

- **File**: `frontend/src/features/handover/HandoverActionPanel.tsx:536`
- **Description**: On confirm_version_stale, the handler starts an asynchronous refresh but immediately keeps or sets the confirmation dialog open. Once the failed mutation leaves pending state, its button is enabled against the still-stale action, so a quick second confirmation resubmits the same obsolete confirm_version and receives another 409. This violates §5.2's requirement that version conflicts automatically reload the current action before the user proceeds.
- **Suggested fix**: Close and disable confirmation on the conflict, await installation of the refreshed action, and require a new confirmation using that action's confirm_version.

## 分片 ea-lease-async — 4 条 (blocker 0 / major 3 / minor 1)

**Shard summary**: The lease primitives generally enforce owner/fence predicates, but the manual async-resolution path can share another worker's live fence and commit competing writes. Manual resolution also incorrectly promotes non-final split batches to final, allowing partial handovers to be recorded as complete. Recovery-side payload conflicts have no usable manual exit and leave the lease cycling indefinitely. The 30-minute attention backoff is not enforced by poll_async_action itself, so direct/manual polling bypasses the frozen cadence.

### [ea-lease-async-01] MAJOR (confirmed) Manual async resolution can adopt a poller's live fence and commit competing writes

- **File**: `src/easyauth/lifecycle/handover.py:1033`
- **Description**: For outcome=done with a batch, async_abandon_action releases its initial locks without claiming the lease or changing its fence, then rereads the active row and constructs a handle from whatever owner/fence is currently stored. Concrete race: a poller claims the sentinel and starts its GET; the administrator then copies that poller's owner/fence and starts complete_data_phase. Before either reaches transaction C and releases the lease, both phase-A transactions can pass require_cas using the same handle, merge different summaries, and both may enter grant transfer. One final release fences the loser only after earlier committed mutations, permitting double-counted summaries or duplicate authorization work. This violates §2.4.2's requirement that every execution writer have exclusive owner/fence authority and that stale/competing responses be discarded.
- **Suggested fix**: In the initial locked transaction, CAS-transfer the lease to a unique manual-resolution owner with a new fence and retain that returned handle across complete_data_phase. Never reconstruct a handle by copying the current database owner/fence.

### [ea-lease-async-02] MAJOR (confirmed) Manual completion turns a non-final split batch into the final batch

- **File**: `src/easyauth/lifecycle/handover.py:1022`
- **Description**: async_abandon_action unconditionally changes batch.is_final to true before completing a manually confirmed batch. If batch 1 of a multi-batch 413 plan reaches async_attention_required, confirming it as done causes complete_data_phase to set the action done, run final grant transfer, and mark the active plan fully complete even though later chunks were never executed. The user sees a completed handover while assets in remaining batches retain their old ownership. This violates §2.4.1.1, which requires non-final successful batches to return the action to previewed and permits action completion only after the genuine final batch succeeds.
- **Suggested fix**: Preserve the immutable batch.is_final value. Let complete_data_phase follow the normal non-final path, including progress increment, lease release, and return to previewed for the next batch.

### [ea-lease-async-03] MAJOR (confirmed) Recovery payload conflicts cannot reach the required manual-resolution exit

- **File**: `src/easyauth/lifecycle/handover.py:2031`
- **Description**: When replay of an expired execution receives HTTP 409, takeover_expired_lease only records an event and retains the lease; it does not move the action to async_attention_required. The action therefore commonly remains executing, while async_abandon_action rejects every manual resolution because it accepts only async_attention_required. After each renewed lease expires, recovery replays again and receives the same conflict, producing an indefinite retry/lease lock cycle with no operator exit. This violates §2.4.2's 409 payload-conflict handling and §7's explicit requirement that this conflict use the same manual outlet as async_attention_required.
- **Suggested fix**: Under the recovered fence, atomically mark the action async_attention_required, persist the conflict state, and hand the renewed lease to the appropriate sentinel so async-abandon becomes available without releasing mutual exclusion.

### [ea-lease-async-04] MINOR (confirmed) The attention-state 30-minute backoff is bypassable at the polling entry point

- **File**: `src/easyauth/lifecycle/handover.py:247`
- **Description**: poll_async_action accepts async_attention_required and immediately claims the lease and issues a GET without checking the last renewal/poll time. The only gate in this file is inside takeover_expired_lease, so a manual console poll or any direct caller can invoke poll_async_action repeatedly, renew the sentinel each time, and poll once per request rather than at most once per 30 minutes. This violates §7's requirement that attention-state polling use ASYNC_ATTENTION_POLL_INTERVAL=30 minutes and defeats the intended 48-polls-per-day ceiling.
- **Suggested fix**: Enforce the attention cutoff atomically inside poll_async_action before claiming the sentinel. Callers may prefilter for efficiency, but the state-transition function must remain the authoritative gate.

## 分片 ea-manifest-apps — 5 条 (blocker 1 / major 4 / minor 0)

**Shard summary**: The EasyAuth lifecycle whitelist correctly accepts and preserves handover_asset_types, and the endpoint enforces both request-body and parsed-template size limits. Normal validation and unsafe webhook URL failures map to 422, but concurrent manifest imports can bypass the intended idempotent/conflict mapping. The corrected capability conflict row is broken when the prior capability is none, allowing actions to remain silently skipped. Capability synchronization also bypasses the updated_by ownership guard, including a separate check-then-save race with console updates. Removing lifecycle entirely leaves stale declared capability state instead of transitioning to undeclared.

### [ea-manifest-apps-01] BLOCKER (confirmed) Conflicting capabilities remain silently skipped when the previous state is none

- **File**: `src/easyauth/applications/handover_capability.py:50`
- **Description**: When an App previously has handover_capability='none' and a new descriptor contains both handover.v2 and handover.none, the conflict audit is written but lines 61-70 deliberately avoid changing the capability. A subsequently created action therefore follows the retained none state and starts skipped, allowing the task to complete without handover. This violates §9.1 conflict row 1, which requires every conflicting descriptor to be blocked and audited, regardless of prior state, with no silent fallback.
- **Suggested fix**: Always transition a conflicting descriptor to undeclared/blocked state, including from none; preserve the conflict audit but do not preserve the prior none capability.

### [ea-manifest-apps-02] MAJOR (confirmed) Removing lifecycle leaves stale declared capability state

- **File**: `src/easyauth/applications/permission_templates.py:77`
- **Description**: Capability synchronization is invoked only when template.lifecycle is non-null. If version N declared handover.v2 and version N+1 removes lifecycle, _sync_webhook_config_from_manifest clears manifest-owned handover_url, but App.handover_capability remains declared. New task creation then encounters declared capability with no effective hook URL and raises instead of creating a blocked action; with a console-owned retained URL it can instead create a pending action despite the descriptor no longer declaring v2. This violates §9.1 row 4, where all other descriptor states, including absence of the declaration, must be undeclared and blocked.
- **Suggested fix**: Invoke capability synchronization for every imported manifest, representing an absent lifecycle as an empty declaration so declared transitions to undeclared while preserving the documented special handling for an existing operational none declaration.

### [ea-manifest-apps-03] MAJOR (confirmed) Capability synchronization deterministically overwrites console-owned webhook configuration

- **File**: `src/easyauth/applications/handover_capability.py:86`
- **Description**: apply_permission_template first calls the updated_by-aware webhook synchronizer, which correctly returns for a console-owned configuration. It then calls sync_handover_capability_from_manifest, whose lines 86-90 fetch the same configuration and unconditionally replace handover_url and set enabled=True whenever the manifest URL differs, without examining updated_by. Thus an authenticated app manifest push can overwrite an administrator's explicit destination and re-enable delivery, potentially redirecting handover payloads, while updated_by still falsely identifies the administrator. This violates the §9.1 descriptor synchronization ownership semantics that console configuration overrides manifest-derived configuration.
- **Suggested fix**: Remove webhook configuration mutation from sync_handover_capability_from_manifest and use only the guarded synchronization path, or enforce the identical updated_by ownership guard without changing enabled for console-owned rows.

### [ea-manifest-apps-04] MAJOR (confirmed) The updated_by ownership guard has a check-then-save race

- **File**: `src/easyauth/applications/permission_templates.py:118`
- **Description**: The manifest path reads AppWebhookConfig and checks updated_by without locking the row, performs URL/DNS work, and later saves URL fields plus updated_by='manifest'. A concurrent console update can read the same manifest-owned row, save an administrator URL and owner first, and then have those changes overwritten by the stale manifest object at lines 145-149. The final row loses both the administrator's destination and ownership marker, violating the §9.1 console-override ownership semantics and creating a webhook redirection race.
- **Suggested fix**: Serialize both manifest and console configuration updates with select_for_update in transactions using a consistent lock order, and perform the ownership check only after acquiring the configuration-row lock.

### [ea-manifest-apps-05] MAJOR (confirmed) Concurrent same-version imports return 422 instead of idempotent success or 409 conflict

- **File**: `src/easyauth/applications/manifest_import.py:64`
- **Description**: sync_app_manifest reads the latest PermissionTemplateVersion before the App row is locked. Two concurrent version-2 pushes can both observe version 1; the first imports version 2, while the second later acquires the App lock inside apply_permission_template and raises PermissionTemplateImportError for the now-duplicate version. manifest_sync_views maps that error to 422. Identical content should return already_up_to_date=true, while different content at the same version should return 409 ManifestVersionConflictError; the race violates the manifest version/idempotency behavior required for the §14 descriptor synchronization integration gate.
- **Suggested fix**: Acquire the App row lock before reading the latest template and perform the version-plus-content-hash decision inside that same critical section; return the idempotent outcome or raise ManifestVersionConflictError there rather than relying on the later duplicate-version rejection.

## 分片 ea-offboard-upgrade — 5 条 (blocker 0 / major 3 / minor 2)

**Shard summary**: Upgrade orchestration correctly locks existing actions, rejects unreleased leases, advances the generation, resets generation-scoped fields, re-evaluates capability states, and re-inventories grants and applications. The current grant-transfer call paths execute inside transactions and lock action/item rows; I found no confirmed partial-commit defect there. However, assignment mutations can diverge from already-frozen batch plans, directory reconciliation can be permanently blocked by one user's offboarding conflict, and concurrent idempotency-key conflicts are not translated to the frozen API contract. Two assignment-shape paths also expose database constraint failures as HTTP 500 responses.

### [ea-offboard-upgrade-01] MAJOR (confirmed) Assignment mutations are allowed while a retryable pending batch contains an older canonical payload

- **File**: `src/easyauth/lifecycle/assignments.py:194`
- **Description**: `_assert_mutable()` calls `action_execution_in_flight()`, whose contract intentionally excludes `pending` batches. After a downstream 429, the lease is released and the batch returns to `pending` for retry; a user can then change defaults or overrides successfully. The retry path reuses the batch's original canonical payload, so data can be transferred according to the old recipient/action even though the current database and UI show the new assignment. This violates frozen contract §2.4.1.1, which requires assignment mutations to treat `pending`, `executing`, and `async_pending` batches as in-flight, and §5.5's canonical-payload immutability.
- **Suggested fix**: Use `assignment_mutation_in_flight()` for assignment endpoints so a pending retry batch returns `409 handover_execution_in_flight` before any assignment row or version is changed.

### [ea-offboard-upgrade-02] MAJOR (confirmed) Changing assignments leaves a zero-progress 413 batch plan active and silently reuses its stale chunks

- **File**: `src/easyauth/lifecycle/assignments.py:200`
- **Description**: The mutation guard rejects an active batch plan only when `completed_batches > 0`; when it is zero, the mutation succeeds without abandoning or rebuilding the plan. Concrete scenario: a 413 creates a plan whose chunks omit an override currently set to `skip`; before any chunk completes, the user changes that override to `transfer`. The next execute retrieves the old active plan, and `_chunk_assignments()` omits the newly transferred asset because its ID is absent from the frozen chunks, allowing the action to complete without performing the current assignment. This violates frozen contract §2.4.1.1: zero-progress plans may be edited only if the old plan is abandoned and replanned atomically using the new canonical assignment hash.
- **Suggested fix**: Within the action-locked mutation transaction, mark any active zero-progress plan `abandoned` and create a replacement plan from the updated assignments, or invalidate it so execute must replan before sending.

### [ea-offboard-upgrade-03] MAJOR (confirmed) One offboarding conflict rolls back the entire directory reconciliation round

- **File**: `src/easyauth/integrations/authentik/directory_sync.py:599`
- **Description**: All users are reconciled inside one outer transaction and `start_offboarding()` is called without per-user error isolation. If departing user A has an open `transfer` task, `ensure_handover_task()` raises a kind conflict; that exception rolls back A's status/revocation and every earlier or later user's status, revocations, tasks, and sync-state advancement. Subsequent runs encounter the same conflict, so unrelated departing user B can remain active and authorized indefinitely. This violates frozen contract §3's requirement that automatic offboarding tasks must not be lost because resolution or orchestration fails, as well as the task-creation/state orchestration requirement for directory-detected departures.
- **Suggested fix**: Isolate each user's status/offboarding unit with an explicit savepoint or separately committed orchestration unit, persist and surface the failing identity for retry, and ensure one identity's task-kind conflict cannot roll back unrelated departures.

### [ea-offboard-upgrade-04] MINOR (confirmed) Concurrent reuse of an idempotency key for different subjects returns an unhandled database error instead of 409

- **File**: `src/easyauth/lifecycle/offboarding.py:94`
- **Description**: The service first queries the idempotency key and later performs a plain `create()`. Subject-row locking serializes requests for the same subject, but two concurrent reassign requests from the same initiator using the same key and different subjects lock different rows and can both observe no key record. The unique constraint rejects the loser with `IntegrityError`, which is not caught or translated to `idempotency_conflict`; the request therefore becomes a 500 rather than the required 409. This violates frozen contract §6.1, which requires `(initiator, idempotency_key)` concurrency to be resolved by the database constraint and same-key/different-body requests to return `409 idempotency_conflict`.
- **Suggested fix**: Perform creation in a savepoint, catch the unique-key `IntegrityError`, refetch by `(created_by, creation_idempotency_key)`, compare the canonical body hash, and return the existing task or raise `HandoverConflictError("idempotency_conflict")`.

### [ea-offboard-upgrade-05] MINOR (confirmed) Non-transfer assignments with a receiver reach database constraints and produce HTTP 500

- **File**: `src/easyauth/lifecycle/assignments.py:72`
- **Description**: Both `patch_asset_type_defaults()` and `put_overrides()` resolve and retain a supplied receiver when the action is `skip` or `release`. The model constraints require receivers to be null for every non-`transfer` action, so a valid active receiver combined with `default_action="skip"` or an override `action="release"` causes an uncaught `IntegrityError` during save/create rather than a contract validation response. This violates frozen contract §2.3/§2.4's assignment-shape invariant and §5.4's execute/API validation boundary.
- **Suggested fix**: Reject a non-null receiver for non-transfer actions with a domain validation error, or canonicalize it to null only if the frozen API contract explicitly defines that behavior; do not let the database constraint become the request validator.

## 分片 ea-payload-models — 4 条 (blocker 0 / major 4 / minor 0)

**Shard summary**: The core enum widths, conditional uniqueness scopes, and child-side PostgreSQL triggers mostly match the frozen contract. Four invariant gaps remain: a normal preview can bypass the override/releasable trigger, manual async resolution can expose an invalid summary shape, and two audit-record state machines lack database enforcement. These defects can leave invalid assignment data or silently corrupt the API and permanent execution history.

### [ea-payload-models-01] MAJOR (confirmed) Override releasability trigger misses parent-side updates

- **File**: `src/easyauth/lifecycle/migrations/0006_handover_v2_schema.py:112`
- **Description**: The constraint trigger runs only when a HandoverAssetOverride's action or asset_type_id changes. Concrete scenario: an existing override has action='release' while its parent type is releasable=true; a later preview preserves the override but updates HandoverAssetType.releasable to false. No override event fires, so the transaction commits an invalid release assignment that the documented database invariant was required to reject. This violates 01-easyauth-backend.md §5.4 and §2.4.
- **Suggested fix**: Add a deferred constraint trigger on HandoverAssetType UPDATE OF releasable that rejects releasable=false whenever a release override exists, while retaining the child-side trigger.

### [ea-payload-models-02] MAJOR (confirmed) Manual async completion leaks a non-contract summary object

- **File**: `src/easyauth/lifecycle/api_payloads.py:327`
- **Description**: aggregated_summary returns any non-empty result_summary dictionary without validating the frozen five-counter shape. The async-abandon done path used by the frontend submits summary=null and stores {'manual_resolution': true} when no prior summary exists; action detail then returns summary={'manual_resolution': true}. The frontend treats manual_resolution as an asset type and reads missing transferred/released/skipped/merged/failed fields, while a multi-batch action may instead expose only earlier batches as if they were the final total. This violates 00-overview-and-contract.md §10.5 and 01-easyauth-backend.md §6.2/§6.3.
- **Suggested fix**: Keep summary null when manual resolution supplies no counts and record manual-resolution metadata separately. Strictly validate result_summary before serialization so every asset row contains exactly the frozen five non-negative counters.

### [ea-payload-models-03] MAJOR (confirmed) Delivery terminal outcomes are mutable despite the single-transition contract

- **File**: `src/easyauth/lifecycle/models.py:768`
- **Description**: The schema checks only that outcome is an allowed value and that a terminal row has some evidence; it does not enforce sent -> terminal exactly once or prevent later edits. For example, after a succeeded delivery is recorded, HandoverDeliveryAttempt.objects.filter(...).update(outcome='failed', error_text='retry error') succeeds and silently rewrites the authoritative execution history. This violates 01-easyauth-backend.md §2.4.1, which requires one controlled transition and forbids all modification after a terminal outcome.
- **Suggested fix**: Install a PostgreSQL transition trigger that permits only sent -> succeeded|failed|async_accepted|superseded and rejects every update to an already-terminal row.

### [ea-payload-models-04] MAJOR (confirmed) Permanent skip records are not append-only and do not protect their task

- **File**: `src/easyauth/lifecycle/models.py:513`
- **Description**: HandoverActionSkipRecord has no update/delete guard, and its SET_NULL task foreign key permits HandoverTask.delete() even when skip history exists. A maintenance or future bulk path can therefore edit/delete the actor or reason, or delete the task and make its supposedly permanent responsibility chain inaccessible through task detail; only the current service-level delete helper prevents the latter. This violates 01-easyauth-backend.md §2.2.1 and §6.2, which define the records as append-only and prohibit deletion of tasks carrying skip history.
- **Suggested fix**: Add database triggers that reject HandoverActionSkipRecord UPDATE/DELETE and reject HandoverTask deletion whenever a matching task_id_snapshot exists.

## 分片 ea-portal-api — 8 条 (blocker 0 / major 5 / minor 3)

**Shard summary**: The common active-session guard, explicit local-admin rejection, anti-enumeration 404 checks, reason table, and 412/413/423 mappings are correctly implemented. Execute-time 413 responses also refresh the action and include batch_progress as required. However, authorization is not atomic with action mutations, and reassign creation has a post-commit assignee correction that can permanently leave the wrong user in control. Additional confirmed defects affect override replacement, grant-receiver validation, concurrent idempotency, replay status codes, pagination validation, and override read consistency.

### [ea-portal-api-01] MAJOR (confirmed) A revoked assignee can win a TOCTOU race and execute a handover

- **File**: `src/easyauth/portal/handover_api.py:739`
- **Description**: _action_for_user reads the task, checks the assignee and current manager scope, and then returns an action without retaining any task or directory-context lock. The mutation helpers subsequently lock only the action and do not repeat authorization. For example, A can pass the check for a reassign task, then directory synchronization can revoke A's scope and another request can move the task to superuser_pool, after which A's already-authorized execute request still creates a batch and sends the transfer webhook. This violates §6.1's requirement to recheck current reassign jurisdiction after assignee validation and fail closed before every mutation.
- **Suggested fix**: Move assignee and jurisdiction verification into each mutation/reservation transaction. Lock the task before the action, verify the current assignee and authoritative directory context while locked, and reserve or apply the mutation before releasing those locks.

### [ea-portal-api-02] MAJOR (confirmed) Reassign creation exposes a committed task with the wrong assignee

- **File**: `src/easyauth/portal/handover_api.py:282`
- **Description**: ensure_handover_task commits the new task using resolve_assignee(subject), and only after that transaction returns does the view replace the assignee with the reassign initiator. If an upper-chain manager A creates a task for B whose direct manager is C, the task is temporarily committed with C as assignee. A process failure in that window leaves C permanently assigned; an idempotent retry returns created=False and skips the correction entirely. Concurrently, C can also pass assignee-only guards and mutate the task before A's unlocked apply_assignee call overwrites it. This violates §6.1's reassign ownership and assignee-only authorization contract.
- **Suggested fix**: Pass the initiator's AssigneeResolution into the creation service and persist it inside the original task-creation transaction. Remove the post-commit apply_assignee call.

### [ea-portal-api-03] MAJOR (confirmed) PUT overrides silently drops duplicate and contract-invalid assignments

- **File**: `src/easyauth/portal/handover_api.py:398`
- **Description**: OverrideItemPayload accepts any action string of length 1–8 and the endpoint performs no duplicate asset_id check. The called replacement service deletes the old override set, keeps the first duplicate, and silently counts later duplicates or invalid actions as dropped_invalid before returning 200. Thus a request containing two entries for the same asset, or action="garbage", can partially erase the previous complete set while reporting success. Section §6.1 restricts action to transfer/release/skip and explicitly requires duplicate assignments to return 422 with details.reason="duplicate_assignment".
- **Suggested fix**: Validate the entire replacement before deleting anything: use an action enum, reject duplicate asset_id values with reason_error("duplicate_assignment"), and ensure the domain service also fails atomically rather than dropping invalid entries.

### [ea-portal-api-04] MAJOR (confirmed) An omitted grant_receiver field silently clears the configured receiver

- **File**: `src/easyauth/portal/handover_api.py:124`
- **Description**: GrantReceiverPayload gives grant_receiver_user_id a default of None, so PATCH with body {} is accepted as an explicit clear. On an offboard action with an existing receiver, this clears the receiver, increments confirm_version, and resets preview state instead of returning 422. A malformed client request can therefore convert the eventual grant step into revoke-only behavior. This violates the frozen PATCH body shape in §6.1, where grant_receiver_user_id must be explicitly supplied as either a string or null.
- **Suggested fix**: Make grant_receiver_user_id required-but-nullable by removing its default. Reserve explicit null for intentional clearing.

### [ea-portal-api-05] MAJOR (confirmed) Concurrent cross-subject reuse of an idempotency key returns 500

- **File**: `src/easyauth/portal/handover_api.py:264`
- **Description**: The creation service serializes on the subject row before checking the initiator/key pair. If one manager concurrently submits the same Idempotency-Key for two different valid managed subjects, the requests lock different rows and can both observe no existing key. One insert then loses the unique-constraint race and raises django.db.IntegrityError, which this endpoint does not catch, producing a 500 instead of 409 idempotency_conflict. This violates §6.1's same-key/different-body rule and its explicit requirement that the database uniqueness constraint safely handle concurrent creation.
- **Suggested fix**: Serialize or reserve idempotency by initiator/key independently of the subject. Alternatively, catch the unique violation outside the failed transaction, load the winning task, compare the canonical hash, and return the original task or idempotency_conflict.

### [ea-portal-api-06] MINOR (confirmed) Successful idempotent creation replays return the wrong status code

- **File**: `src/easyauth/portal/handover_api.py:214`
- **Description**: Both creation handlers return 200 whenever ensure_handover_task reports created=False. An exact Idempotency-Key/body replay therefore returns the original task with 200, while §6.1 freezes both POST creation success codes as 201.
- **Suggested fix**: Return 201 for successful creation replays as well as first-time creation, while retaining 409 for a hash conflict.

### [ea-portal-api-07] MINOR (confirmed) Malformed page values are silently converted to page 1

- **File**: `src/easyauth/portal/handover_api.py:339`
- **Description**: _parse_int returns the default for non-integer input. Consequently, page=abc is converted to page 1 and sent to the downstream items webhook, returning 200 if the webhook succeeds. Section §6.1 requires invalid or out-of-range page values to be rejected before downstream dispatch with 422 and details.reason="items_page_out_of_range"; only page_size may be clamped.
- **Suggested fix**: Parse page strictly and return reason_error("items_page_out_of_range") on conversion failure or range violation. Keep clamping limited to page_size.

### [ea-portal-api-08] MINOR (confirmed) GET overrides can pair a new override set with a stale version

- **File**: `src/easyauth/portal/handover_api.py:374`
- **Description**: The action and its overrides are read in separate statements without a lock or coherent snapshot. If GET loads action.overrides_version=7, a concurrent PUT commits replacement rows and version 8, and GET then queries the rows, the response contains the version-8 set labeled as overrides_version=7. The next save predictably fails with overrides_version_stale even though the user just loaded the data. This violates §6.1's requirement that GET return the current generation's complete override collection together with its corresponding version.
- **Suggested fix**: Read the action version and override rows under one synchronization scheme, such as locking the action in a transaction shared with PUT, or retrying the read if the version changes.

## 分片 ea-sdk — 4 条 (blocker 0 / major 2 / minor 2)

**Shard summary**: Timing-safe HMAC comparison, case-insensitive header lookup, bounded streaming reads, and the pre-short-circuit webhook.test event check are correctly implemented. The required items callback and packaged contract samples also match the frozen API shapes. Four contract-boundary defects remain: signature failures can be configured as successful responses, malformed callback results can produce false success or unstable errors, null asset declarations bypass validation, and signed malformed payloads are misclassified as authentication failures.

### [ea-sdk-01] MAJOR (confirmed) signature_failure_status permits successful authentication-failure responses

- **File**: `sdk/python/src/easyauth_app_sdk/lifecycle.py:159`
- **Description**: The parameter is returned without validating that it is 401 or 403. With signature_failure_status=200 and an invalid HMAC, lifecycle_http_response returns HTTP 200 containing an error object; because the frozen response contract uses HTTP status as the normative success signal, EasyAuth can treat an unauthenticated handover response as successful. This violates the SDK contract §8 item 6.2 and the overview §10.6 requirement that signature failures return only 401/403.
- **Suggested fix**: Reject values outside {401, 403}, preferably when constructing the framework router and defensively inside lifecycle_http_response.

### [ea-sdk-02] MAJOR (confirmed) Malformed callback results escape the fixed-error boundary or return false success

- **File**: `sdk/python/src/easyauth_app_sdk/lifecycle.py:203`
- **Description**: Only the callback invocation is inside the exception boundary; result validation and _json_response run afterward. A callback that accidentally omits return produces HTTP 200 with body null, while a result containing a non-JSON-serializable value raises an uncaught TypeError and delegates the response shape to the web framework. The former can mark preview or execute successful without the required assets/summary, and the latter breaks stable error rendering, violating SDK contract §8 items 6.1 and 7.
- **Suggested fix**: Require the callback result to be a dict, serialize it inside the protected boundary, and convert invalid or unserializable results to the fixed 500 handover_callback_failed response while logging the underlying error.

### [ea-sdk-03] MINOR (confirmed) Explicit null handover_asset_types bypasses manifest validation

- **File**: `sdk/python/src/easyauth_app_sdk/manifest.py:119`
- **Description**: The validator uses lifecycle.get(), so an absent field and an explicitly present null are indistinguishable and both return successfully. A descriptor containing handover_asset_types:null is therefore certified by the SDK even though §9.1 defines this field as an array and requires [] for handover.none; the authoritative EasyAuth parser can subsequently reject the descriptor or classify its capability as malformed.
- **Suggested fix**: Return only when the key is absent; when present, read lifecycle["handover_asset_types"] and require a list, including rejecting null.

### [ea-sdk-04] MINOR (confirmed) Validly signed malformed payloads are reported as signature failures

- **File**: `sdk/python/src/easyauth_app_sdk/lifecycle.py:172`
- **Description**: verify_webhook raises reason INVALID_PAYLOAD after a valid HMAC when the body is invalid JSON or a non-object JSON value, but lifecycle_http_response routes every non-timestamp reason through signature_failure_status. For example, a correctly signed [] receives 401/403 and is classified as a non-retryable secret problem instead of an invalid request, potentially hiding retry after the sender is corrected. This violates SDK contract §8 item 6.2 and overview §10.6, where 401/403 are reserved for signature failures and malformed requests map to 400.
- **Suggested fix**: Handle REASON_INVALID_PAYLOAD separately as HTTP 400 with a stable payload-invalid code; reserve signature_failure_status for missing authentication headers and signature mismatch.

## 分片 ea-webhooks-net — 6 条 (blocker 0 / major 5 / minor 1)

**Shard summary**: Signing canonicalization is correct: event_type is injected before serialization, and the exact deterministic body bytes are signed and reused for downstream raw-body hashing. HTTPS connections are pinned to validated IP addresses, and redirects are not followed. However, the E2E exception can be activated in the public deployment and permits non-loopback private addresses. Error-response evidence, 429 backoff metadata, retry classification, and retry timing also violate the frozen contract.

### [ea-webhooks-net-01] MAJOR (confirmed) The E2E loopback exception can become a production SSRF escape

- **File**: `src/easyauth/config/net.py:137`
- **Description**: The exception is gated only by settings.DEBUG plus EASYAUTH_E2E_ALLOW_INSECURE_WEBHOOK_HOSTS. The repository's public deploy configuration sets DJANGO_DEBUG=1, so adding the E2E variable there activates plaintext HTTP in production. Worse, _e2e_resolve_addresses accepts any literal IP for which is_private is true, including RFC1918 and 169.254.169.254, rather than only loopback. For example, allowing 169.254.169.254 and configuring http://169.254.169.254/latest/meta-data/ causes the transport to connect directly to the metadata endpoint. This violates §10.1's HTTPS transport requirement and the stated E2E-only security boundary.
- **Suggested fix**: Require an explicit test-runtime marker that production settings reject at startup, and accept only ip.is_loopback for E2E literal addresses. Do not use DEBUG as the production exclusion.

### [ea-webhooks-net-02] MAJOR (confirmed) Non-2xx response bodies are discarded before whitelist extraction and redaction

- **File**: `src/easyauth/webhooks/hooks.py:134`
- **Description**: _parse_hook_response raises HookCallError immediately for every non-2xx response and preserves only the status code. Consequently, a 409 body such as {"detail":{"code":"USER_NOT_FOUND","message":"...","traceId":"..."}} never reaches code/message/traceId extraction, and neither its SHA-256 nor a redacted 2000-byte projection can be recorded. Non-JSON error bodies are likewise lost. This violates §10.6 item 2, including its last_error, last_error_raw, and delivery-ledger evidence requirements.
- **Suggested fix**: Carry the bounded response bytes or a centrally redacted error projection in HookCallError, parse both supported error envelopes before raising, and persist only the §10.6 whitelist, hash, lengths, and redacted projection.

### [ea-webhooks-net-03] MAJOR (confirmed) 429 responses cannot honor Retry-After

- **File**: `src/easyauth/webhooks/hooks.py:135`
- **Description**: WebhookHttpResponse exposes only status, body, and Location, while _parse_hook_response converts 429 directly into HookCallError. Retry-After is never captured or parsed anywhere. Thus an APP returning 429 with Retry-After: 120 causes preview/items to fail immediately and execute to return to previewed without scheduling the required delayed retry. This violates the 429 row of §10.6, which requires event-specific handling and backoff according to Retry-After.
- **Suggested fix**: Expose Retry-After from the transport, validate and cap it, and propagate it through HookCallError or HookResponse so each event path can schedule the contractually required retry.

### [ea-webhooks-net-04] MAJOR (confirmed) Asynchronous delivery retries contractually terminal HTTP statuses

- **File**: `src/easyauth/webhooks/delivery.py:178`
- **Description**: Every non-2xx response is passed to the same _mark_attempt_failed path. A 401, 403, 409, 412, 413, or 422 therefore schedules further deliveries until exhaustion, even though §10.6 marks these statuses non-retryable. A webhook.test request rejected with 422, for example, is sent four additional times. The same state machine also ignores Retry-After for 429, and its fifth configured delay of 21600 seconds is unreachable because the fifth failed attempt is exhausted before that delay is scheduled.
- **Suggested fix**: Classify responses by status before scheduling: terminate immediately for non-retryable statuses, implement the special 412/413/423/429 semantics, and define max attempts as one initial attempt plus the number of reachable retry delays.

### [ea-webhooks-net-05] MAJOR (confirmed) Late-ack task redelivery can bypass persisted backoff and exhaust attempts early

- **File**: `src/easyauth/webhooks/delivery.py:293`
- **Description**: A claim is authorized only by generation plus an empty lease; task arguments contain no expected attempt or not-before value. After a failed attempt commits, it clears the claim and schedules a countdown task. If the acks_late Celery worker dies before acknowledging the original task, the broker can immediately redeliver that stale task, which claims the now-empty row and retries without waiting. Previously scheduled tasks can then claim later attempts early, collapsing the backoff and prematurely exhausting a retryable delivery. This breaks the retry/backoff behavior required by §10.6, especially its Retry-After rule for 429.
- **Suggested fix**: Persist next_attempt_at and an expected attempt ordinal, include the ordinal in task arguments, and require both ordinal equality and next_attempt_at <= now in the claim CAS.

### [ea-webhooks-net-06] MINOR (confirmed) POST requests omit the frozen JSON charset parameter

- **File**: `src/easyauth/webhooks/hooks.py:74`
- **Description**: Both signed_hook_post and asynchronous delivery send Content-Type: application/json, while §10.1 freezes application/json; charset=utf-8. An APP that validates the documented media type can reject an otherwise valid signed request with 400 or 415. The body is UTF-8 encoded, so this is a wire-header contract mismatch rather than a serialization issue.
- **Suggested fix**: Set Content-Type to application/json; charset=utf-8 in both hooks.py and delivery.py.

## 分片 ep-commands — 7 条 (blocker 0 / major 5 / minor 2)

**Shard summary**: The collaborator/member merge paths generally delete the correct source relation, preserve existing attribution, and prevent assignees from remaining collaborators. Seven contract defects remain, including incorrect result accounting, an optional required activity, and several reminder rematerialization failures. The reminder defects can retain obsolete recipients or silently omit new occurrences. Outbox owner-CAS behavior is owned outside the listed files and was not independently assessed here.

### [ep-commands-01] MAJOR (confirmed) Owner promotion is incorrectly reported as merged

- **File**: `backend/app/domain/projects/handover.py:141`
- **Description**: When ownership moves from A to B and B already has a MEMBER row, the command deletes A's OWNER row, rewrites B's role to OWNER, but returns `(transferred=0, merged=1)`. This is not a delete-source-only merge: the target relationship and `projects.owner_dingtalk_user_id` are rewritten. It violates 08 §1.3 M13 and 00 §10.5, where `merged` is reserved for deleting the source relation without rewriting the target; the project-owned asset must contribute exactly one transferred unit.
- **Suggested fix**: Return `(1, 0)` when an existing MEMBER is promoted to OWNER; reserve `(0, 1)` for a genuine delete-source-only merge.

### [ep-commands-02] MAJOR (confirmed) Required task activity emission is optional

- **File**: `backend/app/domain/tasks/handover.py:164`
- **Description**: The frozen command can be called with its documented arguments while `activity_writer` remains `None`; personnel changes then commit without the required M11 ASSIGNMENT activity. Although the supplied writer uses a stable source reference and is idempotent, the command does not enforce its presence. This violates 08 §1.3 M10 and §2.6, which require exactly one system activity for every affected task.
- **Suggested fix**: Make the activity writer a required dependency of the command/service and always record the activity whenever any role changes.

### [ep-commands-03] MAJOR (confirmed) Queued reminders for former recipients are not superseded

- **File**: `backend/app/domain/reminders/handover.py:69`
- **Description**: The reconciliation query only loads PENDING and SKIPPED occurrences. If reminder enqueue has already changed an unsent occurrence for former assignee A to QUEUED, then handover A→B never sees or marks that row SKIPPED, leaving the obsolete delivery eligible to reach A. This violates 08 §1.1 and §1.3 M18, which require unsent obsolete occurrences to become SKIPPED with `HANDOVER_SUPERSEDED`.
- **Suggested fix**: Include every contract-defined unsent state in reconciliation and coordinate cancellation of any already-created notification outbox entry so superseding the occurrence actually prevents delivery.

### [ep-commands-04] MAJOR (confirmed) Truncated ad-hoc reminder dedup keys can silently drop recipients

- **File**: `backend/app/domain/reminders/handover.py:113`
- **Description**: New occurrences use `rule_id:scheduled_for:kind:recipient` truncated to 128 characters instead of the calculation's canonical `dedup_base:recipient`. Two valid recipient IDs sharing the truncated prefix produce the same permanent dedup key while having different natural keys; the first insert succeeds and the second is silently discarded by `ON CONFLICT DO NOTHING`, leaving one recipient without a PENDING occurrence. This violates 08 §1.3 M18's required natural-key reconciliation and complete rematerialization.
- **Suggested fix**: Carry each intent's canonical `dedup_base` through `_compute_new_natural_keys` and construct the same dedup key used by the normal materializer; reject invalid lengths instead of truncating identity-bearing data.

### [ep-commands-05] MAJOR (confirmed) Reminder rule version is not advanced and an unauthorized timestamp is changed

- **File**: `backend/app/domain/reminders/handover.py:133`
- **Description**: After rematerialization, `update_rule_cursor` changes `next_trigger_at`, `last_evaluated_at`, and `updated_at` but never increments `rule.version`. Consequently clients holding the pre-handover version cannot detect the semantic update, while `last_evaluated_at` is rewritten even though §1.1 does not authorize that column for handover. This violates 08 §1.1 and §1.3 M18's frozen rule-update semantics.
- **Suggested fix**: Use a handover-specific cursor update that increments `version` exactly once and writes only `next_trigger_at`, `version`, and `updated_at`.

### [ep-commands-06] MINOR (confirmed) Work-record results omit the participant role bucket

- **File**: `backend/app/domain/work_records/handover.py:52`
- **Description**: All three result paths rely on the default empty `role_counts`, so a transferred or merged participant contributes no unit to the participant bucket even though the aggregate totals contain one. A consumer aggregating the documented per-role counts therefore reports zero for this asset. This violates the exactly-one-unit conservation required by 08 §1.3 M40 and 00 §10.5.
- **Suggested fix**: Return `role_counts={"participant": (1, 0)}` or `{"participant": (0, 1)}` on the corresponding paths.

### [ep-commands-07] MINOR (confirmed) Work-record handover accepts a self-transfer as successful

- **File**: `backend/app/domain/work_records/handover.py:34`
- **Description**: For an active participant A, a request with `from=A` and `to=A` deletes A's row, reinserts the same row, and reports one transferred asset. The record is unchanged while the frozen summary claims a transfer. This violates 08 §1.3 M40 and §2.5, which require the target not to be the source and require other conflicts to fail rather than produce a false success.
- **Suggested fix**: Reject `to_dingtalk_user_id == from_dingtalk_user_id` before deleting the source row.

## 分片 ep-infra-identity — 5 条 (blocker 0 / major 3 / minor 2)

**Shard summary**: I traced signature handling, delivery propagation, canonical execute idempotency, generation fencing, and the production identity-binding path. Signature failures correctly return 401, execute uses the frozen three-part key with a canonical parsed-body hash, and delivery_id reaches the execute context and audit record. The watermark repository uses ON CONFLICT safely, and the known internal 429 paths emit Retry-After. The remaining defects are a rolled-back pure binding, two fail-closed gaps in identity binding, a cached-items generation-fence bypass, and loss of dependency throttling metadata.

### [ep-infra-identity-01] MAJOR (confirmed) Production pure identity bindings are always rolled back

- **File**: `backend/app/composition.py:404`
- **Description**: user_repo_factory yields PgDirectoryUserRepository from an AsyncSession but never commits. bind_verified_authentik_sub flushes its authentik_user_id/updated_at update and returns success, after which closing the session rolls the transaction back. Thus an unbound sub can be used for a handover while the required binding silently disappears; a later batch repeats the directory lookup and could resolve a changed sub↔dtuid association instead of detecting a conflict. This violates 05-easyproject-backend.md §2.1's mandatory short write transaction and persistent pure-binding step.
- **Suggested fix**: Make the write-side repository context commit on successful exit and roll back on failure, while retaining a separate explicitly read-only context for lookup.

### [ep-infra-identity-02] MAJOR (confirmed) Cached items responses bypass the generation watermark fence

- **File**: `backend/app/domain/handover/service.py:157`
- **Description**: items returns a cached response before calling _advance_generation_watermark. For example, generation 1 items is cached, generation 2 preview advances the task watermark, and a delayed identical generation 1 items delivery within 300 seconds still receives HTTP 200 instead of HANDOVER_CONFLICT. This violates the generation rule in 05 §4.4 / 08 §2.3 that every preview/items request below the current watermark is rejected.
- **Suggested fix**: Check and advance the generation watermark before consulting the response cache, or include an authoritative watermark validation in the cache-hit path.

### [ep-infra-identity-03] MAJOR (confirmed) Pure binding accepts an inactive local target when its sub was previously null

- **File**: `backend/app/infra/repositories/directory.py:772`
- **Description**: After directory lookup, bind_verified_authentik_sub conditionally updates by dtuid and sub but does not require DirectoryUserRow.is_active. If the local projection has dtuid A with is_active=false and authentik_user_id=NULL while the remote lookup reports A as active, resolve_handover_identity binds and returns A rather than failing with HANDOVER_CONFLICT. The already-bound inactive path is rejected, so behavior depends incorrectly on whether the sub was populated. This violates 05 §2.1 / 08 §1.3's fail-closed requirement that every target be active.
- **Suggested fix**: Make the pure-binding update require is_active=true for target resolution and distinguish inactive rows from unknown/conflicting rows so they map to HANDOVER_CONFLICT.

### [ep-infra-identity-04] MINOR (confirmed) Concurrent pure-binding uniqueness conflicts escape as HTTP 500

- **File**: `backend/app/infra/repositories/directory.py:763`
- **Description**: The owner precheck and conditional UPDATE are not enclosed in an IntegrityError-normalizing savepoint. If another transaction binds the same authentik_user_id to a different dtuid after the precheck, PostgreSQL raises the unique-index violation during this UPDATE; _bind_pure only catches IdentityDomainError, so the lifecycle boundary converts it to INTERNAL_ERROR 500. The frozen identity contract requires binding conflicts to fail closed as 409 IDENTITY_UNMAPPED, not a retryable server failure (05 §2.1).
- **Suggested fix**: Wrap the conditional update/flush in a savepoint, re-read both directions after IntegrityError, and translate a conflicting owner to IdentityDomainError("IDENTITY_BINDING_CONFLICT").

### [ep-infra-identity-05] MINOR (confirmed) Directory throttling loses Retry-After and is exposed as 502

- **File**: `backend/app/domain/identity/handover_identity.py:146`
- **Description**: RateLimited is a Transient subtype, so an EasyAuth directory 429 with retry_after_seconds is caught by the generic Transient branch and replaced with DIRECTORY_UNAVAILABLE. easyauth_lifecycle.py then emits 502 without Retry-After. A previously unbound identity therefore causes uncoordinated retries instead of the frozen dependency-unavailable 503/Retry-After behavior required by the endpoint obligations.
- **Suggested fix**: Catch RateLimited before Transient, preserve its retry delay in the domain error, and map dependency unavailability to the required 503 response with Retry-After.

## 分片 ep-op-worker — 4 条 (blocker 0 / major 4 / minor 0)

**Shard summary**: The worker correctly uses a unique owner per constructed worker, commits claims before HTTP, pins the advisory-lock connection, and normally avoids idle-in-transaction during HTTP. However, lease enforcement is unsafe across slow requests, and lock contention corrupts retry accounting. Repeated exhaustion after conflict resolution cannot persist its terminal state because dedup disagrees with the database uniqueness rule. Advisory-lock cleanup can also leak a session lock into the connection pool on release failure.

### [ep-op-worker-01] MAJOR (confirmed) Expired claims can perform HTTP and commit terminal state without renewal

- **File**: `backend/app/infra/jobs/openproject_handover_projection.py:163`
- **Description**: The worker captures `now` before acquiring the task lock and making the HTTP request, never renews the lease, and later tests `claim_expires_at > now` using that stale timestamp. For example, a claim expiring at t=60 can start HTTP at t=10, finish at t=90, and still transition to APPLIED because expiry is compared with t=10. If another worker reclaims during the request, the first external PATCH has already occurred; the reclaimer may requeue and cause another PATCH. Rows waiting behind earlier members of the 50-row batch can likewise expire before their first HTTP call. This violates frozen contract 08 §1.3, which requires renewal when HTTP may cross the lease and forbids an expired old worker from writing terminal state or conflict ledger entries.
- **Suggested fix**: Before any HTTP call, atomically renew only a still-unexpired claim owned by this claim attempt, using database time. Do not call HTTP when renewal affects zero rows, enforce an HTTP deadline shorter than the renewed lease or heartbeat it, and compare terminal expiry against database current time rather than the pre-HTTP timestamp.

### [ep-op-worker-02] MAJOR (confirmed) Advisory-lock contention both consumes and bypasses the attempts cap

- **File**: `backend/app/infra/jobs/openproject_handover_projection.py:137`
- **Description**: Every claim increments `attempts` before the task advisory lock is acquired, but the lock-contention path always requeues and returns before the `_MAX_ATTEMPTS` check. Seven lock misses followed by one transient HTTP failure therefore writes APPLY_FAILED after only one actual projection attempt. Conversely, if the lock remains unavailable, attempts grows past 8 indefinitely without ever producing APPLY_FAILED or a conflict row. This violates 08 §1.3's attempts/backoff, lock-contention requeue, and retry-exhaustion requirements.
- **Suggested fix**: Count an apply attempt only after the task lock is acquired and immediately before HTTP, using an owner-and-expiry CAS. Keep lock-contention backoff separate from apply attempts, or consistently enforce a separately defined contention cap.

### [ep-op-worker-03] MAJOR (confirmed) Resolved conflict rows make subsequent exhaustion roll back

- **File**: `backend/app/infra/repositories/op_sync.py:193`
- **Description**: Deduplication searches only unresolved conflicts, although the frozen schema permits exactly one non-null `handover_outbox_id` row regardless of resolution. After an outbox first exhausts, its conflict is resolved, and the outbox is redriven, a second exhaustion finds no unresolved row and attempts a duplicate insert. The unique index rejects it during flush, rolling back the preceding APPLY_FAILED update and leaving the outbox CLAIMED until expiry. This violates 08 §1.3's one-conflict-per-outbox rule and its required redrive lifecycle (§1.3, redrive table).
- **Suggested fix**: Use an atomic upsert keyed by `handover_outbox_id`. On repeated exhaustion, update and reopen the existing row—refresh detail/detected_at and clear resolution fields—within the same transaction as the APPLY_FAILED transition.

### [ep-op-worker-04] MAJOR (plausible) Advisory-lock release failures can leak locks into the pool

- **File**: `backend/app/infra/jobs/openproject_handover_projection.py:254`
- **Description**: If `pg_advisory_unlock` raises while the PostgreSQL session remains usable, the exception is only logged. Exiting `engine.connect()` returns the physical session to the pool; its rollback does not release session-scoped advisory locks. That task lock can therefore remain held indefinitely, while reuse of the same physical connection can acquire it reentrantly and defeat mutual exclusion. This violates 08 §1.3's requirement that the worker serialize with ordinary write-through operations using the shared `task_lock_key(task_id)` advisory lock.
- **Suggested fix**: On unlock failure, invalidate or physically close the pinned connection before it can return to the pool. Treat a cleanup failure as requiring connection disposal, optionally attempting `pg_advisory_unlock_all()` first.

## 分片 ep-service — 2 条 (blocker 0 / major 2 / minor 0)

**Shard summary**: The generation watermark is correctly committed before preview/items open their read-only snapshot, while execute advances it atomically with data and receipt writes. Terminal project transitions map to 412 and approval locks to 423, and the current role-count aggregation preserves one unit per asset in normal and empty-role-count fallback paths. Two major defects remain: idempotent replay depends on mutable identity state, and execute builds its plan from an inconsistent unlocked READ COMMITTED view. Both can produce contract-breaking outcomes after an earlier successful preview or execute.

### [ep-service-01] MAJOR (confirmed) Completed idempotent replays are blocked by mutable identity resolution

- **File**: `backend/app/domain/handover/service.py:248`
- **Description**: The service resolves the source and every target identity before consulting the permanent idempotency tombstone at line 277. After a successful execute, if a target is subsequently deactivated or the directory becomes unavailable, an identical retry of the same `(task_id, generation, batch_id)` and payload returns 409/502 instead of the stored 200 summary. A changed-payload retry can likewise fail during identity resolution before producing the required `WEBHOOK_PAYLOAD_CONFLICT`. This violates 05-easyproject-backend.md §4.4, which requires equal replays to return exactly the original summary and unequal hashes to be decided by the tombstone without executing the new request.
- **Suggested fix**: Perform a read-only lookup of the completed tombstone and request hash before identity resolution, returning the stored response or payload conflict immediately. Retain the transactional claim under the generation lock for requests without a completed tombstone.

### [ep-service-02] MAJOR (confirmed) Execute can accept an ABA snapshot while applying a stale plan

- **File**: `backend/app/domain/handover/service.py:296`
- **Description**: `_build_execute_plan` materializes all live asset IDs before `_lock_plan`, and the execute transaction remains at PostgreSQL's READ COMMITTED isolation. For example, preview contains task X owned by A; while execute scans `task_assigned`, X is temporarily reassigned A→B and is therefore omitted from the plan; before the later token recomputation, X is reassigned B→A with the same status. The recomputed token equals preview, but X is neither locked nor transferred, and the response reports zero units for it while other planned assets are committed. The resulting summary violates §10.5 conservation and becomes a permanent bad idempotency receipt; this violates 00-overview-and-contract.md §10.5 and §10.5.1 items 3–4, plus 05-easyproject-backend.md §4.3.3's locked-snapshot requirement.
- **Suggested fix**: Start execute at REPEATABLE READ or SERIALIZABLE isolation before materializing any asset set, and derive the plan and token from that same transaction snapshot after acquiring the fixed-order aggregate locks. Treat serialization failures as the existing retryable 429 path.

## 分片 et-execute-receipt — 3 条 (blocker 0 / major 3 / minor 0)

**Shard summary**: The task-scoped advisory lock spans replay through commit, and receipt replay occurs before identity resolution. Five-field summaries are emitted for every asset type, with absent and skip branches conserving counts for canonical IDs. Virgin and previously applied 0002 upgrade paths converge on the required columns, removed defaults, and task-ID checks. Three confirmed defects remain in action parsing, override matching, and locked receiver validation.

### [et-execute-receipt-01] MAJOR (confirmed) Locked receiver validation can use stale active status

- **File**: `backend/app/domain/authz/easyauth_handover.py:316`
- **Description**: Receiver resolution first loads the User into the session identity map. `_lock_plan_rows()` subsequently obtains `FOR UPDATE` without `populate_existing()`, and `_assert_locked_state()` uses `db.get()`, so both may reuse the previously loaded attributes. If receiver B is active during parsing but directory synchronization deactivates B before the row lock is acquired, the handover can still observe cached `active=True` and transfer assets to the inactive user. This violates §3.6 steps 6–7, which require locking receiver rows and rechecking `receiver.active` inside the lock.
- **Suggested fix**: Lock users with `populate_existing()` or explicitly refresh them after `FOR UPDATE`, then validate the freshly loaded locked rows.

### [et-execute-receipt-02] MAJOR (confirmed) Non-canonical UUID override IDs silently receive the default action

- **File**: `backend/app/domain/authz/easyauth_handover.py:521`
- **Description**: Overrides are indexed by their original string, while frozen asset IDs are matched using canonical `str(UUID)` values. `_assert_locked_state()` separately parses the same override string as a UUID, so an uppercase or braced UUID passes snapshot membership validation but fails the string lookup in `_assign_actions()`. For example, an uppercase customer ID requesting `transfer` with default `release` is released to the pool instead. This violates §3.6 step 5, which requires overrides to take precedence over the default action for their exact asset IDs.
- **Suggested fix**: Parse override IDs into UUID values once, key actions and duplicate detection by UUID, and reject malformed IDs before building the plan.

### [et-execute-receipt-03] MAJOR (confirmed) Explicit null actions are silently interpreted as skip

- **File**: `backend/app/api/v1/easyauth_lifecycle_handlers.py:85`
- **Description**: Both parsers pass `dict.get()` into `_parse_action()`, which returns `skip` whenever the value is `None`; therefore it cannot distinguish a missing action from an explicit JSON null. A payload such as `{"default_action": null}` is accepted and records all affected assets as skipped instead of returning 422, potentially leaving data behind while execute succeeds. This violates §3.6 step 4's declaration validation and the frozen `transfer | release | skip` action contract.
- **Suggested fix**: Use a missing-value sentinel: default only when the key is absent, and reject explicit null or any other non-string value with 422.

## 分片 et-locks-integration — 1 条 (blocker 0 / major 1 / minor 0)

**Shard summary**: The handover locks asset tables in the required global order and locks IDs in ascending order; its freeze, lock, and snapshot-check phases also follow the documented shape. However, the preceding `User FOR UPDATE` locks create an implicit PostgreSQL foreign-key lock inversion with ordinary activity, sample, and order owner changes. I found no other confirmed explicit table-order or preview-to-execute gap defect within the scoped paths.

### [et-locks-integration-01] MAJOR (confirmed) User-first locks deadlock with remediated business writers through implicit FK locks

- **File**: `backend/app/domain/authz/easyauth_handover.py:316`
- **Description**: `_lock_plan_rows` locks the source and receiver `users` rows with `FOR UPDATE` before locking assets. Conversely, `update_activity`, `update_sample_request`, and `update_order` first lock their Customer/Inquiry/Activity, Inquiry/SampleRequest, or Inquiry/Order rows and then may change a user foreign key. PostgreSQL validates the changed FK by taking `KEY SHARE` on the target User row, which conflicts with handover's `FOR UPDATE`. Concrete scenario: an order owned by B is being transferred to C by handover, while an ordinary PUT for that order also assigns C; the PUT holds Inquiry/Order and waits for `KEY SHARE` on User C, while handover holds User C and waits for Inquiry/Order, producing a deadlock and aborting one transaction as a 5xx. This violates `03-easytrade-backend.md` §3.6 step 6 and item 4's repo-wide fixed locking discipline; the prior remediation corrected explicit asset locks but missed this implicit FK edge.
- **Suggested fix**: Make every owner-changing writer acquire the affected User rows before its asset locks, using the same deterministic User→Customer→Inquiry→Activity/SampleRequest/Order order. Alternatively, replace the conflicting User lock with a non-conflicting mechanism only if a shared serialization guard still prevents receiver deactivation and new assignments to the departing user.

## 分片 et-registry-preview — 3 条 (blocker 0 / major 2 / minor 1)

**Shard summary**: The eight-type registry, shared selectors, preview counts, and repeatable-read items flow match the frozen contract. The snapshot digest includes each selected row’s ID, ownership column, and status column rather than hashing only ID sets. Two confirmed hint defects can present incomplete or incorrect decision data. The single-flight implementation is also plausibly bypassed in multi-process or replicated deployments because all coordination is process-local.

### [et-registry-preview-01] MAJOR (confirmed) Receivable hint silently substitutes gross amount when net amount is indeterminate

- **File**: `backend/app/domain/authz/handover_assets.py:254`
- **Description**: For a 100 USD receivable with a valid cross-currency allocation whose conversion data is incomplete, receivable_open_amount() returns None. Lines 260–261 then replace that result with receivable_amount, so the hint reports 100 USD as outstanding despite existing allocations. This is silent financial misinformation and violates §3.1.1, which requires receivable_open hints to contain the outstanding amount net of valid allocations.
- **Suggested fix**: Never substitute the gross receivable amount for an indeterminate net balance. Compute the exact allocated total through a reliable aggregation/conversion path, or reject rendering with an explicit error until the amount can be calculated.

### [et-registry-preview-02] MAJOR (plausible) Items single-flight is bypassed across workers or replicas

- **File**: `backend/app/domain/authz/easyauth_handover.py:181`
- **Description**: _ITEMS_INFLIGHT, _ITEMS_CACHE, and their lock are process-local globals. If two identical signed items requests reach different worker processes or application replicas concurrently, neither sees the other as in flight; both execute the expensive snapshot and pagination queries and neither returns 429. This defeats the read-amplification protection required by §3.5 for concurrent replays of the same signed body fingerprint.
- **Suggested fix**: Coordinate the body fingerprint through a shared cache/lock such as Redis SET NX with TTL or a PostgreSQL try-advisory lock, and use a shared response cache if caching is selected. Keep the local lock only as an optional fast path.

### [et-registry-preview-03] MINOR (confirmed) Task and sample hints omit required related-asset identity

- **File**: `backend/app/domain/authz/handover_assets.py:272`
- **Description**: A task linked to an inquiry always renders the related object merely as “询盘”, without its number or customer, so multiple inquiry tasks cannot be distinguished from the hint. Likewise, a sample request renders purpose (or the generic word “样品”) rather than its SampleRequestItem products; for purpose “Evaluation” and product “Resin X”, the required sample identity is absent. This violates §3.1.1, which makes the related object mandatory for task_open and the sample mandatory for sample_request_open hints.
- **Suggested fix**: Resolve inquiry tasks to an identifying inquiry number/customer, and render sample request item product or alias names rather than purpose. Preserve the 120-character limit after assembling the identifying content.

## 分片 et-route-sdk — 0 条 (blocker 0 / major 0 / minor 0)

**Shard summary**: The lifecycle route is registered at the declared URL and uses bounded streaming before signature verification. Preview, items, and execute handlers are all registered; webhook.test validates the signed body event type first, and EasyTrade preserves 403 signature-failure semantics. Manifest export admits the new lifecycle key and derives all eight asset declarations from the shared registry. The vendored source matches upstream tag easyauth-app-sdk-v0.4.0 and its recorded build/provenance commits, with no local patches found; no contract defects were identified.
