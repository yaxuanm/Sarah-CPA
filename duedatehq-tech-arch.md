# DueDateHQ 技术架构文档

> 本文档同时记录两件事：目标架构，以及截至当前代码库已经真实落地的 MVP 状态。
> 核心原则不变：Executor 直接调用 engine 函数，不走子进程。

---

## 当前状态快照

截至当前代码库，DueDateHQ 已经完成的是**后端交互闭环、飞轮验证基础设施、opt-in 的真实 Claude Sonnet 4.6 NLU 验证路径、Anthropic SDK Tool Use + ReAct Agent Kernel、opt-in 的 cache-first 飞轮运行时路由、追问信号进入飞轮、SQLite 持久化飞轮、Redis session 适配、最小 FastAPI/SSE 骨架、以及 React 前端验证壳**。还没有完成的是**生产级前端接入、后端 render spec generator、生产级 embedding/pgvector 检索、线上 rerank、以及 Sonnet response generator**。

当前已落地：

| 模块 | 当前状态 | 代码位置 |
|---|---|---|
| App 装配 | `create_app()` 已装配 engine、executor、planner、intent library、response generator、interaction backend、内存 session | `src/duedatehq/app.py` |
| 自然语言入口 | `process_message()` 已能处理用户输入、确认、取消、pending action | `src/duedatehq/core/interaction_backend.py` |
| Agent Kernel | 已作为主链路第一跳：默认确定性 kernel，`DUEDATEHQ_USE_AGENT_KERNEL=1` 或兼容 `DUEDATEHQ_USE_AGENT_POLICY=1` 后可用 Claude Sonnet 4.6 通过 Anthropic 原生 Tool Use + ReAct 循环自主查工具、观察结果、选择回答/渲染/追问/交给 planner/flywheel | `src/duedatehq/core/agent_kernel.py` |
| 已知路由快路径 | 已新增 pre-agent known route gate：列表行点击、`打开第 N 条` 等存量 UI 动作先命中确定性 `ClientCard`/planner 路径，不交给 Agent 生成临时工作面 | `src/duedatehq/core/interaction_backend.py` |
| 双路径交互 | 已新增 direct action contract：`selectable_items[].action` 携带完整 read plan，前端点击列表行走 `/action`，不再把按钮点击伪装成自然语言输入 | `src/duedatehq/http_api.py`, `frontend/src/App.tsx` |
| 默认 NLU | 默认仍用 `RuleBasedIntentPlanner` 保持本地 MVP 稳定，输出 Plan JSON | `src/duedatehq/core/intent_planner.py` |
| Claude NLU | 已新增 `ClaudeNLUService`，设置 `DUEDATEHQ_USE_CLAUDE_NLU=1` 可切到 Claude；当前默认模型为 `claude-sonnet-4-6`，`CLAUDE_NLU_MODEL` 仍可显式切回 Haiku 等模型 | `src/duedatehq/core/nlu_service.py` |
| Plan Validator | 已新增确定性 `PlanValidator`，限制 LLM 只能使用 executor 支持的命令和参数，写操作必须声明 `op_class=write` | `src/duedatehq/core/plan_validator.py` |
| Intent Cache | 内存版 `InMemoryIntentLibrary`，使用 lexical/semantic feature，不是真实 embedding | `src/duedatehq/core/intent_cache.py` |
| Persistent Intent Cache | 已新增 SQLite 版 `SQLiteIntentLibrary`，设置 `DUEDATEHQ_PERSIST_FLYWHEEL=1` 后持久化 templates/examples/feedback/review queue | `src/duedatehq/core/persistent_intent_cache.py` |
| Flywheel Router | 已新增 `FlywheelIntentRouter`，设置 `DUEDATEHQ_USE_FLYWHEEL_ROUTER=1` 后先查 intent cache，miss 再走 planner，成功后学习模板；可与 Claude NLU 组合 | `src/duedatehq/core/flywheel_router.py` |
| Follow-up Feedback | 已新增规则型追问信号分类：correction / missing_info / drill_down；correction 降低 template success_rate，missing_info 记录缺失字段诉求 | `src/duedatehq/core/followup_feedback.py` |
| Executor | `PlanExecutor` 已直接调用 engine，支持 `cli_call`、`resolve_entity`、`post_filter`、`foreach`；已可调用 task/blocker/notice/import/client bundle | `src/duedatehq/core/executor.py` |
| Response | 确定性生成 `ListCard` / `ClientCard` / `ConfirmCard` / `HistoryCard` / `ReminderPreviewCard` / `ClientListCard` / `ReviewQueueCard` / `GuidanceCard`，暂未接 Claude Sonnet | `src/duedatehq/core/response_generator.py` |
| 按需渲染契约 | 已新增 contract tests，验证 user need → intent → view.type → 必要事实/action，不允许 source/notification/client/rule 等场景退化成随机 generic panel | `tests/test_on_demand_rendering_contract.py` |
| Session | 内存版 `InMemoryInteractionSessionManager`；设置 `DUEDATEHQ_REDIS_URL` 后可用 `RedisInteractionSessionManager`，TTL 默认 3600 秒 | `src/duedatehq/core/session_manager.py` |
| API helper | 有 Python helper：`process_message`、`process_plan`、`process_action`、`start_interaction_session` | `src/duedatehq/api.py` |
| HTTP API | 已新增可选 FastAPI app，提供 `/bootstrap/today`、`/chat`、`/action`、`/chat/stream`、`/session/:id`、`/flywheel/stats`；安装 `duedatehq[api]` 后可用 | `src/duedatehq/http_api.py` |
| 前端验证壳 | 已新增 React/Vite app；支持左侧真实输入、右侧按 `view.type` 渲染、可接 `/chat/stream`，支持 markdown 消息和 `message_delta` 增量传输 | `frontend/` |
| Flywheel CLI | 已新增 `flywheel stats/templates/feedback/review-queue`，可查看模板、反馈、review queue | `src/duedatehq/cli.py` |
| 传统后端能力 | 已合入 notice → task/blocker、CSV import preview/apply、task/blocker 对象、client bundle、CSV export | `src/duedatehq/core/engine.py`, `src/duedatehq/cli.py` |
| 飞轮样本 | 230 条人工基础样本，覆盖 11 类基础 intent | `src/duedatehq/core/intent_samples.py` |
| 飞轮验证 | 支持 full replay、labeled replay、holdout、Claude 生成模拟样本、真实 Claude NLU eval | `src/duedatehq/core/flywheel.py`, `scripts/` |
| 测试 | 当前后端交互、飞轮、NLU validator 相关测试通过 | `tests/test_*.py` |

---

## 目标状态：Smart Agent + On-demand Rendering

“按需渲染”的最终形态不是一个固定 dashboard 加聊天框，而是一个**聪明 Agent + 自动渲染工作面**：

1. 用户输入的是 intention，不是菜单命令。
2. Agent 根据当前页面、曾看过的页面、可选对象、历史对话和工具结果，推断用户当下真正需要什么。
3. Agent 自主决定要调用哪些受控工具，判断数据是否足够。
4. Agent 决定当前应该保留页面、更新页面、渲染新页面、要求确认写操作，还是只在对话里回答。
5. 如果现有视图不足以表达这个需求，先用受约束的 `RenderSpecSurface` 生成临时工作面；同类追问积累后进入产品待办，评估是否新增正式视图组件。

因此核心链路是：

```text
用户输入
    ↓
Known Route Gate 命中存量 UI 动作 → 直接执行现有 view contract
    ↓ miss
Direct Action 按钮/列表点击 → /action 直接执行 plan，不进入 Agent/NLU
    ↓ 仅自由文字输入继续
Intent Cache 命中高频简单意图 → 直接执行
    ↓ miss
Agent Kernel
    ↓
Claude Tool Use / ReAct loop
    ├── get_current_view
    ├── list_visible_deadlines
    ├── list_all_clients
    ├── list_all_deadlines
    ├── list_client_deadlines
    ├── list_blockers
    └── list_tasks
    ↓
Agent 输出 constrained decision
    ↓
InteractionBackend
    ├── 写操作 → ConfirmCard
    ├── 已知视图 → ResponseGenerator 构建确定性 view.data
    └── 未知但有用的需求 → RenderSpecSurface
    ↓
前端按 view.type / render_spec 渲染
    ↓
用户追问 → correction / missing_info / drill_down 进入飞轮
```

