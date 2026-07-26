# 用户体验审计交叉复核

## 1. 复核范围与结论

本复核交叉检查以下四份报告：

- `07-ui-layout-accessibility.md`
- `08-i18n-and-user-copy.md`
- `09-toast-and-feedback.md`
- `10-motion-and-interaction.md`

复核重点是国际化范围、用户可见文案与内部诊断的边界、toast 与行内反馈的选择、动效是否真的必要、无障碍证据强度、布局复现，以及不同报告之间的重复根因。本轮未修改界面源码和原报告。

裁决口径如下：

- **确认**：源码足以直接证明缺口，或本轮浏览器复现与源码相互印证。
- **降级/限定**：事实部分成立，但严重度、适用范围、反馈载体或修复方案需要收窄。
- **重复**：与另一项是同一根因或同一整改单元，不应重复排期和计数。
- **矛盾**：把没有产品或无障碍必要性的装饰性动效缺失认定为缺陷，或建议与项目硬约束冲突。
- **未验证**：源码只说明风险条件存在，原报告和本轮均没有运行时证据证明结果实际发生。

| 报告 | 确认 | 降级/限定 | 重复 | 矛盾 | 未验证 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 07 | 8 | 3 | 0 | 0 | 1 |
| 08 | 10 | 3 | 3 | 0 | 0 |
| 09 | 20 | 3 | 3 | 0 | 0 |
| 10 | 1 | 1 | 1 | 3 | 0 |
| 合计 | 39 | 10 | 7 | 3 | 1 |

总判断：

1. 07、08、09 的主要事实基础可靠，但部分无障碍和触控结论需要把“代码一致性检查”与“真实辅助技术验证”分开。
2. 09 对 toast 与行内反馈的总体口径正确；需要避免把“明确成功反馈”机械等同于 toast，也不能用全局 mutation toast 造成重复播报。
3. 10 中只有 `MOT-04` 是独立、可保留的功能性问题。`MOT-01`、`MOT-02`、`MOT-05` 是装饰性动画要求，应明确驳回；`MOT-03`、`MOT-06` 只保留非动效的状态和语义部分。
4. 国际化范围由项目公开说明明确覆盖“每个页面”，不是只覆盖 React SPA，见 `README.md:69`、`README.md:131`。因此 Django 登录、安全和错误页属于双语范围。

## 2. 浏览器证据与证据边界

### 2.1 本轮独立浏览器验证

本轮访问运行中的 `http://localhost:8001/auth/local/`，取得以下结果：

- 在 `390×844` 视口，卡片宽度为 `358px`，左右各 `16px`，文档 `scrollHeight=845`，比视口多 `1px`。
- 在 `1280×800` 视口，文档 `scrollHeight=801`，同样多 `1px`。
- 无障碍树把“使用工作账号登录”宣告为按钮；DOM 实际是带 `role="button"` 的 `<a>`，见 `src/easyauth/accounts/templates/accounts/local_admin/login.html:250`。
- 产生 `1px` 滚动的源码条件与实测一致：顶栏内容高 `56px` 且另有 `1px` 边框，主区仍使用 `calc(100vh - 56px)`，见 `src/easyauth/accounts/templates/accounts/local_admin/login.html:41-54`、`:93-100`。

### 2.2 未能独立验证的业务页

访问 `/console/` 会跳转到外部 OIDC 登录页。本轮没有真实账号，也没有伪造登录态或业务数据。因此：

- `EA-UI-01`、`EA-UI-02` 可由布局源码直接支持，并且原报告记载了隔离浏览器渲染；本轮将其标为确认，但明确不是本轮真实业务页复现。
- `EA-UI-11` 没有本轮或原报告的实际裁剪截图，只能保留为未验证风险。
- 10 号报告已经明确所有动效结论均为代码推断，不能升级成浏览器实测结论。

### 2.3 无障碍证据强度

除 `EA-UI-10` 的真实无障碍树外，本轮没有使用 NVDA、JAWS、VoiceOver 等辅助技术，也没有取得 axe 扫描结果。因此：

