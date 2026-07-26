# EasyAuth 权威审计综述

审计日期：2026-07-27
审计基线：`18cd9363854efd9dfb0dce82291543c43b517add`
适用范围：本目录 00—17 号主报告及 `review/` 下 01—08 号交叉复核报告

## 1. 权威口径

本文是本轮仓库审计的权威执行摘要。原始报告用于保留专项证据，交叉复核用于裁决重复、矛盾、
严重度和证据边界；两者冲突时，以交叉复核结论为准，尤其以
[全局一致性复核](review/08-global-consistency-review.md)为最终口径。

00 号报告是[仓库地图](00-repository-map.md)，其余主报告共出现 247 个带编号标题，但这些标题
混合了已确认缺陷、条件风险、假设、提示项、产品决策和重复观察，不能相加为独立问题总数。
本文按共同根因、失效路径和修复目标去重，并重新采用统一的 P0—P3 优先级。

稳定编号采用 `EA-AUD-###`。编号不随优先级变化；以后若证据或优先级调整，只修改登记项内容和
优先级，不复用或重排编号。

登记项是整改根因簇，不等同于单一源码症状。同一登记项可以收纳多个具有相同事实边界或必须在
同一变更集中关闭的子项；登记项优先级由其中最高影响且证据充分的子项决定，不把同簇的低影响
子项自动提升为同等严重度。第 5.5 节补充容易从摘要文字中漏读的归属。

### 1.1 统一优先级

| 优先级 | 含义 |
| --- | --- |
| P0 | 上线或公开暴露阻断项；已确认破坏信任根、特权撤权或关键安全动作恢复能力 |
| P1 | 可造成权限或业务事实错误、关键动作假成功、持久化不变量失效或质量证据失真 |
| P2 | 可恢复功能失效、确定的工程或运维缺口、有限信息暴露、可规模放大的性能机制 |
| P3 | 维护性、低影响体验、待产品决策或需要外部契约确认的治理项 |

### 1.2 统一证据状态

| 状态 | 含义 |
| --- | --- |
| 动态确认 | 已由最小复现、命令、只读探针或浏览器行为实际验证 |
| 静态确认 | 当前代码或配置能确定到达错误状态，不依赖未定义外部行为 |
| 条件成立 | 失效机制已确认，但实际影响取决于部署拓扑、数据规模、外部响应或平台基线 |
| 待决策 | 是否构成缺陷或如何修复取决于尚未确定的产品、安全或外部契约 |
| 假设 | 只有风险结构，尚未证明正式路径可达或影响成立 |

## 2. 范围与方法

审计覆盖 Django 后端、React 前端、领域模型与迁移、认证与授权、公共/控制台/门户 API、
Celery、Outbox、Webhook、连接器、Authentik 与 DingTalk 集成、SDK、测试、构建、容器部署、
供应链、隐私保留、国际化、反馈、布局和无障碍。

方法包括：

- 沿模型、领域服务、事务、任务、API、前端解码与页面调用追踪同一业务事实；
- 对 00—17 号报告逐项检查证据、可达性、重复关系、严重度和修复建议；
- 使用 01—08 号复核报告裁决重复、降级、条件项、错误叙述和遗漏；
- 以根因簇建立登记项，不按报告数量或局部严重度直接累计；
- 保留每项的主报告与复核来源，便于回到精确文件和行号证据。

本次工作只形成审计文档，没有修改应用代码、测试、配置、迁移、构建产物或运行数据。

## 3. 验证边界

本轮能够证明与不能证明的边界如下：

- 主后端 SQLite 套件曾得到 `1291 passed, 1 skipped`。这不覆盖 SDK、FastAPI 跳过项、
  PostgreSQL 行锁、多连接并发、真实 Redis/broker 或多 worker 语义。
- SDK 在正确入口下为 `69 passed, 2 skipped`；两个跳过是未安装可选 FastAPI 依赖导致的整模块
  跳过，不是 FastAPI 产品缺陷已经被验证。
- Vitest 在同一基线上出现过失败后重跑通过；只能确认结果不可重复，不能确认固定失败数量，也
  不能把“文件并发竞争”写成唯一根因。
- Playwright 的 27 项失败均停在缺少匹配版本的 Chromium Headless Shell，业务断言没有执行。
  现有 Playwright 又大量模拟 EasyAuth 自身 API，只能视为 UI/布局冒烟。
