# DueDateHQ 按需渲染技术计划

Internal / Product + Engineering
v0.1 / Technical plan
Apr 2026

## 1. 目标

这份计划定义 DueDateHQ 如何从当前固定格式渲染，演进到受规则约束的按需渲染系统。

这里的“按需”不是“用户说什么，界面就显示什么”。

这里的“需”来自用户输入的 intention，但不能停留在 intention 本身。系统必须从用户的原始意图中推导出用户当时当下真正需要的东西：

- 用户想完成什么目的
- 用户现在卡在哪个判断
- 用户缺哪一个事实或确认
- 用户下一步能做哪一种选择
- 系统可以替用户准备、核验或记录哪一步

因此，按需渲染的定义是：

```text
按需渲染 = 从用户意图推导当前决策需求，并只渲染满足这个需求的最小可行动工作面。
```

它不是动态拼页面，也不是把更多信息搬到右侧。它的任务是降低用户的决策成本。

正确链路应该是：

```text
user intention
-> inferred need
-> decision question
-> required facts
-> allowed choices
-> action boundary
-> minimal render surface
```

其中：

- `user intention`：用户原始表达，例如“今天要做什么”“Acme 为什么 blocked”“帮我处理这个”
- `inferred need`：系统推导出的当前需求，例如“用户需要判断是否现在推进 Acme”
- `decision question`：页面必须回答的一个主问题，例如“Acme 现在要不要推进？”
- `required facts`：做这个判断必须知道的少量事实
- `allowed choices`：用户此刻可选的少数路径，例如推进、查看更多信息、暂时不做
- `action boundary`：每个选择会改变什么，不会改变什么
- `minimal render surface`：只渲染完成这个判断所需的内容

核心目标不是让 LLM 无限生成页面。

核心目标是：

```text
理解用户意图
推导当前决策需求
取可信数据
生成最小可判断上下文
渲染为可行动工作面
保留来源、动作边界和审计
```

最终产品形态：

```text
左侧：GPT-style interaction
右侧：dynamic work tabs
每个 tab：一个按需生成、经过校验的 render surface
```

## 2. 技术原则

### 2.1 LLM 不直接生成 HTML

LLM 可以参与理解用户意图、总结 tab 名称、组织 render spec。

LLM 不应该直接输出任意 HTML 给浏览器。

正确链路：

```text
user input / system event
-> intent understanding
-> need inference
-> decision question selection
-> decision task
-> data plan
-> deterministic executor
-> render spec
-> spec validator
-> frontend renderer
```

### 2.2 用户需求开放，系统边界有限

用户可以提出开放需求。

但系统不能把用户原话直接当成渲染需求。用户说的是 intention，系统要推导的是 need。

例如：

```text
用户说：今天要做什么？
intention：想开始当天工作
inferred need：需要知道最值得现在处理的一件事，以及为什么
decision question：我现在是否推进这个任务？
surface：少量事实 + 一个问题 + 三个选择
```

```text
用户说：Acme 为什么 blocked？
intention：想理解 blocked 原因
inferred need：需要知道缺什么、谁能补、现在能不能推进
decision question：我要现在推进 Acme，还是先查看更多信息？
surface：blocked 事实 + 缺口 + 推进/更多信息/暂不处理
```

系统必须把 inferred need 收敛到：

- 有限 `DecisionTask`
- 有限 `DecisionQuestion`
- 有限 `Block` 类型
- 可信 `DataBinding`
- 白名单 `Action`
- 可校验 `RenderSpec`
- 可追踪 `WorkspaceState`

### 2.3 Need inference rules

Need inference 是按需渲染的核心。

输入不是页面需求，而是用户意图。系统必须先回答以下问题：

- 用户的目的是什么：开始工作、理解原因、推进任务、核验来源、暂停处理、记录结果
- 用户指向哪个对象：今天清单、某个客户、某条 deadline、某个来源、某个导入批次
- 用户当前缺什么：事实、解释、来源、后果预览、可执行动作、确认入口
- 当前风险是什么：时间风险、合规风险、错误记录风险、误操作风险
- 用户此刻应该面对哪个问题：是否推进、是否查看更多信息、是否暂停

Need inference 输出结构：

```json
{
  "intent": "understand_blocker",
  "inferred_need": "decide_whether_to_advance_acme",
  "entity": {
    "type": "client_deadline",
    "id": "acme_q2_sales_tax"
  },
  "decision_question": "Should I advance Acme Dental now?",
  "required_facts": [
    "Acme is blocked",
    "Client documents are missing",
    "Due date is May 15",
    "Preparing a request will not send email or change tax data"
  ],
  "choices": [
    "advance",
    "need_more_information",
    "pause_or_leave"
  ]
}
```

