---
type: crystallization
title: "DueDateHQ — 产品设计探索日志"

authors:
  - name: "Xuan"
    role: "product thinker / initiator"
    type: human
  - name: "Claude"
    model: "claude-sonnet-4-6"
    role: "synthesis partner"
    type: ai

platform: "claude.ai"
location: "Gilbert, Arizona / Phoenix metro"
timestamps:
  conversation_start: "2026-04-19T21:00:00-07:00"
  synthesis_created: "2026-04-19T21:30:00-07:00"
  last_updated: "2026-04-19T21:30:00-07:00"

conversation_scale: { turns: ~40, compacted: false }

sources:
  - { type: conversation, id: "current", description: "完整产品设计对话" }
  - { type: upload, path: "/mnt/user-data/uploads/", description: "DueDateHQ 商业计划书文本 + 截图" }

entities_crystallized:
  - DueDateHQ
  - Sarah（目标用户原型）
  - Fetch / Manage / Notify（三件核心事）
  - CLI-first 架构
  - 弱提醒 / 强提醒分层
  - 对话驱动 + 动态渲染

blindspot: "定价敏感性未测试；规则库维护的人工成本边界未量化；语音识别在税务术语上的准确率未验证"
confidence: 0.88

coverage:
  included:
    - { source: "current session", range: "full", mode: "A" }
    - { source: "商业计划书", path: "/mnt/user-data/uploads/", range: "full" }
  completeness: "full"
  processing_modes: ["A"]
---

# DueDateHQ — 产品设计探索日志

> 这是一份编辑过的探索日志，记录了从零开始推导 DueDateHQ 产品形态的完整思维过程。对话从分析一份现有商业计划书开始，逐步深入到功能边界、架构设计、交互哲学，最终形成了一个与原始计划书有显著差异的产品主张。保留推导路径，因为结论的价值来自推导过程。

---

## 一、问题本质：不是日历，是认知负担

对话从一句话定性开始：DueDateHQ 是帮 CPA 追踪美国税务截止日期的 compliance calendar 工具。但这个定性很快被推翻了。

商业计划书里描述的痛点——一名独立 CPA 服务 80 位客户，跨越 10 个州，理论上需要追踪数百个截止日期——这个痛点不是"工具不够多"，而是现有工具全部要求 CPA 自己承担信息处理的认知负担。Excel 手工录入、Google Calendar 手工创建条目、File In Time 功能接近但数据不更新。

**[SPARK]** 核心洞察在这里：CPA 的核心焦虑不是"找不到信息"，而是"不知道自己是不是漏了什么"。这种焦虑是持续性的背景噪音。产品要解决的是这种不确定感，而不是日历管理。
^[source: synthesis, context: 从商业计划书痛点分析到用户心理状态的推导]

---

## 二、功能边界：三件事，不多不少

从问题本质倒推，CPA 的核心工作流是：知道什么时候要做什么事 → 记住它 → 在对的时间被提醒。对应三个动词：**Know / Store / Remind**，产品里叫 **Fetch / Manage / Notify**。

**[DECISION]** 三件事的工程量比定为 Fetch 6 : Notify 3 : Manage 1。Manage 做薄是明确的设计决策，它只是触发器，不是产品重心。

**Fetch** 是护城河。竞品全部败在这里——数据过时、手工维护、覆盖不全。File In Time 有近 200 条规则但不自动更新，Karbon/Canopy 州税日期仍需手工录入。能做到规则库自动更新、24 小时内推送变更，这一点本身足以让用户不离开。

**Notify** 是产品唯一的前台。Fetch 和 Manage 是输入，Notify 是产品的唯一出口。用户每天感知到这个产品，就是通过提醒感知的。Google Calendar 的问题不是提醒本身，而是提醒没有上下文——只知道"到期了"，不知道对应哪个客户、什么税种、该做什么动作。

**Manage** 是胶水层。本质上只有两个人工操作：录入客户、标记完成。其他全部自动化。

---

## 三、CLI-first 架构：面向 Agent 的未来设计

