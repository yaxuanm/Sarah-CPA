# DueDateHQ 交互层开发指导文档 v5

> 本文档是完整重写，不是 v4 的修订版。
> **所有 CLI 调用以 `cli-reference.md` 为准。**
> 现有 `conversation.py` 是关键词分类 + 内存 session，目标架构与此不同，需要重做交互后端。

---

## 产品交互的本质

Sarah 每天打开产品时，心理状态不是"我要查什么"，而是"现在有什么我需要知道的"。她不是在搜索，她在响应。

所有交互设计从这个判断出发：产品的默认状态是系统已经替她算好了今天最重要的事，她打开就看到结论。她的操作是对系统呈现的内容做出判断，不是导航到某个功能再操作。

---

## 一、交互的三个层次

### 1.1 系统主动找她（推模式，主要路径）

系统在该找她的时候找她，不在不该找的时候打扰她。

**找她的条件：**

- 今天有待处理事项 → 每天早上定时推送
- 有需要她立刻决定的变更 → 事件触发，立即推送
- 强提醒升级 → deadline 临近且未响应，按升级机制推送

**不找她的条件：**

- 系统自动处理完的变更 → 汇总进早上的告知，不单独打断
- 没有待处理事项的天 → 沉默，不发送

### 1.2 她主动问（拉模式，补充路径）

她可以问任何事，用任何方式表达。系统理解意图，执行，渲染结果。系统不限制她怎么说，但碰到自身能力边界会告诉她，不假装能做。

### 1.3 她追溯和核查（历史入口，独立路径）

税务场景的特殊性：Sarah 需要能随时看到发生了什么、为什么、谁做的。这不是高级功能，是基本权利。这一层独立于对话存在，不依赖 session，随时可访问。

---

## 二、界面结构

界面只有四个固定元素，始终在场：

```
┌──────────────────────────────┐
│  消息区                       │
│  系统回应 / state_summary     │
├──────────────────────────────┤
│                              │
│  内容区                       │
│  按需渲染，随对话变化          │
│                              │
├──────────────────────────────┤
│  历史入口（独立，不受 session 影响）│
├──────────────────────────────┤
│  输入区                       │
└──────────────────────────────┘
```

没有导航栏，没有菜单，没有预设页面。内容区是对话的输出，不是预先设计好的布局。

---

## 三、内容区的六种形态

根据当前上下文，内容区渲染六种形态之一。

### 3.1 待办列表（ListCard）

产品的默认启动状态。数据来源：`today <tenant_id> --enrich`。

```typescript
interface ListCardItem {
  deadline_id: string
  client_name: string       // today --enrich 返回
  client_id: string
  tax_type: string
  due_date: string
  days_remaining: number    // today --enrich 返回
  status: string
}

interface ListCardData {
  items: ListCardItem[]     // 最多 5 条，按 days_remaining 升序
  total: number
  has_more: boolean
}
```

超出 5 条显示"还有 N 条"，点击追加加载（增大 `--limit`）。每条可点击，触发客户详情。

### 3.2 客户详情（ClientCard）

数据来源：`deadline list <tenant_id> --client <id>`，由 Response Generator 做 enrich，并为每条 deadline 调用 `deadline available-actions`。

```typescript
interface DeadlineItem {
  deadline_id: string
  tax_type: string
  jurisdiction: string
  due_date: string
  days_remaining: number
  status: string
  rule_id: string
  available_actions: string[]  // 来自 deadline available-actions
}

interface ClientCardData {
  client_id: string
  client_name: string
  entity_type: string
  registered_states: string[]
  deadlines: DeadlineItem[]
}
```

每条 deadline 只渲染 `available_actions` 里存在的操作按钮，不渲染不允许的。

### 3.3 变更通知（ChangeNoticeCard）

数据来源：推送调度层构建，不来自单一 CLI 命令。

```typescript
interface AffectedClient {
  client_name: string
  client_id: string
  old_date: string
  new_date: string
  auto_updated: boolean
}

interface ChangeNoticeCardData {
  source_label: string
  source_url: string
  affected_clients: AffectedClient[]
  requires_action: boolean
}
```

