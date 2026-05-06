# DueDateHQ 十分钟展示讲稿

这份讲稿对应 `due-datehq-ten-minute-story-compact.html`。建议控制在 8 分 30 秒到 9 分钟，留一点时间给页面切换和现场加载。

## 0. 开场

大家好，我们今天展示的是 DueDateHQ。

一句话概括：DueDateHQ 想把 CPA 从截止日期里解放出来。

它不是一个更漂亮的日历，也不是一个报税软件。它解决的是更前置的问题：当一个 CPA 同时管理几十个客户、多个州、不同税种和不断变化的官方规则时，她每天怎么知道先做什么、谁被卡住了、哪条政策变化真的影响了自己的客户。

产品里有两个入口。

第一个是 Dashboard，它是结构化工作台，适合系统性地看客户、任务、截止日、规则变化和状态流转。

第二个是 Ask，它是自然语言入口。用户可以直接问“今天先做什么”，也可以问“最近有什么政策变化会影响客户”。Ask 不是独立聊天产品，它背后仍然用的是同一套客户、规则和 deadline 数据。

## 1. Sarah 的处境

我们先从一个具体用户讲起。

Sarah Johnson 是一个在 Dallas 独立执业的 CPA。她不是大型事务所，她就是她自己，加一个兼职助理。她管理 60 个客户，其中 23 个有跨州经营，全年有 400 多个联邦和州级 deadline 需要追踪。

她每周大概花 12 个小时在合规追踪和日历维护上。

这 12 个小时不是在做真正的税务判断，而是在维护“我到底什么时候该做什么”这件事本身。她现在靠 Excel、Google Calendar、Email 和同行群拼出一个工作流，但没有一个地方真正负责结果。

## 2. 真实代价

这个问题平时看起来只是麻烦，但一旦官方规则发生变化，就会变成风险。

比如 IRS 或州税局发布一条延期公告。Sarah 可能不是第一时间知道。等她从同行群里看到时，已经过去 48 小时。

然后她要回到 Excel 里，一个客户一个客户地查：谁在这个州？谁适用这个税种？谁的 deadline 需要变？谁已经提交了？谁还没提交？

所以我们认为，这不是提醒做得不够好的问题，而是小型 CPA firm 没有能力人工维护 50 州规则变化的问题。

## 3. 产品定位

DueDateHQ 的核心对象不是 calendar 上的一个格子，而是一个 work item。

一个 work item 里面包含：客户是谁、税种是什么、在哪个州、什么时候 due、现在是什么状态、谁负责、有没有 blocker、有没有 extension、提醒和沟通记录是什么。

所以用户看到的不是一堆日期，而是一个行动工作台：

Work now 是现在可以推进的事项。

Blocked 是缺文件、缺确认、缺客户信息，暂时推不动。

Needs review 是官方规则或政策变化，需要 CPA 判断。

Archive 是已经处理完的事项。

接下来我用三个用户故事来展示。

## 4. User Story 1: Import

第一个故事是：Sarah 第一次使用 DueDateHQ，怎么把现有客户带进来。

她不可能手工录 60 个客户，也不可能花一周时间配置系统。所以第一步必须是 import。

这里我会现场上传一个 CSV。系统会解析客户表、做字段映射、让用户确认哪些是新客户、哪些是更新已有客户，最后再写入系统。

这里 AI 的作用不是为了聊天，而是为了降低 onboarding 阶段的数据清洗成本。很多 CPA 手里的客户表并不规范，字段名可能来自 Excel、TaxDome、Karbon、QuickBooks 或自己手写的模板。系统先给出 mapping 建议，用户保留最终控制权。

这一条 demo 的 aha moment 是：上传客户表之后，系统不是生成一张静态表，而是生成一个可以工作的 portfolio。客户画像会继续驱动 deadline、work item 和 blocker。

## 5. User Story 2: Weekly Triage

第二个故事是 Sarah 周一早上打开产品。

以前她会先打开 Excel，花 20 到 30 分钟判断：今天哪些 deadline 最急？哪些被客户卡住？哪些可以往后放？哪些已经过期？

现在她打开 Work board，系统已经把事项按工作状态分好。

这里我会展示 Work now、Blocked、Needs review、Overdue 和 work detail。重点不是每一个按钮，而是让大家看到：系统已经把“日期”变成了“今天该怎么做”。

然后我会展示 Ask 的第一个场景：直接问“今天先做什么？”

Ask 会基于当前客户、deadline、blocked 状态和紧急程度，给出今天最值得先处理的事项。它不是替 CPA filing，而是帮她把优先级判断和下一步行动连接起来。

在具体 work item 里，如果缺客户资料，AI 还可以根据当前上下文起草 follow-up。它会读取 client、tax type、due date、blocker 和 contact，生成一封可以检查和发送的客户邮件。

