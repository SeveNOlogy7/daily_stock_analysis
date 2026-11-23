# PR #2440 大盘复盘结构化输出：亮/暗色前后对比图（第 2 轮 / r2）

本分支只存放可视证据，**不属于 PR diff**（PR 分支：`feat/market-review-enhance-1584`）。上一轮证据在 `evidence/pr-2440`。

## 对比对象

- **BEFORE**：本轮收口前的 PR head `ecbcd826`
- **AFTER**：4 项正确性修复 + 卡片排版打磨后的 `00b8a2d0`

| OR-COR | 内容 | commit |
| --- | --- | --- |
| `OR-COR-91e5bc73` | 移除无真实行情支撑的均线状态列（`ma_status`） | `ee3bbcbe` |
| `OR-COR-f4725a90` | 指数点评按内部代码挂载，兼容行情符号别名与名称回退 | `e3d915b8` |
| `OR-COR-c81484a4` | 指数行情缺失时宽度兜底不再声称与指数表现匹配 | `aff45add` |
| `OR-COR-50abc372` | 结构化文本清洗剔除未配对的 UTF-16 代理码点 | `006147a9` |
| — | 卡片排版打磨（间距/层级/行高，信息架构不变） | `00b8a2d0` |

## 文件

| 文件 | 说明 |
| --- | --- |
| `market-review-compare-light.png` | 亮色：左 BEFORE / 右 AFTER |
| `market-review-compare-dark.png` | 暗色：左 BEFORE / 右 AFTER |
| `market-review-before-{light,dark}.png` | BEFORE 单页全页截图（1280px 视口，DPR 2） |
| `market-review-after-{light,dark}.png` | AFTER 单页全页截图 |
| `market-review-{before,after}-{light,dark}.html` | 自包含 HTML：组件真实 DOM + **各自版本** `vite build` 编译 CSS 内联，浏览器离线直接打开即为页面观感 |

## 生成方式（可复现）

1. 用 `git archive` 把 BEFORE（`ecbcd826`）与 AFTER（`00b8a2d0`）两份 `apps/dsa-web` 导出到仓库外的临时目录，共用同一份 `node_modules`；各自执行 `vite build` 得到**本版本**的编译 CSS（输出目录重定向到临时目录，不触碰仓库的 `static/`）。
2. 在各自副本内用 vitest + @testing-library/react 渲染真实的 `MarketReviewReportView`（固定 fixture），关键 DOM 断言通过后写出自包含 HTML。
3. 用 Playwright 驱动系统 Edge headless（1280×900 视口，DPR 2，fullPage）截图，Pillow 拼成左右对比图。

说明：BEFORE / AFTER 使用同一份 fixture；fixture 的 `indices` 带 `maStatus`，所以 BEFORE 显示“均线状态”列，AFTER 不再渲染该列（`OR-COR-91e5bc73`）。同一页面高度 2161px → 1903px。

本地无完整运行栈/数据环境，以上为组件级渲染证据（与第 1 轮口径一致）。
