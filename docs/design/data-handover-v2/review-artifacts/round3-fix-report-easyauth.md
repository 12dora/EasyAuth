# EasyAuth round-3 fix report

Commits (main, not pushed):
- `66f37c9` fix(lifecycle): 修复 async-abandon 租约与守恒失败回滚
- `a155b5b` fix(api): 对齐交接端点契约(错误码/summary/建单/能力同步)
- `499d191` fix(access): 审批改派稳健化与 ADR-002 §36 闭环
- `34d5a6b` fix(tasks): beat 提醒/上交/轮询与 manifest 白名单钉扎

## 分片 a1c-endpoints

- a1c-endpoints-01 → fixed@66f37c9
- a1c-endpoints-02 → fixed@a155b5b
- a1c-endpoints-03 → fixed@a155b5b
- a1c-endpoints-04 → fixed@a155b5b
- a1c-endpoints-05 → fixed@66f37c9
- a1c-endpoints-06 → fixed@a155b5b
- a1c-endpoints-07 → fixed@a155b5b
- a1c-endpoints-08 → fixed@66f37c9
- a1c-endpoints-09 → fixed@a155b5b
- a1c-endpoints-10 → fixed@a155b5b
- a1c-endpoints-11 → fixed@a155b5b

## 分片 a1c-reassign-adr36

- a1c-reassign-adr36-01 → fixed@499d191
- a1c-reassign-adr36-02 → fixed@499d191
- a1c-reassign-adr36-03 → fixed@499d191
- a1c-reassign-adr36-04 → fixed@499d191
- a1c-reassign-adr36-05 → fixed@499d191
- a1c-reassign-adr36-06 → fixed@499d191 (link 显式 `unavailable:app=…`，无稳定钉钉入口 URL 时不写空串)
- a1c-reassign-adr36-07 → fixed@499d191
- a1c-reassign-adr36-08 → fixed@a155b5b

## 分片 a1c-beat-upgrade-conservation

- a1c-beat-upgrade-conservation-01 → fixed@66f37c9
- a1c-beat-upgrade-conservation-02 → fixed@66f37c9
- a1c-beat-upgrade-conservation-03 → fixed@a155b5b
- a1c-beat-upgrade-conservation-04 → fixed@34d5a6b (注册 `easyauth.lifecycle.send_reminder` + 审计 `lifecycle_reminder_recorded`；`easyauth-lifecycle` 完整 notify 身份 provisioning 仍为 accepted-debt)
- a1c-beat-upgrade-conservation-05 → fixed@34d5a6b
- a1c-beat-upgrade-conservation-06 → fixed@66f37c9
- a1c-beat-upgrade-conservation-07 → fixed@34d5a6b
- a1c-beat-upgrade-conservation-08 → fixed@34d5a6b
- a1c-beat-upgrade-conservation-09 → fixed@34d5a6b
- a1c-beat-upgrade-conservation-10 → fixed@34d5a6b
- a1c-beat-upgrade-conservation-11 → fixed@34d5a6b
- a1c-beat-upgrade-conservation-12 → fixed@66f37c9

## Extra

- EA-EXTRA-1 → fixed@499d191
- EA-EXTRA-2 → fixed@34d5a6b

## Accepted debt (shell / 非本轮完整交付)

- notify identity `easyauth-lifecycle` App + channel + 启动健康检查 + lifecycle. 模板：任务已可观测且不再静默丢 outbox 名，完整身份 provisioning 仍待 §7 交付表。

## Tests

- Full suite: **1481 passed, 9 skipped, 0 failed**
- `manage.py check`: ok
- `makemigrations --check --dry-run`: No changes detected
- Frontend: not touched

## Disputed

- (none)