- `EA-UI-04`、`EA-UI-06`、`EA-UI-08` 是依据 ARIA 交互契约和事件处理代码确认，不是读屏实测。
- `EA-UI-03`、`EA-UI-05` 是颜色值计算，不是浏览器自动化对比度审计。
- `EA-UI-09` 只证明组件没有显式扩大命中区；没有运行时测量目标间距例外，不能直接断言所有实例都违反 WCAG 2.5.8。

## 3. 07 号报告逐项裁决

| 报告项 | 裁决 | 复核证据与限定 |
| --- | --- | --- |
| `EA-UI-01` | 确认 | `PageHeader` 固定单行布局，动作区不可收缩，见 `frontend/src/components/PageHeader.tsx:12-18`；应用列表确实传入三个动作，见 `frontend/src/pages/console/ConsoleAppList.tsx:177-192`；移动端主内容裁剪横向溢出，见 `frontend/src/styles/responsive.css:58-61`。浏览器证据来自原报告的隔离渲染，不是本轮真实业务页。 |
| `EA-UI-02` | 确认 | 滚动容器存在，但表格只有 `min-w-full`，见 `frontend/src/components/ui/TablePrimitives.tsx:21-31`、`frontend/src/components/ui/tableStyles.ts:5`；表头和单元格没有列最小宽度，见 `frontend/src/components/ui/tableStyles.ts:11-14`。门户确有七列主表，见 `frontend/src/pages/portal/PortalPage.tsx:74-90`。浏览器证据仍限于原报告隔离渲染。 |
| `EA-UI-03` | 确认 | 弱文本和状态色 token 见 `frontend/src/styles/index.css:15-29`，小字号见 `frontend/src/styles/index.css:53-56`；状态标签直接消费这些颜色，见 `frontend/src/components/Badge.tsx:8-21`。这是公式计算与代码证据，不是本轮浏览器对比度扫描。 |
| `EA-UI-04` | 确认 | 选项是可聚焦按钮却只处理 `onPointerDown`，见 `frontend/src/components/UserSelect.tsx:82-101`；输入框使用方向键高亮但缺少 `aria-controls`、`aria-activedescendant` 和稳定选项 `id`，见 `frontend/src/components/UserSelect.tsx:135-180`、`:235-299`。属于代码契约确认，未做读屏实测。 |
| `EA-UI-05` | 确认 | 全局焦点环为半透明 `accent/50`，见 `frontend/src/styles/index.css:137-139`；认证页使用更弱的半透明深色轮廓，见 `src/easyauth/accounts/templates/accounts/local_admin/login.html:145-148`。结论来自颜色计算。 |
| `EA-UI-06` | 确认 | 工作区和门户审批都声明 `tablist/tab`，但所有 tab 保持默认 Tab 顺序，且没有方向键处理，见 `frontend/src/pages/console/ConsoleAppWorkspace.tsx:133-162`、`frontend/src/pages/portal/components/PortalApprovalsSection.tsx:232-249`。 |
| `EA-UI-07` | 降级/限定 | `StatusBanner` 本身没有 live 语义，见 `frontend/src/components/StatusBanner.tsx:20-30`，而全仓有大量调用点。问题仅适用于操作后动态插入且焦点不移动的错误或状态；首屏静态说明、页面导航后的错误不应默认 `role="alert"`。组件应要求调用方显式选择 `alert/status/off`，不能把所有 banner 一律改成 assertive。 |
| `EA-UI-08` | 确认 | 用户菜单声明 `menu/menuitem`，见 `frontend/src/components/shell/UserSummary.tsx:34-68`，但顶栏只处理外部点击和 Escape，见 `frontend/src/components/shell/Topbar.tsx:37-61`；语言与通知弹层的触发器没有程序化关联，见 `frontend/src/components/shell/LanguageSwitcher.tsx:23-59`、`frontend/src/components/shell/NotificationsButton.tsx:16-33`。这是键盘模型代码检查，不是辅助技术实测。 |
| `EA-UI-09` | 降级/限定 | `InfoTip`、用户 chip 删除和 toast 关闭按钮确实只有小图标且没有显式最小尺寸，见 `frontend/src/components/InfoTip.tsx:11-18`、`frontend/src/components/UserSelect.tsx:313-323`、`frontend/src/components/ui/Toast.tsx:261-268`。但 WCAG 2.5.8 允许目标间距例外，原报告未测实际中心间距；应按组件命中区缺少保证处理，不宜直接认定所有实例违规，也不宜维持“中”严重度。 |
| `EA-UI-10` | 确认 | 本轮真实页面无障碍树复现。源码是 `<a role="button">`，见 `src/easyauth/accounts/templates/accounts/local_admin/login.html:250`，链接角色与键盘行为不一致。 |
| `EA-UI-11` | 未验证 | 固定 `w-64` 且始终居中定位的条件存在，见 `frontend/src/components/InfoTip.tsx:19-24`，移动端又隐藏横向溢出，见 `frontend/src/styles/responsive.css:58-61`；但没有实际元素位置和裁剪矩形，不能确认指定页面必然裁剪。应先在 `320px`、`390px` 真实页面测量再入整改。 |
| `EA-UI-12` | 降级/限定 | `1px` 滚动已由本轮在两个视口独立复现，源码见 `src/easyauth/accounts/templates/accounts/local_admin/login.html:41-54`、`:93-100`。不同模板复制 token 也是事实，但“品牌视觉漂移”没有统一设计基线或并排浏览器证据；合并项应拆成“已确认的高度计算错误”和“样式事实源维护风险”，后者不是同等强度的用户缺陷。 |

