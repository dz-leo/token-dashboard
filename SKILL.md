---
name: token-dashboard
description: 生成 WorkBuddy Token 消耗看板（单文件离线 HTML，含 KPI / 省钱体检 / 使用习惯画像 / 日历热力图 / 0-24 时模型分布 / 每日模型比例 / 工作空间-会话-请求三级下钻，按最新牌价与峰谷分时计价）。当用户想查看自己的 token 用量、消耗统计、成本审计时使用，例如"看看我的 token 用量""token 审计""生成本月消耗看板"。
---

# Token 消耗看板

为本机 WorkBuddy 生成一张请求级真实 usage 的 Token 消耗看板（单文件自包含 HTML，离线可看，无外部依赖）。

## 执行步骤

1. **确认数据目录**：默认 `~/.workbuddy/projects`（Windows / macOS / Linux 通用）。若用户想看其他目录的日志，用 `--projects` 参数传入。
2. **选择 Python**：优先使用平台的托管 Python 运行时；没有则用系统 `python3`（Windows 为 `python`）。生成脚本仅依赖标准库（3.8+），**无需安装任何依赖**。
3. **运行脚本**（scripts 与 SKILL.md 同目录，用绝对路径调用）：

   ```
   python <skill目录>/scripts/gen_dashboard.py --out <工作区>/token-dashboard.html
   ```

   - 默认输出 `token-dashboard.html` 到当前目录。
   - 数据目录不存在时脚本会报错退出并提示，此时告知用户本机可能未使用过 WorkBuddy。
   - 页面结构与样式在 `scripts/template.html`，价格表在同级 `prices.json`；两者都可用 `--template` / `--prices` 覆盖。

4. **（可选）自检**：改动过模板或价格表后，跑一次端到端校验：

   ```
   python <skill目录>/scripts/verify.py --build
   ```

   它会先生成看板，再校验 JS 语法、价格引擎断言（前缀匹配 / 按日期生效 / 峰谷分时 / 成本计算），并在 Node DOM 桩上跑多窗口与下钻的健壮性冒烟测试。需要 Node.js，仅测试用。

5. **展示结果**：用文件展示工具打开发出的 HTML，并口头汇报关键数字：合计 token、日均、会话/轮次、输入输出比、缓存命中率、预估金额、TOP 模型。

## 看板能力

- KPI：合计 Token / 日均 / 会话 / 轮次 / 输入输出比 / 缓存命中率 / 预估金额（元）/ 价格表核实状态
- **省钱体检**：缓存未命中多付、高峰时段多付、长会话上下文膨胀、几乎无输出的请求——给出「理论上限」而非账单
- **使用习惯画像**：连续使用天数、活跃时段、作息类型（深夜党/上午型/午后型/晚间型）、工作日 vs 周末、会话节奏中位数、主力模型浓度
- 日活热力图（20 分钟粒度）、0–24 时模型山脊图、每日模型用量堆叠柱、单次请求大小分布（50%/90% 分位）
- 工作空间 → 会话 → 单次请求三级下钻（散点 + 明细表）
- 深浅色主题（记忆偏好）、1/3/7/30 天窗口 + 自定义日期区间

## 数据与口径说明

- 数据源：`~/.workbuddy/projects/**/*.jsonl` 中每条记录的 `providerData.rawUsage / usage` 字段（请求级真实 usage，非估算）；深层子代理日志（subagents/agent-*.jsonl）自动归属父会话。
- 会话标题取首条非内部标签的用户消息前 42 字；标题以「非空覆盖空」合并，避免文件遍历顺序影响结果。
- **缓存字段兼容三套流派**：DeepSeek（`prompt_cache_hit_tokens` / `prompt_cache_write_tokens`）、OpenAI（`prompt_tokens_details.cached_tokens`）、Anthropic（`cache_read_input_tokens` / `cache_creation_input_tokens`）。Anthropic 的 `input_tokens` 与缓存读写是**并列**关系，另两家把缓存命中**包含**在 `prompt_tokens` 里——脚本用「base_in < 缓存读+写」自适应判断，不能无脑截断。
- **计价读 `prices.json`**（单位：元 / 百万 token），规则含：最长前缀匹配（不依赖 key 顺序）、`from` 字段控制按日期生效（按**本地时区**解释，厂商公告写的是北京时间）、`peak` 字段控制峰谷分时（如 DeepSeek 高峰 9–12 / 14–18，空闲价为高峰价一半）。
- 价格表缺失或损坏时回退到内置兜底值并在页面显著标注，不中断生成。
- 预估金额按 API 挂牌价估算，订阅套餐用户实付结构不同，**汇报时应说明这是粗略预估**。

## 维护价格表

价格表会过期。新增或调价时改 `prices.json`：给新条目加 `from` 生效时间，不要删旧条目——历史请求要按当时价格计价。核实过的条目置 `verified: true`，页面 KPI 会显示「核实 N/M 条」。

## 注意

- Windows 控制台为 GBK 时脚本已内置 UTF-8 输出保护，若仍乱码不影响 HTML 生成。
- 看板内数据完全来自本机日志，不会外发；生成的是本地文件，不会自动上传。
- 日志时间戳只精确到分钟，因此「单会话活跃时长」不可靠，看板只报**会话跨度中位数**，不报活跃时长。
