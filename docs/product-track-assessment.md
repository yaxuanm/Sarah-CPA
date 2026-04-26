# DueDateHQ 产品方向评估

Internal / Product + Engineering
v0.1 / Discovery alignment
Apr 2026

## 文档目的

这份文档提取当前用户故事、价值主张画布和商业计划书中最重要的产品与技术含义。

核心问题是：

- 我们现在是不是在做正确的东西？
- 当前技术方向是否和产品命题一致？

## 1. 核心产品定义

DueDateHQ 应该被理解为一个面向独立 CPA 和小型会计事务所的合规信息管理器。

它首先不是：

- 聊天机器人
- 通用 AI 助手
- 日历替代品
- 通用工作流系统

它的本质是：把分散的税务合规信息，转化为针对具体客户组合的、可执行、可追溯、可判断的工作上下文。

核心信息流是：

```text
税务来源变化
-> 结构化规则
-> 客户影响匹配
-> 系统主动提示或用户主动查询
-> 决策界面
-> 确认后的动作
-> 审计历史
```

对话、语音输入和实时渲染都是交互方式。它们有价值的前提是：让这个信息管理器更快、更安全、更值得信任。

这里的交互原则应该进一步收敛为一句话：

```text
用户需求无边界，系统展示必须有边界。
```

用户可以用任何方式表达需求：问今天要做什么、要求解释某个客户为什么高风险、暂停当前动作、回到清单、查看来源、处理导入异常。系统不应该把这些需求硬塞进固定页面，而应该先从用户 intention 推导出当下真正的 need，再把 need 收敛成当前决策需要的最小工作面。

按需渲染的产品定义应该是：

```text
按需渲染 = 从用户意图推导当前决策需求，并只渲染满足这个需求的最小可行动工作面。
```

默认工作面不应该先想“展示哪些卡片”，而应该先回答：

- 用户现在的目的是什么
- 用户需要知道哪些事实才能判断
- 用户此刻真正面对的一个问题是什么
- 用户有哪些少数可选路径
- 每个选择会改变什么、不会改变什么

因此默认交互可以进一步收敛为：

```text
必要事实 -> 一个问题 -> 三个选择
```

三个选择是：

- 推进
- 需要更多信息
- 暂时不做

这比继续堆 `Problem / Missing / Your move / DueDateHQ can` 更接近“按需”的本质。后者仍然容易变成工业软件式的信息拼接；前者强迫系统围绕用户当下的判断组织页面。

但是这四块仍然不够。页面还必须把任务带到完成状态，而不是只解释当前状态。专注任务页应该围绕生命周期组织：

```text
发现问题 -> 系统准备 -> 用户在外部执行 -> 回来记录 -> 返回清单
```

例如用户点击 `Prepare request` 之后，页面主状态不应该继续展示普通任务详情，也不应该把 prepared message 放到下方让用户自己找。首屏应该直接变成“现在发送这段消息；发送后回来点 Mark request sent”的完成向导。这样用户不用重新理解页面，也不会卡在“然后呢？”。

这里有一个文案边界：`Next step`、`Decision`、`Ask / Inspect`、`What happens next` 这类词最多只能作为内部结构名，不应该直接成为用户可见按钮或推荐问题。界面也不应该堆一组“为什么要……”的问题按钮。用户可见交互应围绕三个选择组织：推进、需要更多信息、暂时不做。具体按钮再映射到业务动作，例如 `Prepare request`、`Show source`、`Back to list`。

这里有一个重要边界：交互不只由用户发起。用户故事里已经明确包含系统主动提示，例如本周分诊提醒、deadline 阶梯提醒、州税局突发延期公告 banner、邮件通知和受影响客户清单。

因此 DueDateHQ 的交互模型应该同时支持：

- 用户主动问：这周有什么？Acme 为什么高风险？
- 系统主动推：加州延期公告已确认，6 个客户可能受影响。

## 2. 最重要的客户问题

客户最强的痛点不是单纯的“追踪日期”。

真正的问题是：