- 浏览器真实验证覆盖未登录的本地管理员页面；受保护 React 页主要来自 Vite/API 隔离渲染。
  隔离渲染可证明布局条件，不证明真实鉴权、CSRF、数据库和前后端闭环。
- 未执行 PostgreSQL 空库迁移回放、历史快照升级、生产规模压测、真实外部系统联调、故障注入、
  渗透测试或生产拓扑演练。
- 仓库中名为“公网反代部署”的编排具有开发级配置是静态事实；该编排当前是否实际启用、是否被
  DNS/反代暴露到互联网没有验证。
- 性能项确认的是无界读取、N+1、锁内网络、全表扫描等机制；没有生产指标时，不表述为已发生
  延迟、资源耗尽或事故。
- 公开 SDK 和 legacy 输入是否已有仓库外消费者没有证据，删除前仍需核对发布和下游清单。

## 4. 去重后的系统性结论

### 4.1 部署与身份信任根尚未闭合

仓库中的反代部署路径会使用 `DEBUG=1`、`runserver`、SQLite、公开开发密钥、本地镜像和源码
挂载，并把同一环境文件注入全部服务。即使尚未证明其当前公网可达，这条路径也不能作为上线
路径。与此同时，本地管理员和 OIDC 管理员各有一条既有会话不能按权威状态及时撤销的路径。

### 4.2 异步任务把“已接收”误当成“已完成”

Webhook 租约过期后没有权威恢复扫描器；离职禁号失败会返回任务成功；目录同步、通知对账和
依赖健康会把部分失败或依赖失败解释成成功、空变化或健康。连接器租约还短于任务硬时限，旧
worker 失去租约后仍可能继续执行外部撤权。共同根因是状态机、租约、fencing、watchdog 和
任务返回语义没有形成一个可恢复协议。

### 4.3 授权命令缺少被审批事实的版本前置条件

`change`、`revoke`、`renew` 申请没有绑定基础授权修订；转岗计划也没有冻结模板修订。审批或
确认完成时，系统可能把旧决定应用到后来变化的事实。WebAuthn 计数、状态机字段形状、跨应用
归属和多态目标也有不同程度的数据库不变量缺口。

### 4.4 跨层契约存在系统性静默纠错

非法列表信封会变成空数组，非 JSON 2xx 可进入成功分支，非法分页和筛选会被默认、截断或忽略，
未知状态可回显内部枚举，模型异常和底层错误可成为用户文案。前端能力展示、可执行动作和后端
权限/状态机也未使用同一事实源。

### 4.5 当前质量体系会产生假绿灯

唯一 CI 只构建镜像；主 pytest 不覆盖 SDK，默认 SQLite 不验证 PostgreSQL 并发，控制台测试
用生产不存在的登录桥，通知测试自动伪造业务事实，前端测试结果不稳定，Playwright 不验证真实
后端。测试数量不能弥补入口、替身和环境边界错误。

### 4.6 外部网络、秘密和隐私保留需要统一边界

自动接入存在 DNS 二次解析/重定向 SSRF 缺口；多个外部响应无界读取或异常未归一化；secret
校验错误、TOTP/一次性凭据响应和浏览器 mutation 状态扩大了秘密暴露面。离职画像、Stream、
Webhook 和审计数据缺少统一保留矩阵。

### 4.7 UI 问题以可完成性和错误真实性为主

优先问题不是缺少装饰性动画，而是移动页头与表格压缩、颜色和焦点对比度、组合框/Tab/Menu
键盘语义、错误伪装为空态、操作失败静默、密码策略文案错误、双语边界和内部协议术语外露。

## 5. 优先级登记册

### 5.1 P0：上线与安全动作阻断项

