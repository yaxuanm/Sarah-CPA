# DueDateHQ 交互架构文档

> 本文档定义 DueDateHQ 的完整交互架构。
> 核心原则：对话层和工作区层是同一份状态的两种呈现方式，不是两个独立系统。

---

## 第一性原理

这个产品的本质是：**一个懂税务的助手，帮 Sarah 管理她的工作流。**

三个核心约束：

**约束一：Sarah 的注意力是稀缺资源。** 任何不必要的等待、任何需要她重新定向的操作，都是浪费。

**约束二：税务操作零容错。** 确定性操作必须是确定性的，写操作必须经过确认，Agent 不能在不该做决定的地方做决定。

**约束三：上下文不能断。** Sarah 无论在哪个页面、做了什么操作，系统始终知道她在做什么、为什么在这里。

---

## 唯一的核心问题

整个架构要解决的根本问题只有一个：

**对话层和工作区层必须始终描述同一个状态。**

如果这个同步断了——对话层说"已记录"但工作区还显示旧状态，或者工作区切换了但对话层的按钮还指向旧对象——用户会持续产生疑问："我现在看到的是真实状态吗？"

在税务场景里，这个疑问一旦产生，信任就断了。

**解法：对话层和工作区层不是两个需要同步的独立系统，而是同一份 SystemState 的两种渲染方式。**

```
SystemState（唯一的真实状态）
    ↓
对话层渲染（时间线视图）    ← 同一份数据的两种展示
工作区层渲染（当前焦点视图）←
```

每次操作先更新 SystemState，然后两个层同时从新状态重新渲染。不存在谁先谁后的问题。

---

## 整体架构：三层模型

```
┌─────────────────────────────────────────────────────┐
│              SystemState（唯一真实状态）               │
│   所有操作都先更新这里，两个展示层从这里读取数据         │
├──────────────────────┬──────────────────────────────┤
│      对话层           │         工作区层               │
│   （时间线视图）       │      （当前焦点视图）           │
│   永久存在，记录一切   │    动态替换，有语义身份          │
├──────────────────────┴──────────────────────────────┤
│                    执行层                             │
│        确定性路径              不确定性路径             │
│     /action（<200ms）      /chat（Agent Loop）        │
└─────────────────────────────────────────────────────┘
```

---

## 一、SystemState：唯一的真实状态

```python
@dataclass
class SystemState:

    # 业务数据
    deadlines: dict[str, Deadline]       # 所有 deadline 的当前状态
    clients: dict[str, Client]           # 所有客户
    rules: dict[str, Rule]               # 规则库

    # 交互状态
    current_workspace: WorkspaceSnapshot  # 当前工作区的数据快照
    previous_workspace: WorkspaceSnapshot # 上一个工作区
    breadcrumb: list[str]                # 导航路径
    selectable_items: list[Item]         # 当前可引用对象
    pending_action: Plan | None          # 等待确认的写操作
    prefetch_pool: dict[str, WorkspaceSnapshot]  # 预计算池

    # 对话状态
    conversation: list[ConversationTurn] # 完整对话历史
    history_window: list[ConversationTurn]  # NLU 用最近 10 轮

    # 操作记录
    operation_log: list[Operation]       # 本次 session 所有操作

    # 用户记忆（跨 session）
    preferred_clients: list[str]
    frequent_intents: list[str]
    common_patterns: list[str]

def apply_operation(self, operation: Operation):
    """所有操作都通过这个方法更新状态，保证原子性"""
    # 1. 更新业务数据
    self._update_business_data(operation)
    # 2. 更新交互状态
    self._update_interaction_state(operation)
    # 3. 记录操作
    self.operation_log.append(operation)
    # 4. 失效相关缓存
    self._invalidate_cache(operation)
    # 5. 通知展示层重新渲染
    self._notify_renderers()
```

所有操作都通过 `apply_operation` 更新状态，保证原子性——不存在业务数据更新了但交互状态没更新的情况。

---

## 二、对话层

### 永久存在，记录一切

对话层是整个系统的骨架。无论工作区渲染什么，对话层始终在左侧，记录所有发生的事。

