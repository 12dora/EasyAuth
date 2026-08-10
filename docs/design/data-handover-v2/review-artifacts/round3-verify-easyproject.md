# Verification findings — EasyProject (verdict: pass-with-nits)

## V-01 [minor/confirmed] Projection worker's owner-CAS uses a shared constant claim_owner, so it cannot distinguish a preempting worker

File: /Users/konata/code/EasyProject/backend/app/infra/jobs/openproject_handover_projection.py

c36e9bc implements 08 §1.3 bullet 4 as `UPDATE ... WHERE id=? AND status='CLAIMED' AND claim_owner=?`, but `_WORKER_OWNER` (line 35) is a module-level literal ("handover-projection-worker") identical for every worker instance, and the CAS does not consult `claim_expires_at` either. The claim itself is committed with a 60 s lease and rows whose lease expired are re-claimable (`_claim_batch`, lines 111-117), so the preemption path exists by design — but a stale claimer's terminal write still satisfies the predicate. Failure scenario: instance A claims row R and hangs in `patch_handover_person_fields` past the 60 s lease; the scheduler's per-job advisory lock on A's connection is lost (PG restart / pgbouncer blip), instance B re-claims R (attempts+1, new lease) and starts its own PATCH; A returns and `_cas_terminal` matches status='CLAIMED' + claim_owner='handover-projection-worker' → rowcount 1, so A writes APPLIED (or APPLY_FAILED plus an op_sync_conflicts row) for a claim it no longer owns, and B's later CAS silently no-ops. Impact is bounded today because `patch_handover_person_fields` is not implemented on any gateway (every row takes the OPENPROJECT_CF_PATCH_NOT_IMPLEMENTED branch, no network I/O) and app/infra/scheduler.py holds a per-job advisory lock for the whole run, so it activates only when the real PATCH lands.

Suggested fix: Make the owner per worker instance (e.g. `self._owner = f"handover-projection-worker:{uuid4()}"`, stored on the instance and used in both `_claim_batch` and the two CAS statements) and additionally require `claim_expires_at > now` in the terminal CAS. Re-claiming keys off status+expiry, not owner, so nothing else changes.

## V-02 [minor/plausible] Worker still holds an open DB transaction across the HTTP call, and the 217-line rewrite has zero tests

File: /Users/konata/code/EasyProject/backend/app/infra/jobs/openproject_handover_projection.py

`_process_one` (lines 171-186) acquires the task advisory lock via `PgAdvisoryLock.try_acquire` on `lock_session`; that `SELECT pg_try_advisory_lock(...)` implicitly begins a SQLAlchemy transaction which is never committed before `await self._apply_http(...)` runs, so the connection sits idle-in-transaction for the whole OpenProject round-trip. No business row locks are held (a real improvement over the pre-fix `run_once`), but the 'connection pinned across network I/O' half of the original finding survives; pg_try_advisory_lock is session-scoped and survives a commit, so committing right after acquisition would cost nothing. Separately, `grep -rl 'HandoverProjectionWorker\|handover_projection' backend/tests` finds no test of this file at all: the claim/HTTP/terminal split, the lease-preemption branch, the requeue-on-lock-contention branch (which burns one of the 8 attempts without any apply attempt) and both CAS statements are entirely unexercised, which is why the owner-CAS weakness above survived a round dedicated to test honesty.

Suggested fix: `await lock_session.commit()` immediately after `try_acquire` (the session-level advisory lock persists), and add an integration test with two worker instances over one outbox row: assert the stale claimer's terminal CAS is a no-op, that a lock-contended row is requeued with backoff and no HTTP, and that exhaustion writes exactly one op_sync_conflicts row keyed by handover_outbox_id.

## V-03 [minor/confirmed] M19 assignee-transfer collaborator deletion lost its only test pin when the assertion changed to (1,0)

File: /Users/konata/code/EasyProject/backend/tests/integration/handover/test_owner_commands_pg.py

Before 2e21f60, `test_m19_assignee_transfer_removes_target_collaborator` asserted `role_counts['assignee'] == (1,1)`, and the `merged==1` half could only come from the deletion of the incoming assignee's `RecurringTemplateCollaboratorRow`. After the (correct) change to `(1,0)` the test asserts only counts (lines 97-106) and never inspects the collaborator table — unlike its M10 sibling, which still asserts `collabs == []`. Deleting the `collab_of_new` block in backend/app/domain/recurrence/handover.py:62-64 now turns nothing red: `test_recurring_collab_to_final_assignee_merged_pg` and `test_recurring_collaborator_merge` exercise the collaborator-transfer branch, not the assignee branch, and the 9-type test seeds `nine-ra` with no collaborators. The result would be a template with assignee ∈ collaborators — precisely the `assignee_cannot_be_collaborator` invariant 08 §1.3 M19 names.

Suggested fix: In the M19 test, after the handover assert that no `RecurringTemplateCollaboratorRow(template_id=tpl, dingtalk_user_id=to_uid)` remains (mirroring the M10 test's `collabs == []`), or seed a collaborator on the `nine-ra` template in the 9-type test.

## V-04 [minor/confirmed] Terminal-project 409→412 fix (ep-fix1-production-04) has no regression test

File: /Users/konata/code/EasyProject/backend/app/domain/handover/service.py

The fix at service.py:500-504 (`_lock_plan` now raises `SnapshotStaleError` → 412 for COMPLETED/CANCELLED projects instead of `HandoverConflictError` → 409) is correct against 00 §10.5.1 / 08 §2.2 and the endpoint mapping (easyauth_lifecycle.py:69 → 412), but nothing pins it. The only terminal-project test, `test_approval_lock_423_vs_terminal_409` (test_execute_composite_keys.py:464), calls `project_handover` directly and asserts `ProjectHandoverConflict` — that is the M13 command path, which reaches the API as 412 only via `_call_domain`'s translation, a different code path from `_lock_plan`. Reverting service.py:503 to `HandoverConflictError` leaves the whole suite green, and the test's own name still says 409, which now contradicts the service-level contract.

Suggested fix: Add an integration test that previews a live project, flips it to COMPLETED behind the service's back, then executes and asserts `SnapshotStaleError` (412) out of `service.execute` — plus the sibling case asserting `HandoverTemporarilyLockedError` (423) for an approval-locked project.