- Sarah 不确定自己是否已经看到了所有重要事项
- 相关信息分散在 Excel、日历、邮件、政府网站和记忆里
- 税务规则会变化，而且影响范围取决于客户所在州、实体类型、税种，有时还取决于县
- 错过截止日会带来真实的财务责任和专业责任

因此，产品承诺应该是：

- Sarah 能快速知道现在什么需要行动
- Sarah 能看到为什么这件事重要
- Sarah 不需要手工重建上下文就能做出判断
- Sarah 事后能证明信息来自哪里、系统改了什么、自己做过什么

这不是一个普通 reminder 产品，而是一个信息信心产品。

## 3. 优先级最高的用户故事

Discovery 材料里有三个主要用户故事。它们不应该被当成同等优先级来实现。

### 3.1 每周分诊

优先级：P0

这是核心留存场景。

Sarah 在周一早上打开 DueDateHQ，需要在 30 秒内知道本周必须处理什么。当前基线是大约 45 分钟的 Excel 筛选、日历核对和手工确认。

目标结果：

- 每周分诊在 5 分钟内完成
- 今日新增事项和待处理事项有统一清单
- 用户可以从清单进入单个事项的专注处理面
- 专注处理某一事项时，不主动推荐跳到另一件事
- 用户可以主动返回清单，再选择其他事项
- 每个事项默认展示 Problem、Missing / Check、Your move、DueDateHQ can
- 每项都显示剩余天数、状态、风险和推荐动作
- 系统可在周一早上主动提示本周需要分诊的事项

这个场景决定用户是否每周都会回来使用产品。

### 3.2 客户导入与上手

优先级：P0

这是转化场景。

如果 CPA 不能快速导入客户数据，产品可能在用户体验到核心价值之前就流失。

目标结果：

- 30 分钟内导入 30 个客户
- 支持 TaxDome、Drake、Karbon、QuickBooks 导出 CSV
- 自动识别客户名、EIN、州、实体类型等常见字段
- 对模糊或缺失字段提供建议
- 导入后立即生成每个客户的全年截止日历

这个场景决定试用到付费的转化。

### 3.3 州税变更响应

优先级：P1 / Differentiator

这是战略护城河场景。

DueDateHQ 最强的长期差异化，是自动监控政府来源、解读官方公告，并识别受影响客户。

目标结果：

- 24 小时内捕获官方州税公告
- 基于州、县、实体类型、税种识别受影响客户
- 在主看板 banner 和邮件里通知用户
- 用户可以查看受影响客户，并批量调整截止日
- 每条公告都附官方来源链接

这个场景创造防御性，但它依赖 P0 流程先建立好的数据基础和客户档案质量。

这一类场景尤其重要，因为它不是用户问出来的，而是系统发现风险后主动发起的交互。

主动提示不应该只是 notification。它应该直接生成一个可操作的 render surface，例如：

```text
系统：California 延期公告已确认，可能影响 6 个客户。
右侧：change impact surface，包括公告摘要、受影响客户、来源链接和批量动作。
```

## 4. AI 杠杆点

AI 策略应该窄而实用。

AI 的价值不在于让产品看起来更像聊天助手，而在于降低维护和解读碎片化合规信息的成本。

最高杠杆的 AI 用例是：

- 导入 CSV 时的字段映射
- 从混乱客户记录中识别实体类型
- 政府公告监控
- 税务公告语义解读
- 受影响客户匹配
- 紧急程度和优先级排序
- 基于结构化数据的自然语言查询理解

商业计划书里最强的战略主张是：AI 能把数据维护成本降到足以支撑 $49/月产品的水平。

因此 AI 路线应该优先服务：

- 数据获取
- 数据解读
- 客户影响匹配
- 工作优先级判断

Chat 应该是这些能力之上的交互层，而不是产品中心。

## 5. 当前技术方向对齐情况

当前仓库和产品命题是方向一致的。

已有优势：

- 已经有 `Client`、`Rule`、`Deadline`、`Reminder`、`Notification`、`Audit` 等核心概念
- deadline 状态迁移已经被显式建模
- audit log 支持信任和追溯
- reminder scheduling 和 notification routing 已经存在
- `PlanExecutor` 提供了确定性执行边界
- `InteractionBackend` 和 `ResponseGenerator` 为结构化交互提供了路径