`auto_updated: true` 灰色显示，无操作按钮。`auto_updated: false` 显示确认按钮，点击生成决策卡。

### 3.4 决策卡（ConfirmCard）

需要用户明确响应的单条事项。一个问题，最多三个选项，互斥。选完卡片消失，内容区回到剩余待办列表。

```typescript
interface ConfirmOption {
  label: string
  style: "primary" | "secondary" | "danger"
  plan: Plan | null          // null = 取消，不执行
}

interface ConfirmCardData {
  description: string
  due_date: string | null
  consequence: string | null // 后果说明，强提醒类必填
  options: ConfirmOption[]
}
```

### 3.5 月历（CalendarView）

> ⚠️ **过渡实现，不计入第一阶段验收。** 可以上线，但不是稳定承诺的能力。

仅在用户主动要求时渲染。数据来源：`deadline list <tenant_id> --within-days 31 --limit 200`，由 Response Generator 补充 `client_name` 后前端按月分组。CLI 支持精确日期范围查询后重构。

```typescript
interface CalendarDay {
  date: string
  deadline_count: number
  deadlines: {
    deadline_id: string
    client_name: string
    tax_type: string
    status: string
  }[]
}

interface CalendarViewData {
  year: number
  month: number
  days: CalendarDay[]
}
```

### 3.6 引导卡（GuidanceCard）

意图不明确或引用失败时使用，不是正式业务视图。

```typescript
interface GuidanceCardData {
  message: string
  options: string[]
  context_options: { label: string; ref: string }[]
}
```

渲染为可点击按钮。点击 = 发送对应文字进入 NLU 流程。

---

## 四、后端四层架构

```
用户输入（文字 / voice transcript）
        ↓
    NLU 服务
    自然语言 → Plan
        ↓
    Executor
    Plan → CLI 调用序列 → 聚合结果
        ↓
    Response Generator
    聚合结果 → message + view（含 selectable_items）
        ↓
    前端
    渲染 view，更新 selectable_items
```

每一层职责单一，独立可测。

---

## 五、NLU 服务

### 职责

把用户输入翻译成执行计划（Plan）。不执行，不渲染，只翻译。

### 两种引用解析通路

**通路 A：相对引用** — "第一条"、"这个客户"、"刚才那个"，只从 `selectable_items` 解析。解析不到输出 `reference_unresolvable`，不猜测。

**通路 B：实体解析** — 用户说"Acme LLC 的情况"但当前视图没有 Acme，Plan 里增加 `resolve_entity` 步骤，Executor 执行 `client list` 并内存匹配实体名。

### 输入

```json
{
  "user_input": "Acme LLC 的情况给我看一下",
  "session": {
    "history_window": [...],
    "current_view": {
      "type": "ListCard",
      "selectable_items": [
        { "ref": "item_1", "deadline_id": "dl-001", "client_id": "cl-002", "client_name": "Brightfield Studio" }
      ]
    },
    "today": "2026-04-19",
    "tenant_id": "tenant-001"
  }
}
```

### System Prompt 结构

```
你是 DueDateHQ 的意图解析器。
把用户输入翻译成执行计划（Plan）。
输出必须是合法 JSON，不输出任何解释。

当前上下文：
- 今天：{today}
- 租户：{tenant_id}
- 当前可引用对象（selectable_items）：{selectable_items}
- 对话历史（最近 10 轮）：{history_window}

可用 CLI 命令（严格按此，不使用不存在的参数）：

today <tenant_id> [--limit <int>] [--enrich]
client list <tenant_id>
client add <tenant_id> <name> --entity <type> --states <csv> --tax-year <year>
client update-states <tenant_id> <client_id> --states <csv>
deadline list <tenant_id> [--client <id>] [--within-days <int>]
              [--status <pending|completed|snoozed|waived|overridden>]
              [--jurisdiction <state>] [--limit <int>] [--offset <int>]
              [--show-reminders]
deadline action <tenant_id> <deadline_id> <action>
              [--until <iso_ts>] [--new-date <date>] [--actor <name>]
              action 允许值：complete / snooze / waive / reopen / override
              reopen 不是通用 undo，只适用于 completed/waived 状态
deadline available-actions <tenant_id> <deadline_id>
deadline transitions <tenant_id> <deadline_id>
deadline trigger-reminders --tenant-id <tenant_id> [--at <iso_ts>]
notify preview <tenant_id> [--within-days <int>]
notify history <tenant_id>
notify send-pending <tenant_id>
log [--tenant-id <tenant_id>] [--object-id <object_id>]
export <tenant_id> [--client <client_id>] [--actor <name>]
rule list
rule review-queue

引用解析规则：
- 相对引用只从 selectable_items 解析，不猜其他字段
- 显式实体名走 resolve_entity 步骤
- 解析不到输出 reference_unresolvable

历史查询路由：
- "这个为什么变了" → deadline transitions（单对象）
- "看历史"/"操作记录" → log --tenant-id（全局审计）

op_class 标注规则：
- 任何包含写操作的 Plan 必须标注 op_class: "write"
- 写操作：deadline action / client add / client update-states / notify config add
- 读操作：其余所有命令
```