规则：

- 如果用户问“为什么”，系统不能只展示来源；它要推导用户是否在决定要不要行动
- 如果用户问“今天做什么”，系统不能展示完整任务表；它要推导用户需要一个推荐焦点和少量备选
- 如果用户点击一个 action，系统不能只改变状态；它要渲染下一步需要的确认、外部动作或结果
- 如果用户表达不确定，系统不能继续推进；它要把 `need_more_information` 作为默认选择
- 如果缺少关键事实，系统不能假装有结论；它要渲染 clarification 或 source review

### 2.4 个性化不能污染合规事实

系统可以学习用户偏好和平台共性模式。

系统不能通过学习自动改变：

- 税法事实
- deadline 计算
- 客户真实状态
- 官方公告解释
- 已确认业务动作

## 3. 总体架构

```text
Input Layer
  - user message
  - voice transcript
  - click action
  - system event

Understanding Layer
  - intent parser
  - need inference
  - entity resolver
  - decision task classifier

Planning Layer
  - decision question planner
  - data planner
  - surface lifecycle planner
  - action planner

Execution Layer
  - deterministic executor
  - data fetch
  - action confirmation

Rendering Layer
  - render spec generator
  - spec validator
  - workspace state manager
  - frontend block renderer

Learning Layer
  - interaction event logging
  - user preference memory
  - platform pattern aggregation
```

## 4. 核心对象

### 4.1 DecisionTask

第一版只允许这些任务：

```text
weekly_triage
today_action_queue
client_deadline_review
change_impact_review
customer_import_review
deadline_confirmation
source_review
audit_review
ambiguity_resolution
system_alert_review
```

任何输入必须先落到一个 task。

落不进去时，不生成复杂 surface，返回 clarification。

### 4.2 DecisionQuestion

`DecisionQuestion` 是按需渲染的中心对象。

`DecisionTask` 回答“这是哪类工作”，`DecisionQuestion` 回答“用户现在到底要判断什么”。

第一版问题类型：

```text
what_should_i_do_now
should_i_advance_this_task
why_is_this_blocked
what_is_missing
what_will_change_if_i_act
do_i_need_more_information
should_i_pause_this_task
```

每个 `DecisionQuestion` 必须定义：

- `question`：用户可理解的主问题
- `required_facts`：回答问题必须展示的事实
- `default_choice`：系统建议的选择
- `allowed_choices`：用户当前最多 3 个选择
- `action_boundary`：每个选择会改变什么、不会改变什么
- `supporting_info`：用户需要更多信息时才展开的内容

第一版通用选择模型：

```text
advance
need_more_information
pause_or_leave
```

这三个选择对应用户自然决策：

- `advance`：推进当前任务，让系统准备、执行可自动化部分，或进入确认
- `need_more_information`：不推进，先展开来源、原因、历史、影响范围或缺口细节
- `pause_or_leave`：暂时不处理，回到清单、稍后提醒或保持原状态

默认 surface 不应该展示一组松散按钮。它应该先提出一个清楚的问题，再给出这三个方向的选择。具体按钮文案可以因任务变化，例如：

- `Advance` -> `Prepare request` / `Open review` / `Apply update`
- `Need more information` -> `Show source` / `Explain missing item` / `Show audit trail`
- `Pause or leave` -> `Back to list` / `Remind me later` / `Do nothing now`

### 4.3 WorkspaceState

WorkspaceState 管理右侧所有 dynamic work tabs。

```json
{
  "active_surface_id": "surface_weekly_001",
  "surfaces": [
    {
      "surface_id": "surface_weekly_001",
      "tab_summary": "This Week - 12",
      "decision_task": "weekly_triage",
      "created_by": "user_triggered",
      "context": {},
      "render_spec": {}
    }
  ]
}
```

每个 surface 必须成为后续对话上下文的一部分。

用户说：

```text
这个 tab
第二个客户
刚才那个 import
把当前结果导出
```

系统应能基于 WorkspaceState 解析引用。

### 4.4 RenderSpec

RenderSpec 是前端渲染的唯一输入。

```json
{
  "surface_id": "surface_ca_extension_001",
  "tab_summary": "CA Extension - 6",
  "decision_task": "change_impact_review",
  "title": "California Extension Impact",
  "primary_block_id": "affected_deadlines",
  "blocks": [
    {
      "id": "summary",
      "type": "summary",
      "priority": 1,
      "data_binding": "change_event.summary"
    },
    {
      "id": "affected_deadlines",
      "type": "deadline_table",
      "priority": 2,
      "data_binding": {
        "source": "deadline.list",
        "filters": {
          "jurisdiction": "CA",
          "affected_by_event": "event_123"
        }
      }
    }
  ],
  "actions": ["review_clients", "prepare_bulk_adjustment", "open_source"]
}
```