## 4. 08 号报告逐项裁决

### 4.1 国际化范围与字符串边界

用户可见字符串包括可见文本、`aria-label`、placeholder、toast、表单错误、下载或复制结果、浏览器直接响应，以及会被前端原样展示的 API `message`、`last_error`。内部日志、仅服务端保存的异常、代码标识符、协议字段名本身不属于国际化缺口；只有它们越过展示边界时才属于问题。

项目 README 明确承诺“每个页面”提供简体中文与 English，见 `README.md:69`，并说明可在顶栏运行时切换，见 `README.md:131`。因此不能把 Django 模板排除在产品国际化范围之外。

| 报告项 | 裁决 | 复核证据与限定 |
| --- | --- | --- |
| `I18N-01` | 确认 | `GuideTab` 和 `ManifestTab` 直接写中文，代表性证据见 `frontend/src/pages/console/workspace/tabs/GuideTab.tsx:20-39`、`frontend/src/pages/console/workspace/tabs/ManifestTab.tsx:79-130`、`:161-191`。 |
| `I18N-02` | 确认 | 分页、复制和主导航的用户可见/无障碍文案硬编码中文，见 `frontend/src/components/ui/PaginationBar.tsx:39-70`、`frontend/src/components/CodeBlock.tsx:35-38`、`frontend/src/components/shell/ShellNav.tsx:21`。 |
| `I18N-03` | 降级/限定 | 当前 locale 只存在浏览器状态，见 `frontend/src/i18n/I18nProvider.tsx:28-57`，API 请求不传 locale，见 `frontend/src/lib/api.ts:63-100`，后端又返回自然语言。混合语言问题成立，但“必须增加 `Accept-Language`”不是唯一或首选结论；若 API 只返回稳定错误码和结构化参数，前端按当前 locale 翻译，就不需要服务端语言通道。 |
| `I18N-04` | 确认 | 原始异常被写入并返回到可见字段的链路成立，例如交接错误落库见 `src/easyauth/lifecycle/services.py:388-393`，API 返回见 `src/easyauth/admin_console/lifecycle_api.py:850`，前端展示见 `frontend/src/pages/console/lifecycle/HandoverTaskDetail.tsx:321-342`。具体会泄露何种主机、端口或英文内容取决于异常，属于代码确认的边界缺陷，不是本轮运行时泄露复现。 |
| `I18N-05` | 重复 | 与 `TF-15` 是同一校验契约问题：后端把模型校验字符串放进 `details`，前端没有字段映射。代表性证据见 `src/easyauth/admin_console/approval_rules_api.py:134-136`、`src/easyauth/admin_console/apps_api.py:215-218`、`frontend/src/lib/api.ts:184-192`。合并为一个“结构化字段错误 + 前端本地化”整改项。 |
| `I18N-06` | 降级/限定 | 未知状态回显原始枚举的事实成立，见 `frontend/src/lib/status.ts:22-145`、`frontend/src/pages/console/lifecycle/lifecycleLabels.ts:12-79`。但原报告建议统一显示“未知状态”会掩盖契约漂移，与项目快速失败约束不一致；应在响应解析或穷尽映射处失败并显示页面级契约错误，原始枚举只进诊断日志。 |
| `I18N-07` | 确认 | 员工门户主表直接展示 `kind`、permission/scope key、来源枚举和版本，见 `frontend/src/pages/portal/PortalPage.tsx:283-321`；这已经越过内部协议与用户文案边界。具体信息层级优先级仍是代码推断，未做用户研究。 |
| `I18N-08` | 确认 | 响应解析器构造包含 JSON 路径和分页公式的异常，见 `frontend/src/pages/portal/portalListPayload.ts:55-104`，页面直接展示 `error.message`，见 `frontend/src/pages/portal/PortalPage.tsx:103-107`、`:175-179`。快速失败应保留，但完整路径应进入诊断而非员工主文案。 |
| `I18N-09` | 重复 | 固定中文 HTTP 兜底位于 `frontend/src/lib/api.ts:166-195`，与 `I18N-03` 的本地化边界和 `TF-13` 的传输错误归一化属于同一 `apiRequest` 整改单元，不应单独实施三套错误基础设施。 |
| `I18N-10` | 确认 | 后端策略最小长度为 12，见 `src/easyauth/config/settings/base.py:169-176`；安全设置页却写 8 并设置 `minlength="8"`，见 `src/easyauth/accounts/templates/accounts/local_admin/security.html:378-394`。这是直接误导，不只是术语问题。 |
| `I18N-11` | 确认 | 产品承诺覆盖每个页面，见 `README.md:69`。登录模板固定 `lang="zh-Hans"` 并硬编码中文，见 `src/easyauth/accounts/templates/accounts/local_admin/login.html:3-7`、`:236-265`；403/404 同类，见 `src/easyauth/config/templates/403.html:3-7`、`:68-75`、`src/easyauth/config/templates/404.html:3-7`、`:190-194`。 |
| `I18N-12` | 降级/限定 | `str(error)` 直返路径存在，见 `src/easyauth/accounts/local_admin_views.py:162-171`、`:329-338`、`:386-393`。当前具体异常文本是否为英文或含内部信息未运行时触发，因此确认的是“不稳定自然语言契约”，不是每条路径都已发生泄露。 |
| `I18N-13` | 确认 | 运营筛选器把 `app_key`、`actor_id`、`created_from`、`current` 等协议名直接作为 placeholder 和无障碍名称，见 `frontend/src/pages/console/OperationsPage.tsx:387-443`。 |
| `I18N-14` | 重复 | 与 `I18N-05`、`TF-15` 同属“后端技术字符串代替结构化字段错误”。代表性证据见 `src/easyauth/admin_console/managed_scope_policy_api.py:132-176`、`src/easyauth/admin_console/lifecycle_api.py:594-600`。 |
| `I18N-15` | 确认 | 术语不一致可直接由消息目录证明，例如“概览/总览”见 `frontend/src/i18n/messages.ts:57`、`:317`，“停用/禁用”见 `frontend/src/i18n/messages.ts:23-25`、`:508`、`:781`。属于低优先级一致性问题。 |
| `I18N-16` | 确认 | 测试只扫描固定白名单，见 `frontend/src/i18n/noHardcodedChinese.test.ts:12-56`，而 `GuideTab`、`ManifestTab`、`PaginationBar`、`CodeBlock`、`ShellNav` 均不在其中；Manifest 测试还直接按中文查找，见 `frontend/src/pages/console/workspace/tabs/ManifestTab.test.tsx:34-47`。 |