| 稳定编号 | 结论 | 状态 | 主要证据 |
| --- | --- | --- | --- |
| EA-AUD-001 | 仓库中的反代部署路径不是可信生产路径：`DEBUG`、开发密钥、`runserver`、SQLite、本地镜像/源码覆盖和全服务共享 secrets 共同破坏部署、数据与供应链边界。当前互联网可达性未验证，但启用该路径应阻断上线。 | 静态确认；外部暴露条件未验证 | [14/BCO-01—05](14-build-config-operations.md)、[16/SPB-01、SPB-04](16-security-privacy-boundaries.md)、[安全运维复核](review/05-security-operations-review.md) |
| EA-AUD-002 | 控制台本地管理员 actor 绕过 `session_version` 和专用会话标志；改密或第二因子变更后，旧会话仍可保留超级管理员能力。 | 动态确认 | [02/BF-01](02-backend-functional-bugs.md)、[16/SPB-02](16-security-privacy-boundaries.md)、[后端复核](review/01-backend-evidence-review.md) |
| EA-AUD-003 | OIDC 超级管理员能力长期依赖登录时组快照；撤组后现有会话继续拥有权限。失效时限尚需政策固定，但当前没有权威请求期撤权机制。 | 静态确认；时限待决策 | [02/BF-02](02-backend-functional-bugs.md)、[16/SPB-03](16-security-privacy-boundaries.md)、[安全运维复核](review/05-security-operations-review.md) |
| EA-AUD-004 | Webhook 投递在认领后的非预期异常、硬超时或 worker 丢失时会永久停在 `pending`；没有过期租约 watchdog，人工重投也不接受该状态。 | 静态确认 | [04/REL-PERF-01](04-backend-reliability-performance.md)、[后端复核](review/01-backend-evidence-review.md) |
| EA-AUD-005 | 离职禁号的未配置、分页上限和用户查找失败可被任务返回为成功，使外部账号继续有效且不再自动重试。 | 静态确认 | [04/REL-PERF-02](04-backend-reliability-performance.md)、[后端复核](review/01-backend-evidence-review.md) |

### 5.2 P1：权限、事实、契约和质量可信度