### Plan 格式

```json
{
  "plan": [
    {
      "step_id": "s1",
      "type": "resolve_entity",
      "entity_name": "Acme LLC",
      "entity_type": "client",
      "cli_group": "client",
      "cli_command": "list",
      "args": { "tenant_id": "tenant-001" },
      "match_field": "name",
      "bind_as": "resolved_client"
    },
    {
      "step_id": "s2",
      "type": "cli_call",
      "cli_group": "deadline",
      "cli_command": "list",
      "args": {
        "tenant_id": "tenant-001",
        "client_id": "$resolved_client.client_id"
      },
      "depends_on": "s1"
    }
  ],
  "intent_label": "client_deadline_list",
  "confidence": 0.95,
  "op_class": "read"
}
```

### Plan 步骤类型

| type | 含义 |
|---|---|
| `cli_call` | 执行一条 CLI 命令 |
| `resolve_entity` | client list + 内存匹配实体名，结果绑定供后续引用 |
| `foreach` | 对上一步结果的每一项执行同一条命令，结果合并 |
| `post_filter` | 对上一步结果做内存过滤（非 CLI 参数） |

### 特殊输出

```json
// 引用无法解析
{ "plan": [], "special": "reference_unresolvable",
  "message": "没找到你说的那条记录，当前视图里有这些：",
  "selectable_items": [...] }

// reopen 不可用
{ "plan": [], "special": "reopen_unavailable",
  "message": "当前状态不支持撤销。这个 deadline 现在是 pending 状态。",
  "op_class": "write" }

// 意图不明确
{ "plan": [], "confidence": 0.55,
  "options": ["查看今天的待处理事项", "查一个具体客户的情况", "录入新客户"],
  "context_options": [{ "label": "Brightfield Studio", "ref": "item_1" }],
  "fallback_message": "没太理解。你是想——" }
```

### 降级逻辑

**read 操作：**

```
confidence ≥ 0.75      执行 Plan
0.60 ≤ conf < 0.75    执行 Plan，message 注明"如果不对告诉我"
conf < 0.60            不执行，输出 options
第二次仍 < 0.60        保留 session，扩大候选选项
第三次仍 < 0.60        执行 today <tenant_id> --enrich，不重置 session
```

**write 操作：**

```
confidence ≥ 0.90      生成 ConfirmCard，用户确认后才执行
confidence < 0.90      不执行，输出 options
任何置信度             都必须经过用户确认，不猜测写操作
```

### 意图映射表

