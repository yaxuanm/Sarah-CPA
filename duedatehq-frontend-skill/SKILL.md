# DueDateHQ Frontend Design Skill

这是 DueDateHQ 产品的前端设计语言规范。所有前端页面、组件、原型都应遵循这套规范，确保视觉语言统一。

---

## 设计哲学

**克制、信任、专业。**

这是一个税务合规工具，用户是 CPA 专业人士。界面传达的信息是：我替你想清楚了，你只需要做决定。

不炫技，不花哨。每一个视觉元素都应该有功能目的。认知负担在系统这边，不在用户这边。

---

## 字体系统

```css
@import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Sans:wght@300;400;500;600&family=DM+Mono:wght@400;500&display=swap');

--serif: 'DM Serif Display', Georgia, serif;
--sans:  'DM Sans', sans-serif;
--mono:  'DM Mono', monospace;
```

**使用规则：**

- `--serif`：标题、大数字、品牌名。传达权威感和优雅感。用于 H1/H2 级别的标题，不用于正文。
- `--sans`：所有正文、按钮、标签、说明文字。清晰可读，不抢戏。
- `--mono`：日期、ID、代码、数字数据。强调精确性，用于截止日期显示、金额、技术标注。

**字号层级：**

```css
/* 品牌 / 超大标题 */
font-size: 28-38px; font-family: var(--serif);

/* 页面标题 / 卡片标题 */
font-size: 22-26px; font-family: var(--serif);

/* 正文大 */
font-size: 15-16px; font-family: var(--sans); font-weight: 400-500;

/* 正文标准 */
font-size: 13-14.5px; font-family: var(--sans);

/* 标签 / 辅助信息 */
font-size: 11-12px; font-family: var(--sans); font-weight: 600-700;
letter-spacing: 0.06-0.1em; text-transform: uppercase;

/* 日期 / 数字 */
font-size: 11-13px; font-family: var(--mono);
```

---

## 色彩系统

```css
:root {
  /* 基础色 */
  --ink:       #0e1a2b;   /* 主文字、深色背景 */
  --ink-2:     #2c3e55;   /* 次级文字 */
  --ink-3:     #5a6f87;   /* 三级文字、占位符 */
  --ink-4:     #94a3b5;   /* 最淡文字、辅助信息 */

  /* 纸质背景系 */
  --paper:     #f5f3ee;   /* 主背景，微暖白 */
  --paper-2:   #edeae3;   /* 次级背景、分割线区域 */
  --paper-3:   #e3dfd7;   /* 边框、分割线 */
  --white:     #ffffff;   /* 卡片背景 */

  /* 强调色 */
  --gold:      #c8953a;   /* 主品牌色，用于高亮、焦点、品牌元素 */
  --gold-soft: #fdf3e3;   /* 金色背景区域 */

  /* 语义色 */
  --red:       #c0392b;   /* 紧急、错误、危险操作 */
  --red-soft:  #fdf0ee;   /* 红色背景区域 */
  --green:     #1a7a4a;   /* 完成、成功、低风险 */
  --green-soft:#e8f5ee;   /* 绿色背景区域 */
  --blue:      #1a4f8a;   /* 信息、变更通知、系统事件 */
  --blue-soft: #e8f0fa;   /* 蓝色背景区域 */
}
```

**使用原则：**

- 金色（`--gold`）是唯一的品牌强调色，用于交互焦点、品牌标识、重要高亮。不要滥用。
- 语义色只用于传达状态：红色=紧急/危险，绿色=完成/安全，蓝色=信息/变更。
- 背景始终用纸质色系，不用纯白作为页面背景。卡片用 `--white`，页面用 `--paper`。
- 深色（`--ink`）只用于品牌栏、客户详情 header 等需要强对比的区域。

---

## 间距与圆角

```css
/* 圆角 */
--radius-sm:  6px;    /* 按钮、标签 */
--radius-md:  8px;    /* 输入框、小卡片 */
--radius-lg:  12px;   /* 主卡片、面板 */
--radius-full: 999px; /* 胶囊标签、圆形元素 */

/* 内边距标准 */
卡片内边距：  20-28px
行内边距：    16-24px
按钮内边距：  0 13-16px（高度固定）
```

---

## 组件规范

### 顶部导航栏（Topbar）

```css
高度：56px
背景：var(--ink)
内容：左侧品牌名（serif，金色强调）+ 右侧租户名 + 头像
```

品牌名格式：`DueDate<em>HQ</em>`，em 标签用金色，其余用白色。

### 主布局（Workspace）

双栏布局：左侧对话区固定宽度 380px，右侧内容区占满剩余空间。

```css
display: grid;
grid-template-columns: 380px 1fr;
```

### 卡片（Card）

所有卡片共用基础样式：

