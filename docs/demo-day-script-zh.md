# DueDateHQ 十分钟展示讲稿

这份讲稿对应 `due-datehq-ten-minute-story-compact.html`。建议整体控制在 8 分 30 秒到 9 分钟，留 1 分钟给切换、加载和评委提问。核心策略是：先让大家理解 Sarah 的处境，再用三个产品故事证明 DueDateHQ 如何把“截止日期管理”变成可运行的工作闭环。

## 0. 开场

大家好，我们今天展示的是 DueDateHQ。

一句话概括：DueDateHQ 想把 CPA 从截止日期里解放出来。

它不是一个更漂亮的 calendar，也不是一个 tax filing system。它解决的是一个更前置的问题：当一个 CPA 同时管理几十个客户、多个州、不同税种和不断变化的官方规则时，她每天到底怎么知道先做什么、谁被卡住了、哪条政策变化真的影响了自己的客户。

我们的产品把四件事连在一起：客户画像、官方规则、截止日期和下一步动作。最后呈现出来的不是一堆日期，而是一个 CPA 可以每天打开来工作的 dashboard。

## 1. Sarah 的处境

我们先从一个具体用户讲起。

Sarah Johnson 是一个在 Dallas 独立执业的 CPA。她不是大型事务所，她就是她自己，加一个兼职助理。她现在管理 60 个客户，其中 23 个有跨州经营，全年有 400 多个联邦和州级 deadline 需要追踪。

她每周大概花 12 个小时在合规追踪和日历维护上。

这里的重点是，这 12 个小时不是在做真正的税务判断，也不是在给客户创造价值。她只是在维护“我到底什么时候该做什么”这件事本身。

她现在的工具非常典型：Excel 记录客户和 deadline，Google Calendar 做提醒，Email 和客户沟通，微信群或者同行消息偶尔告诉她 IRS 或州税局出了新公告。

这些工具都能存信息，但没有一个工具真正负责结果。

## 2. 真实代价

这个问题最危险的地方，是平时看起来只是麻烦，但一旦官方规则发生变化，就会变成风险。

比如 IRS 或州税局发布一条延期公告。Sarah 可能不是第一时间知道。等她从同行群里看到时，已经过去 48 小时。

然后她要回到 Excel 里，一个客户一个客户地查：谁在这个州？谁适用这个税种？谁的 deadline 需要变？谁已经提交了？谁还没提交？

一个看起来只是“更新一下日期”的动作，可能会变成整个周末的人工核查。

所以我们认为，这不是提醒做得不够好的问题，而是小型 CPA firm 没有能力人工维护 50 州规则变化的问题。

## 3. 产品定位

DueDateHQ 的核心对象不是 calendar 上的一个格子，而是一个 work item。

一个 work item 里面包含：客户是谁、税种是什么、在哪个州、什么时候 due、现在是什么状态、谁负责、有没有 blocker、有没有 extension、提醒和沟通记录是什么。

所以用户看到的不是一堆日期，而是四个真正和工作相关的状态：

Work now：现在可以推进的事项。

Blocked：缺文件、缺确认、缺客户信息，暂时推不动。

Needs review：官方规则或政策变化，需要 CPA 判断。

Archive：已经处理完的事项。

同时，我们有一个 Ask 入口。但 Ask 不是另一个独立聊天产品，也不是让用户离开 dashboard 去聊天。它最适合展示的场景，是像一个工作队列秘书一样，陪 CPA 完成“先做什么、准备什么、记录什么、下一步是什么”。

接下来我用三个用户故事来展示。

## 4. User Story 1: Import

第一个故事是：Sarah 第一次使用 DueDateHQ，怎么把现有客户带进来。

她不可能手工录 60 个客户，也不可能花一周时间配置系统。所以我们的第一步必须是 import。

现场操作：

1. 打开产品，进入 Clients。
2. 点击 Import。
3. 上传测试 CSV。
4. 展示 column mapping 和 row review。
5. 展示 AI mapping 和手动修正：字段不规范时，系统建议映射，用户可以自己改。
6. 点击 Apply。
7. 回到 Clients，看新客户和更新过的客户。

这里 AI 的作用不是为了聊天，而是为了降低 onboarding 阶段的数据清洗成本。很多 CPA 手里的客户表并不规范，字段名可能来自 Excel、TaxDome、Karbon、QuickBooks 或自己手写的模板。传统软件通常要求用户自己选字段、改 schema。我们希望系统能先给出建议，再让用户保留最终控制权。

这一条 demo 的 aha moment 是：上传客户表之后，系统不是生成一张静态表，而是生成一个可以工作的 portfolio。

新客户进入 client directory，已有客户被更新，客户画像会继续驱动 deadline、work item 和 blocker。

## 5. User Story 2: Weekly Triage

第二个故事是 Sarah 周一早上打开产品。

以前她会先打开 Excel，花 20 到 30 分钟判断：今天哪些 deadline 最急？哪些被客户卡住？哪些可以往后放？哪些已经过期？

现在她打开 Work board，系统已经把事项按工作状态分好。

现场操作：

1. 进入 Work。
2. 指出 Work now、Blocked、Needs review、Archive。
3. 展示 overdue 标识。
4. 点开一个 work item。
5. 展示 source、status、assignee、reminder timeline、blocker、extension。
6. 打开 client follow-up，点击 AI draft。
7. 展示生成出来的邮件草稿。