### 4.5 Block Library

第一版 block 控制在 10-12 个：

```text
decision_brief
fact_strip
decision_question
choice_set
consequence_preview
supporting_detail
summary
priority_summary
alert_banner
deadline_table
grouped_deadline_list
client_profile
source_evidence
timeline
import_sample_review
ambiguous_rows_review
action_bar
confirmation
guidance
```

Block 只能展示可信数据。

`decision_brief`、`fact_strip`、`decision_question`、`choice_set` 是默认决策骨架。其他 block 是按需展开的支持层。

默认 surface 应该先完成四件事：

- `decision_brief`：用一句话说明当前情况和系统建议
- `fact_strip`：展示做判断必需的 2-4 个事实
- `decision_question`：提出用户现在要回答的一个问题
- `choice_set`：给出最多三个选择：推进、需要更多信息、暂时不做

`consequence_preview` 用来说明用户选择后会发生什么。它必须在用户行动前出现，不能让用户点完按钮后才发现结果。

`supporting_detail`、来源、审计、历史、表格默认不展开。只有当用户选择 `need_more_information`，或者当前判断本身无法在少量事实下完成时，才进入默认 surface。

默认 surface 不能只说“blocked”就结束，也不能直接跳到按钮。它必须把“事实是什么 -> 我现在要回答什么问题 -> 我有哪些选择 -> 每个选择会造成什么结果”接起来。

同时，专注任务页必须展示任务生命周期，而不是只展示静态信息。第一版生命周期：

```text
understand -> system_prepare -> user_execute_outside -> record_result -> back_to_list
```

含义：

- `understand`：用户知道这件事为什么需要处理
- `system_prepare`：系统准备消息、记录、来源上下文或审查界面
- `user_execute_outside`：用户在 DueDateHQ 外完成真实动作，例如发邮件或走客户门户
- `record_result`：用户回来确认已经完成，系统只记录工作状态
- `back_to_list`：任务结束或暂停后回到统一清单

如果一个 action 会把用户带入后续步骤，例如 `Prepare request`，action 之后的主界面必须立刻切换成完成向导，而不是把准备好的内容藏在下方辅助 block。用户应该在首屏直接看到“现在做什么、在哪里做、做完回来点什么”。

这些骨架名是内部结构，不应该直接成为用户可见按钮文案。用户可见动作必须是具体动作，例如：

- `Prepare request`
- `Prepare question`
- `Mark sent`
- `Review extension record`
- `Back to list`

不允许把 `Next step`、`Decision`、`Ask / Inspect`、`What happens next` 这类结构名直接放进 action button 或推荐问题。默认界面也不应该堆一组“为什么要……”的问题按钮。用户可见交互应围绕三个选择组织：

- `推进`：具体写成 `Prepare request`、`Open review`、`Mark sent`
- `需要更多信息`：具体写成 `Show source`、`Show why blocked`、`Show audit trail`
- `暂时不做`：具体写成 `Back to list`、`Remind me later`、`Do nothing now`

### 4.6 ActionRegistry

所有业务动作必须来自 action registry。

第一版动作：

```text
open_detail
open_source
request_docs
create_reminder
mark_in_progress
complete_deadline
snooze_deadline
override_due_date
prepare_bulk_adjustment
confirm_import
cancel
export
```

写操作必须进入 confirmation。

## 5. 规则系统

### 5.0 UI reduction rules

按需渲染系统的 UI 必须做减法。

默认用户界面不展示内部实现语言：

- `RenderSpec`
- `Validator`
- `DataBinding`
- `Block`
- `DecisionTask`
- `DecisionQuestion`
- `WorkspaceState`

这些内容只允许出现在：

- debug mode
- logs
- internal QA
- technical documentation

每个 surface 默认只展示四类内容：

- facts：当前判断所需的少量事实
- question：用户此刻要回答的一个问题
- choices：推进、需要更多信息、暂时不做
- consequences：每个选择会改变什么、不会改变什么

如果一个 UI 元素不能帮助用户判断、核验或行动，就不进入默认 render spec。

支持信息的默认层级：

- 清单页负责切换任务，不负责处理任务
- 专注页负责处理当前任务，不主动推荐跳到另一项任务
- 专注页必须展示当前任务处于生命周期哪一步
- 系统准备动作完成后，首屏必须变成下一步完成向导
- 证据、来源、审计、完整队列默认折叠或按追问打开
- 动作按钮和左侧推荐 prompt 必须随当前 surface 状态同步变化