```python
@dataclass
class ConversationTurn:
    role: str                     # "system" | "user"
    message: str                  # 显示在对话区的文字
    actions: list[Action]         # 这条消息附带的按钮
    workspace_ref: str | None     # 关联的工作区快照 key
    operation_ref: str | None     # 关联的操作记录 key
    timestamp: datetime
```

### 对话层的三个职责

**记录** — 每次操作（点击按钮、内联编辑、Agent 回复）都追加一条记录：

```
DH: 当前有 5 件待处理，最早 2026-04-25 到期。
    [Lone Pine Ventures] [Acme Dental] [今天该先做什么]

SJ: Lone Pine Ventures               ← 用户操作回显

DH: Lone Pine 有 2 个截止日期，最近 2026-04-25。
    [记录为已发送] [查看依据] [回到今日清单]

SJ: 记录为已发送

DH: 已记录。还剩 4 件待处理。      ← 操作结果
```

**导航** — 按钮出现在对话区，点击触发工作区切换。按钮是对话的一部分，不是工作区的附属物。

**沟通** — 用户随时可以在输入框说话，不管当前工作区是什么。

### 按钮挂在消息上，不挂在工作区上

这是解决"按钮指向旧对象"问题的关键。

按钮携带的是操作的语义描述，执行时从当前 SystemState 取最新上下文：

```python
@dataclass
class DeterministicAction:
    type: str = "deterministic"
    label: str
    operation_spec: OperationSpec    # 操作的语义描述（不是具体对象引用）
    prefetch_key: str | None
    feedback_template: str           # "已{action}。还剩{remaining}件待处理。"

@dataclass
class AgentRoutedAction:
    type: str = "agent_routed"
    label: str
    prompt: str
    context_keys: list[str]          # 从 SystemState 取哪些上下文注入 Agent
```

---

## 三、工作区层

### 有语义身份的工作空间

工作区不是数据容器，是有目的的工作空间。每个工作区类型定义自己的语义身份：

```python
WORKSPACE_REGISTRY = {

    "TodayQueue": {
        "purpose": "优先级判断",
        "primary_intent": "导航",
        "description": "Sarah 的今日待办，用于决定先处理哪个",
        "editable_fields": [],
        "available_actions": ["snooze_all_low_risk", "export"],
        "context_actions": ["prioritize", "filter", "compare"],
        "prefetch_targets": ["ClientWorkspace"],
    },

    "ClientWorkspace": {
        "purpose": "客户合规管理",
        "primary_intent": "操作",
        "description": "单个客户的合规状态，用于处理具体 deadline",
        "editable_fields": ["due_date", "notes"],
        "available_actions": ["complete", "snooze", "waive", "override"],
        "context_actions": ["view_history", "view_rule", "draft_message"],
        "prefetch_targets": ["AuditWorkspace", "TodayQueue"],
    },

    "AuditWorkspace": {
        "purpose": "审计追溯",
        "primary_intent": "查阅",
        "description": "查看 deadline 的变更历史，不支持修改",
        "editable_fields": [],
        "available_actions": [],
        "context_actions": ["explain_change", "back_to_client"],
        "prefetch_targets": ["ClientWorkspace"],
    },

    "PrioritizeWorkspace": {
        "purpose": "优先级推荐",
        "primary_intent": "决策",
        "description": "Agent 推荐的处理顺序",
        "editable_fields": [],
        "available_actions": [],
        "context_actions": ["start_with_first", "adjust_priority"],
        "prefetch_targets": ["ClientWorkspace"],
    },

    "ConfirmWorkspace": {
        "purpose": "写操作确认",
        "primary_intent": "确认",
        "description": "确认一个写操作，防止误操作",
        "editable_fields": [],
        "available_actions": ["confirm", "cancel"],
        "context_actions": [],
        "prefetch_targets": [],
    },

    "GuidanceWorkspace": {
        "purpose": "意图澄清",
        "primary_intent": "引导",
        "description": "系统无法确定意图，请用户选择",
        "editable_fields": [],
        "available_actions": [],
        "context_actions": ["option_select"],
        "prefetch_targets": [],
    },
}
```

### 工作区的三种目的类型