## 5. 09 号报告逐项裁决

### 5.1 反馈载体复核

09 号报告的基础判定矩阵可以保留，但应补充以下约束：

- 字段错误、下拉查询错误、对话框提交错误、区块加载错误优先行内展示。
- 行级或跨区块的瞬时操作失败适合 toast，但错误必须包含对象或操作上下文。
- 后台轮询失败只能在数据区显示“数据可能已过期”，不能周期性弹 toast。
- 401 应由壳层合并为单一持久 banner 或 modal，并提供重新登录动作。
- 重要操作成功需要明确确认，但载体可以是 toast、按钮旁“已保存”、持久状态行或焦点可达的结果区；不能机械规定必须 toast。
- 全局兜底只可处理明确未被局部消费的 mutation。无条件全局 `onError` 会造成 toast 与行内提示重复。

| 报告项 | 裁决 | 复核证据与限定 |
| --- | --- | --- |
| `TF-01` | 确认 | `apiRequest` 对任何 `response.ok` 返回解析值，见 `frontend/src/lib/api.ts:97-103`；非 JSON 被转成 Symbol 而不抛错，见 `frontend/src/lib/api.ts:151-164`。设置保存会把该值当成功并 toast，见 `frontend/src/pages/console/ConsoleSettingsPage.tsx:71-77`。 |
| `TF-02` | 确认 | 应用详情查询错误未消费，见 `frontend/src/pages/console/onboarding/AppOnboardingWizard.tsx:67-72`；只要 URL 有 `app_key` 就渲染绿色已有应用摘要并允许继续，见 `frontend/src/pages/console/onboarding/AppOnboardingWizard.tsx:267-281`。应使用步骤内行内错误，不用 toast。 |
| `TF-03` | 确认 | 应用状态 mutation 只有成功回调，见 `frontend/src/pages/console/ConsoleAppList.tsx:63-70`，触发点没有错误展示，见 `frontend/src/pages/console/ConsoleAppList.tsx:121-128`。行级 error toast 合适。 |
| `TF-04` | 确认 | 删除 mutation 无错误回调，见 `frontend/src/pages/console/ConsoleAppList.tsx:71-80`，确认框也没有错误属性，见 `frontend/src/pages/console/ConsoleAppList.tsx:258-266`。用户仍在对话框上下文，应优先对话框行内错误，不能再叠加 toast。 |
| `TF-05` | 确认 | Scope 开关 mutation 没有错误消费，见 `frontend/src/pages/console/workspace/tabs/CatalogTab.tsx:133-142`、`:198-205`。行级 error toast 合适。 |
| `TF-06` | 确认 | 用户查询存在，见 `frontend/src/components/UserSelect.tsx:22-39`，`OptionList` 却只有 loading/empty，没有 error，见 `frontend/src/components/UserSelect.tsx:58-103`。搜索会随输入重试，必须下拉框内行内错误，禁止逐次 toast。 |
| `TF-07` | 确认 | `!status` 与 `supported=false` 都直接返回空，见 `frontend/src/pages/console/TwoFactorSection.tsx:45-53`。查询失败应显示区块错误与重试。 |
| `TF-08` | 确认 | 运行记录每 30 秒轮询，见 `frontend/src/pages/console/workspace/tabs/ConnectorTab.tsx:935-950`，错误时降为空数组并显示空态，见 `frontend/src/pages/console/workspace/tabs/ConnectorTab.tsx:951-992`。首次失败用区块错误，旧数据刷新失败用区块 warning，禁止 toast。 |
| `TF-09` | 确认 | 三个 mutation 错误以固定 `??` 优先级合并，见 `frontend/src/pages/console/workspace/credentials/useCredentialsActions.ts:147`，reset 又不覆盖 disable，见 `frontend/src/pages/console/workspace/credentials/useCredentialsActions.ts:149-153`。应移除聚合 effect，按操作产生唯一反馈。 |
| `TF-10` | 确认 | `writeText` 不等待、不捕获，且 API 不存在时仍设置 copied，见 `frontend/src/components/CodeBlock.tsx:19-24`。成功只需要按钮内“已复制”；失败可用按钮旁行内错误或单一 error toast。此项与 `I18N-02` 使用同一组件，但一个是结果真实性，一个是文案国际化，不应合并成同一验收断言。 |
| `TF-11` | 确认 | 后端允许 `revoked_count=0` 仍返回 accepted，见 `src/easyauth/admin_console/operations_api.py:155-180`、`src/easyauth/grants/services.py:78-96`；前端任何 2xx 都显示完成，见 `frontend/src/pages/console/OperationsPage.tsx:168-181`。 |
| `TF-12` | 确认 | 决定已提交后的授权失败携带 `decision_committed=true`，见 `src/easyauth/access_requests/approvals.py:271-291`；控制台仍按普通 422，见 `src/easyauth/admin_console/operations_approvals_api.py:123-144`，前端只特判 409，见 `frontend/src/pages/console/OperationsPage.tsx:123-141`。 |
| `TF-13` | 重复 | fetch/JSON 解析异常未归一化，见 `frontend/src/lib/api.ts:97-100`、`:154-160`。与 `I18N-04`、`I18N-09` 同属 `apiRequest` 错误边界，应一次性实现稳定 code、保留 cause 供诊断、由调用方决定行内或 toast。 |
| `TF-14` | 确认 | 根渲染没有错误边界，见 `frontend/src/main.tsx:24-35`，路由树也没有边界，见 `frontend/src/App.tsx:55-99`。崩溃应使用可恢复页面，不是 toast。 |
| `TF-15` | 重复 | 与 `I18N-05`、`I18N-14` 是同一字段错误契约。后端把校验字符串塞进 `details.errors`，见 `src/easyauth/admin_console/apps_api.py:215-218`、`:522-528`；创建应用只消费顶层 message，见 `frontend/src/pages/console/ConsoleAppList.tsx:248-255`。字段行内错误是唯一主反馈，表单摘要可选，禁止再弹 toast。 |
| `TF-16` | 确认 | 后端返回真实 `queued`，见 `src/easyauth/admin_console/connectors_api.py:296-307`；`false` 表示 generation 已推进但不需新投递，见 `src/easyauth/connectors/services.py:97-142`；前端不读 payload，统一称已入队，见 `frontend/src/pages/console/workspace/tabs/ConnectorTab.tsx:244-260`。 |
| `TF-17` | 确认 | 后端把所有钉钉错误归为同一消息，见 `src/easyauth/admin_console/notification_channel_api.py:124-131`；前端只能原样放入 error toast，见 `frontend/src/pages/console/workspace/tabs/IntegrationTab.tsx:254-265`。单一 toast 合适，但正文应按安全稳定 code 提供行动建议。 |
| `TF-18` | 确认 | 两处 `file.text()` 都没有失败分支，见 `frontend/src/pages/console/onboarding/AppOnboardingWizard.tsx:622-634`、`frontend/src/pages/console/workspace/tabs/ManifestTab.tsx:163-176`。文件控件旁行内错误优先，不建议在报告中继续保留“行内或 toast 二选一”的模糊口径。 |
| `TF-19` | 确认 | 导出直接 `window.location.assign`，见 `frontend/src/pages/console/workspace/tabs/ManifestTab.tsx:182-189`，失败会替换 SPA。下载失败适合单一 error toast；浏览器下载本身已是成功反馈，不要再发 success toast。 |
| `TF-20` | 确认 | grant items 查询错误未展示，见 `frontend/src/pages/console/lifecycle/HandoverTaskDetail.tsx:383-390`，页面只显示模板错误，见 `frontend/src/pages/console/lifecycle/HandoverTaskDetail.tsx:447-449`，确认仍可执行，见 `frontend/src/pages/console/lifecycle/HandoverTaskDetail.tsx:505-514`。必须面板内行内错误并阻断依赖不完整数据的确认。 |
| `TF-21` | 确认 | error toast 永久保留，见 `frontend/src/components/ui/Toast.tsx:54-60`，push 无条件追加，见 `frontend/src/components/ui/Toast.tsx:126-136`，全部队列都会渲染，见 `frontend/src/components/ui/Toast.tsx:209-225`。需要 key、替换和数量边界；不需要为此增加动画。 |
| `TF-22` | 重复 | 全局 QueryClient 确实没有 mutation 错误策略，见 `frontend/src/lib/query.ts:3-9`，但这不是独立用户缺陷，而是 `TF-03`、`TF-04`、`TF-05` 的架构性重复说明。优先使用封装和测试要求反馈策略；若没有可靠的“已消费”标记，不应增加全局 error toast。 |
| `TF-23` | 确认 | API 返回结构化 401，见 `src/easyauth/admin_console/request_guards.py:16-23`；前端只构造普通 `ApiError`，见 `frontend/src/lib/api.ts:184-195`，壳层只处理首次没有用户，见 `frontend/src/App.tsx:49-75`。应合并为单一会话失效恢复界面。 |
| `TF-24` | 降级/限定 | 保存成功仅更新缓存，见 `frontend/src/pages/console/ConsoleAppWorkspace.tsx:215-227`，确实没有显式“已保存”。但 success toast 不是唯一正确载体；按钮旁可访问的“已保存”状态同样成立，并可能比短时 toast 更接近操作对象。 |
| `TF-25` | 降级/限定 | 两步验证成功后更新权威状态并关闭弹窗，代表性证据见 `frontend/src/pages/console/TwoFactorSection.tsx:220-225`、`:301-306`、`:471-481`、`:560-565`。这已经提供一部分可见结果，因此不能仅凭“没有 toast”定为中严重度；应先确认状态行变化是否清楚、是否被焦点读到，再决定 toast 或页面内状态。 |
| `TF-26` | 降级/限定 | 角标查询失败与 0 条都返回空字符串，见 `frontend/src/components/shell/Sidebar.tsx:72-84`，事实成立。但导航角标是辅助信息，主审批页已有完整错误反馈时，不一定需要在导航加入警告和 tooltip；保留低优先级，并避免后台重取产生 toast。 |