### 5.1 Surface lifecycle rules

每次输入或系统事件后，系统必须决定：

- 更新当前 surface
- 新开 surface
- 切换已有 surface
- 打开 confirmation surface
- 返回 clarification
- 归档旧 surface

第一版规则：

- 同一 task + 同一实体，更新当前 surface
- 新 task 或新实体，新开 surface
- 系统主动风险事件，新开 alert surface
- 写操作，打开或聚焦 confirmation surface
- 最多保留 5 个 open surfaces
- 超过上限时，归档最旧的非 pinned surface

### 5.2 Block budget rules

- 每个 surface 必须有一个 primary block
- 每个 surface 默认最多展示 3-5 个主要 blocks
- source、audit、history 默认可以折叠
- 低优先级信息不默认展开
- 不允许为了“看起来有用”堆无关 block

### 5.3 Naming rules

Tab name 必须来自 surface 内容摘要。

规则：

- 2-5 个词
- 包含实体、范围、数量或状态之一
- 必须基于 surface 数据
- 不使用营销或夸张语气

示例：

```text
This Week - 12
Acme Dental - High
CA Extension - 6
TaxDome Import - 4 issues
Confirm Acme
```

### 5.4 Validation rules

SpecValidator 必须检查：

- `decision_task` 是否在白名单
- `block.type` 是否在 block library
- `data_binding.source` 是否允许
- `actions` 是否在 action registry
- 写操作是否有 confirmation
- required context 是否齐全
- block 数量是否超过预算
- tab name 是否符合 naming rule

## 6. 分阶段实施计划

### Phase 0: Static Mock Alignment

目标：

- 用静态 HTML 验证左侧 GPT 式交互 + 右侧 dynamic work tabs 的产品形态。
- 用规则模拟 render surface 生成。

当前状态：

- `docs/mock-interaction.html` 已经模拟了 dynamic surfaces、tab summary、surface context 和 spec validation。

验收：

- 用户输入能生成或更新 surface
- tab name 基于 surface 内容
- selected item 能影响后续 surface
- 左侧推荐 prompt 随右侧 surface 和状态变化
- 默认工作面包含必要事实、一个决策问题、最多三个选择和后果预览
- 任务切换只能在清单 surface 中发生
- 写操作进入 confirmation
- 页面不超出浏览器视口

### Phase 1: Rule-based On-demand Rendering

目标：

- 不接 LLM，先用规则跑通完整按需渲染链路。

新增模块：

```text
decision_tasks.py
render_spec.py
surface_manager.py
spec_validator.py
action_registry.py
```

功能：

- 根据关键词分类 `DecisionTask`
- 根据 task 生成 data plan
- 调用现有 `PlanExecutor`
- 生成 `RenderSpec`
- 校验 spec
- 返回 workspace payload

验收：

- `this week` -> weekly triage surface
- `Acme risk` -> client deadline review surface
- `California extension` -> change impact surface
- `Import TaxDome CSV` -> import review surface
- `mark first in progress` -> confirmation surface

### Phase 2: WorkspaceState And Context References

目标：

- 支持多 tab 上下文。
- 支持用户引用当前 tab、某个 tab、选中项、可见行。

新增能力：

- `WorkspaceState` 持久化或 session 存储
- `active_surface_id`
- `selected_items`
- `surface_summaries`
- `surface_context`

验收：

- 用户说“这个 tab”能解析为 active surface
- 用户说“第二个客户”能解析为当前 surface 可见行
- 用户说“回到 import review”能切换或聚焦对应 surface
- 用户说“把当前结果导出”能走当前 surface action

### Phase 3: LLM Intent And Entity Understanding

目标：

- 用 LLM 替换规则版 intent parser，但不让 LLM 执行动作。

LLM 输出只允许结构化 JSON：

```json
{
  "decision_task": "change_impact_review",
  "entities": {
    "jurisdiction": "CA",
    "client": null,
    "time_range": "this_week"
  },
  "operation": "read",
  "confidence": 0.87,
  "needs_clarification": false
}
```

验收：

- 同义表达能落到同一 task
- 模糊实体能触发 clarification
- 低 confidence 不生成复杂 surface
- LLM 输出无法绕过 validator

### Phase 4: LLM-assisted RenderSpec Generation

目标：

- LLM 可参与组织 blocks 和生成 tab summary。
- 系统仍由 validator 和 data binding 控制事实边界。

约束：