这个设计刻意不引入 LangGraph/LangChain。ReAct loop 只是标准 Python while loop；工具调用使用 Anthropic 官方 SDK 原生 `tool_use` / `tool_result`。这样保留 Agent 的语义能力，同时让 DueDateHQ 控制工具、数据、写操作确认和最终视图契约。

一个关键边界是：Agent Kernel 不是所有输入的第一执行者。已知 UI 动作和存量工作流先走确定性路由，例如“打开第 1 条”“完成当前这个”“回到今天”。这些动作已经有稳定的 `view.type` 契约和测试，不应该被 Claude 重新解释成 `RenderSpecSurface`。Agent Kernel 只负责 known route / cache / planner 覆盖不了的语义判断、复合查询、策略视图和长尾按需渲染。

交互层也必须双路径分离：按钮和列表点击是确定动作，应该携带完整 `direct_execute` action 并调用 `/action`；自由文字和语音输入才进入 `/chat/stream` 的 Agent Loop。当前 `ListCard` 的 `selectable_items` 已携带打开对应 `ClientCard` 的 read plan，前端点击行会直接调用 `/action`，后端通过 `process_direct_action()` 执行并更新 session。写操作即使来自 `/action` 也仍然只生成 `ConfirmCard`，不会绕过确认。

当前验证结果：

```text
基础样本：230
基础 intent：11
基础 holdout：100% hit / 100% accuracy / 0 wrong matches

Claude 模拟样本：55
合并样本：285
LLM 模拟 holdout：94.34% hit / 94.34% accuracy / 0 wrong matches

真实 Claude Sonnet 4.6 NLU 小规模验证：
- 每类 1 条：11/11，100%
- 每类 2 条：22/22，100%
- 每类 5 条：55/55，100%

Flywheel Router 运行时模拟：
- 样本：230
- 第一轮：planner calls 35 / 230，cache hit 195 / 230，cache hit rate 84.78%
- 第二轮：planner calls 0 / 230，cache hit 230 / 230，cache hit rate 100%
- 学到模板：11
- 从第一轮到第二轮的 planner call reduction：100%

追问信号验证：
- 用户说“不对 / 不是这个 / wrong”会记录 correction event
- 如果上一轮来自模板，模板 `success_rate` 会下降，`correction_count` 增加
- 用户问“来源 / 历史 / 缺什么 / 谁改的”等，会记录 missing_info
- correction 输入不会被学习成新模板，避免把纠错语句污染 intent library

持久化飞轮验证：
- `DUEDATEHQ_PERSIST_FLYWHEEL=1` 后模板、examples、canonical plan、success_rate、feedback events 会写入 SQLite
- 重启 app 后相似输入仍能命中已学习模板
- correction / missing_info 事件可通过 library 和 CLI 查询

HTTP/SSE 骨架验证：
- `/bootstrap/today` 是默认入口 fast path，直接走 today plan，不进入 Agent/NLU
- `/chat` 返回 response + session
- `/action` 是确定性按钮路径，直接执行 action plan；读操作渲染现有 view，写操作返回 `ConfirmCard`
- `/chat/stream` 推送 `message_delta`、`intent_confirmed`、`view_rendered`、`feedback_recorded`、`done`
- `/chat/stream` 在进入 Agent 推理前先推一个即时 `message_delta`，让左侧对话立刻开始流式输出
- `/flywheel/stats` 返回当前 intent library 指标

Agent Kernel 验证：
- “今天先做什么”仍走 planner / flywheel，不被 kernel 截断
- “打开第 1 条”这类列表行动作先走 known route，直接打开现有 `ClientCard`，即使 Claude Agent 可用也不会生成临时工作面
- 前端真实列表行点击不再发送“打开第 1 条”文本，而是使用 `selectable_items[].action` 走 `/action`，因此正常点击不会消耗 Agent/LLM
- “这几件事分别是什么”会识别为 `explain_current_view`，保留当前 `ListCard`，左侧逐条解释
- “急着处理么 / 哪个最优先”会识别为 `answer_advice`，保留当前页面并回答判断依据
- “我所有的客户的情况如何 / 哪个客户最不紧急”这类开放问题不再由关键词策略硬编码；Claude Agent Kernel 自主调用允许工具、观察结果，再输出 `need_type`、`view_goal`、`suggested_actions`
- 导航、写操作、查来源等仍交给 planner / executor / confirmation flow

前端验证壳：
- `frontend/` 只保留 AI/SSE 后端路径，不再提供 Local 模式
- 已经实现 stream client，可消费 `/chat/stream`
- 左侧消息支持轻量 markdown 渲染，并通过 `message_delta` 增量更新同一条 assistant message
- 已知 `view.type` 有专门 renderer，未知/随机需求进入受约束 `RenderSpecSurface`
- `npm run test:render-spec` 验证 6 条随机需求都能生成合法 render spec，并包含可执行下一步

按需渲染契约验证：
- `today` → `ListCard`，必须包含 deadline/client/tax/due/status/days_remaining 等决策事实
- `client_deadline_list` → `ClientCard`，只包含被请求客户的事项，不给跨任务快捷跳转
- `deadline_action_complete` → `ConfirmCard`，确认前不修改状态，并说明确认后果
- `deadline_history` → `HistoryCard`，必须包含当前 deadline、source_url、transitions，而不是 generic GuidanceCard
- `upcoming_deadlines` → `ListCard`，只显示 pending 未来事项，不混入 completed
- `completed_deadlines` → `ListCard`，只显示 completed 事项，不提供写操作 action
- `notification_preview` → `ReminderPreviewCard`，必须包含 reminder、client、deadline、due date、tax type
- `client_list` → `ClientListCard`，展示客户清单，不提供任务操作
- `rule_review` → `ReviewQueueCard`，展示 review_id、source_url、raw_text、confidence_score

全飞轮闭环测试：
- cache miss → planner → learn template
- similar input → cache hit → render contract
- correction → template success_rate 下降并进入 review queue
- missing_info → 记录到对应 intent template
- write intent → ConfirmCard，确认前不变更数据
- confirm → 执行 engine action，回到 ListCard

这轮真实 NLU 验证暴露并修正了三个边界问题：
- “为什么这个还没完成”应当是 `deadline_history`，不是 `defer`
- `help` 不能发明 `help.show` 命令，应当返回 guidance
- 模型偶发 malformed JSON 时，允许一次 JSON repair，但 repair 后仍必须通过 `PlanValidator`

pytest：96 passed, 1 skipped
```

当前关键判断：

- MVP 现在可以验证“对话即行动，行动即对话”的最小闭环。
- 飞轮可以验证“高置信缓存复用 + 未命中走 LLM fallback”的机制。
- 当前 matcher 不是生产级语义检索，只是为了验证收敛机制和危险错命中边界。
- 当前最重要的质量指标不是覆盖率到 100%，而是 write intent 和跨轮引用不能错命中。
- Claude NLU 已经能跑真实链路，但暂时是 opt-in；默认路径保持规则 planner，避免还没接 FastAPI/Redis 前把本地 MVP 变得不稳定。
- Flywheel Router 已经能证明“同类需求越多，planner/LLM 调用越少”的成本下降机制；SQLite 模式开始支持跨 app 重启验证。
- Follow-up Feedback 已经能证明“用户纠错和追问可以反向改变模板质量”的机制；SQLite 模式下 review queue 和 missing info 已可持久化查询。
- 按需渲染现在有了第一层自动化验收：不是只验证“有 response”，而是验证 response 是否服务当前用户意图、是否包含必要事实、是否避免无关下一步。
- 前端现在可以开始验证“是否可玩”：同一套对话输入可以驱动真实 `view.type` renderer，也可以用受约束 `render_spec` 检查随机需求是否退化成 generic panel。

---

## 整体架构

下面是目标架构，不代表当前全部已实现：