这些都是合规信息管理器需要的正确基础。

当前方向最正确的地方，是把系统看成：

- 先有结构化数据
- 再有确定性执行
- 再用 AI 做理解和解读
- 最后才是对话交互

## 6. 当前不对齐的风险

主要风险是产品重心。

当前工作容易漂移到：

- 实时聊天体验
- 更多渲染卡片
- 泛化的动态界面
- 把语音交互当成主卖点

这些方向不是错误，但它们不是当前最大的产品风险。

当前最大的产品风险是：

- Sarah 不能足够快地完成每周分诊
- onboarding 仍然需要太多手工清洗
- 系统不能可靠解释某个 deadline 为什么存在或为什么变化
- 税法变更监控还不足以让用户信任

当前渲染实现也仍然太固定格式。

现在的渲染基本还是：

```text
intent_label -> fixed card template
```

这不足以支撑产品承诺。产品真正需要的是：

```text
decision task + customer context + urgency + available actions
-> selected work surface
-> layered rendering payload
```

## 7. 正确的产品架构

系统应该围绕 decision task 建模，而不是围绕 chat intent 建模。

推荐的任务模型：

- `weekly_triage`
- `today_action_queue`
- `customer_import_review`
- `client_deadline_review`
- `change_impact_review`
- `deadline_confirmation`
- `ambiguity_resolution`
- `audit_or_source_review`
- `system_alert_review`

每个 decision task 都应该定义：

- 用户正在做什么判断
- 判断需要的最小完整上下文是什么
- 这个判断的 Problem、Missing / Check、Your move、DueDateHQ can 分别是什么
- 需要获取哪些记录
- 哪些紧急信号重要
- 当前允许哪些动作
- 哪些来源或审计证据必须可见
- 通常应该使用哪种渲染 pattern

这样系统既有稳定结构，也能支持自适应渲染。

Decision task 可以由两类入口触发：

- `user_triggered`：用户通过文字、语音、点击或上传主动发起
- `system_triggered`：系统通过 reminder、公告监控、规则变更、导入异常或风险升级主动发起

这点很关键。DueDateHQ 不是被动问答工具，而是会主动把需要 Sarah 判断的事项推到她面前。

## 8. 渲染方向

正确的渲染方向不是自由生成 UI，也不是继续增加固定页面。

最小正确交互形态应该是：

```text
左侧：交互区
右侧：按需渲染区
```

左侧承载用户输入、语音入口和必要的对话上下文。右侧不做固定 dashboard，而是根据当前用户需求实时渲染她现在需要看的工作面。

这意味着：

- 左侧负责理解用户要什么
- 左侧也承载系统主动提示和提醒
- 右侧负责呈现当前最有用的信息面
- 对话不应该成为页面中心
- 渲染结果不应该被固定页面结构限制

### 8.1 不直接生成任意 HTML

有 LLM 之后，技术上可以实时生成 HTML，但产品级方案不应让模型直接输出任意 HTML 给浏览器。

更稳的路径是：

```text
用户输入
-> LLM 理解 intent / information need
-> Planner 决定需要哪些可信数据
-> Executor 获取结构化数据
-> LLM 或规则生成 render spec
-> Validator 校验 spec
-> Renderer 转成 HTML
```

也就是说，LLM 可以参与“组织页面”，但不直接拥有最终页面执行权。

这可以同时满足两个要求：

- 右侧确实能按需实时变化
- 系统仍然有安全、稳定、可测试、可审计的边界

### 8.2 Spec 要覆盖场景，但不能爆炸

我们的 spec 需要覆盖大部分 CPA 工作场景，但 spec 不是越多越好。

如果为每个场景写一个独立页面 spec，很快会变成：

```text
weekly_triage_page
client_detail_page
change_impact_page
import_review_page
deadline_history_page
source_review_page
risk_summary_page
...
```

这会重新回到固定格式系统。

正确方向是定义少量可组合的 render primitives。