```css
background: var(--white);
border: 1px solid var(--paper-3);
border-radius: 12px;
overflow: hidden;
animation: slideIn 0.25s ease both;

@keyframes slideIn {
  from { opacity: 0; transform: translateY(10px); }
  to   { opacity: 1; transform: translateY(0); }
}
```

特殊状态的卡片边框：
- 确认操作（ConfirmCard）：`1.5px solid var(--gold)`
- 危急事项（CriticalCard）：`2px solid var(--red)`
- 变更通知（ChangeCard）：`1px solid var(--paper-3)`（用深色 banner 区分）
- 引导卡（GuidanceCard）：`1px solid var(--paper-3)`

### 按钮

**主按钮（Primary）：**
```css
background: var(--ink);
color: var(--white);
border: 1px solid var(--ink);
border-radius: 8px;
height: 42px;
font-weight: 600;

&:hover {
  background: var(--gold);
  border-color: var(--gold);
  color: var(--ink);
}
```

**次级按钮（Secondary）：**
```css
background: var(--white);
color: var(--ink-2);
border: 1px solid var(--paper-3);

&:hover {
  border-color: var(--ink-3);
  color: var(--ink);
}
```

**行内操作按钮（Action）：**
```css
height: 30px;
padding: 0 13px;
border-radius: 6px;
border: 1px solid var(--paper-3);
font-size: 12.5px;
```

**快捷按钮（Quick）：**
```css
height: 32px;
border-radius: 16px;  /* 圆角胶囊 */
border: 1px solid var(--paper-3);
font-size: 13px;

&:hover {
  border-color: var(--gold);
  color: var(--gold);
  background: var(--gold-soft);
}
```

### 状态标签（Badge Pill）

```css
display: inline-block;
padding: 2px 9px;
border-radius: 999px;
font-size: 11.5px;
font-weight: 600;

/* 状态变体 */
.urgent { background: var(--red-soft);   color: var(--red);   }
.medium { background: var(--gold-soft);  color: var(--gold);  }
.low    { background: var(--green-soft); color: var(--green); }
.done   { background: var(--paper-2);   color: var(--ink-4); }
```

### 输入框

```css
border: 1.5px solid var(--paper-3);
border-radius: 8px;
padding: 6px 8px 6px 14px;
background: var(--paper);
transition: border-color 0.15s;

&:focus-within {
  border-color: var(--gold);
  background: var(--white);
}
```

### 消息气泡（Conversation）

系统消息：
```css
background: var(--paper);
border: 1px solid var(--paper-2);
border-radius: 2px 10px 10px 10px;
padding: 11px 15px;
font-size: 14.5px;
color: var(--ink-2);
```

用户消息：
```css
background: var(--ink);
color: rgba(255,255,255,0.9);
border-radius: 10px 2px 10px 10px;
```

### 弱提醒（Weak Notice）

出现在对话流中，不在内容区。视觉权重极低。

```css
display: flex;
align-items: flex-start;
gap: 8px;
padding: 8px 12px;
background: var(--paper);
border: 1px solid var(--paper-2);
border-radius: 8px;
font-size: 13px;
color: var(--ink-4);

/* 绿点 */
.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--green);
  flex-shrink: 0;
  margin-top: 5px;
}
```

### 注释框（Annotation）

用于 demo 模式，标注"真实系统这里做了什么"。

```css
padding: 10px 14px;
background: #fffbf0;
border: 1px dashed var(--gold);
border-radius: 7px;
font-size: 12px;
color: var(--ink-3);
line-height: 1.55;

strong { color: var(--gold); }
code {
  font-family: var(--mono);
  font-size: 11px;
  background: var(--paper-2);
  padding: 1px 5px;
  border-radius: 3px;
}
```

---

## 动画规范

```css
/* 标准入场动画（所有卡片） */
@keyframes slideIn {
  from { opacity: 0; transform: translateY(10px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* 消息气泡入场 */
@keyframes fadeUp {
  from { opacity: 0; transform: translateY(6px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* 完成状态弹出 */
@keyframes popIn {
  from { opacity: 0; transform: scale(0.5); }
  to   { opacity: 1; transform: scale(1); }
}

/* 危急事项脉冲点 */
@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50%       { opacity: 0.5; transform: scale(0.85); }
}
```

**原则：**
- 卡片切换用 slideIn（0.25s ease）
- 对话消息用 fadeUp（0.2s ease）
- 成功/完成状态用 popIn（0.4s cubic-bezier(0.34,1.56,0.64,1)）带弹性
- 持续状态（危急红点）用 pulse（1.2s ease infinite）
- 过渡时间不超过 0.4s，不做复杂序列动画

---

## 视图组件体系

DueDateHQ 的内容区只有以下六种视图，每种视图对应明确的使用场景：