```
操作型（ClientWorkspace、ConfirmWorkspace）
  editable_fields 非空，available_actions 丰富
  用户进来是为了做事情

导航型（TodayQueue、PrioritizeWorkspace）
  editable_fields 为空，按钮主要是跳转入口
  用户进来是为了决定去哪里

查阅型（AuditWorkspace）
  editable_fields 为空，available_actions 为空
  用户进来是为了看信息
```

### 字段的渲染规则

同样的字段在不同工作区有不同的渲染方式：

```python
def render_field(field_name, value, workspace_type, system_state):
    spec = WORKSPACE_REGISTRY[workspace_type]

    if field_name in spec["editable_fields"]:
        # 可编辑：显示值，点击变成编辑器
        return InlineEditableField(
            value=value,
            on_save=lambda new_val: execute_deterministic(
                OperationSpec("override", field=field_name, new_value=new_val),
                system_state
            )
        )
    else:
        # 只读：显示值，给出跳转提示
        correct_workspace = find_edit_workspace(field_name)
        return ReadonlyField(
            value=value,
            tooltip=f"在 {correct_workspace} 中可修改" if correct_workspace else None
        )
```

### 跨工作区操作的处理

用户在查阅型工作区请求操作型行为，系统引导而不是拒绝：

```python
def handle_cross_workspace_request(request, system_state):
    current_spec = WORKSPACE_REGISTRY[system_state.current_workspace.type]

    if not is_applicable(request, current_spec):
        correct = find_correct_workspace(request)
        return Response(
            message=f"这里是{current_spec['description']}，"
                    f"不支持此操作。需要在 {correct} 中进行。",
            actions=[DeterministicAction(
                label=f"前往 {correct}",
                prefetch_key=f"{correct}:{current_item_id(system_state)}"
            )]
        )
```

---

## 四、执行层

### 两条路径，完全分离

```
确定性路径                       不确定性路径
──────────                       ──────────
触发：确定性按钮 / 内联编辑        触发：不确定性按钮 / 输入框

路由：/action                    路由：/chat

处理：                            处理：
  1. 查预计算池                     1. 注入完整 SystemState 上下文
     命中 → 0ms 视图切换              2. 视图可行性预判
     未命中 → /action                 3. Intent Cache 查询
  2. 写操作 → ConfirmWorkspace         4. Agent Loop（Tool Use + ReAct）
  3. 读操作 → 直接执行                    工具调用（完全开放）
  4. 更新 SystemState                     写操作拦截（ConfirmWorkspace）
  5. 两层同时重新渲染                      视图白名单验证
                                          确定性数据构建
响应时间：0-200ms                   5. 更新 SystemState
                                  6. 两层同时重新渲染

                                 响应时间：500-1500ms
```

### 预计算机制

工作区渲染完成时，根据 `prefetch_targets` 在后台预计算目标工作区：

```python
async def render_workspace(workspace_type, data, system_state):
    # 渲染当前工作区
    snapshot = build_workspace_snapshot(workspace_type, data)
    system_state.apply_operation(
        Operation("workspace_change", snapshot=snapshot)
    )

    # 后台并行预计算目标工作区
    spec = WORKSPACE_REGISTRY[workspace_type]
    tasks = []
    for target_type in spec["prefetch_targets"]:
        for item in data.get("items", [])[:5]:
            key = f"{target_type}:{item['id']}"
            tasks.append(
                asyncio.create_task(
                    compute_workspace_snapshot(target_type, item["id"], system_state)
                )
            )

    results = await asyncio.gather(*tasks, return_exceptions=True)
    for key, result in zip(keys, results):
        if not isinstance(result, Exception):
            system_state.prefetch_pool[key] = result
```

预计算在工作区渲染完成后立即开始，通常在用户做出下一步决定之前就完成了。

### 缓存失效规则

操作发生后，相关缓存立即失效：

```python
def _invalidate_cache(self, operation: Operation):
    if operation.type in ["complete", "snooze", "waive", "override"]:
        # deadline 状态变更，失效所有包含该 deadline 的工作区快照
        affected_keys = [
            k for k in self.prefetch_pool
            if operation.deadline_id in self.prefetch_pool[k].data
        ]
        for key in affected_keys:
            del self.prefetch_pool[key]
```

这保证了用户永远不会看到过期的预计算数据。

---

## 五、Agent 架构

### Tool Use + ReAct 循环