推荐的 block primitives：

- `summary`
- `priority_summary`
- `alert_banner`
- `grouped_deadline_list`
- `deadline_table`
- `client_profile`
- `change_impact`
- `source_evidence`
- `timeline`
- `field_mapping_review`
- `action_bar`
- `confirmation`
- `empty_state`
- `guidance`

右侧渲染区每次不是选择一个固定页面，而是组合多个 block，形成当前任务需要的 surface。

主动提示通常会组合成：

```text
alert_banner + summary + relevant list/table + source_evidence + action_bar
```

### 8.3 跨内容、跨场景渲染

用户需求天然可能是跨内容、跨场景的。

例如用户可能问：

```text
这周加州相关的 deadline 有哪些？其中有没有受最近延期影响的？帮我看 Acme 是否需要处理。
```

这个请求同时涉及：

- weekly triage
- state filter
- change impact
- client detail
- action recommendation

如果系统只能选择一个固定 view，就会卡住。

更合理的输出是 composite render spec：

```json
{
  "surface_type": "composite",
  "title": "本周 California 相关事项",
  "intent_summary": "筛选本周 California deadline，并识别延期影响和 Acme 的处理事项。",
  "blocks": [
    {
      "block_type": "summary",
      "priority": 1,
      "data": {
        "message": "本周 California 有 6 个事项，2 个可能受延期影响。Acme 需要处理 1 项。"
      }
    },
    {
      "block_type": "grouped_deadline_list",
      "priority": 2,
      "data": {}
    },
    {
      "block_type": "change_impact",
      "priority": 3,
      "data": {}
    },
    {
      "block_type": "client_profile",
      "priority": 4,
      "data": {}
    },
    {
      "block_type": "source_evidence",
      "priority": 5,
      "data": {}
    }
  ],
  "actions": []
}
```

这就是按需渲染的核心：

```text
用户需求可以无边界
渲染系统必须有边界
```

边界来自三层：

- block primitives 有边界
- 数据来源有边界
- action registry 有边界

LLM 不能凭空生成事实，也不能发明业务动作。它只能基于可信数据组织 spec。

同样，系统主动提示也不能凭空生成。它必须来自明确事件，例如：

- reminder due
- deadline approaching
- missing documents detected
- official announcement captured
- rule confidence below threshold
- client import ambiguity detected
- deadline status risk escalated

这些事件可以触发同一套 render spec pipeline，只是入口不是用户输入，而是系统事件。

### 8.4 按需渲染必须有规则边界

按需渲染的目标不是生成更多页面、更多 block、更多信息。

真正目标是：

```text
理解用户当前要完成的判断
只呈现完成这个判断所需的最小完整上下文
同时提供可信来源和允许动作
```

如果没有规则限制，按需渲染会退化成垃圾信息堆积。系统会不断生成 tab、block、解释和建议，最后用户反而更难判断。

因此按需渲染至少需要六类规则：

### 8.4.1 Intent boundary

系统必须先判断用户在做哪类 decision task。

如果意图不清楚，不应该直接生成复杂 surface，而应该先澄清。

规则：

- 意图不明确时，渲染 `guidance` 或 clarification
- 写操作必须进入 `confirmation`
- 数据不足时，显示缺失信息，而不是补全事实

### 8.4.2 Surface rule

每次输入或系统事件后，系统必须决定：

- 更新当前 tab
- 新开 tab
- 切换已有 tab
- 追加 supporting block
- 折叠旧内容
- 要求澄清

不能默认新开页面。

规则：

- 同一任务 + 同一实体，优先更新当前 surface
- 新任务 + 新实体，可以新开 surface
- 系统主动风险事件，可以新开 alert surface
- 写操作必须聚焦 confirmation surface
- 打开的 surface 需要有数量上限，旧的非关键 surface 应归档或关闭

### 8.4.3 Block budget

每个 surface 不能无限堆 block。

规则：

- 每个 surface 必须有一个 primary block
- 默认最多展示 3-5 个主要 block
- supporting block 必须服务当前判断
- 历史、来源、审计可以折叠展示
- 低优先级内容不默认展开