```
前端（React）
    ↑↓ HTTP / SSE
API 网关（FastAPI）
    ├── POST /chat          主对话入口
    ├── POST /action        action 直接执行（不走 NLU）
    └── GET  /session/:id   session 恢复
    ↓
交互后端（五层）
    ├── Agent Kernel        Tool Use + ReAct 判断此刻应该回答、查数据、渲染页面、追问还是执行前确认
    ├── Intent Cache        飞轮第一关：意图模板匹配
    ├── NLU                 Claude Sonnet 4.6 → Plan JSON（仅在缓存未命中时调用）
    ├── Executor            Plan → CLI 调用序列 → 聚合结果
    ├── Response Generator  Claude Sonnet → message + view
    └── Session             Redis TTL=3600
    ↓
现有 CLI 基础设施（engine.py 直接 import）
    ↓
PostgreSQL / SQLite
```

### Agent-Native 技术方向

现在这套系统的地基是对的：有 session、executor、view contract、确认流、飞轮和 SSE。上一版链路偏 `planner-first`，现在已经开始迁到 `agent-first`：

```text
用户输入
  ↓
Claude Agent Kernel
  ↓
受控 Tool Use / ReAct
  ↓
Intent Cache / Planner 快路径或 ResponseGenerator / RenderSpecSurface
```

这会导致一个根本问题：即使用 Claude Sonnet 4.6，模型也只是一个窄路由器，无法真正主导“现在应该理解什么、查什么、展示什么”。所以系统会显得笨、僵硬、像传统软件。

按需渲染的更准确表述应该是：

> **聪明 agent 识别用户需求，自动渲染页面。**

这里的“需”不是固定 intent，而是用户当下的目的、上下文、可见页面、历史页面和可执行行动共同推导出的即时需求。

主链路方向是 `agent-first`：

```text
用户输入
    ↓
Agent Kernel
    ├── 理解用户真实需求
    ├── 判断当前页面是否足够
    ├── 选择需要读取的数据
    ├── 决定是否回答 / 是否渲染 / 渲染什么
    ├── 选择可执行动作，但不直接写入
    ↓
Allowed Tool/Data Space
    ├── current_view
    ├── visible_deadlines
    ├── all_clients
    ├── all_deadlines
    ├── client_deadlines
    ├── blockers
    └── tasks
    ↓
Render Spec Generator
    ├── 已知 view.type
    └── LLM 生成受约束 render_spec
    ↓
Validator / Guardrails
    ├── schema 校验
    ├── 数据字段只能来自工具结果
    ├── action 只能来自 allowed_actions
    └── write 必须 ConfirmCard
    ↓
Response + View
```

也就是说，planner 不再是主角。Planner / Intent Cache / Flywheel 退到两个位置：

- 快路径：高频稳定需求可以直接命中模板，降低成本。
- 约束层：写操作、实体解析、工具调用仍然复用确定性后端。

但“用户到底想要什么”和“右侧应该长什么样”，必须交给 agent kernel。

技术选型：

- 当前阶段采用 Anthropic 官方 SDK Tool Use + 一个普通 Python ReAct loop，不引入 LangGraph / Semantic Kernel / LlamaIndex 这类重编排框架。
- Agent Kernel 调用 Claude Sonnet 4.6，但输出必须是受约束 JSON。
- Agent Kernel 只决定交互策略，不直接生成业务事实，不直接执行写操作。
- 业务事实仍来自 `engine` / `executor`，写操作仍走 `ConfirmCard`。
- 后续如果出现长链路、多工具、人审暂停恢复等复杂流程，再评估 LangGraph 或 OpenAI Agents SDK。

Agent Kernel 第一版输出结构：

```json
{
  "need_type": "Agent 自己命名的语义标签，例如 client_risk_review / workload_comparison / explain_current_view / prepare_action / ask_clarifying_question / pass_to_planner",
  "route": "answer_current_view | render_strategy_surface | prepare_action | ask_clarifying_question | pass_to_planner",
  "render_policy": "keep_current_view | no_view_needed | update_current_view | render_new_view | pass_to_planner",
  "data_requests": ["current_view | visible_deadlines | all_clients | all_deadlines | client_deadlines | blockers | tasks"],
  "answer_mode": "answer_only | answer_and_render | render_only | pass_to_planner",
  "view_goal": "右侧工作面应该帮助用户完成的判断",
  "answer": "如果当前上下文足够，直接给用户的回答",
  "selected_refs": ["item_1"],
  "suggested_actions": [
    {"label": "按钮文案", "intent": "点击后作为自然语言继续发送", "style": "primary"}
  ],
  "next_step": "一个明确下一步",
  "requires_confirmation": false,
  "confidence": 0.91,
  "reason": "内部原因"
}
```

执行规则：

- `keep_current_view`：左侧回答，右侧页面不动。
- `no_view_needed`：只回答，不强行渲染垃圾面板。
- `render_new_view` / `update_current_view`：只有当 `data_requests` 命中白名单时，后端才读取对应数据并生成受约束工作面。
- `prepare_action`：必须进入确认流，不能直接写入。
- `pass_to_planner`：策略层不确定时，交给现有 flywheel + planner。

这个设计借鉴 Codex-style harness 的核心思想：每轮不是简单分类，而是让模型结合当前上下文、工具能力、历史状态决定下一步；同时保留确定性 guardrails，避免 LLM 自由执行业务写操作。

现在已经清理掉 `portfolio_overview`、`deadline_priority_ranking` 这种后端硬编码策略面。Agent 可以继续输出这些或任何其他 `need_type` 作为语义标签，但后端不再根据标签走特殊分支，而是统一用工具结果和 Agent 的 `view_goal / suggested_actions` 构建受约束工作面。

这标志着意图识别从“固定 intent 分类”升级为“Agent 先理解需求，再由可选数据和可选行动空间约束执行”。最终目标是：

- agent 负责需求理解和页面构思
- tool layer 负责真实数据读取
- renderer 负责把 agent 的页面意图变成受约束 UI
- validator 负责防止假数据和越权动作
- flywheel 负责把高频需求沉淀成低成本路径

当前实际链路是本地 Python MVP：

```
用户输入
    ↓
api.process_message / InteractionBackend.process_message
    ↓
RuleBasedIntentPlanner（临时 NLU）
    ↓
PlanExecutor（直接调用 engine）
    ↓
ResponseGenerator（确定性生成 view）
    ↓
InMemoryInteractionSessionManager / session dict
```

当前也有 opt-in 的 LLM NLU 链路：

```
用户输入
    ↓
ClaudeNLUService（Sonnet 4.6）
    ↓
PlanValidator（命令 allowlist / 参数校验 / write op_class 校验）
    ↓
PlanExecutor
    ↓
ResponseGenerator
```

当前也有 opt-in 的飞轮运行时链路：

```
用户输入
    ↓
FlywheelIntentRouter
    ├── cache hit → 实例化 cached Plan
    └── cache miss → RuleBasedIntentPlanner 或 ClaudeNLUService
            ↓
       PlanValidator（Claude 路径）
            ↓
       Intent Library learn
    ↓
PlanExecutor
    ↓
ResponseGenerator
```

当前还没有：

- 生产级 React 前端接真实 `/chat`
- 后端 LLM-assisted render spec generator
- 生产级 embedding 检索 / pgvector / 线上 rerank
- Claude Sonnet response generation
- HTTP API 的鉴权、租户隔离中间件和生产部署配置

---

## 一、飞轮架构：Intent Cache

### 当前实现状态

当前已经有内存版 `InMemoryIntentLibrary`，它用于验证飞轮机制，而不是生产级语义检索。

已经实现：

- `IntentTemplate` / `IntentMatch`
- 按 `intent_label` 聚合 example inputs
- Plan 抽象化：`tenant_id`、当前 `deadline_id`、当前 `client_id` 会替换为 `$tenant_id` / `$selected.deadline_id` / `$selected.client_id`
- 命中后实例化：从当前 session 注入真实 tenant 和当前 selected item
- 模板向量使用 lexical/semantic feature dict
- 匹配时同时看 template 平均向量和 `example_inputs` 最大相似度，避免短表达被平均向量稀释
- `record_feedback()` 已存在，会根据 correction 调整 `success_rate`，低于 0.70 标记 `review_needed`