| 稳定编号 | 结论 | 状态 | 主要证据 |
| --- | --- | --- | --- |
| EA-AUD-006 | 连接器任务硬时限长于租约，且撤组、封禁等收缩动作缺少 `lease_token + generation` fencing；旧 worker 失去租约后仍可对外部系统写入。 | 静态确认 | [后端复核/OMIT-BE-01](review/01-backend-evidence-review.md) |
| EA-AUD-007 | 访问申请提交与批准落地使用了不同的有效授权成员口径，且 `change`、`revoke`、`renew` 不绑定基础授权主键和修订；已批准命令可能作用于不同于提交或审批时的授权事实。 | 静态确认 | [01/BAS-03](01-backend-architecture-smells.md)、[03/DS-01](03-domain-schema-invariants.md)、[后端复核](review/01-backend-evidence-review.md)、[契约领域复核](review/03-contract-domain-review.md) |
| EA-AUD-008 | 转岗计划只绑定可变模板，确认时重新读取当前模板；预览内容与最终执行内容可能不同。 | 静态确认 | [03/DS-02](03-domain-schema-invariants.md)、[后端复核](review/01-backend-evidence-review.md) |
| EA-AUD-009 | WebAuthn `sign_count` 读取、验证和写回不是原子操作，并发请求可丢失或回退计数。 | 静态确认 | [03/DS-03](03-domain-schema-invariants.md)、[04/REL-PERF-03](04-backend-reliability-performance.md) |
| EA-AUD-010 | 申请、通知、Outbox、审批回调和 Stream 等状态机缺少完整数据库真值表约束；结构缺口已确认，具体非法组合的正式可达性需逐状态机验证。 | 静态确认；影响按状态机限定 | [03/DS-07](03-domain-schema-invariants.md)、[后端复核](review/01-backend-evidence-review.md) |
| EA-AUD-011 | 跨应用权限归属主要由 `clean()` 保证，数据库无法拒绝跨 App 组合；正式写路径目前会调用校验，尚未证明现有越权旁路。 | 条件成立 | [03/DS-08](03-domain-schema-invariants.md)、[01/HYP-02](01-backend-architecture-smells.md)、[后端复核](review/01-backend-evidence-review.md) |
| EA-AUD-012 | `UserMirror` 的“不可物理删除”只覆盖实例删除，而相关外键同时使用 `CASCADE`/`PROTECT`；正式批量删除入口未发现，但数据库不变量互相矛盾。与该主体相关的离职画像最小化是同一主体生命周期的独立 P2 子项，不能用外键修复替代。 | 条件成立；画像保留政策待决策 | [03/DS-04](03-domain-schema-invariants.md)、[16/SPB-08](16-security-privacy-boundaries.md)、[后端复核](review/01-backend-evidence-review.md)、[安全运维复核](review/05-security-operations-review.md) |
| EA-AUD-013 | 托管范围策略使用无外键多态整数，钉钉身份绑定缺少唯一关系且通知任取首行，均可形成孤儿或错误主体归属。 | 静态确认 | [03/DS-09、DS-10](03-domain-schema-invariants.md)、[契约领域复核](review/03-contract-domain-review.md) |
| EA-AUD-014 | 通知受理同时存在幂等哈希遗漏 `biz_tag`、错误 JSON 类型静默强转、汇总计数与明细落库即矛盾。 | 动态/静态确认 | [02/BF-04、BF-05](02-backend-functional-bugs.md)、[03/DS-06](03-domain-schema-invariants.md) |
| EA-AUD-015 | 登录、凭据签发、目录代次、通知对账、依赖健康、非 JSON 2xx 及关键前端动作存在“未完成、部分失败或依赖失败被解释为成功、空变化、健康或可继续”的共同错误语义。 | 静态确认 | [02/BF-08](02-backend-functional-bugs.md)、[04/REL-PERF-04、REL-PERF-13、REL-PERF-14、REL-PERF-22、REL-PERF-25、REL-PERF-26](04-backend-reliability-performance.md)、[09/TF-01、TF-02、TF-11、TF-12、TF-16、TF-20](09-toast-and-feedback.md)、[01/BAS-11](01-backend-architecture-smells.md)、[后端复核](review/01-backend-evidence-review.md)、[体验复核](review/06-user-experience-review.md)、[全局复核/GC-15](review/08-global-consistency-review.md) |
| EA-AUD-016 | 目录/OIDC 外部响应无界读取、OIDC 每次重取 JWKS、DNS 超时遗留线程、Webhook Unicode request-target 异常等会绕过既有重试或恢复边界。 | 静态确认；容量影响条件成立 | [04/REL-PERF-05、REL-PERF-07、REL-PERF-15、REL-PERF-17](04-backend-reliability-performance.md) |
| EA-AUD-018 | 通用 API 与持久化输入边界会静默吞重复键、把损坏配置变为空对象、把非法列表信封变为空数组、改写/忽略非法查询参数或跨字段约束、截断资源选择，并让未知枚举或错误路由继续渲染。非 JSON 2xx 另归 `EA-AUD-015`，不与列表信封特例合并。 | 动态/静态确认；个别坏数据路径条件成立 | [01/BAS-09、BAS-10](01-backend-architecture-smells.md)、[02/BF-06](02-backend-functional-bugs.md)、[06/C-05、C-08、C-15、R-06](06-frontend-functional-bugs.md)、[15/CTR-04—CTR-07、CTR-09](15-cross-layer-contracts.md)、[09/TF-15](09-toast-and-feedback.md)、[契约领域复核/NEW-CD-01](review/03-contract-domain-review.md)、[全局复核/GC-06、GC-09、GC-14、GC-20](review/08-global-consistency-review.md) |
| EA-AUD-019 | Console 导航、路由、工作区和动作状态没有使用与后端一致的细粒度能力/状态机；用户会看到后端明确禁止的动作，或在停用、不可删除状态下缺少正确的恢复闭环。 | 静态确认 | [06/C-01—C-03、C-06、C-07](06-frontend-functional-bugs.md)、[前端复核](review/02-frontend-evidence-review.md)、[契约领域复核](review/03-contract-domain-review.md) |
| EA-AUD-020 | 门户只生成 `grant`，无法发起 `change`、`revoke`、`renew`，且“我的申请”未接入已有撤回能力。 | 静态确认 | [15/CTR-01、CTR-02](15-cross-layer-contracts.md)、[06/C-04](06-frontend-functional-bugs.md) |
| EA-AUD-021 | 成员、凭据、权限和授权组写入只失效局部查询，应用详情、列表和配置就绪度会继续展示旧派生事实。 | 静态确认 | [15/CTR-03](15-cross-layer-contracts.md)、[契约领域复核/NEW-CD-02](review/03-contract-domain-review.md) |
| EA-AUD-022 | CI、测试入口和测试替身共同制造假绿灯：发布不依赖质量作业，控制台登录桥和通知自动造数偏离生产事实，SDK/FastAPI/PostgreSQL/真实全栈均未形成必跑门禁。 | 动态/静态确认 | [11/BTD-01—BTD-05、BTD-08](11-backend-test-decay.md)、[12/F-03、F-04](12-frontend-e2e-test-decay.md)、[测试复核](review/04-test-evidence-review.md) |
| EA-AUD-023 | 历史迁移含无条件删除申请/授权和清空凭据的路径；从零空库不触发数据损失，但携带试点/开发数据升级时属于上线基线阻断。 | 条件成立 | [03/DS-12](03-domain-schema-invariants.md)、[契约领域复核](review/03-contract-domain-review.md) |
| EA-AUD-024 | PostgreSQL、多连接、Redis、broker 和多 worker 并发语义缺少必跑验证；当前 SQLite 绿色不能证明锁、租约和 `skip_locked` 正确。 | 静态确认的测试缺口 | [11/BTD-02、BTD-13](11-backend-test-decay.md)、[测试复核](review/04-test-evidence-review.md) |