## 6. 10 号报告逐项裁决

动效只有在它传递了无法由文字、语义、焦点、选中态、忙碌态或布局稳定性充分表达的信息时，才可能成为功能性要求。淡入、位移、缩放、退出和列表重排动画本身不是可用性或无障碍验收条件。任何实现还必须在 `prefers-reduced-motion: reduce` 下不依赖运动表达状态。

| 报告项 | 裁决 | 复核证据与限定 |
| --- | --- | --- |
| `MOT-01` | 矛盾 | `AppShell` 只按 pathname 触发路由入场动画是事实，见 `frontend/src/components/AppShell.tsx:19-31`；工作区 tab 有 `aria-selected`、指示条和明确 tabpanel，见 `frontend/src/pages/console/ConsoleAppWorkspace.tsx:133-175`；向导也有步骤器并按步骤渲染，见 `frontend/src/pages/console/onboarding/AppOnboardingWizard.tsx:97-144`。没有证据证明淡入和位移是完成任务所必需。驳回给 tab/步骤强制增加方向性动画的要求；真正需要补的是 `EA-UI-06` 的键盘 tab 语义。 |
| `MOT-02` | 矛盾 | Dialog 瞬时挂载/卸载是事实，见 `frontend/src/components/Dialog.tsx:45-88`，但它已在打开时移入焦点、关闭时恢复焦点并管理滚动锁，见 `frontend/src/components/Dialog.tsx:109-156`。淡入、缩放、退出等待都属于装饰性要求，不能作为中严重度缺陷。顶栏菜单的焦点和 ARIA 问题保留在 `EA-UI-08`，与是否有退出动画无关。 |
| `MOT-03` | 重复 | 应用删除成功后关闭对话框再失效查询、列表行没有 pending 状态，见 `frontend/src/pages/console/ConsoleAppList.tsx:71-79`、`:224-238`。应保留“明确对象级成功反馈、请求中禁用目标、删除后合理焦点落点”等非动效要求，并与 `TF-04` 合并；透明度、高度和行退出动画不是必要条件，明确驳回。 |
| `MOT-04` | 确认 | 公共 Button 加载时只有对读屏隐藏的 spinner，按钮没有 `aria-busy` 或加载文案，见 `frontend/src/components/Button.tsx:36-64`；减弱动效会把动画压到一次，见 `frontend/src/styles/index.css:188-196`。应增加非运动的可见或隐藏加载文本及忙碌语义。此项是代码推断，尚未做读屏实测。 |
| `MOT-05` | 矛盾 | toast 直接加入和移除属实，见 `frontend/src/components/ui/Toast.tsx:77-83`、`:126-135`、`:209-225`，但没有证据说明 120–180ms 淡入、位移和布局过渡是理解反馈所必需。保留 `TF-21` 的去重、替换、数量上限和持久错误规则，驳回动画要求。 |
| `MOT-06` | 降级/限定 | 自定义“按应用分别设置”按钮缺少 `aria-expanded` 和关联目标，见 `frontend/src/pages/console/lifecycle/HandoverWizard.tsx:382-386`，这是应修的语义缺口；原生 `<details>/<summary>` 已有正确展开语义，见 `frontend/src/pages/console/lifecycle/HandoverTaskDetail.tsx:331-346`。两处瞬时展开都不是动效缺陷，不需要复制权限树的复杂存在生命周期。 |