| 用户说的话 | Plan 执行的命令 | op_class |
|---|---|---|
| "今天有什么" | `today --enrich` | read |
| "Acme 的情况"（视图内有） | `deadline list --client <id>`，由 Response Generator enrich | read |
| "Acme 的情况"（视图内无） | resolve_entity → `deadline list --client <id>`，由 Response Generator enrich | read |
| "完成了" | `deadline action ... complete` | write |
| "下周再提醒我" | `deadline action ... snooze --until <iso_ts>` | write |
| "不适用" | `deadline action ... waive` | write |
| "改日期到 5 月 15 日" | `deadline action ... override --new-date 2026-05-15` | write |
| "撤销"（状态允许） | `deadline action ... reopen` | write |
| "撤销"（状态不允许） | reopen_unavailable | — |
| "新客户，Texas S-Corp..." | `client add ...` | write |
| "导出 Acme 的记录" | `export --client <id>` | read |
| "导出全部记录" | `export <tenant_id>` | read |
| "看变更历史" | `log --tenant-id` | read |
| "这条为什么变了" | `deadline transitions <tenant_id> <id>` | read |
| "本周要到期的" | `deadline list --within-days 7`，由 Response Generator enrich | read |
| "加州客户的 deadline" | `client list` → post_filter(CA) → foreach `deadline list --client` | read |
| "提醒发出去了吗" | `notify history` | read |
| "本月日历" | `deadline list --within-days 31 --limit 200`，由 Response Generator enrich | read |

---

## 六、Executor

### 职责

接收 Plan，按步骤顺序执行 CLI 调用，处理步骤依赖、过滤、合并，返回聚合结果。

### 执行规则

**变量替换：** `$step_id.field` 从已完成步骤的结果取值。

```python
def resolve_args(args, results):
    for key, val in args.items():
        if isinstance(val, str) and val.startswith("$"):
            ref_step, ref_field = val[1:].split(".", 1)
            args[key] = results[ref_step][ref_field]
    return args
```

**foreach 分批：** 源列表超过 20 项时，每批最多 5 个并发 CLI 调用，批次间顺序执行。默认只处理前 50 项，超出标注 `truncated: true`。

**post_filter：** 内存过滤，不是 CLI 参数。

```python
def execute_post_filter(step, results):
    source = results[step.depends_on]
    return [item for item in source
            if match(item[step.filter["field"]], step.filter["value"])]
```

### 失败处理

| 失败类型 | 处理方式 |
|---|---|
| 单个 `cli_call` 失败 | Plan 中止，返回 `execution_failed`，含失败步骤和错误信息 |
| `resolve_entity` 匹配不到 | 返回 `entity_not_found`，提示用户确认实体名 |
| `foreach` 部分子步骤失败 | 继续执行其他子步骤，聚合结果标注失败项 |
| write 操作用户取消 | Plan 不执行，session 不变 |

写操作无回滚。执行完成即最终态，事后撤销走 `reopen`（仅限状态允许）。

### 输出

```json
{
  "plan_id": "plan-abc",
  "intent_label": "client_deadline_list",
  "op_class": "read",
  "steps_executed": ["s1", "s2"],
  "final_data": [...],
  "meta": {
    "total": 4,
    "truncated": false,
    "entity_resolved": { "Acme LLC": "cl-001" }
  },
  "errors": []
}
```

---

## 七、Response Generator

### 职责

把 Executor 的聚合结果转换成前端可渲染的响应。包含四件事：选择 view type、做 enrich、生成 message、从 `deadline available-actions` 生成 actions。

### LLM 使用边界

- `message` 生成优先使用 LLM，模板兜底
- `view.type` 选择必须由确定性规则决定，不交给 LLM
- `actions` 生成必须由 `deadline available-actions` 和业务规则决定，不交给 LLM
- enrich 属于确定性数据拼装，不交给 LLM

### actions 生成

Response Generator 调用 `deadline available-actions <tenant_id> <deadline_id>` 获取当前允许的操作，据此生成 actions 列表。前端只渲染允许的按钮。

```python
def build_actions(tenant_id, deadline_id, intent_label):
    available = cli("deadline available-actions", tenant_id, deadline_id)
    # 根据 available["available_actions"] 和 intent_label 生成 actions
    return [
        build_action(action, tenant_id, deadline_id)
        for action in available["available_actions"]
        if action in INTENT_RELEVANT_ACTIONS[intent_label]
    ]
```

### 写操作拦截

当 Plan 的 `op_class == "write"` 时，Response Generator 不执行，渲染 ConfirmCard：