**[DECISION]** CLI 的存在不是为了让 CPA 手写命令——他们不会这么做。CLI 是为了给 Agent 提供一种快速的调试和使用手段，是面向未来的设计。

这个决策带来了一个关键架构原则：**CLI-first，UI 作为 CLI 的可视化包装**。UI 里每一个按钮点击，背后对应一条 CLI 命令。这意味着 UI 的功能边界 = CLI 的功能边界，不会多也不会少。Agent 接管时，替换的只是输入层，业务逻辑不动。

```
外部 Agent / 第三方集成
        ↓
    REST API / Webhook        ← 对外暴露
        ↓
    CLI layer                 ← 所有能力在此定义
        ↓
    Core Engine               ← 业务逻辑（只实现一次）
        ↓
    Data layer
```

按钮少这个要求在这个架构下有了更强的约束依据：UI 按钮数量 ≈ CLI 命令数量。命令越少，Agent 的 tool set 越干净，调用越可靠。这不只是 UX 审美，是 Agent 可靠性的工程要求。

### CLI 命令集（完整版，即产品功能边界）

```bash
# 客户
duedate client add <name> --entity <type> --states <list>
duedate client list
duedate client update <id>
duedate client remove <id>

# Deadline
duedate deadline list --client <id> --days <n>
duedate deadline complete <id>
duedate deadline snooze <id> --until <date>
duedate deadline override <id> --date <date>
duedate deadline add <client_id> --type <tax_type> --date <date>

# 信息获取
duedate fetch --source irs
duedate fetch --state <state>
duedate fetch --all

# 提醒
duedate notify config --channel <email|sms|slack>
duedate notify preview
duedate notify history

# 查询 / 对话
duedate today
duedate ask "<自然语言问题>"

# 系统
duedate log --last 24h
duedate export --client <id> --format <csv|pdf>
```

命令总数：21 条。这就是产品的完整功能边界。

---

## 四、产品形态：对话驱动 + 动态渲染

**[DECISION]** 这是对话中最重要的一次形态跃迁。产品不是带聊天框的 dashboard，而是对话即界面——页面本身是对话的输出物，不是预先设计好的静态布局。

两种输入，完全等价：语音和打字。输入方式不影响任何功能，只是偏好问题。

系统的每次回应由两部分同时构成：**语言回应**（一句话，说结论）+ **视图渲染**（根据当前上下文实时生成用户需要看到的那块信息）。

视图不是固定模板，是按需生成的。视图组件只有五种：ListCard / ClientCard / ChangeNoticeCard / ConfirmCard / CalendarView。前端不做任何业务判断，只负责渲染。

```json
{
  "message": "有3件事，最紧急的今天截止",
  "view": {
    "type": "ListCard",
    "data": [...]
  }
}
```

**[SPARK]** 这个形态为什么比传统 dashboard 更对：传统 dashboard 把所有信息同时在场，认知负担在用户身上。对话驱动把认知负担转移给系统——系统决定现在该呈现什么，用户只需要响应。Sarah 每次打开产品，不需要想"我该看哪里"。这是 *complexity hiding*——把复杂性藏起来，而不是消灭它。
^[source: synthesis, context: 对话驱动形态的深层逻辑推导]

`duedate today` 是产品的默认启动状态。用户打开产品，不是看到空白对话框，也不是看到全量日历，而是直接看到今天的待决策列表，按紧急程度排序，最多显示 5 条。

---

## 五、获取 — 做到极致

目标：比用户更早知道规则变了。

信息源分三级：一级是官方权威（IRS.gov、50 州税务局、FEMA、Federal Register）；二级是加速预警（Thomson Reuters、Bloomberg Tax、AICPA tax alert）；三级是兜底验证（Reddit r/taxpros、专业税务论坛）。一级是数据来源，二级是预警信号，三级是异常检测。

轮询频率：IRS + FEMA 每 15 分钟，50 州税务局每 1 小时，二级信息源每 6 小时。