尚未实现：

- 真实 embedding
- pgvector 持久化
- 多租户共享/隔离策略
- top-k rerank
- 线上 feedback 自动接入

所以本文后面关于 embedding、pgvector、0.92 threshold 的内容是目标形态；当前 MVP 的作用是验证 flywheel 是否能收敛，以及错命中风险能否被控制住。

### 核心逻辑

```
用户输入
    ↓
意图向量化（embedding）
    ↓
在 Intent Library 做相似度匹配
    ↓
命中（similarity > 0.92）→ 直接返回缓存 Plan，跳过 NLU
未命中 → 调用 NLU（Claude Sonnet 4.6）→ 生成 Plan
    ↓
执行 Plan（Executor）
    ↓
Response Generator 生成 view
    ↓
将结果抽象化 → 写入 Intent Library
```

### Intent Library 的数据结构

```python
@dataclass
class IntentTemplate:
    intent_id: str
    intent_label: str           # 如 "prioritize_today"
    example_inputs: list[str]   # 触发过这个意图的真实输入
    embedding: list[float]      # 所有 example_inputs 的平均 embedding
    canonical_plan: Plan        # 抽象化的 Plan 模板（含变量占位符）
    view_type: str              # 期望渲染的视图类型
    hit_count: int              # 被命中次数
    success_rate: float         # 用户操作成功率（未立即追问的比例）
    created_at: datetime
    updated_at: datetime
```

### 抽象化规则

Plan 写入 Intent Library 之前需要去除具体值，保留结构：

```python
# 具体 Plan（执行时生成）
{
  "steps": [{
    "cli_command": "list",
    "args": { "tenant_id": "t-001", "client_id": "cl-007" }
  }]
}

# 抽象化后（存入 Intent Library）
{
  "steps": [{
    "cli_command": "list",
    "args": { "tenant_id": "$tenant_id", "client_id": "$resolved_client_id" }
  }]
}
```

`$tenant_id` 这类占位符在 Executor 执行时从 session 上下文注入。

### 命中后的 Plan 实例化

```python
class IntentCache:
    def match(self, user_input: str, session: Session) -> Plan | None:
        embedding = self.embed(user_input)
        candidates = self.vector_search(embedding, top_k=5)
        best = max(candidates, key=lambda c: c.similarity)

        if best.similarity < 0.92:
            return None  # 未命中，走 NLU

        # 命中：实例化模板
        plan = self.instantiate(best.template, session)
        best.hit_count += 1
        self.save(best)
        return plan

    def instantiate(self, template: Plan, session: Session) -> Plan:
        # 把 $placeholder 替换成 session 里的真实值
        return replace_vars(template, {
            "$tenant_id": session.tenant_id,
            "$today": session.today,
            "$selectable_items": session.selectable_items
        })

    def learn(self, user_input: str, plan: Plan, view_type: str):
        # NLU 生成了新 Plan，写入 Intent Library
        embedding = self.embed(user_input)
        existing = self.find_close(embedding, threshold=0.85)

        if existing:
            # 更新已有模板：追加 example，重新计算平均 embedding
            existing.example_inputs.append(user_input)
            existing.embedding = self.average_embed(existing.example_inputs)
            self.save(existing)
        else:
            # 新意图：创建新模板
            self.create(IntentTemplate(
                intent_label=plan.intent_label,
                example_inputs=[user_input],
                embedding=embedding,
                canonical_plan=self.abstract(plan),
                view_type=view_type,
                hit_count=0,
                success_rate=1.0
            ))
```

### 飞轮效果

```
用户数量    NLU 调用比例    平均响应时间
0-100       ~100%           1.5-2s
100-1000    ~40%            0.8-1.2s
1000-10000  ~10%            0.3-0.5s
10000+      ~2%             <0.2s（大部分直接命中缓存）
```

命中缓存的请求不调 Claude API，成本趋近于零，响应时间取决于 embedding 检索速度（通常 <50ms）。

### 质量反馈回路

用户操作是隐性反馈信号：

```python
# 用户收到渲染结果后
# 如果立即追问 → 说明渲染结果不对，success_rate 下降
# 如果直接操作（点按钮、继续对话）→ 说明渲染结果正确，success_rate 维持

def on_user_followup(intent_id: str, is_correction: bool):
    template = intent_library.get(intent_id)
    if is_correction:
        template.success_rate = template.success_rate * 0.95  # 衰减
    else:
        template.success_rate = min(1.0, template.success_rate * 1.02)  # 增长

    # success_rate 低于 0.7 的模板标记为待审核，不再参与匹配
    if template.success_rate < 0.70:
        template.status = "review_needed"
    intent_library.save(template)
```

---

## 二、NLU 服务（仅在缓存未命中时调用）

### 当前实现状态

真实 `NLUService` 还没有接入产品链路。当前用 `RuleBasedIntentPlanner` 临时代替 NLU，保持同一个边界：输入是用户文本和 session，输出是 Plan JSON。

当前 planner 已覆盖 11 类基础 intent：

- `today`
- `client_deadline_list`
- `deadline_history`
- `deadline_action_complete`
- `defer`
- `help`
- `upcoming_deadlines`
- `completed_deadlines`
- `notification_preview`
- `rule_review`
- `client_list`

当前已经支持：

- 客户名匹配，例如 `Acme`、`TechCorp`
- 相对引用，例如 `第一条`、`这个`、`当前这个`、`刚才那个`
- 写操作识别，例如 `完成第一条`、`record as sent`
- 否定写操作识别，例如 `先别标记完成`、`don't complete this yet`
- history / source 类追问不清空当前 `selectable_items`
- 写操作统一进入 `ConfirmCard`，不会直接执行

当前没有实现：

- Claude Sonnet 4.6 在线解析 Plan
- confidence score
- NLU prompt 注入 CLI spec
- 低置信 options 兜底
- 实体解析的 LLM 推理能力

### 两种引用解析通路

**通路 A：相对引用** — "第一条"、"这个客户"，只从 `selectable_items` 解析。

**通路 B：实体解析** — "Acme LLC 的情况"，Plan 里加 `resolve_entity` 步骤。

### 实现

```python
class NLUService:
    def parse(self, user_input: str, session: Session) -> Plan:
        response = anthropic.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
            system=self.build_system_prompt(session),
            messages=[{"role": "user", "content": user_input}]
        )
        plan = Plan.from_json(response.content[0].text)

        # 解析完成后写入 Intent Library（飞轮学习）
        intent_cache.learn(user_input, plan, plan.expected_view_type)

        return plan

    def build_system_prompt(self, session: Session) -> str:
        return f"""
你是 DueDateHQ 的意图解析器。
输出合法 JSON，不输出任何解释文字。

今天：{session.today}
租户：{session.tenant_id}
当前可引用对象（selectable_items）：{json.dumps(session.selectable_items)}
对话历史（最近 10 轮）：{json.dumps(session.history_window[-10:])}

可用命令集（严格按此，不使用不存在的参数）：
{CLI_SPEC}

op_class 规则：
- 任何包含写操作的 Plan 标注 op_class: "write"
- 写操作：deadline action / client add / client update-states
- 读操作：其余所有命令

相对引用规则：
- 只从 selectable_items 解析，不猜测其他字段
- 解析不到输出 reference_unresolvable

历史查询路由：
- "这个为什么变了" → deadline transitions（单对象）
- "看历史" → log --tenant-id（全局审计）
        """
```

### 降级逻辑（read / write 分开）

```
read 操作：
  confidence ≥ 0.75   → 执行 Plan
  0.60-0.75           → 执行，message 注明"如果不对告诉我"
  < 0.60              → 输出 options，不执行

write 操作：
  任何 confidence     → 先渲染 ConfirmCard，用户确认后才执行
  < 0.90              → 不执行，输出 options
```

---

## 三、Executor

### 当前实现状态

`PlanExecutor` 已经实现，并且已经按目标原则直接调用 `InfrastructureEngine`，不走 CLI 子进程。

当前支持的 step：

- `cli_call`
- `resolve_entity`
- `post_filter`
- `foreach`

当前支持的命令组：