这里是我主要展示 Ask 的场景。

Ask 会像一个工作队列秘书一样，先告诉 Sarah：“Aurora 的 federal income 5 月 15 日到期，最紧急。先处理这个吗？”

Sarah 点“好的”，系统把对应的工作面打开。然后 Sarah 可以点 Prepare request，系统生成客户消息草稿。发出之后，Sarah 可以说“记录为已发送”，系统就把这一步写回操作记录。

接下来，Sarah 再确认完成，系统继续提示：“当前还有 5 件待处理，最早 2026-04-25 到期。”

所以 Ask 不是替 CPA filing，而是把优先级判断、客户沟通、操作记录和下一步串成一个连续流程。

在具体 work item 里，AI 的作用是帮 CPA 起草客户跟进邮件。它会读取当前 work item 的上下文，比如 client、tax type、due date、blocker 和 contact，然后生成一封可以发给客户的 follow-up。

但注意，AI 不会替 CPA 做专业判断，也不会直接完成 filing。它只是把重复沟通和整理上下文的成本降下来。

这一条 demo 的 aha moment 是：DueDateHQ 不是提醒“有一个 deadline”，而是告诉 CPA“现在该处理哪件事，以及下一步怎么做”。

## 6. User Story 3: Rule Change

第三个故事是最能体现差异化的：官方规则发生变化。

传统软件可能能存 deadline，也可能能做提醒。但当一个州税政策变化时，CPA 仍然要自己读公告、理解影响、回到客户表里查谁被影响。

DueDateHQ 的目标是把这个过程变成一个 review workflow。

现场操作：

1. 进入 Review。
2. 展示 official changes queue。
3. 点开一条 rule change。
4. 展示 official source link。
5. 展示 before / after diff。
6. 展示 affected clients。
7. 点击 review detail，看每个 client 会怎么变化。
8. 点击 Apply。
9. 跳到相关 client 或 work item，看变化已经反映出来。

这里也可以追问“这条变化会影响哪些客户”，系统会基于当前规则变化雷达和客户画像列出受影响事项。但在 10 分钟 demo 里，我建议 Ask 的主展示还是放在 Weekly triage，因为那个场景最像日常工作，也最容易让观众看到它不是普通聊天。

如果时间够，我会在 Review 这里补一个很短的 Ask 演示：先问“最近有什么新规会影响客户吗”，系统打开 Tax Change Radar；然后追问“这条变化会影响哪些客户？”系统会基于当前这条变化，回答受影响客户、税种、州、截止日、状态和 source，并提示可以去 Review detail 或 apply 后看 client / work 的更新结果。

这里的关键不是 AI 自动替 CPA 做决定，而是 AI 帮她完成三件事：读官方来源、提取变化、匹配客户组合。

最后是否 apply，仍然由 CPA 决定。

这一条 demo 的 aha moment 是：Sarah 不再需要从一条公告出发，手工反推客户影响。系统先把影响范围找出来，CPA 最后只做专业判断。

## 7. AI 差异化

所以我们的 AI 不是一个浮在产品表面的 chatbot layer。

它嵌在四个具体场景里：

第一，Parse。把混乱的客户表、字段名和官方 notice 变成结构化数据。

第二，Watch。监控官方来源，识别哪些变化值得 CPA 注意。

第三，Match。把规则变化匹配到真实客户、州、税种和 work item。

第四，Draft。基于当前 work item 上下文生成客户 follow-up。

Ask 最强的 demo 场景是工作队列：用户不用学习所有按钮，也可以通过对话完成优先级判断、客户请求、记录和下一步。这一点很重要，因为 CPA 的核心需求不是聊天，而是把工作推进下去。

## 8. 市场与 GTM

从市场角度看，现有产品大概分两类。

一类是传统 due date tracking 软件，它证明了 deadline 本身足够成为一个产品核心，但体验更像数据库，规则更新和现代协作能力比较弱。

另一类是事务所 workflow 软件，比如更大的 practice management 工具。它们很擅长团队协作和状态流转，但核心对象通常不是 50 州税务规则和 deadline intelligence。

DueDateHQ 的切入点就在中间：Deadline intelligence + CPA workflow。

我们的第一批用户会是 40 到 150 个客户规模的小型 CPA firm。这个群体痛点足够强，但又没有大事务所那种完整的内部合规团队。

GTM 上，我们不打算一开始就做泛广告。更合理的是 concierge onboarding：帮他们导入客户表，第一周就把 Work queue 清出来，让用户马上看到“我不用再维护 Excel 了”。

## 9. 当前完成度

目前我们已经不是只有前端 demo。

这个版本已经部署到线上。Demo 结束后，我们会把体验链接、测试 CSV 和 GitHub repo 发到聊天框。非技术同学可以直接打开产品体验 import、work queue 和 rule review；技术同学也可以看代码、API、CLI、测试数据和文档。

已经实现的部分包括：

客户导入：CSV 上传、preview、apply、AI mapping、新客户创建、已有客户更新。

Work board：Work now、Blocked、Needs review、Overdue、Archive、extension、client follow-up。

官方规则：CA / TX / NY 的 source sync、official source、before / after diff、affected clients、Review apply。

AI 与 API：Ask streaming、AI import mapping、AI follow-up draft、notification preview，以及 dashboard payload。

CLI 和后端：import、client、deadline、task、notice、source、notify、export 等命令都已经有基础能力。

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