### 5.3 P2：可用性、规模、运维和隐私治理

| 稳定编号 | 结论 | 状态 | 主要证据 |
| --- | --- | --- | --- |
| EA-AUD-017 | 自动接入的先解析后 `urlopen` 不能固定已验证 IP 且默认跟随重定向；Passkey 二次验证未复用既有节流；Pydantic secret 回显、秘密响应无 `no-store`、前端 mutation 保留 token，以及审批编号存在性差异扩大敏感面。机制已确认，但原报告将这些子项评为中、低或条件风险，不按 P1 计。 | 静态/动态确认；可利用性和缓存影响条件成立 | [02/BF-03](02-backend-functional-bugs.md)、[16/SPB-05—SPB-07、SPB-10、SPB-12](16-security-privacy-boundaries.md)、[安全运维复核](review/05-security-operations-review.md) |
| EA-AUD-025 | 多个列表和后台任务存在无界集合、N+1、全表扫描、逐行写锁、非原子指标累计或同步远端读取；审计/健康历史还会持续增长。机制已确认，具体索引、容量阈值和生产影响仍需 PostgreSQL 实测。 | 条件成立 | [03/DS-13](03-domain-schema-invariants.md)、[04/REL-PERF-06、REL-PERF-09—12、REL-PERF-18—21、REL-PERF-23](04-backend-reliability-performance.md)、[16/SPB-09](16-security-privacy-boundaries.md)、[全局复核/GC-32](review/08-global-consistency-review.md) |
| EA-AUD-026 | Stream 与 Webhook 原始正文缺少与处理/重试窗口绑定的自动最小化和清理；具体保留期限尚未确定。审计历史和离职画像分别归入 `EA-AUD-025`、`EA-AUD-012`，不得用一个数据集的关闭证据代替另一个。 | 静态确认的治理缺口；政策待决策 | [16/SPB-09](16-security-privacy-boundaries.md)、[安全运维复核](review/05-security-operations-review.md)、[全局复核/GC-32](review/08-global-consistency-review.md) |
| EA-AUD-027 | 错误、校验、状态文案和交互完成反馈未形成“稳定 code + 结构化参数 + 前端本地化/状态机”边界；仍有原始异常、语言混排、错误密码策略、失败静默、旧响应覆盖新结果、越界分页、剪贴板假成功和会话过期无统一恢复动作。 | 静态确认 | [06/C-09—C-14](06-frontend-functional-bugs.md)、[08/I18N-03—I18N-16](08-i18n-and-user-copy.md)、[09/TF-03—TF-10、TF-13、TF-14、TF-17—TF-19、TF-21、TF-23—TF-26](09-toast-and-feedback.md)、[15/CTR-08](15-cross-layer-contracts.md)、[体验复核](review/06-user-experience-review.md) |
| EA-AUD-028 | 移动页头和多列表格布局、弱文本/焦点对比、组合框/Tab/Menu 键盘模型、动态状态播报和小图标命中区存在共享组件级缺口。 | 静态确认；部分隔离/真实浏览器确认 | [07/EA-UI-01—EA-UI-10、EA-UI-12](07-ui-layout-accessibility.md)、[体验复核](review/06-user-experience-review.md) |
| EA-AUD-029 | 前端测试结果不可重复、测试脚本参数转发失败、Playwright 环境不可复现，且现有浏览器套件不验证真实后端。 | 动态确认；具体失败数量和根因未稳定 | [12/F-01、F-03—F-05](12-frontend-e2e-test-decay.md)、[14/BCO-11](14-build-config-operations.md)、[测试复核](review/04-test-evidence-review.md)、[全局复核/GC-21、GC-23—GC-25](review/08-global-consistency-review.md) |
| EA-AUD-030 | 交接预览持行锁执行外部 HTTP，通知/生命周期上帝模块、重复授权判定、平行 CRM manifest 写入和分散前端契约增加了变更与恢复风险。 | 静态确认；部分严重度已降级 | [01/BAS-02、BAS-03、BAS-05—BAS-07](01-backend-architecture-smells.md)、[05/EA-FE-01、EA-FE-02、EA-FE-07](05-frontend-architecture-smells.md)、[架构复核](review/07-dead-code-architecture-review.md) |
| EA-AUD-031 | 数据服务 readiness、匿名健康信息分层、Stream 心跳存活、Action pin/权限拆分、工具版本、ASGI 文档、`.env.local` 解析器及前端分包预算存在确定的构建运维缺口；主包单入口 826.08 kB 已观察，实际首屏影响未测。 | 静态确认；匿名健康外部暴露和前端性能影响条件成立 | [04/REL-PERF-16](04-backend-reliability-performance.md)、[14/BCO-06—BCO-11](14-build-config-operations.md)、[16/SPB-11](16-security-privacy-boundaries.md)、[17/C-09](17-independent-full-sweep.md)、[安全运维复核](review/05-security-operations-review.md)、[全局复核/GC-33](review/08-global-consistency-review.md) |