```json
{
  "message": "确认要标记 Acme LLC 的 Texas Franchise Tax 为已完成吗？",
  "view": {
    "type": "ConfirmCard",
    "data": {
      "description": "Acme LLC — Texas Franchise Tax Annual Report",
      "due_date": "2026-04-19",
      "consequence": null,
      "options": [
        { "label": "确认完成", "style": "primary", "plan": { "steps": [...], "op_class": "write" } },
        { "label": "取消", "style": "secondary", "plan": null }
      ]
    },
    "selectable_items": [
      { "ref": "item_1", "deadline_id": "dl-001", "client_id": "cl-001", "client_name": "Acme LLC" }
    ]
  },
  "actions": [],
  "state_summary": null
}
```

用户点"确认"→ Plan 发给 Executor 执行。用户点"取消"→ plan 为 null，不执行。

### 输出格式

```json
{
  "message": "Acme LLC 有 4 个截止日期，最近的是 5 月 15 日的 Texas Franchise Tax。",
  "view": {
    "type": "ClientCard",
    "data": { ... },
    "selectable_items": [
      { "ref": "item_1", "deadline_id": "dl-001", "client_id": "cl-001", "client_name": "Acme LLC" },
      { "ref": "item_2", "deadline_id": "dl-002", "client_id": "cl-001", "client_name": "Acme LLC" }
    ]
  },
  "actions": [
    {
      "label": "标记完成",
      "plan": {
        "steps": [{ "type": "cli_call", "cli_group": "deadline", "cli_command": "action",
                    "args": { "tenant_id": "tenant-001", "deadline_id": "dl-001", "action": "complete" } }],
        "op_class": "write"
      }
    }
  ],
  "state_summary": "显示 Acme LLC 的 4 个截止日期。"
}
```

### message 规则

- 永远先说结论
- 数字必须出现
- 不超过 50 字
- 禁止前缀："好的"、"我来帮你"、"当然"、"没问题"

### view type 选择逻辑

| 场景 | view.type |
|---|---|
| `today` 结果 / 多条待办 | `ListCard` |
| 单客户 deadline 列表 | `ClientCard` |
| 规则变更通知（推送触发） | `ChangeNoticeCard` |
| write 操作待确认 | `ConfirmCard` |
| 用户主动要求月历 | `CalendarView`（过渡实现） |
| 意图不明确 / 引用失败 | `GuidanceCard` |

---

## 八、Session 管理

### 结构

```python
@dataclass
class Session:
    session_id: str
    tenant_id: str
    today: str
    history_window: list[dict]      # 最近 10 轮（20 条 message）
    current_view_snapshot: dict     # 含 selectable_items，持久化到 Redis
    created_at: datetime
    last_active: datetime
    ttl_seconds: int = 3600
```

### TTL 机制

- 1 小时无操作后过期，不是"关闭即销毁"
- 刷新、断线重连、切换标签后回来，TTL 内 session 有效
- TTL 到期后 session 和 `current_view_snapshot` 同时失效
- 过期后前端创建新 session，自动执行 `today <tenant_id> --enrich`，从干净状态开始
- 不做半途恢复，不保留旧视图用于展示或引用解析

### history 窗口化

- 只保留最近 10 轮（20 条 message）
- 超出丢弃，当前阶段不做摘要
- NLU system prompt 注入 `history_window`

### current_view_snapshot 持久化

```python
# 每次响应后写入
redis.setex(f"view:{session_id}", 3600, json.dumps(current_view_snapshot))

# session 恢复时读取（TTL 内）
snapshot = redis.get(f"view:{session_id}")
```

### selectable_items 更新规则

每次响应后必须更新，是 NLU 下一轮相对引用解析的唯一来源：

| view.type | selectable_items 内容 |
|---|---|
| `ListCard` | 每条 deadline 条目（含 deadline_id、client_id、client_name） |
| `ClientCard` | 该客户的每条 deadline |
| `ChangeNoticeCard` | 每个受影响的客户 |
| `ConfirmCard` | 当前这一条 deadline（单项） |
| `CalendarView` | 当前展开那天的 deadline 列表 |
| `GuidanceCard` | `context_options` 里的项 |

---

## 九、推送调度

### 定时触发（每天早上）