这一条 demo 的 aha moment 是：DueDateHQ 不是提醒“有一个 deadline”，而是告诉 CPA“现在该处理哪件事，以及下一步怎么做”。

## 6. User Story 3: Rule Change

第三个故事是最能体现差异化的：官方规则发生变化。

传统软件可能能存 deadline，也可能能做提醒。但当一个州税政策变化时，CPA 仍然要自己读公告、理解影响、回到客户表里查谁被影响。

DueDateHQ 的目标是把这个过程变成一个 review workflow。

这里我会先展示 Review 页面：官方监控识别到 rule change，系统展示 source、before / after diff、affected clients。CPA 可以看 detail，确认这条变化会如何影响客户，然后选择 apply 或 dismiss。

然后我会切到 Ask，展示第二个 Ask 场景。

我会先问：“最近有什么新规会影响客户吗？”系统打开 Tax Change Radar。

然后追问：“这条变化会影响哪些客户？”系统会基于当前规则变化和客户画像，回答受影响客户、税种、州、截止日、状态和 source。

这里我会顺带解释：Dashboard 和 Ask 现在界面上还没有完全融合成最终形态，但产品逻辑是一致的。Dashboard 是结构化入口，Ask 是快捷入口。它们背后用的是同一套客户、规则和 deadline 数据。

这一条 demo 的 aha moment 是：Sarah 不再需要从一条公告出发，手工反推客户影响。系统先把影响范围找出来，CPA 最后只做专业判断。

## 7. AI 差异化

所以我们的 AI 不是一个浮在产品表面的 chatbot layer。

它嵌在四个具体场景里：

Parse：把混乱客户表和官方 notice 变成结构化数据。

Watch：监控官方来源，识别哪些变化值得 CPA 注意。

Match：把规则变化匹配到真实客户、州、税种和 work item。

Draft：基于当前 work item 上下文生成客户 follow-up。

Ask 的价值不是“聊天”，而是让用户不用学习所有按钮，也可以快速进入正确的工作面。

## 8. 市场与 GTM

从市场角度看，现有产品大概分两类。

一类是传统 due date tracking 软件，它证明了 deadline 本身足够成为一个产品核心，但体验更像数据库，规则更新和现代协作能力比较弱。

另一类是事务所 workflow 软件，它们擅长团队协作和状态流转，但核心对象通常不是 50 州税务规则和 deadline intelligence。

DueDateHQ 的切入点就在中间：Deadline intelligence + CPA workflow。

我们的第一批用户会是 40 到 150 个客户规模的小型 CPA firm。这个群体痛点足够强，但又没有大事务所那种完整的内部合规团队。

GTM 上，我们会从 concierge onboarding 开始：帮他们导入客户表，第一周就把 Work queue 清出来，让用户马上看到“我不用再维护 Excel 了”。

## 9. 当前完成度

目前我们已经不是只有前端 demo。

这个版本已经部署到线上。Demo 结束后，我们会把体验链接、测试 CSV 和 GitHub repo 发到聊天框。非技术同学可以直接打开产品体验 import、work queue 和 rule review；技术同学也可以看代码、API、CLI、测试数据和文档。

已经实现的核心能力包括：

客户导入：CSV 上传、preview、apply、AI mapping、新客户创建、已有客户更新。

Work board：Work now、Blocked、Needs review、Overdue、Archive、extension、client follow-up。

官方规则：CA / TX / NY 的 source sync、official source、before / after diff、affected clients、Review apply。

AI 与 API：Ask streaming、AI import mapping、AI follow-up draft、notification preview，以及 dashboard payload。

还在继续完善的是更广的州税来源、真实 Email / Slack 发送、PDF 报告、完整审计链和 production-grade auth。

## 10. 未来期待

长期来看，DueDateHQ 有两个飞轮。

第一个是规则库飞轮。用户越多，规则变化会被更多真实客户组合验证；规则库越准，用户越愿意把 deadline tracking 托付给系统。

第二个是意图飞轮。CPA 的高频表达其实是收敛的，比如“今天先做什么”“谁被卡住了”“这条变化影响谁”。随着使用增加，这些会形成 Intent Library，让 Ask 越用越快、越便宜、越懂 CPA。

今天 demo 的 wedge 是 deadline intelligence，但长期目标是成为 deadline-heavy CPA practice 的 operating layer。

## 11. 收尾

最后我想强调一点：DueDateHQ 保护的不是一张日历，而是 CPA 的判断力。

一个 CPA 最有价值的东西，从来不是她记住了多少截止日期，而是她对客户情况的理解和判断。

我们希望系统承担那些机械但高风险的部分：盯官方规则、维护 deadline、排序优先级、记录操作、生成沟通草稿。

这样 Sarah 每天打开产品时，不需要先问“我是不是漏了什么”，而是可以直接开始做最重要的事。

这就是 DueDateHQ。