```python
async def agent_loop(user_input, system_state):
    messages = build_messages(user_input, system_state)

    for _ in range(5):  # 安全阀：最多 5 轮
        response = await claude.messages.create(
            model="claude-sonnet-4-6",
            tools=TOOLS,
            system=build_system_prompt(system_state),
            messages=messages
        )

        tool_calls = extract_tool_calls(response)

        # 写操作拦截：直接返回 ConfirmWorkspace，不经过 Agent 视图判断
        if any(is_write_op(t.name) for t in tool_calls):
            return build_confirm_workspace(tool_calls, system_state)

        # 模型决定结束
        if response.stop_reason == "end_turn":
            view_type = extract_view_choice(response)
            validated = view_validator.validate(view_type, system_state)
            workspace = build_workspace_snapshot(
                validated.view_type,
                extract_tool_results(messages),
                system_state
            )
            message = extract_message(response)
            return AgentResponse(message=message, workspace=workspace)

        # 读操作：执行，结果喂回模型
        tool_results = execute_read_ops(tool_calls, system_state)
        messages = append_results(messages, tool_results)
```

### Agent 的 system prompt 注入 SystemState

```python
def build_system_prompt(system_state: SystemState) -> str:
    workspace_spec = WORKSPACE_REGISTRY[system_state.current_workspace.type]

    return f"""
你是 DueDateHQ 的交互 Agent。

当前工作区：{system_state.current_workspace.type}
工作区目的：{workspace_spec['purpose']}
工作区描述：{workspace_spec['description']}
导航路径：{" → ".join(system_state.breadcrumb)}
可编辑字段：{workspace_spec['editable_fields']}
本次已操作：{format_operation_log(system_state.operation_log)}
当前可引用对象：{format_selectable(system_state.selectable_items)}
用户偏好：最常查询 {system_state.preferred_clients[:2]}

工作区语义约束：
- 如果用户的请求超出当前工作区的目的，引导到正确的工作区
- 可编辑字段为空时，不允许修改任何数据
- 写操作必须经过 ConfirmWorkspace 确认

可用视图白名单：
{format_workspace_registry(WORKSPACE_REGISTRY)}

重要：只能从白名单中选择视图类型，不能创造新类型。
如果现有视图无法满足用户需求，选择 GuidanceWorkspace 并说明原因，
同时记录这个需求缺口。
    """
```

### 视图可行性预判

在 Agent Loop 开始前，轻量预判现有视图是否能回答用户的问题：

```python
async def assess_feasibility(user_input, system_state):
    response = await claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        messages=[{"role": "user", "content": f"""
用户问题：{user_input}
可用工作区：{format_workspace_registry(WORKSPACE_REGISTRY)}

输出 JSON：
{{
  "can_answer": true/false,
  "best_workspace": "工作区名或 null",
  "gap": "缺少什么能力",
  "user_need": "用户真正需要的",
  "closest_workspace": "最接近的现有工作区"
}}
        """}]
    )
    return FeasibilityResult(**parse_json(response.content[0].text))
```

检测到 gap 时，记录到 ViewGapRegistry，积累到 5 次自动进产品待办。

---

## 六、追问信号：飞轮的最后一块

每次用户追问，系统判断信号类型，写入飞轮：

```python
def classify_followup(prev_turn, curr_input, system_state):
    text = curr_input.lower()

    if re.search(r"不是|不对|错了|我要的是|no that's not", text):
        return "correction"      # 意图理解偏了

    if re.search(r"为什么|来源|怎么来的|source|where.*from", text):
        return "missing_info"    # 视图缺字段

    return "drill_down"          # 正常深入

async def process(user_input, system_state):
    if system_state.conversation:
        prev = system_state.conversation[-1]
        signal = classify_followup(prev, user_input, system_state)

        if signal == "correction":
            intent_library.record_feedback(
                prev.operation_ref, is_correction=True
            )
            review_queue.append(prev, user_input)

        elif signal == "missing_info":
            intent_library.record_missing_field(
                prev.operation_ref, user_input
            )
```

三个纠错时间点：

- **执行前**：视图可行性预判
- **执行中**：意图描述帧（Agent Loop 第一轮后推送）
- **执行后**：追问信号分类

---

## 七、完整的操作闭环