```python
# Step 1: 查询数据
today_result = cli("today", tenant_id, enrich=True, limit=5)
log_result   = cli("log", tenant_id=tenant_id)

# Step 2: 判断是否有内容推送
if not today_result and not has_batch_updates(tenant_id):
    return  # 无待办，零 delivery，不发送

# Step 3: 构建 delivery 记录
notify_config = cli("notify config list", tenant_id)
deliveries = build_morning_deliveries(
    tenant_id     = tenant_id,
    today_data    = today_result,
    batch_updates = drain_daily_batch(tenant_id),
    notify_config = notify_config
)

# Step 4: 持久化
persist_notification_deliveries(deliveries)

# Step 5: 发送
cli("notify send-pending", tenant_id)
```

**`notify send-pending` 只发送已持久化的 pending deliveries。Steps 1-4 是前置，不可跳过。**

### 事件触发（规则变更）

```python
def on_rule_changed(change_event):
    affected  = get_affected_clients(change_event)
    priority  = assess_priority(change_event)

    if priority == "immediate":
        notify_config = cli("notify config list", change_event.tenant_id)
        deliveries = build_event_deliveries(
            tenant_id        = change_event.tenant_id,
            change           = change_event,
            affected_clients = affected,
            notify_config    = notify_config
        )
        persist_notification_deliveries(deliveries)
        cli("notify send-pending", change_event.tenant_id)

    else:  # batch
        add_to_daily_batch(change_event.tenant_id, change_event)
```

### immediate / batch 的判断条件

**immediate（立即推送）：**
- 强提醒升级：PTE 选举类截止日 30 天内，且无用户操作记录
- 任何系统判断需要用户立刻决定的明确变更

**batch（进汇总队列）：**
- 官方已确认，系统已自动更新 deadline，无需用户操作

> **注意：** "FEMA 已发布 IRS 未跟进"这类跨机构语义判断属于业务规则引擎范畴，当前不实现。immediate 的判断基于规则库变更状态，不做跨机构推断。该能力单独立项。

### 推送内容格式

**早上推送（有待办）**

```
今天有 N 件事需要你处理。[最紧急的一句描述]
[如有昨日批量更新] 另外，昨天系统自动更新了 M 条记录。
```

**事件触发推送（immediate）**

```
你有 N 个客户的截止日期需要确认。
```

---

## 十、历史入口

独立于对话，不受 session 影响，始终可访问。两层结构：

### 第一层：全局审计流

数据来源：`log --tenant-id <tenant_id>`

按时间倒序显示所有写操作记录。字段：action_type / object_id / actor / created_at。

### 第二层：单对象状态流转（从第一层下钻）

用户在全局审计流里点击某条 deadline 记录 → 执行 `deadline transitions <tenant_id> <deadline_id>` → 展示该 deadline 的完整状态流转历史。

### NLU 路由规则

```
"这个为什么变了" / "这条怎么改的"  → Plan: deadline transitions（单对象）
"看历史" / "操作记录" / "变更记录" → Plan: log --tenant-id（全局审计）
```

两者语义不同，不可互换。

---

## 十一、前后端通信协议

### 普通输入请求

```json
{ "user_input": "完成了", "session_id": "session-abc" }
```

### Action 点击请求

```json
{
  "plan": {
    "steps": [{ "type": "cli_call", "cli_group": "deadline", "cli_command": "action",
                "args": { "tenant_id": "tenant-001", "deadline_id": "dl-001", "action": "complete" } }],
    "op_class": "write"
  },
  "session_id": "session-abc"
}
```

Action 请求不走 NLU，直接进 Executor → Response Generator。

### 成功响应

```json
{
  "status": "ok",
  "message": "已标记完成。还剩 1 件待处理。",
  "view": { "type": "ListCard", "data": { ... }, "selectable_items": [...] },
  "actions": [...],
  "state_summary": "还剩 1 件待处理。",
  "session_id": "session-abc"
}
```

### 错误响应

```json
{
  "status": "error",
  "error_type": "cli_execution_failed | session_expired | tenant_mismatch | nlu_failed | entity_not_found",
  "message": "用户可读的错误描述",
  "recoverable": true,
  "fallback_view": { "type": "GuidanceCard", "data": { ... } },
  "session_id": "session-abc"
}
```