## 7. 跨报告重复关系

| 合并整改单元 | 涉及报告项 | 源码锚点 | 复核结论 |
| --- | --- | --- | --- |
| API 错误与本地化边界 | `I18N-03`、`I18N-04`、`I18N-09`、`TF-13`、`TF-23` | `frontend/src/lib/api.ts:97-103`、`:154-195` | 建立稳定错误码、结构化参数、传输异常归一化、前端按 locale 翻译、401 单一恢复入口；不要并行增加多套错误设施。 |
| 字段校验契约 | `I18N-05`、`I18N-14`、`TF-15` | `src/easyauth/admin_console/apps_api.py:215-218`、`frontend/src/lib/api.ts:184-192` | 合并为字段错误 schema 和前端字段映射；禁止把模型异常字符串作为用户文案。 |
| 动态状态播报 | `EA-UI-07` 与 09 中多个行内反馈项 | `frontend/src/components/StatusBanner.tsx:20-30` | 反馈位置和 live 语义是两个维度；先选行内/toast，再按是否动态且需播报选择 `alert/status/off`。 |
| 复制组件 | `I18N-02`、`TF-10` | `frontend/src/components/CodeBlock.tsx:19-38` | 同一组件、两个独立验收点：文案走 i18n；成功必须等待 Clipboard Promise。 |
| 删除反馈 | `TF-04`、`MOT-03` | `frontend/src/pages/console/ConsoleAppList.tsx:71-79`、`:258-266` | 以 `TF-04` 为主，补目标级 pending、明确结果和焦点；不要求行退出动画。 |
| 顶栏弹层 | `EA-UI-08`、`MOT-02` | `frontend/src/components/shell/UserSummary.tsx:34-68`、`frontend/src/components/shell/Topbar.tsx:37-61` | 保留 ARIA、键盘和焦点整改；删除进入/退出动画要求。 |
| Toast 队列 | `TF-21`、`MOT-05` | `frontend/src/components/ui/Toast.tsx:54-60`、`:126-136` | 保留去重、替换和数量上限；删除动画要求。 |
| mutation 反馈治理 | `TF-03`、`TF-04`、`TF-05`、`TF-22` | `frontend/src/lib/query.ts:3-9` | `TF-22` 不另算用户缺陷；通过封装、元数据和测试防漏，不能无条件全局 toast。 |