以"Sarah 处理 Lone Pine 的 deadline"为例：

```
1. 系统推送今日摘要
   SystemState 更新：current_workspace = TodayQueue
   对话层渲染：DH 消息 + 操作按钮
   工作区渲染：TodayQueue（5条待办）
   后台预计算：前 5 个 ClientWorkspace

2. Sarah 点击"Lone Pine Ventures"（确定性按钮）
   执行层：查预计算池 → 命中 → 0ms
   SystemState.apply_operation(workspace_change: ClientWorkspace)
   对话层重新渲染：追加"正在查看 Lone Pine..."
   工作区重新渲染：ClientWorkspace
   后台预计算：AuditWorkspace、TodayQueue

3. Sarah 直接编辑截止日期（内联编辑）
   执行层：走 /action
   SystemState.apply_operation(override: due_date = 2026-05-15)
   缓存失效：包含该 deadline 的所有预计算失效
   对话层重新渲染：追加"截止日期已更新为 2026-05-15"
   工作区重新渲染：字段显示新日期

4. Sarah 点击"查看依据"（不确定性按钮）
   执行层：走 /chat
   对话层：显示意图描述帧"正在查询规则来源..."
   Agent Loop：调用 deadline_transitions
   SystemState.apply_operation(workspace_change: AuditWorkspace)
   对话层重新渲染：追加 Agent 回复
   工作区重新渲染：AuditWorkspace

5. Sarah 在 AuditWorkspace 打字"把这个日期改了"
   Agent 检测：AuditWorkspace 是查阅型，editable_fields 为空
   SystemState 不更新（未执行操作）
   对话层：追加"历史记录不支持修改，需要回到 Lone Pine 管理页面"
   工作区：渲染引导按钮

6. Sarah 点击"返回 Lone Pine"（确定性按钮）
   执行层：查预计算池 → 命中 → 0ms
   SystemState.apply_operation(workspace_change: ClientWorkspace)
   对话层重新渲染：追加"已返回 Lone Pine"
   工作区重新渲染：ClientWorkspace（数据来自 SystemState 最新状态）

7. Sarah 点击"记录为已发送"（确定性写操作）
   执行层：走 /action → 写操作拦截
   SystemState.apply_operation(workspace_change: ConfirmWorkspace)
   对话层重新渲染：ConfirmWorkspace 消息
   工作区重新渲染：ConfirmWorkspace

8. Sarah 确认
   SystemState.apply_operation(complete: deadline_id)
   SystemState.apply_operation(workspace_change: TodayQueue)
   缓存失效：相关预计算
   对话层重新渲染：追加"已记录。还剩 4 件待处理。"
   工作区重新渲染：TodayQueue（deadline 已消失）
```

关键：每一步都是先更新 SystemState，然后对话层和工作区同时从新状态渲染。用户在任何时刻看到的对话层和工作区，描述的是同一个状态。

---

## 八、响应时间分层

```
瞬时（0ms）
    预计算命中的确定性按钮
    内联字段切换编辑状态

快速（50-200ms，无 LLM）
    预计算未命中的确定性按钮
    内联编辑保存
    写操作确认执行
    → /action 接口，纯 Python

正常（500-1500ms，走 Agent）
    不确定性按钮
    输入框文字输入
    语音输入
    → /chat 接口，Agent Loop
    → 第一帧（意图描述）< 500ms
    → 最终帧 < 1500ms
```

---

## 九、技术依赖

```python
# 核心
anthropic          # Tool Use + ReAct，claude-sonnet-4-6
fastapi            # API 网关
sse-starlette      # SSE 分帧推送
uvicorn            # ASGI server

# 状态管理
redis              # SystemState 持久化，TTL=3600

# 向量检索（Intent Cache）
pgvector           # PostgreSQL 扩展
psycopg2-binary    # PostgreSQL 客户端
sentence-transformers  # 本地 embedding（验证阶段）
openai             # text-embedding-3-small（生产阶段）

# 已有
duedatehq.engine   # 直接 import，不走子进程
```

不引入 LangChain、AutoGen、Pinecone 等外部框架。

---

## 十、架构边界

### 在架构范围内