### 8.4.4 Data boundary

LLM 不能凭空生成事实。

规则：

- 所有客户、日期、状态、金额、风险信号必须来自可信数据绑定
- 没有来源的数据不能作为事实展示
- LLM 可以总结和组织，但不能创造 deadline、客户状态或官方解释

推荐 spec 使用 data binding，而不是让模型直接写数据：

```json
{
  "block_type": "deadline_table",
  "data_binding": {
    "source": "deadline.list",
    "filters": {
      "jurisdiction": "CA",
      "risk": "high"
    }
  }
}
```

### 8.4.5 Action boundary

所有动作必须来自系统 action registry。

规则：

- LLM 不能发明业务动作
- 写操作必须确认
- 批量操作必须显示影响范围
- 高风险动作必须显示 audit consequence

### 8.4.6 Naming rule

Tab name 应该来自 surface 内容摘要，而不是固定路由名。

规则：

- 2-5 个词
- 包含实体、范围、数量或状态之一
- 必须基于 surface 数据
- 不使用夸张或营销语气

示例：

- `This Week - 12`
- `Acme Dental - High`
- `CA Extension - 6`
- `TaxDome Import - 4 issues`
- `Confirm Acme`

### 8.5 Dynamic work tabs

右侧不应该是固定 tab 页面。

更准确的模型是：

```text
左侧：GPT-style interaction
右侧：dynamic work tabs
每个 tab：一个按需生成的 render surface
```

每个 tab 都应该有自己的 surface context，并参与后续对话理解。

例如用户说：

```text
把这个 tab 导出。
回到 import review。
第二个 tab 里的 Acme 为什么高风险？
```

系统需要能理解：

- 当前 active surface
- 所有 surface summary
- 当前 surface 的 selected item
- surface 内可见行
- surface 支持的 allowed actions

推荐 workspace state：

```json
{
  "active_surface_id": "surface_weekly_001",
  "surfaces": [
    {
      "surface_id": "surface_weekly_001",
      "tab_summary": "This Week - 12",
      "decision_task": "weekly_triage",
      "context": {},
      "render_spec": {}
    },
    {
      "surface_id": "surface_ca_extension_001",
      "tab_summary": "CA Extension - 6",
      "decision_task": "change_impact_review",
      "context": {},
      "render_spec": {}
    }
  ]
}
```

这比固定 scenario 更接近真实按需渲染：用户或系统事件不是切换到预设页面，而是生成或更新一个经过校验的 surface。

### 8.6 UI 减法原则

按需渲染不等于把系统内部机制展示给用户。

用户没有问系统怎么工作，用户问的是现在该处理什么。

因此产品 UI 不应该展示这些内部语言：

- `RenderSpec`
- `Validator`
- `DataBinding`
- `Block`
- `DecisionTask`
- `validated surface`
- `workspace state`

这些概念应该存在于技术文档、日志、debug 工具和测试环境，而不是默认用户界面。

每个 surface 只应该保留四类信息：

- 结论：当前发现了什么
- 工作对象：用户需要处理的客户、deadline、公告或导入行
- 证据：为什么适用、官方来源、审计历史
- 动作：当前允许做什么

删除或降级这些内容：

- 重复指标卡
- 大段解释系统如何生成页面
- 不影响判断的全局状态
- 装饰性统计
- 与当前意图无关的 block

这条原则适用于所有 surface：

```text
如果某个 UI 元素不能帮助用户判断、核验或行动，就默认不要展示。
```

### 8.7 推荐的渲染层结构

渲染层应该拆成五个子层：

- information need parsing
- data planning
- context assembly
- render spec generation
- spec validation and rendering

这比简单的 `intent_label -> fixed card template` 更适合真实用户需求。

当前产品可以先从小 spec 开始，不需要一开始覆盖所有边界情况。关键是架构方向要允许组合，而不是继续堆固定页面。

### 8.8 Pattern 仍然有用

推荐的 pattern library：

- weekly triage surface
- today action queue
- client detail surface
- import review surface
- change impact surface
- proactive alert surface
- confirmation surface
- ambiguity resolution surface
- source and audit review surface