抓到原始文本后，Claude Sonnet 解析成结构化数据，包含 type、affected_states、tax_type、old_date、new_date、reason、confidence、source_url、effective_immediately 字段。置信度低于 0.85 的进人工审核队列，不自动推送。

**极致的标准：** 官方公告发布到系统更新完成，端到端不超过 15 分钟。

---

## 六、处理 — 做到极致

目标：变更发生后，系统自动知道影响谁、影响什么、该怎么改。

处理分三步：

**第一步，影响范围计算。** 纯数据库查询，不调 AI。变更的 affected_states × tax_type，匹配所有符合条件的客户，输出受影响客户列表和对应 deadline ID。速度快，成本低。

**第二步，更新决策。** 按变更类型分路：灾难延期官方确认 → 直接更新，事后告知；灾难延期预警阶段 → 标记"可能延期"，推确认卡给用户；立法变更影响确定 → 直接更新；立法变更影响不确定 → 进人工审核；规则新增 → 推"可能适用"建议，用户确认后才加入。

**第三步，版本控制。** 每次 deadline 被更新，保留完整历史，附原始来源链接。用户永远可以追溯"这个日期为什么变了"。这是产品信任度的基础。

**极致的标准：** 影响范围计算完成，所有受影响客户的 deadline 全部更新，端到端不超过 2 分钟。

---

## 七、提醒 — 做到极致

目标：让用户在正确的时间，以正确的方式，对正确的事做出响应。

### 强提醒：逼迫响应

时间层次：30 天前预告、14 天前行动提醒、7 天前重点提醒、1 天前最终警告、当天紧急。

对于 PTE 选举等不可撤销的截止日，从 30 天前开始，用户不响应就升级频率：30 天前正常提醒，14 天前附后果说明，7 天前要求明确回应，3 天前最高级别所有渠道同时触达。不允许静默忽略。

每条提醒携带五个元素：客户名、税种、截止日、建议动作、一个响应动作（完成/延期/不适用）。用户在提醒本身就能完成响应，不需要打开产品再操作。

### 弱提醒：管家式告知

**[DECISION]** 系统自动处理的事情（灾难延期官方确认后自动更新 deadline），不打断用户，不推送实时通知。等自然节点汇总：当天收工前"今天系统处理了 N 件事"，第二天早上顺带在今日待办下方一行灰色小字。

**[SPARK]** 管家的语感是："顺便告诉您，已经处理好了。"不是"请注意！发生了重要变化！"存在感低，信任感高。这才是好管家的状态。弱提醒的具体形式留给用户反馈迭代，或给用户选项——这个细节不影响核心设计。
^[source: human, context: "需要保护用户的精力，有些事情不必用户准许"]

### 渠道优先级

应用内始终推送（基础层），邮件用于 7 天前及以上，SMS 用于 1 天前和当天，Slack 用户配置后启用。当天截止的提醒，SMS 默认强制开启，不允许关闭。

---

## 八、授权边界：什么需要用户决定

**[DECISION]** 这是设计哲学的核心边界，由用户明确提出："需要保护用户的精力，有些事情不必用户准许。"

系统默默做、事后告知的：规则库更新、受影响客户 deadline 自动同步、例行年度调整、灾难延期官方确认后的更新。这些事情的共同特征是结果确定、没有歧义、做错了可以撤销。

必须用户决定的：标记 deadline 为已完成、主动放弃或延期某个选择（如 PTE）、新客户录入、手动覆盖系统推算的 deadline、延期申请状态更新。这些涉及客户的真实状态，系统无法独立判断。

这条边界画清楚之后，产品的交互密度自然降下来了。Sarah 每次打开产品，看到的只有需要她做决定的事。

---

## 九、Sarah 的一天（产品形态具象化）

Sarah 早上 8 点打开产品。屏幕上没有日历，没有表格，只有一句话："早上好，Sarah。今天有 2 件事需要你处理，其中 1 件今天截止。"

她说"先看今天截止的"，系统渲染一张卡片。她说"完成了"，这条从视野里消失。第二件事是下周的，系统问"要我 3 天前再提醒你吗"，她说"好"。整个过程不到两分钟。