### 5.4 P3：清理与待决策项

| 稳定编号 | 结论 | 状态 | 主要证据 |
| --- | --- | --- | --- |
| EA-AUD-032 | 已确认的无调用模块、函数、类型、历史 `blocked` 分支和多余导出应删除或收窄；Django 动态入口和运行中前端构建产物不得按普通死代码处理。 | 静态确认 | [13/D-01—D-09](13-dead-code-and-dev-junk.md)、[架构复核](review/07-dead-code-architecture-review.md) |
| EA-AUD-033 | legacy 目录引用、SDK 公开常量、静态 token facade 和 CRM seed 是否可删除取决于外部消费者或产品入口事实；没有白名单时不得长期保留。 | 待决策 | [11/BTD-06、BTD-07](11-backend-test-decay.md)、[13/R-01、R-02、R-04](13-dead-code-and-dev-junk.md) |
| EA-AUD-034 | 单因素本地超管、Django Admin 平行特权面、全部 App 基础目录可见性、授权版本究竟是 revision 还是不可变历史，以及通知/门户安全设置占位入口是否属于已承诺能力，均需要先形成明确产品/安全决定。 | 待决策 | [02/BR-01、BR-02、BR-04](02-backend-functional-bugs.md)、[03/DS-11](03-domain-schema-invariants.md)、[17/C-04](17-independent-full-sweep.md)、[全局复核](review/08-global-consistency-review.md) |
| EA-AUD-035 | 项目没有明确的浏览器/WebView 支持矩阵、未知路由策略和窄屏 Toast 验收基线；因此 `localStorage`、`ResizeObserver`、`crypto.randomUUID`、未知路由和 Toast 遮挡目前只能作为待验证风险，不能宣称已有功能故障。 | 静态确认的治理缺口；具体故障未验证 | [06/R-02—R-04](06-frontend-functional-bugs.md)、[17/H-01、H-02](17-independent-full-sweep.md)、[前端复核](review/02-frontend-evidence-review.md) |

### 5.5 根因簇归属补充

以下已确认子项容易因登记表采用根因簇而被误读为遗漏，实施和关闭时必须按对应稳定编号一并
处理：

- `EA-AUD-007` 同时覆盖 `BAS-03` 的“提交与批准落地采用不同有效授权成员口径”，不能只增加
  基础修订字段而保留两套成员计算。
- `EA-AUD-015` 同时覆盖 `BF-08`、`REL-PERF-25`、`REL-PERF-26` 以及 `TF-02`、`TF-11`、
  `TF-12`、`TF-16`、`TF-20` 的假成功、错误分类或在事实不完整时继续操作；`TF-01` 的
  非 JSON 2xx 与列表信封损坏不是同一解码特例，归入本项而不是 `EA-AUD-018`。
- `EA-AUD-018` 同时覆盖连接器映射重复键、损坏配置空对象、`C-05` 经限定后成立的本地 XOR
  校验缺口、资源选择器分页、运维筛选任意字符串、未知运维分区和坏数据下空 scope 语义；修复
  必须在输入/解码边界快速失败，不能增加读取纠正。