- LLM 只能选择 block types
- LLM 只能引用允许 data source
- LLM 只能选择 action registry 中的动作
- LLM 不能直接输出业务事实

验收：

- 跨场景请求能生成 composite surface
- block 数量受预算控制
- tab summary 基于真实数据
- spec validation failure 能回退到 safe guidance

### Phase 5: User Learning Loop

目标：

- 学习单个用户的工作方式和展示偏好。

新增对象：

```text
InteractionEvent
PreferenceObservation
CandidateMemory
ConfirmedUserMemory
```

可学习：

- 常用筛选维度
- 默认排序偏好
- 常关注州和税种
- 是否默认展开 source evidence
- 常用动作组合

不可学习：

- 税法事实
- deadline 计算
- 客户真实状态
- 官方公告解释

验收：

- 系统能提出偏好建议
- 高影响偏好需要用户确认
- 用户可查看、删除、关闭记忆
- render spec 能解释使用了哪些偏好

### Phase 6: Platform Pattern Flywheel

目标：

- 从匿名事件中沉淀平台级默认模式，提升所有用户默认体验。

可聚合：

- block 使用率
- action 转化率
- import 字段映射模式
- triage 排序模式
- alert 响应模式
- time-to-action

不可聚合：

- 客户名
- EIN
- 原始文件内容
- 事务所私有客户组合

产物：

- 更好的默认 weekly triage 排序
- 更准的 CSV field mapping priors
- 更合理的 alert thresholds
- 更有效的 block combinations
- 更强的 risk scoring priors

## 7. 当前代码落点

当前仓库中可复用的部分：

- `PlanExecutor`：继续作为 deterministic execution layer
- `InteractionBackend`：演进为 workspace-aware interaction backend
- `ResponseGenerator`：拆分或演进为 render spec generator
- `InfrastructureEngine`：继续提供可信业务数据
- audit / deadline state machine：继续控制写操作和追溯

建议新增：

```text
src/duedatehq/core/decision_tasks.py
src/duedatehq/core/decision_questions.py
src/duedatehq/core/need_inference.py
src/duedatehq/core/render_spec.py
src/duedatehq/core/surface_manager.py
src/duedatehq/core/spec_validator.py
src/duedatehq/core/action_registry.py
src/duedatehq/core/learning.py
```

## 8. 主要风险

### 8.1 过度生成

风险：

- 右侧 tab 太多
- surface block 太多
- 用户不知道该看哪里

控制：

- tab 上限
- block budget
- old surface archive
- unclear intent clarification

### 8.2 错误上下文引用

风险：

- “这个 tab”“第二个客户”解析错误

控制：

- WorkspaceState 明确记录 active surface 和 selected items
- 低 confidence 要求用户确认

### 8.3 LLM 编造事实

风险：

- 模型生成不存在的 deadline 或税务解释

控制：

- data binding
- validator
- source evidence
- no raw fact generation

### 8.4 动作越权

风险：

- 模型发明动作或绕过确认

控制：

- ActionRegistry
- confirmation required
- audit log
- state machine

### 8.5 飞轮污染合规判断

风险：

- 用户偏好或平台模式影响税法事实

控制：

- memory scope
- evidence trail
- confirmed preference only
- compliance facts cannot be overridden by memory

## 9. MVP 验收标准

第一版可用 MVP 应满足：

- 左侧 GPT 式输入可驱动右侧 surface
- 右侧 dynamic work tabs 基于 render spec 渲染
- tab name 来自 surface 内容摘要
- surface context 可参与后续引用
- 每个默认 surface 必须有一个明确 `DecisionQuestion`
- 每个默认 surface 必须展示少量必要事实、一个问题、最多三个选择和选择后果
- 至少支持 weekly triage、client review、change impact、import review、confirmation
- 所有写操作必须确认
- 所有事实来自 deterministic data
- spec validator 能拒绝非法 block/action/source
- 页面不会因为内容增长而撑出浏览器视口

## 10. 工作结论

按需渲染技术上可行，但必须作为“从意图推导需求，再把需求收敛为决策问题”的系统来做。

关键资产不是生成 UI 的能力，而是：

- intention 到 inferred need 的推导能力
- inferred need 到 decision question 的收敛能力
- 可信数据绑定
- 动作安全边界
- surface lifecycle 规则
- 个人与平台飞轮

最稳妥的推进方式是：

```text
规则版按需渲染
-> NeedInference
-> DecisionQuestion
-> WorkspaceState
-> LLM intent parser
-> LLM-assisted render spec
-> User memory
-> Platform pattern flywheel
```

这样可以逐步接近真正的按需渲染，同时避免系统退化成无边界的信息垃圾生成器。