- `today.today`
- `client.list`
- `deadline.list`
- `deadline.available-actions`
- `deadline.transitions`
- `deadline.action`
- `notify.preview`
- `notify.history`
- `log.list`
- `export.export`
- `rule.list`
- `rule.review-queue`

当前错误处理：

- entity 找不到抛 `EntityNotFoundError`，由 `InteractionBackend` 转成 `GuidanceCard`
- step 执行失败抛 `PlanExecutionError`
- unsupported step/command 抛 `UnsupportedPlanStepError`
- `foreach` 单项失败会写入 `errors` 并继续执行后续 item

### 关键决策：直接调用 engine，不走子进程

```python
# ✗ 错误做法（慢，难测试）
subprocess.run(["duedatehq", "deadline", "list", "--client", client_id])

# ✓ 正确做法（快，可 mock）
from duedatehq.engine import DeadlineEngine
engine = DeadlineEngine(db_url)
result = engine.list_deadlines(tenant_id=tenant_id, client_id=client_id)
```

函数调用 vs 子进程：延迟差 10-100ms，错误处理更干净，测试更容易。

### 步骤类型

```python
class Executor:
    def run(self, plan: Plan) -> ExecutorResult:
        results = {}
        for step in plan.steps:
            match step.type:
                case "cli_call":
                    results[step.step_id] = self.cli_call(step, results)
                case "resolve_entity":
                    results[step.step_id] = self.resolve_entity(step, results)
                case "foreach":
                    results[step.step_id] = self.foreach(step, results)
                case "post_filter":
                    results[step.step_id] = self.post_filter(step, results)

        return ExecutorResult(
            final_data=results[plan.steps[-1].step_id],
            intent_label=plan.intent_label,
            op_class=plan.op_class
        )

    def foreach(self, step, results):
        # 超过 20 项时分批，每批最多 5 个并发
        source = results[step.depends_on]
        if len(source) > 20:
            source = source[:50]  # 截断，标注 truncated
        batches = [source[i:i+5] for i in range(0, len(source), 5)]
        all_results = []
        for batch in batches:
            batch_results = [
                self.cli_call(step, {step.depends_on: item})
                for item in batch
            ]
            all_results.extend(batch_results)
        return flatten(all_results)
```

### 失败处理

| 失败类型 | 处理方式 |
|---|---|
| 单个 cli_call 失败 | Plan 中止，返回 execution_failed |
| resolve_entity 匹配不到 | 返回 entity_not_found |
| foreach 部分失败 | 继续执行，结果里标注失败项 |
| write 操作用户取消 | Plan 不执行，session 不变 |

写操作无回滚，执行完成即最终态。

---

## 四、Response Generator

### 当前实现状态

当前 `ResponseGenerator` 是确定性的，还没有接 Claude Sonnet。

当前已支持：

- `today` → `ListCard`
- `client_deadline_list` → `ClientCard`
- write plan → `ConfirmCard`
- 其他读类结果 → `GuidanceCard`
- 从 engine 补齐 client name、days remaining、available actions
- actions 从 `available_deadline_actions()` 生成，且最多返回 3 个
- history / guidance 类响应保留 session 中原有 `selectable_items`，支持跨轮引用继续成立

当前没有实现：

- Claude Sonnet message generation
- 根据用户 intent 动态选择更丰富的 view
- 更完整的 on-demand rendering view schema
- 前端消费真实 view 的适配层

### 写操作拦截

```python
class ResponseGenerator:
    def build(self, result: ExecutorResult, session: Session) -> Response:
        if result.op_class == "write":
            return self.build_confirm_card(result, session)
        enriched = self.enrich(result.final_data, session.tenant_id)
        message  = self.generate_message(enriched, result.intent_label)
        view     = self.select_view(result.intent_label, enriched)
        actions  = self.build_actions(enriched, session.tenant_id)
        return Response(message=message, view=view, actions=actions)
```

### Enrich 层（CLI 返回数据 → 前端可用数据）

| 前端需要 | CLI 返回 | Enrich 方式 |
|---|---|---|
| `client_name` | 无（today 返回 Deadline 模型） | join client list，按 client_id 匹配 |
| `days_remaining` | 无 | `(due_date - today).days` |
| `jurisdiction_label` | 原始州代码 `CA` | 映射表 `CA → California` |
| `rule_source_url` | `rule_id` | join rule list，按 rule_id 匹配 |

Enrich 所需的 join 数据在单次请求内缓存，不持久化。

### actions 从状态机生成

```python
def build_actions(self, data, tenant_id):
    actions = []
    for item in data:
        if "deadline_id" in item:
            available = engine.available_actions(
                tenant_id, item["deadline_id"]
            )
            for action in available["available_actions"]:
                actions.append({
                    "label": ACTION_LABELS[action],
                    "plan": {
                        "steps": [{ "type": "cli_call",
                                    "cli_group": "deadline",
                                    "cli_command": "action",
                                    "args": { "action": action,
                                              "deadline_id": item["deadline_id"],
                                              "tenant_id": tenant_id } }],
                        "op_class": "write"
                    }
                })
    return actions[:3]  # 最多三个
```

---

## 五、Session 管理

### 当前实现状态

当前是内存版 `InMemoryInteractionSessionManager`，并且 `InteractionBackend.process_message()` 也可以直接接收可变 session dict。

当前 session 已记录：

- `session_id`
- `tenant_id`
- `today`
- `history_window`
- `selectable_items`
- `current_view`
- `state_summary`
- `pending_action_plan`（仅在等待确认时存在）

当前关键行为：

- 每轮用户输入和系统回复都会写入 `history_window`
- `history_window` 保留最近 20 条 message
- `current_view` 和 `selectable_items` 跟随 response 更新
- 写操作确认前写入 `pending_action_plan`
- `确认` 执行 pending action
- `取消` 清除 pending action，但保留当前任务上下文

当前没有实现：

- Redis TTL
- session 过期恢复
- 多进程共享 session
- HTTP session resume

```python
@dataclass
class Session:
    session_id: str
    tenant_id: str
    today: str
    history_window: list    # 最近 10 轮（20 条 message）
    selectable_items: list  # 当前视图可引用对象，NLU 相对引用的唯一来源
    current_view: dict
    ttl: int = 3600         # 1 小时无操作过期

class SessionManager:
    def get(self, session_id: str) -> Session:
        data = redis.get(f"session:{session_id}")
        if not data:
            raise SessionExpired()
        return Session(**json.loads(data))

    def save(self, session: Session):
        redis.setex(
            f"session:{session.session_id}",
            session.ttl,
            json.dumps(asdict(session))
        )
```

### 过期行为

session 过期后，`current_view` 和 `selectable_items` 同时失效。前端检测到 `SessionExpired` 错误后，创建新 session，自动执行 `today --enrich`，从干净状态开始。不做半途恢复。

---

## 六、加载体验：渐进式渲染

### 当前实现状态

当前还没有 FastAPI/SSE，也没有前端接入真实后端。下面的 SSE 分帧推送仍然是目标方案。

当前已有的是同步 Python helper：

- `api.process_message(...)`
- `api.process_plan(...)`
- `api.process_action(...)`
- `api.start_interaction_session(...)`

这些 helper 已足够做后端 MVP 验证，但还不能验证真实浏览器加载体验。

### 问题

NLU + Executor + Response Generator 完整链路需要 1-2 秒。用户说完话之后盯着空白等，体验差。

### 方案：SSE 分帧推送

服务端用 Server-Sent Events，按处理阶段逐帧推送，前端即时响应每一帧。

**服务端：**

