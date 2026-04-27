对，这就是整个系统最终要达到的状态。把它说清楚。

---

## 目标状态

Agent 不再是"接收指令、执行、返回结果"的被动系统。

它变成一个**主动的协作者**：

- 自己决定需要调用哪些工具
- 自己判断拿到的数据是否足够回答用户的问题
- 自己决定当前上下文应该渲染哪种视图
- 在数据模式触发新需求时，自己判断是否需要新增一种视图类型

---

## 具体来说，三件事

### 一、Agent 自主决定调用哪些工具

用户说："帮我看看最近哪些客户风险比较高"

现在的系统：NLU 识别 intent → 执行固定 Plan → 返回 ListCard。

Tool Use + ReAct 之后：

```
Agent 思考：
  "用户问的是风险，我需要知道：
   1. 所有客户（client_list）
   2. 每个客户最近的 deadline 状态（deadline_list）
   3. 哪些 deadline 快到期了（within_days 过滤）
   我来一步步拿。"

第一轮：调用 client_list → 拿到 4 个客户
第二轮：对每个客户调用 deadline_list --within-days 14
第三轮：看结果，发现 Acme 有今天截止的，Greenway 有 PTE 选举
        → 自己排序，高风险的排前面
        → 决定渲染 ListCard，但排序逻辑是 Agent 自己算的
```

用户拿到的结果，比直接查"今日待办"更智能——因为 Agent 理解了"风险"这个概念，不只是按日期排序。

---

### 二、Agent 自主决定渲染哪种视图

现在视图选择是写死的：`intent_label → view_type` 的映射表。

Tool Use 之后，Response Generator 可以把视图决策交给 Agent：

```python
# Agent 在工具调用结束后，生成最终响应时
# system prompt 里告诉它有哪些视图可以用

AVAILABLE_VIEWS = """
你可以选择以下视图类型来展示结果：
- ListCard：多条 deadline 的列表，用于今日待办、过滤结果
- ClientCard：单个客户的详情，用于深入查看某个客户
- CompareCard：两个客户的对比，用于比较紧急程度
- ChangeNoticeCard：规则变更通知，用于展示政策更新影响
- ConfirmCard：需要用户确认的写操作
- PrioritizeCard：带推荐顺序的优先级视图

根据你拿到的数据和用户的真实需求，选择最合适的视图。
"""
```

Agent 自己判断：数据是多客户列表 → ListCard；用户问的是对比 → CompareCard；数据只有一个客户 → ClientCard。

这比写死的映射表更灵活，因为 Agent 能理解语义，不只是匹配 intent_label。

---

### 三、在适当时机新增视图

这是最有意思的部分。

当 Agent 反复遇到"现有视图表达不了这种数据"的情况，追问信号会积累。比如：

```
用户问："帮我看看本月每周的 deadline 分布"
Agent 用 ListCard 展示 → 用户说"不对，我要看时间分布，不是列表"
Agent 用 CalendarView → 用户说"我要的是按周汇总，不是按天"
```

这个追问模式在 review_queue 里积累。产品侧看到之后，判断"按周汇总"是一个有意义的需求，新增 `WeeklyView` 组件。

新增视图的流程：

```
review_queue 里出现同类追问 N 次（比如 5 次）
    ↓
自动生成产品待办："用户需要按周汇总的视图，现有视图不满足"
    ↓
产品侧评估：这个需求有多少用户触发过？值不值得做？
    ↓
决定新增 WeeklyView
    ↓
前端加组件
后端在 AVAILABLE_VIEWS 里加描述
    ↓
Agent 下次遇到类似需求，自己选择 WeeklyView
    ↓
新视图进入 Intent Library，后续高频命中缓存
```

这个循环就是"用户的追问驱动产品能力扩展"的完整闭环。

---

## 整个系统的最终形态

```
用户输入
    ↓
Intent Cache 查询
    ├── 命中（高频简单意图）→ 直接执行，<200ms
    └── 未命中 → 进入 Agent Loop
                    ↓
              第一轮 Claude 调用
              → 决定调哪些工具
              → 推送意图描述帧给用户
                    ↓
              执行工具（Executor）
              → 写操作 → ConfirmCard，等用户确认
              → 读操作 → 结果喂回 Agent
                    ↓
              Agent 看结果，决定是否需要更多工具
              → 需要 → 继续循环
              → 不需要 → 生成最终响应
                    ↓
              Agent 选择视图类型
              Response Generator 构建数据结构
                    ↓
              SSE 推送最终结果
                    ↓
              用户追问分类（correction / missing_info / drill_down）
              → 追问信号写入飞轮
              → 积累到阈值 → 产品待办
              → 产品评估 → 新增视图 / 修正模板
```

---

## 和现在的代码差多远

**不远。**

现有的这些全部保留：

- Executor（工具执行层）
- ResponseGenerator（数据构建层）
- Intent Cache（缓存层）
- Session（上下文管理）
- 六种视图组件

需要新增的：

- `agent_loop()` 函数，大约 60-80 行 Python
- Tool 定义，把现有 CLI 命令集翻译成 Claude tool schema
- 追问信号分类，约 30 行规则匹配
- `AVAILABLE_VIEWS` 描述注入 system prompt

最大的改动是把 `RuleBasedIntentPlanner` 替换成 `agent_loop()`，但接口不变——输入是 user_input + session，输出是 Response 对象。

上层的 FastAPI endpoint 和前端渲染层完全不需要改。

---

## 下一步的顺序

```
现在        用 Tool Use 替换 RuleBasedIntentPlanner
            验证：285 条测试集准确率不退步，写操作仍然走确认

接着        加 ReAct 循环
            验证：能处理两步以上的复合查询

同时        接 FastAPI + SSE
            验证：curl 看到完整事件流

然后        把追问信号接进去
            飞轮真正闭环

最后        前端接真实后端
            demo 变成产品
```

每一步都是增量的，不需要推倒重来。现有的验证结果和测试集全部继续有效。