| 组件 | 触发场景 | 核心特征 |
|---|---|---|
| `ListCard` | 今日待办、过滤列表 | 左侧彩色竖条表示紧急度，最多5条 |
| `ClientCard` | 单客户详情 | 深色 header，每条 deadline 有操作按钮 |
| `ConfirmCard` | 写操作确认 | 金色边框，一个问题，最多三个选项 |
| `ChangeNoticeCard` | 规则变更通知 | 深色 banner，三步说明，对比新旧日期 |
| `CriticalCard` | 强提醒、不可撤销事项 | 红色边框，脉冲红点，后果说明 |
| `GuidanceCard` | 意图不明确、降级 | 可点击选项列表，无结构化数据 |

**扩展原则：**
新增视图类型时，必须能用一句话说清楚"这个视图在什么情况下出现"。如果说不清楚，说明这个视图不应该存在。

---

## 完成状态（Done State）

所有待办处理完后的收尾画面：

```css
.done-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 64px 40px;
}

/* 绿色对号圆圈，带 popIn 动画 */
.done-mark {
  width: 64px;
  height: 64px;
  border-radius: 50%;
  background: var(--green-soft);
  display: grid;
  place-items: center;
  font-size: 28px;
  margin-bottom: 22px;
  animation: popIn 0.4s cubic-bezier(0.34,1.56,0.64,1) both;
}

.done-title {
  font-family: var(--serif);
  font-size: 28px;
  margin-bottom: 10px;
}

.done-sub {
  font-size: 15px;
  color: var(--ink-4);
  max-width: 320px;
}
```

---

## 滚动条

统一使用细滚动条，不抢视觉：

```css
::-webkit-scrollbar { width: 4px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--paper-3); border-radius: 2px; }
scrollbar-width: thin; /* Firefox */
```

---

## 禁止项

以下是这套设计语言明确禁止的做法：

- **禁止用 Inter、Roboto、Arial、system-ui** 作为字体。始终用 DM Sans + DM Serif Display + DM Mono。
- **禁止紫色、渐变色背景**。背景只用纸质色系。
- **禁止超过三种强调色同时出现**在同一个视图里。
- **禁止纯白（#ffffff）作为页面背景**。页面背景用 `--paper`，卡片背景用 `--white`。
- **禁止 box-shadow 叠加过多**。如需投影，用 `0 18px 60px rgba(22,37,65,0.09)`。
- **禁止按钮高度不一致**。主按钮 42px，行内操作按钮 30px，快捷按钮 32px，严格遵守。
- **禁止动画时间超过 0.4s**。超过这个时长用户会感到迟钝。
- **禁止在对话区显示结构化数据**。结构化数据只在内容区（右侧）渲染。对话区只显示自然语言。

---

## 快速启动模板

每个新页面或组件，从这个基础开始：

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>DueDateHQ — [页面名]</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Sans:wght@300;400;500;600&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet"/>
<style>
:root {
  --ink:       #0e1a2b;
  --ink-2:     #2c3e55;
  --ink-3:     #5a6f87;
  --ink-4:     #94a3b5;
  --paper:     #f5f3ee;
  --paper-2:   #edeae3;
  --paper-3:   #e3dfd7;
  --white:     #ffffff;
  --gold:      #c8953a;
  --gold-soft: #fdf3e3;
  --red:       #c0392b;
  --red-soft:  #fdf0ee;
  --green:     #1a7a4a;
  --green-soft:#e8f5ee;
  --blue:      #1a4f8a;
  --blue-soft: #e8f0fa;
  --serif:     'DM Serif Display', Georgia, serif;
  --sans:      'DM Sans', sans-serif;
  --mono:      'DM Mono', monospace;
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: var(--sans);
  background: var(--paper);
  color: var(--ink);
  min-height: 100vh;
}

@keyframes slideIn {
  from { opacity: 0; transform: translateY(10px); }
  to   { opacity: 1; transform: translateY(0); }
}

@keyframes fadeUp {
  from { opacity: 0; transform: translateY(6px); }
  to   { opacity: 1; transform: translateY(0); }
}
</style>
</head>
<body>
<!-- 内容从这里开始 -->
</body>
</html>
```

---

## 设计决策速查

**Q: 这个信息应该放在对话区还是内容区？**
自然语言 → 对话区。结构化数据、操作按钮 → 内容区。

**Q: 这个操作需要确认卡吗？**
会修改数据库状态的操作（complete / snooze / waive / override）→ 需要。只读操作 → 不需要。

**Q: 用什么颜色表示紧急程度？**
今天截止 → 红色（urgent）。7天内 → 金色（medium）。7天以上 → 绿色（low）。

**Q: 新增一种视图合理吗？**
能用一句话说清"这个视图什么时候出现"→ 合理。说不清楚 → 用现有六种视图之一，或者 GuidanceCard 降级。

**Q: 按钮文字怎么写？**
动词开头，说清楚动作："Mark complete"、"Snooze 7 days"、"Got it"。不用"OK"、"Submit"、"Proceed"。