- 对话层 + 工作区层的统一状态管理
- 确定性 / 不确定性按钮的完整路径
- 工作区语义身份和跨工作区引导
- 预计算机制和缓存失效规则
- Agent Loop 的视图白名单和 Harness
- 追问信号和飞轮闭环
- 视图可行性预判和需求缺口记录

### 不在架构范围内（独立模块）

- 规则库的抓取和解析（现有 CLI 基础设施）
- 提醒调度和推送（现有 worker + Celery）
- 多租户数据隔离（现有 PostgreSQL RLS）
- 语音输入（Whisper，转文字后进入同一路径）

---

## 一句话总结

**SystemState 是唯一的真实状态，对话层和工作区层是它的两种呈现。执行层有两条路径：确定性操作绕过 Agent 直接执行，不确定性操作由 Agent 推理后执行。所有操作都先更新 SystemState，然后两个层同时重新渲染，用户永远看到一致的状态。**

验证：
分三层验证，从内到外。

---

## 第一层：机器验证（自动化，开发阶段）

**验证 SystemState 的原子性**

每次操作后，对话层和工作区层的数据必须来自同一个 SystemState 快照：

```python
def test_state_consistency():
    state = SystemState()
    state.apply_operation(Operation("complete", deadline_id="dl-001"))

    # 对话层和工作区层读到的是同一个状态
    conv_view = render_conversation(state)
    workspace_view = render_workspace(state)

    assert conv_view.deadline_status("dl-001") == "completed"
    assert workspace_view.deadline_status("dl-001") == "completed"
    # 两者必须一致，不允许任何差异
```

**验证写操作永远过确认**

```python
def test_write_always_confirms():
    write_inputs = [
        "完成第一条",
        "record as sent",
        "mark done",
        "snooze this one"
    ]
    for inp in write_inputs:
        result = process(inp, mock_session)
        assert result.workspace_type == "ConfirmWorkspace"
        assert result.system_state.pending_action is not None
        # 状态机没有执行，只是等待确认
        assert mock_session.deadline_status == "pending"
```

**验证缓存失效**

```python
def test_cache_invalidation():
    state = SystemState()
    # 预计算 ClientWorkspace
    state.prefetch_pool["ClientWorkspace:cl-001"] = compute_client_ws("cl-001")

    # 执行一个影响该客户的操作
    state.apply_operation(Operation("complete", deadline_id="dl-001",
                                    client_id="cl-001"))

    # 预计算必须失效
    assert "ClientWorkspace:cl-001" not in state.prefetch_pool
```

**验证工作区语义边界**

```python
def test_workspace_semantic_boundary():
    # AuditWorkspace 是查阅型，不应该有可编辑字段
    audit_spec = WORKSPACE_REGISTRY["AuditWorkspace"]
    assert audit_spec["editable_fields"] == []
    assert audit_spec["available_actions"] == []

    # Agent 在 AuditWorkspace 上收到修改请求，应该引导而不是执行
    result = agent_process("把这个日期改了",
                           current_workspace="AuditWorkspace")
    assert result.workspace_type != "ConfirmWorkspace"  # 没有执行写操作
    assert "ClientWorkspace" in result.message  # 引导去正确的工作区
```

**验证按钮分类**

```python
def test_button_classification():
    # 所有确定性按钮的操作集合，必须覆盖 available_actions
    for ws_type, spec in WORKSPACE_REGISTRY.items():
        workspace = render_workspace(ws_type, mock_data)
        deterministic_btns = [b for b in workspace.buttons
                              if b.type == "deterministic"]
        agent_btns = [b for b in workspace.buttons
                     if b.type == "agent_routed"]

        # 确定性按钮只来自 available_actions
        for btn in deterministic_btns:
            assert btn.operation in spec["available_actions"]

        # 不确定性按钮只来自 context_actions
        for btn in agent_btns:
            assert btn.action in spec["context_actions"]
```

这一层的验收标准：**所有测试通过，zero wrong matches，写操作零误触。**

---

## 第二层：场景验证（半自动，集成阶段）

**核心场景走通**

定义五个核心场景，每个场景手动走一遍，验证每一步的状态：