| error_type | recoverable | 前端处理 |
|---|---|---|
| `cli_execution_failed` | true | 展示 GuidanceCard，保留 session |
| `session_expired` | true | 提示"会话已过期"，创建新 session，执行 `today --enrich` |
| `tenant_mismatch` | false | 强制重新登录 |
| `nlu_failed` | true | 展示 GuidanceCard，执行 `today --enrich` |
| `entity_not_found` | true | 展示 GuidanceCard，提示用户确认实体名 |

### Action 执行失败响应

```json
{
  "status": "action_failed",
  "error_type": "invalid_state_transition | cli_execution_failed",
  "message": "这个操作当前不可用。",
  "view": null,
  "session_id": "session-abc"
}
```

失败时前端不更新内容区，message 区域显示错误原因。

### Partial Render（预留，当前不实现）

```
event: intent_resolved   → { intent_label, session_id }
event: cli_executing     → { command, step_id, session_id }
event: response_complete → { status, message, view, session_id }
```

实现时机：前端体验验证完成后按需升级为 SSE 或 WebSocket。

---

## 十二、开发顺序

```
第一步   NLU 测试集
         先于实现存在
         100 条测试句子，覆盖：
           简单指令 / 复杂查询 / 复合意图 / 模糊引用
           实体解析（视图内无目标实体）
           write 操作确认流程
           reopen 边界（允许 / 不允许）
           reference_unresolvable 触发条件

第二步   NLU 服务实现
         验收：测试集正确率 ≥ 92%
               write 操作全部标注 op_class: write
               输出的 CLI 参数全部对照 cli-reference.md 验证合法性

第三步   Executor
         独立于 NLU 可测：直接构造 Plan JSON，验证执行结果
         验收：foreach 分批正确，post_filter 过滤正确
               entity_not_found 正确触发
               write 取消后 session 不变

第四步   Response Generator
         验收：available-actions 正确驱动 actions 列表
               write 操作返回 ConfirmCard 而非直接执行
               selectable_items 每次输出且与 view.data 对应
               message ≤ 50 字，无禁止前缀

第五步   Session 管理
         验收：TTL 到期后 session 和 snapshot 同时失效
               过期后前端创建新 session 自动执行 today
               相对引用只从 selectable_items 解析

第六步   推送调度
         验收：build → persist → send-pending 三步链路跑通
               immediate 类 5 分钟内发出
               batch 类只进队列，不立即发送
               无待办时零 delivery 创建

第七步   前端
         验收：输入到渲染 ≤ 3 秒
               五种正式业务组件任意数据不崩溃
               session 过期提示正常，新 session 自动加载 today
               历史入口可访问，可下钻到单对象 transitions
               actions 只渲染 available_actions 里存在的操作

第八步   错误处理端到端
         验收：五种 error_type 各有测试
               action 失败视图不变
               write 操作取消后 session 不变
```

---

## 十三、验收标准

| 组件 | 验收标准 |
|---|---|
| NLU | 测试集正确率 ≥ 92%；write 全标注；特殊输出（reopen_unavailable / reference_unresolvable）有测试 |
| Executor | foreach / post_filter / 失败处理全有测试；write 无自动回滚 |
| Response Generator | available-actions 驱动 actions；ConfirmCard 拦截 write；selectable_items 每次输出 |
| Session | TTL 过期行为统一；相对引用只认 selectable_items |
| 推送调度 | 三步链路（build→persist→send）跑通；无待办零 delivery |
| 前端 | ≤ 3 秒渲染；历史入口可下钻；过期提示正常 |
| 整体 | 5 个真实 CPA 用 30 天，零漏报，30 秒内找到历史记录，平均处理待办 ≤ 5 分钟 |

---

## 附录：范围边界

### 本期包含

NLU → Executor → Response Generator → Session → 推送调度 → 前端五种正式组件 → 历史入口两层结构 → 通信协议五种响应类型。

### 本期不包含

- **CalendarView** — 过渡实现，可上线但不计入验收
- **immediate 跨机构风险判断引擎** — 单独立项，当前推送调度不实现跨机构语义判断
- **Partial Render（SSE/WebSocket）** — 预留结构，前端体验验证后按需升级
- **rule_source_url enrich** — 可选增强，非主链路，不计入本期验收