上午 10 点半，电话还没挂，她对着手机说"新客户，Brightfield Studio，S-Corp，Delaware 注册，California 和 New York 也有"，系统回答"已创建，生成了 23 个截止日期"。电话挂掉，档案建好了。

下午 2 点，她什么都没做。系统检测到 IRS 发布加州灾难延期公告，自动比对客户列表，Brightfield Studio 符合条件，deadline 静默更新。她没收到任何打扰。

下午 4 点，一条通知："今日系统自动处理了 1 件事：Brightfield Studio 的加州截止日已更新至 10 月 15 日。"她点开看了 10 秒，确认没问题，关掉。

这一天，Sarah 没有查过一次日历，没有打开过一次 Excel，没有搜索过一次 IRS 网站。

---

## 十、技术基建

### 技术栈

核心语言 Python，CLI 用 Typer，API 用 FastAPI，同一套业务逻辑 CLI 和 API 共享。数据库 PostgreSQL，多租户用 Row-Level Security，连接池用 PgBouncer。任务队列 Celery + Redis，提醒推送和规则库抓取都是异步任务。

意图解析走 Claude Haiku（便宜且够用），规则库解析走 Claude Sonnet（准确性要求高）。语音用 Whisper API，转文字后和文字输入走完全相同的路径。

### 成本优化（$49/月 定价下的生存逻辑）

提醒不是实时计算，是每小时一次 batch job——查询未来 24 小时需要触发的提醒，写入队列，按时触发。即使 6 万用户每人 50 个客户，计算压力也是可控的。

50 州轮询错开时间，变更频率低的州降低轮询频率。缓存常见问题的回答，相同意图不重复调用 AI API。

### 数据模型核心表

tenants（租户）、clients（客户）、deadlines（deadline 条目）、rule_library（税法规则库，全局共享）、rule_versions（规则历史版本）、change_events（变更事件日志）、notifications（提醒队列）、audit_log（操作记录）。

rule_library 是全局的，所有租户共享。deadlines 是按客户实例化的，从规则库 derive 出来，可以被手动覆盖。

### 扩展路径

```
现在       规则库 → deadline 实例化 → 提醒推送
Phase 2    与 Drake/UltraTax 集成，客户数据双向同步
Phase 3    规则库 API 对外销售
           其他会计工具付费订阅规则库数据
           产品从工具变成数据基础设施
```

Phase 3 是真正的杠杆点——规则库一旦建好，边际成本趋近于零，但可以向整个行业收费。

---

## 最终综合

### 产品主张（一句话）

不是一个更好的税务日历，而是一个替 CPA 承担税务合规认知负担的系统——让 Sarah 每天只需要处理真正需要她判断的事，其他全部由系统处理。

### 核心设计原则（按优先级）

一、complexity hiding：复杂性必须存在（美国税法本身是复杂的），产品的工作是不让用户亲自面对这种复杂性。

二、授权边界清晰：结果确定的事系统自动做，涉及客户真实状态的事必须人来确认。

三、CLI-first：所有能力只实现一次，UI 和 Agent 都是这层的调用者。

四、对话即界面：页面是对话的输出物，不是预先设计好的布局。用户问什么出现什么。

五、弱提醒是管家，强提醒逼迫响应：两种提醒形态服务于完全不同的目的，不能混淆。

### 结论置信度

产品形态定义：**高确信**。三件核心事的分工、授权边界、交互哲学，在对话中多次从不同角度验证，结论稳定。

技术选型：**中高确信**。技术栈合理，成本逻辑清晰，但未经实际负载测试。

规则库质量 SLA：**中确信**。这是最大的技术风险，AI 解析准确率在极端税法文本上未验证。

---

## PENDING

### Unresolved

- 规则库人工审核队列的运营成本。置信度低于 0.85 的变更需要人工确认，这个比例在实际运行中是多少？团队需要多少人力维护？Context: 这决定了 $49/月 定价下的单位经济模型是否成立。