## 8. 建议后的实施优先级

1. 先处理假成功、静默失败和错误伪装为空态：`TF-01` 至 `TF-12`、`TF-16`、`TF-20`。
2. 一次性建立错误契约与国际化边界：合并 `I18N-03`、`I18N-04`、`I18N-05`、`I18N-09`、`I18N-14`、`TF-13`、`TF-15`、`TF-23`。
3. 修复浏览器和代码均有强证据的布局/无障碍问题：`EA-UI-01` 至 `EA-UI-06`、`EA-UI-08`、`EA-UI-10`、`MOT-04`。
4. 补齐生产组件国际化、Django 页面和全量测试护栏：`I18N-01`、`I18N-02`、`I18N-11`、`I18N-13`、`I18N-16`。
5. 最后评估低优先级项：图标命中区、导航角标、明确成功反馈的具体载体和 tooltip 碰撞实测。
6. 不把 `MOT-01`、`MOT-02`、`MOT-05` 的装饰性动画纳入整改；`MOT-03`、`MOT-06` 只实施状态、焦点和 ARIA 语义部分。

## 9. 验收证据要求

- 浏览器验证必须注明是真实后端数据页、隔离渲染还是静态模板，不得混写。
- 无障碍结论至少区分源码契约检查、无障碍树、自动扫描和真实辅助技术测试。
- 颜色对比必须记录前景、背景、字号和计算值；不能以肉眼“偏淡”代替证据。
- 移动布局应在 `320px`、`390px`、`768px`、`900px` 测量实际矩形、裁剪和滚动宽度。
- 每个错误场景只保留一个主反馈载体；若同时有字段错误和摘要，摘要不得重复逐字段播报。
- 所有加载、成功、失败和展开状态在关闭动效或 `prefers-reduced-motion: reduce` 下仍必须可理解。
- 动画验收只检查不妨碍操作、可减弱和不延迟语义状态，不要求为了“更顺滑”而新增动画。