```python
@app.post("/chat")
async def chat(req: ChatRequest):
    async def event_stream():
        session = session_mgr.get(req.session_id)

        # 第一帧：立即返回，告知正在理解
        yield sse("thinking", {
            "stage": "understanding",
            "message": "…"           # 前端显示打字动画
        })

        # Intent Cache 查询（<50ms）
        plan = intent_cache.match(req.user_input, session)

        if plan:
            # 命中缓存
            yield sse("thinking", {
                "stage": "executing",
                "message": "找到了，正在拿数据…"
            })
        else:
            # 未命中，调 NLU
            yield sse("thinking", {
                "stage": "understanding",
                "message": "理解中…"
            })
            plan = await nlu.parse(req.user_input, session)
            yield sse("thinking", {
                "stage": "executing",
                "message": "正在处理…"
            })

        # Executor 执行
        result = await executor.run(plan)

        # 写操作 → 直接推 confirm
        if result.op_class == "write":
            confirm = response_gen.build_confirm_card(result, session)
            yield sse("response", confirm.dict())
            return

        # Response Generator
        yield sse("thinking", {
            "stage": "rendering",
            "message": "正在生成视图…"
        })
        response = await response_gen.build(result, session)

        # 最终帧
        session_mgr.update(session, req.user_input, response)
        yield sse("response", response.dict())

    return EventSourceResponse(event_stream())
```

**前端：**

```javascript
async function send(input) {
  appendMsg("user", input)
  const typingEl = showTypingIndicator()  // 左侧出现打字动画

  const es = new EventSource(`/chat?input=${encodeURIComponent(input)}&sid=${session_id}`)

  es.addEventListener("thinking", e => {
    const { stage, message } = JSON.parse(e.data)
    updateTypingIndicator(typingEl, stage, message)
    // 根据 stage 更新动画状态：理解中 / 执行中 / 渲染中
  })

  es.addEventListener("response", e => {
    es.close()
    removeTypingIndicator(typingEl)
    const { message, view, actions, state_summary } = JSON.parse(e.data)
    appendMsg("system", message)
    renderView(view)           // 现有视图组件不变
    setQuickActions(actions)
    updateStateBar(state_summary)
  })
}
```

### 打字动画的三个阶段

```
用户发送后立即出现：
  [●●●]  "理解中…"          （NLU 或缓存查询阶段）
      ↓
  [●●●]  "正在处理…"         （Executor 执行阶段）
      ↓
  [●●●]  "正在生成视图…"     （Response Generator 阶段）
      ↓
  动画消失，message + view 出现
```

三个阶段的切换是真实的，对应后端实际的处理进度，不是假动画。

### 缓存命中时的特殊处理

Intent Cache 命中的请求，整个链路 <200ms，不需要显示多阶段动画——直接显示一个短暂的加载闪烁（100ms）然后出结果，比慢慢走三个阶段更流畅。

```javascript
es.addEventListener("thinking", e => {
  const { stage } = JSON.parse(e.data)
  if (stage === "cache_hit") {
    // 命中缓存：只显示短暂闪烁，不走完整动画
    typingEl.classList.add("fast")
  } else {
    typingEl.classList.remove("fast")
    updateTypingIndicator(typingEl, stage)
  }
})
```

---

## 七、完整请求链路

### 当前实现状态

当前实际请求链路是同步本地调用：

```
process_message(user_input, session)
    ↓
如果有 pending_action_plan 且用户确认：process_action()
如果用户取消：清 pending_action_plan，返回 GuidanceCard
否则：RuleBasedIntentPlanner.plan()
    ↓
InteractionBackend.process_plan()
    ↓
write → ResponseGenerator.generate_confirm_card()
read  → PlanExecutor.execute() → ResponseGenerator.generate()
    ↓
更新 current_view / selectable_items / state_summary / history_window
```

下面的缓存命中/未命中 SSE 链路是目标形态，还没有接入产品。

**正常路径（缓存未命中）：**

```
用户输入 "今天最紧急的是哪个"
    ↓ 第一帧 SSE（<10ms）
前端显示打字动画
    ↓
Intent Cache 查询（<50ms）→ 未命中
    ↓ SSE 推送 stage: understanding
NLU 调用 Claude Sonnet 4.6（~500ms）→ Plan
    ↓ SSE 推送 stage: executing
intent_cache.learn(input, plan)  ← 飞轮写入
    ↓
Executor 执行 CLI（~100-300ms）
    ↓ SSE 推送 stage: rendering
Response Generator + enrich（~300ms）
    ↓ 最终帧 SSE
前端渲染 view，更新 session
    ↓
总时长 ~1.0-1.5s
```

**缓存命中路径：**

```
用户输入 "今天最紧急的是哪个"
    ↓
Intent Cache 查询（<50ms）→ 命中
    ↓ SSE cache_hit 帧
Plan 实例化（<10ms）
    ↓
Executor 执行 CLI（~100-300ms）
    ↓
Response Generator + enrich（~300ms）
    ↓
总时长 ~0.2-0.4s，无 NLU 调用
```

---

## 八、技术选型

### 当前实现状态

当前代码库实际使用：

| 层 | 当前实现 |
|---|---|
| NLU | `RuleBasedIntentPlanner` |
| LLM 模拟测试 | Claude Messages API，默认模型 `claude-sonnet-4-6` |
| Response Generator | 确定性 Python 生成 |
| Intent Cache | `InMemoryIntentLibrary` |
| Session | `InMemoryInteractionSessionManager` + session dict |
| API | Python helper functions |
| Storage | SQLite / Postgres storage abstraction，测试多用临时 SQLite |
| Frontend | React/Vite 验证壳，已可接 FastAPI `/chat/stream` |

目标技术选型：

| 层 | 选择 | 原因 |
|---|---|---|
| NLU | Claude Sonnet 4.6 | 当前验证优先保证复杂意图理解质量；Haiku 可作为未来降本回退 |
| Response Generator | Claude Sonnet | 质量要求高 |
| Intent Cache 向量检索 | pgvector（PostgreSQL 扩展） | 不引入新依赖，现有 PG 直接用 |
| Session | Redis | TTL 天然支持 |
| 推送 | SSE（Server-Sent Events） | 比 WebSocket 简单，单向推送够用 |
| API | FastAPI | 异步支持好，和现有 Python 生态一致 |
| 前端 | React | demo 已验证，视图组件不需要改 |
| 语音输入 | OpenAI Whisper | 转文字后进入同一条处理路径 |

### 为什么用 pgvector 而不是独立向量库

Intent Library 的数据量不大（几千到几万条模板），pgvector 完全够用，而且省掉了维护 Pinecone / Weaviate 等独立服务的运维成本。在用户规模达到 10 万以上之前，pgvector 不会成为瓶颈。

---

## 九、建设顺序

### 已完成

```
第零步   MVP 后端闭环
         状态：完成
         实现：
           用户输入 → RuleBasedIntentPlanner → Plan → Executor
           → Response/View → Session
         验收：
           今天列表、聚焦客户、写操作确认、确认执行已跑通

第一步   engine 函数化
         状态：完成
         实现：
           PlanExecutor 直接调用 InfrastructureEngine
           不走 CLI 子进程
         验收：
           executor tests 通过

第二步   Executor
         状态：完成 MVP
         实现：
           cli_call / resolve_entity / post_filter / foreach
           支持 today、client、deadline、notify、log、export、rule 等命令组
         验收：
           tests/test_executor.py 通过

第三步   InteractionBackend
         状态：完成 MVP
         实现：
           process_message / process_plan / process_action
           pending_action_plan
           confirm / cancel
           history_window
           cross-turn reference preservation
         验收：
           tests/test_interaction_backend.py 通过

第四步   Response Generator
         状态：完成确定性 MVP
         实现：
           ListCard / ClientCard / ConfirmCard / GuidanceCard
           selectable_items 输出
           available-actions 生成 actions
         未完成：
           Claude Sonnet 生成自然语言 message
           更完整的 on-demand view schema

第五步   Intent Cache 机制验证
         状态：完成内存版 MVP
         实现：
           InMemoryIntentLibrary
           IntentTemplate 抽象化/实例化
           example max similarity + average vector
           feedback success_rate
         未完成：
           embedding / pgvector / 持久化 / rerank

第六步   飞轮离线验证
         状态：完成第一轮
         实现：
           230 条基础样本
           11 类基础 intent
           full replay + holdout
           Claude 生成样本模拟
         验收：
           基础 holdout 100% / 100%，0 wrong matches
           LLM 模拟 holdout 94.34% / 94.34%，0 wrong matches
```

### 从当前状态往前的最短五步

当前后端 MVP 已经证明：自然语言输入可以变成 Plan，Plan 可以调用 engine，写操作会被确认拦截，view 可以回写 session，飞轮样本可以收敛。接下来最短路径不是继续扩静态 mock，而是把真实 Agent 闭环补齐。