- 语音识别对税务专业术语的准确率。"Pass-Through Entity"、"Delaware Franchise Tax"、"PTE election"——Whisper 在这些词上的错误率会影响口述录入的可用性。Context: 可能需要税务领域的 fine-tuning 或 prompt 工程补偿。

- 弱提醒的具体形式。当天收工前的汇总通知、第二天早上的灰色小字——这些具体交互模式留给用户反馈迭代，或提供选项让用户配置。Context: 不影响核心设计，但影响用户体验细节。

- 首次登录的冷启动体验。Sarah 第一次打开产品，没有任何客户数据，`duedate today` 返回空。这个时刻的引导设计未讨论。Context: PLG（产品主导增长）的关键转化节点。

- H1B 和雇主情况对工程团队组建的影响。未讨论。

### Resolved

- ~~CLI 是否真的有必要~~  → Resolved：CLI 是 Agent 的 API surface，不是给用户手写的。UI 按钮点击 = CLI 命令调用。这个定位清楚之后，CLI-first 的架构决策自然成立。

---

## Appendix A: Framework Evolution Record

| Stage | 产品形态 | 变化 | Trigger |
|---|---|---|---|
| 初始 | Compliance calendar | 基于商业计划书的定义 | 原始文档 |
| 第一次演化 | 三件核心事（Fetch/Manage/Notify） | 从用户工作流倒推功能边界 | 从问题本质倒推 |
| 第二次演化 | CLI-first + UI 包装 | 引入面向 Agent 的架构设计 | 用户提出 CLI 化要求 |
| 第三次演化 | 对话驱动 + 动态渲染 | 产品形态跃迁 | 用户提出语音/交互+实时渲染 |
| 第四次演化 | 授权边界明确 | 强弱提醒分层，保护用户精力 | 用户："有些事情不必用户准许" |

## Appendix B: Entity Index

| Entity | Type | First Appearance | Status | Notes |
|---|---|---|---|---|
| DueDateHQ | system | §一 | stable | 核心产品 |
| Sarah | example | §一 | stable | 目标用户原型，独立 CPA，60 个客户 |
| Fetch | concept | §二 | stable | 信息获取层，护城河 |
| Manage | concept | §二 | stable | 客户管理层，薄 |
| Notify | concept | §二 | stable | 提醒层，产品前台 |
| CLI-first | concept | §三 | stable | 架构原则 |
| duedate today | system | §三 | stable | 产品默认启动状态 |
| complexity hiding | concept | §四 | stable | 产品设计哲学 |
| 弱提醒 | concept | §七 | stable | 管家式告知，事后汇总 |
| 强提醒 | concept | §七 | stable | 逼迫响应，不允许忽略 |
| rule_library | system | §十 | stable | 全局共享税法规则库，护城河核心 |
| File In Time | example | §一 | stable | 最直接竞品，Windows 桌面软件 |
| Karbon / Canopy | example | §一 | stable | 竞品，定价过高，工作流为主 |
| PTE election | concept | §七 | stable | 典型强提醒场景，不可撤销 |

## Appendix C: Logical Dependency Graph

```
用户核心焦虑（不知道自己是否漏了什么）
    └─→ 功能边界定义（Fetch / Manage / Notify）
         ├─→ Fetch（护城河）
         │    ├─→ 三级信息源体系
         │    ├─→ AI 解析 + 置信度过滤
         │    └─→ 15分钟端到端 SLA
         ├─→ Manage（薄胶水层）
         │    └─→ 口述录入 → CLI → 自动推算 deadline
         └─→ Notify（唯一前台）
              ├─→ 强提醒（逼迫响应）
              │    └─→ 不可撤销事件 → 升级机制
              └─→ 弱提醒（管家式）
                   └─→ 系统自动处理 → 事后汇总告知
                            ↓
         授权边界（结果确定 → 系统做；状态判断 → 人做）
                            ↓
         产品形态（CLI-first → 对话驱动 → 动态渲染）
                            ↓
         核心结论：complexity hiding — 复杂性留在系统，用户只面对决策
```