这些 pattern 不应该被当成固定页面，而应该被当成常用 block 组合模板。

例如：

- `weekly triage surface` = `priority_summary` + `deadline_table` + `selected_detail` + `action_bar`
- `change impact surface` = `summary` + `change_impact` + `source_evidence` + `deadline_table`
- `import review surface` = `summary` + `field_mapping_review` + `confirmation`
- `proactive alert surface` = `alert_banner` + `summary` + `deadline_table` + `source_evidence` + `action_bar`

这样系统既能覆盖常见场景，也能处理跨场景需求。

## 9. 近期路线建议

### 9.1 先做每周分诊界面

这应该是默认产品体验。

必须具备：

- 按本周、本月、长期计划分组 deadline
- 显示剩余天数
- 显示状态和允许动作
- 支持按客户、州、税种快速筛选
- 在相关位置暴露 deadline 来源或原因

这是留存循环。

### 9.2 同步推进导入上手

这应该和每周分诊同等优先。

必须具备：

- CSV 上传和解析
- TaxDome、Drake、Karbon、QuickBooks 的来源 profile
- 字段映射建议
- 实体类型建议
- 提交前 validation review
- 提交后立即生成 deadline

这是转化循环。

### 9.3 增加 DecisionTask 和 StageSelector

当前 `ResponseGenerator` 不应该继续堆更多 intent-specific 分支。

推荐变化：

- 引入 `DecisionTask`
- 引入 `StageSelector`
- 引入 `WorkspaceState`
- 引入 dynamic work tabs
- 引入 composable render spec
- 保留确定性的 block primitives
- 增加 spec validator
- 让 `ResponseGenerator` 根据 validated render spec 组装 payload

这是从固定格式渲染走向需求驱动、跨场景渲染的桥。

### 9.4 先实现左侧交互、右侧按需渲染

MVP 页面不需要复杂三栏结构。

推荐最小页面结构：

```text
左侧交互区：输入、语音、简短对话历史、系统主动提示
右侧渲染区：多个 dynamic work tabs，每个 tab 是一个 validated render surface
```

这个结构足够表达产品核心：

- 左侧理解用户表达
- 左侧接收系统主动事件
- 右侧按需生成或更新工作面
- 用户可以连续追问
- tab 内容可以作为后续对话上下文
- 系统可以跨内容组合渲染，但必须受 block、data、action、naming 规则约束

这也是最适合验证产品方向的交互模型。

### 9.5 暂缓完整实时语音

Voice 目前可以继续保持 transcript-driven。

当前产品风险不是语音是否真正流式输入，而是 Sarah 是否能看到正确的工作上下文，并信任系统结果。

等 task model 和 rendering model 稳定后，再做 live voice 更合理。

## 10. 是否在正确轨道上

如果目标是下面这些，项目就在正确轨道上：

- 构建 CPA 合规信息管理器
- 用 AI 降低数据维护和信息解读成本
- 用对话和渲染降低用户操作阻力
- 保持执行确定性和可审计性

如果目标变成下面这些，项目就会跑偏：

- 先做 AI assistant
- 优先优化聊天新鲜感
- 把渲染理解成动态生成 UI
- 在 weekly triage 和 import 还没打透之前，继续扩展交互包装

最清晰的产品方向是：

```text
MVP = weekly triage + customer import + deadline state management + reminders
Differentiator = AI-assisted tax change monitoring and affected-client matching
Interface = structured decision surfaces with optional text or voice input
```

## 11. 工作结论

DueDateHQ 方向正确，但实现优先级应该更紧地围绕信息管理器这个命题。

最重要的下一步不是增加更多聊天能力，而是把两个 P0 循环做扎实：

- 周一早上的每周分诊
- 30 分钟客户导入和日历生成

同时，渲染架构应该从固定卡片选择，升级到基于 decision task 的 stage selection 和 composable render spec。

这样产品路径会更清楚：

- 立即有用
- 长期可防御
- 技术上可控
- 符合 $49/月独立 CPA 市场