```
场景一：今日待办 → 打开客户 → 记录为已发送
  验证：
  ✓ 点击客户名，0ms 切换（预计算命中）
  ✓ 点击"记录为已发送"，弹出 ConfirmWorkspace
  ✓ 确认后，deadline 从列表消失
  ✓ 对话层显示"已记录，还剩 N 件"
  ✓ 对话层和工作区显示的剩余数量一致

场景二：查阅型工作区上发起修改
  验证：
  ✓ 在 AuditWorkspace 说"把日期改了"
  ✓ Agent 拒绝执行，引导到 ClientWorkspace
  ✓ 点击引导按钮，跳回 ClientWorkspace
  ✓ 对话层有完整的操作记录

场景三：操作后数据一致性
  验证：
  ✓ 在 ClientWorkspace 修改截止日期
  ✓ 回到 TodayQueue，该客户显示新日期
  ✓ 预计算池中旧的 ClientWorkspace 快照已失效
  ✓ 再次打开客户，显示新日期（不是缓存的旧日期）

场景四：Agent 生成新工作区
  验证：
  ✓ 点击"今天该先做什么"（不确定性按钮）
  ✓ 意图描述帧在 500ms 内出现
  ✓ Agent 生成 PrioritizeWorkspace
  ✓ 视图类型在白名单内
  ✓ 对话层有 Agent 的推荐说明

场景五：追问信号
  验证：
  ✓ Agent 生成 ClientWorkspace 后，用户说"不对，我要看已完成的"
  ✓ 系统识别为 correction 信号
  ✓ review_queue 有记录
  ✓ intent_library 的 success_rate 下降
```

**响应时间验证**

```bash
# 确定性路径（预计算命中）
measure_time: 点击按钮 → 工作区切换完成
目标: < 50ms

# 确定性路径（预计算未命中）
measure_time: 点击按钮 → /action 返回 → 工作区渲染完成
目标: < 200ms

# 不确定性路径
measure_time: 发送输入 → 意图描述帧出现
目标: < 500ms

measure_time: 发送输入 → 最终工作区渲染完成
目标: < 1500ms
```

这一层的验收标准：**五个核心场景全部走通，响应时间达标，对话层和工作区在每一步都显示一致的状态。**

---

## 第三层：用户验证（真实用户，上线前）

这一层不看技术指标，看用户行为。

**找 5 个真实 CPA，用 30 天。**

观察以下行为信号，不问用户感受，直接看数据：

**信号一：用户有没有重复操作**

如果用户点了"记录为已发送"之后，又去打字确认"刚才的操作成功了吗"，说明对话层和工作区的状态不一致，用户不确定操作有没有生效。

目标：重复确认操作的比例 < 5%。

**信号二：用户有没有走错工作区**

如果用户在 AuditWorkspace 上反复尝试修改，说明工作区的语义引导不够清晰。

目标：跨工作区修改请求被正确引导的比例 > 95%。

**信号三：追问的类型分布**

```
correction（意图理解偏了）  目标 < 8%
missing_info（视图缺字段）  目标 < 15%
drill_down（正常深入）      目标 > 77%
```

如果 correction 比例高，说明 NLU 准确率不够。如果 missing_info 比例高，说明视图设计缺少关键信息。

**信号四：按钮使用 vs 输入框使用的比例**

确定性按钮覆盖了高频操作之后，用户应该主要用按钮，偶尔用输入框处理复杂情况。

```
按钮操作     目标 > 70%
输入框对话   目标 < 30%
```

如果输入框比例过高，说明按钮设计没有覆盖用户的实际需求，或者按钮太难发现。

**信号五：30 天后的使用频率趋势**

如果架构是对的，用户用得越多应该越顺手——因为飞轮在积累，系统越来越懂这个用户。

目标：第 4 周的日均使用时长比第 1 周下降（不是增加）。

使用时长下降说明用户完成同样的工作花了更少时间，效率提升了。这才是真正的成功信号。

---

## 最终判断标准

```
第一层（机器验证）    全部测试通过，写操作零误触      → 可以进行第二层
第二层（场景验证）    五个核心场景通过，响应时间达标   → 可以进行第三层
第三层（用户验证）    信号四和五达标，用户主动问上线   → 系统验证成功
```

第三层的最终信号只有一个：**30 天结束时，至少 4 个用户主动问"这个什么时候正式上线"。**

前两层是门槛，这一句话才是成功。