#### 第一步：把追问信号接进飞轮（内存版已完成）

这是飞轮真正闭环的最后一块。当前已经完成内存版 MVP：每轮 response 后记录 `last_turn`，下一轮用户输入会先经过 `classify_followup()`，再继续正常规划。

当前实现：

```python
def process_message(self, user_input, session):
    if session.get("last_turn"):
        classification = classify_followup(session["last_turn"], user_input)
        if classification.signal == "correction":
            intent_library.record_feedback(
                session["last_turn"]["template_id"],
                is_correction=True,
            )
            session["flywheel_review_queue"].append(...)
        elif classification.signal == "missing_info":
            intent_library.record_missing_field(
                session["last_turn"]["intent_label"],
                user_input,
            )

    # 然后正常处理当前输入
```

`classify_followup` MVP 阶段不需要 LLM，先用规则判断：

- 否定词、纠错词：`不对`、`不是`、`你理解错了`、`wrong`、`not that` → `correction`
- 疑问词 + 字段词：`为什么`、`来源`、`什么时候`、`谁改的`、`缺什么` → `missing_info`
- 其他追问：继续当作新的 intent 处理，可标记为 `drill_down`

已验证：

- 每轮 response 后 session 记录 `last_turn`
- 用户纠错后，对应 template 的 `success_rate` 下降
- `success_rate < 0.70` 的 template 进入 `review_needed`
- missing info 进入可审计记录，后续用于补 view 字段
- 不影响当前 `pending_action_plan` 的确认/取消语义
- correction 输入不会被学习成新模板

尚未完成：

- review queue 持久化
- missing info 聚合成产品待办
- 用真实线上行为校准 correction / missing_info / drill_down 的规则边界

#### 第二步：意图描述推送

当前目标 SSE 只有阶段描述，例如“理解中…”。下一步需要在 NLU 解析完、Executor 执行前增加 `intent_confirmed` 帧，让用户在结果出来前知道系统理解成了什么。

目标链路：

```python
plan = await nlu.parse(user_input, session)
description = generate_intent_description(plan, session)

yield sse("intent_confirmed", {
    "message": description,
})

result = await executor.run(plan)
```

`generate_intent_description` 用 Claude Sonnet 4.6，`max_tokens=60`，只输出一句话，例如：

```text
正在为你查看：接下来 14 天内，加州客户的待处理 deadline。
```

验收：

- SSE 中出现 `intent_confirmed` event
- 用户可以在执行前看出系统是否理解错
- 这类执行前纠错可以直接进入第一步的 follow-up feedback

#### 第三步：接入真实 Claude Sonnet 4.6 NLU

当前 `RuleBasedIntentPlanner` 只适合验证边界，不适合生产。下一步接入 `NLUService`，保持同一接口：输入 `user_input + session`，输出 Plan JSON。

要做：

```python
class NLUService:
    def plan(self, user_input: str, session: dict) -> dict:
        response = self.client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
            system=build_system_prompt(session),
            messages=[{"role": "user", "content": user_input}],
        )
        plan = parse_plan_json(response)
        intent_cache.learn(user_input, plan, session)
        return plan
```

验收：

- `.env` 中 Claude key 可用
- 现有 285 条人工/LLM 混合测试集能跑 NLU eval
- 记录 hit rate、accuracy、wrong intent match
- write intent 不直接执行，仍然进入 `ConfirmCard`
- NLU 不能输出不存在的 engine command 或参数

#### 第四步：Claude Sonnet 接管 Response Generator 的语言和视图选择

当前 `ResponseGenerator` 是确定性模板。Sonnet 接入后，只负责两件事：生成短 message，选择 view type。

硬约束：**Sonnet 不生成 view 数据结构。** view data 必须由 Executor 结果和 enrich 层确定性构建，避免 LLM 编造字段。

目标形态：

```python
decision = sonnet.decide({
    "intent_label": result["intent_label"],
    "data_summary": summarize(result["final_data"]),
    "data_count": len(result["final_data"]),
})

view_data = build_view_data(decision["view_type"], result["final_data"])

return {
    "message": decision["message"],
    "view": {"type": decision["view_type"], "data": view_data},
    "actions": build_actions(result["final_data"]),
}
```

验收：

- message 简短、明确、解释下一步
- view type 与 intent 和数据规模匹配
- view data 字段完全由代码构造
- actions 仍然来自 `available_deadline_actions()`，不由 LLM 编造

#### 第五步：FastAPI + Redis + 前端接入

这一步把本地 Python MVP 变成真实产品链路。

顺序：

1. FastAPI 包装现有 `api.process_message()`，暴露 `/chat` 和 `/action`
2. `/chat` 接入 SSE：`thinking` → `intent_confirmed` → `response`
3. Redis 替换 `InMemoryInteractionSessionManager`
4. 前端把 mock `routeInput` 换成真实 `/chat` SSE
5. quick actions 走 `/action`

验收：

- 浏览器输入一句话，后端真实更新 session
- 右侧 view 来自后端 `view.type` / `view.data`
- 前端 view renderer 不需要知道数据来自 mock 还是后端
- 刷新后能按 session 恢复
- 写操作必须确认，不能通过 action 绕过确认策略

### 优先级和并行顺序

产品验证优先级：

```text
1. 追问信号接进飞轮
2. 意图描述推送
3. 真实 Claude Sonnet 4.6 NLU
4. Claude Sonnet Response Generator
5. FastAPI + Redis + 前端接入
```

工程最快路径：

```text
并行 A：接真实 Claude Sonnet 4.6 NLU
并行 B：FastAPI /chat + SSE 骨架
随后：把 intent_confirmed 和 follow-up feedback 接进 SSE 链路
然后：Redis session + 前端真实接入
最后：Sonnet 接管 message + view choice
```

这样做完后，系统才形成完整的按需渲染 Agent 闭环：

```text
任意输入 → 意图确认 → 执行 → 渲染 → 追问反馈进飞轮
```

---

## 十、飞轮的收敛性验证

这是整个产品最重要的前提假设：**CPA 群体的意图空间是有限且收敛的。**

当前 MVP 先用内存版 `InMemoryIntentLibrary` 和 `RuleBasedIntentPlanner` 做离线验证。这个阶段不验证真实 embedding 的语义质量，只验证飞轮机制本身：

- 用户输入能否学习成 `IntentTemplate`
- 相似输入第二轮能否命中缓存
- 命中后能否实例化成可执行 Plan
- 多种表达能否收敛成少量 intent template
- 写操作 template 是否仍然依赖 `selectable_items`，不凭空猜对象

验证方法：

```python
# 生成 500 条测试输入（覆盖各种意图和表达方式）
# 第一轮：全部走 NLU，Intent Library 从零开始积累
# 第二轮：相同 500 条，观察命中率

def run_convergence_test(test_inputs: list[str]):
    round1_hits = 0
    round2_hits = 0

    # 第一轮
    for inp in test_inputs:
        plan = intent_cache.match(inp, mock_session)
        if plan:
            round1_hits += 1
        else:
            plan = nlu.parse(inp, mock_session)
            intent_cache.learn(inp, plan)

    # 第二轮（相同输入）
    for inp in test_inputs:
        plan = intent_cache.match(inp, mock_session)
        if plan:
            round2_hits += 1

    print(f"第一轮命中率：{round1_hits/500:.1%}")   # 预期接近 0%
    print(f"第二轮命中率：{round2_hits/500:.1%}")   # 预期 > 80%
    print(f"意图簇数量：{len(intent_library.all())}")  # 预期 < 50
```

如果第二轮命中率 ≥ 80%，意图簇数量 ≤ 50，收敛性假设成立，可以放心扩规模。

如果命中率低或簇数量持续增长，说明这个群体的需求比预想更分散，需要重新评估产品边界——这个结论比在生产环境里发现要便宜得多。

### 当前 MVP 验证结果

当前基础模板库在 `src/duedatehq/core/intent_samples.py`，覆盖 11 类后端当前可执行的基础意图：