- `EA-AUD-019` 同时覆盖动作的权限和状态可用性，包括连接器映射写入、交接任务删除以及停用
  授权组恢复，不得只隐藏侧栏。
- `EA-AUD-027` 收纳其余已确认的反馈、国际化和前端局部状态缺口；其中会把未完成动作显示为
  成功或允许继续的子项已提升到 `EA-AUD-015`，不在两个登记项中重复计数。
- `EA-AUD-012`、`EA-AUD-025`、`EA-AUD-026` 分别关闭离职画像、审计/健康历史、Stream 与
  Webhook 数据集；它们共享保留矩阵，但索引、最小化、清理任务和验收证据分别记录，不能合并
  成一个“已清理”结论。

## 6. 被排除、降级或限定的结论

以下内容不得在后续汇报中恢复为未经限定的事实：

1. 不得声称存在“247 个独立问题”，也不得直接相加任何报告的严重度数量。
2. 不得声称当前服务已经确认公网可达；只能说仓库中的该部署编排若启用并暴露，会以开发级
   配置运行。
3. 不得声称前端稳定失败 10 项或 11 项，也不得声称已确认唯一根因是 Vitest 文件并发。
4. 不得声称 27 个 Playwright 业务场景失败；失败发生在浏览器启动之前。
5. 不得把 SDK 未设置正确安装入口造成的 5 个收集错误计为 SDK 产品缺陷。
6. `[06]/C-05` 所称“走完整流程后最终失败”被源码否定。成立范围仅是前端缺少接收策略 XOR
   校验，点击下一步会立即发出一次必失败且可见的 PATCH。
7. `[01]/BAS-01` 的“无法表达部分完成”过强。授权项与动作状态已共同保存部分事实；成立的是
   总览状态不自足、钩子步骤未成为一等状态。
8. `[01]/BAS-04` 的“外部连接器故障回滚授权”不准确。授权事务内只更新同库连接器 generation
   和 Outbox；数据库持久化失败继续使事务失败是正确的快速失败边界。
9. `[03]/DS-05` 的 Stream event ID 冲突需要上游契约或真实样本；在此之前保持条件风险，不按
   已确认高危事件丢失计数。
10. `[03]/DS-04`、`DS-08` 的数据库结构问题成立，但当前正式批量删除或跨 App 绕过路径未被
    证明，必须保留“条件成立”。
11. `[03]/DS-12` 不得写成已发生生产数据丢失；它是携带旧开发/试点数据升级时的发布阻断。
12. `[03]/DS-13` 缺少索引的事实成立，但具体索引和严重度要由 PostgreSQL `EXPLAIN`、基数和
    保留策略决定。
13. `[10]/MOT-01`、`MOT-02`、`MOT-05` 的装饰性动画要求被驳回；`MOT-03`、`MOT-06` 只保留
    pending、焦点、ARIA 和状态语义，不要求动画。
14. 不得要求每个 mutation 成功都弹 Toast。失败必须可见；成功反馈按风险和界面变化选择
    Toast、页内状态或单一可见结果。
15. 未知枚举不得作为合法业务行显示“未知状态”；解析必须快速失败，页面可显示本地化契约错误。
16. 受保护页面的移动截图、像素测量和无障碍结论必须区分真实后端页面、隔离渲染、源码契约、
    无障碍树和真实辅助技术测试。
17. 前端散列产物不是普通开发垃圾。运行中清理后必须立即重建、重启 Django，并用真实 HTTP
    响应验证新 manifest 与资源已加载。
18. 占位通知、安全设置、移动导航可发现性和成功反馈是否构成产品缺陷，必须结合已承诺能力或
    真实任务验证，不能仅凭组件存在提高严重度。

## 7. 总体结论

EasyAuth 当前的主要风险不是缺少功能，而是多个核心边界没有使用同一份权威事实：部署配置与
生产基线分叉，管理员权限与会话撤权分叉，审批命令与被审批版本分叉，异步任务返回值与外部动作
完成事实分叉，API 成功与数据契约分叉，前端能力与后端权限分叉，测试绿色与生产路径分叉。

项目尚未上线，这是一次性修正这些边界的窗口。整改应按
[整改路线图](remediation-roadmap.md)重建唯一 schema、领域状态机、API 契约、前端能力模型、
测试门禁和中文文档；不得增加兼容字段、双写、读取纠错、空结果兜底或长期兼容层。