- `today`
- `client_deadline_list`
- `deadline_history`
- `deadline_action_complete`
- `defer`
- `help`
- `upcoming_deadlines`
- `completed_deadlines`
- `notification_preview`
- `rule_review`
- `client_list`

样本输入覆盖 230 条中英混合表达，包括：

```text
今天先做什么
今天最紧急的是什么
show today's list
what should I do first
list urgent items
先看 Acme
打开 Acme LLC
先看今天最急的 Acme
帮我处理 Acme 但先别标记完成
为什么这个还没完成
这个来源是什么
who changed this
完成第一条
mark first done
已发送，记录一下
暂时不做
don't mark complete
你能干嘛
未来30天有什么
show next 30 days
已完成的有哪些
notification preview
规则审核队列
all clients
show my work queue
where is Acme stuck
audit trail
finish this item
leave this alone for now
show available operations
next week deadlines
client reminders
source parsing issues
client roster
```

验证结果：

```text
total_inputs = 230
first_round_hits = 0
second_round_hit_rate = 100%
second_round_accuracy = 100%
template_count = 11
planner_mismatches = []
cache_mismatches = []
missed_inputs = []
matched_intents = [
  client_deadline_list,
  client_list,
  completed_deadlines,
  deadline_action_complete,
  deadline_history,
  defer,
  help,
  notification_preview,
  rule_review,
  today
  upcoming_deadlines
]
```

这个结果说明飞轮机制可以工作：不同表达能学习成模板，第二轮可以直接命中，并实例化回当前 session 的真实 `tenant_id` / `selected.deadline_id`。

但上面是 full replay，也就是同一批样本学习后再回测，会高估泛化能力。当前还增加了按 intent 分层的 holdout 验证：每类 intent 约 65% 样本用于学习，剩余样本只用于测试 cache 泛化。

Holdout 结果：

```text
train_inputs = 145
test_inputs = 85
template_count = 11
holdout_hit_rate = 100%
holdout_accuracy = 100%
wrong_intent_matches = 0
missed_inputs = 0
```

这个结果比 full replay 更接近真实质量。当前最重要的结论不是“基础模板已经覆盖一切”，而是：**基础模板库在已知边界内没有错命中**。在未来架构里，miss 会走 LLM fallback；错命中才是危险路径，尤其是 write intent。

### LLM 模拟验证

现在已经可以进入 LLM 模拟测试阶段。`scripts/run_llm_flywheel_simulation.py` 会读取 `.env` 中的 Claude key，用 Claude 生成新的自然语言表达，再把这些表达和基础样本合并后做 holdout 验证。

当前命令：

```bash
python3 scripts/run_llm_flywheel_simulation.py --per-intent 5
```

模型配置说明：当前默认使用 `claude-sonnet-4-6`。Anthropic 公开模型列表里没有 Haiku 4.6；如果显式传入 `4.6 haiku` / `haiku-4.6`，代码会解析到当前官方 Haiku，避免调用不存在的模型 ID。需要降本验证时可设置 `CLAUDE_NLU_MODEL=claude-haiku-4-5-20251001`。

当前一轮结果：

```text
model = claude-sonnet-4-6
base_samples = 230
generated_samples = 55
combined_samples = 285
generated_intents = 11
train_inputs = 179
test_inputs = 106
template_count = 11
holdout_hit_rate = 94.34%
holdout_accuracy = 94.34%
wrong_intent_matches = 0
missed_inputs = 6
```

剩余 6 条都是 cache miss，不是错命中：

```text
这个怎么变成逾期了
what are my options
show what's already done
已处理项目有哪些
哪些已经完成了
源头解析问题
```

这个结果的意义是：当前 deterministic matcher 已经可以作为高置信复用层使用；没有命中的表达应该进入 LLM NLU，而不是继续强行用规则猜。LLM 模拟测试的价值在于持续发现新的自然表达，并把稳定、高频、低风险的表达沉淀回基础模板库。

这轮扩样本暴露过这些关键问题，并已修正：

- `今天先做什么` 这类表达不能因为包含“先”就被误判成 focus 当前项。
- 模板只用平均向量会稀释短表达，例如 `Acme Dental`。当前 MVP 同时使用 template 平均向量和 `example_inputs` 最大相似度。
- 完成列表和完成写操作容易混淆，例如 `show completed` vs `mark current complete`，当前通过 intent 优先级和更精确的短语规则区分。
- `record this as handled` 不能因为包含 `handled` 被误判成 completed list，当前不再使用单独的 `handled` 作为 completed 信号。
- `show available operations` 不能因为包含 `show` 被误判成 focus，help intent 需要覆盖“支持哪些操作 / available operations”。
- `show customer list` 不能因为包含 `show` 被误判成 focus，client list intent 需要先于 focus 处理。
- `do not complete this` 不能命中到 write template。当前否定写操作会被打上 defer 信号，避免危险误命中。

### 跨轮引用验证

除了单轮 intent 样本，还新增了跨轮引用测试，验证连续对话里的 `selectable_items`、`pending_action_plan` 和确认/取消语义：

```text
今天先做什么
看第一条
刚才那个为什么变了
完成这个

先看 Acme
这个来源是什么
完成当前这个
取消
完成刚才那个
确认
```

验收点：

- `刚才那个 / 当前这个 / 这个` 能解析到当前 `selectable_items[0]`
- history / guidance 类追问不会清空当前可引用对象
- 写操作先进入 `ConfirmCard`，不会直接执行
- `取消` 清除 `pending_action_plan`，但保留当前任务上下文
- 再次发起写操作并 `确认` 后，deadline 状态从 `pending` 变为 `completed`

当前可用命令：

```bash
python3 scripts/run_flywheel_convergence.py
python3 scripts/run_llm_flywheel_simulation.py --per-intent 5
```

但它还不能证明生产环境中的真实语义收敛质量。下一步需要持续扩到 300-500 条人工/LLM 混合样本，并把 matcher 从 lexical feature 替换成真实 embedding 检索。

---

## 十一、MVP 验证切片

MVP 第一阶段已经证明后端交互链路成立。当前切片的重点已经前移到 Agent-native 验证：**模型能否在受控工具空间内理解用户需求，并选择有用的工作面，而不是退回随机面板或硬编码 intent 映射。**

### 当前范围

```
用户自然语言输入
    ↓
InteractionBackend
    ↓
Intent Cache / Flywheel Router
    ├── 高频简单意图命中 → planner/executor 快速路径
    └── miss / 复杂语义 → Agent Kernel
                            ↓
                      Claude Tool Use + ReAct
                            ↓
                      受控 read tools
                            ↓
                      constrained decision
                            ↓
    ├── read → ResponseGenerator / RenderSpecSurface
    └── write → ConfirmCard，再等用户确认
    ↓
Session 记录 current_view / selectable_items / pending_action_plan / feedback
```

### MVP 必须跑通的四个动作

1. 用户问“今天先做什么”
   - 后端输出 `ListCard`
   - session 写入 `selectable_items`

2. 用户说“先看 Acme”或“看第一条”
   - 后端输出 `ClientCard`
   - 右侧视图进入单客户上下文

3. 用户说“完成第一条”
   - 后端不执行写操作
   - 只输出 `ConfirmCard`
   - session 写入 `pending_action_plan`

4. 用户说“确认”
   - 后端执行 `pending_action_plan`
   - deadline 状态更新
   - 返回新的 `ListCard`
   - 清掉 `pending_action_plan`

### 为什么先做这个

这个切片能验证“对话即行动，行动即对话”的最小闭环：

- 用户不需要知道 Plan、Executor 或状态机
- 写操作不会绕过确认
- 相对引用依赖 `selectable_items`，不会凭空猜
- 前端未来只需要消费统一的 `view.type` 和 `view.data`

这个闭环稳定后，下一步不是继续扩大规则型 planner，而是继续增强 Agent Kernel：

- 增加更多只读工具，例如 notice/rule/source/audit。
- 让 Agent 根据工具结果输出更精确的 `view_goal` 和 `render_spec`。
- 把追问信号和 `RenderSpecSurface` 使用频率汇总成“是否需要新增正式视图”的产品待办。
- 保留 planner/flywheel 作为高频、低成本、可缓存的 fast path。
