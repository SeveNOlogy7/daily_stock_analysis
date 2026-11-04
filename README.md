# evidence/pr-2429 — 设置页可视证据（PR #2429 / issue #2143）

TDX 本地 vipdoc 数据源三个设置字段（`data_source` 分类）的 Web 设置页渲染证据。
本分支为**孤儿分支**，仅含证据文件，与 PR 分支 `feat/local-cache-datasource-2143` 完全分离，不进入 PR diff。

## 文件

| 文件 | 内容 |
| --- | --- |
| `evidence/settings-data-source-tdx-local.png` | 设置页「数据源」区块截图：同时可见 `TDX_LOCAL_PATH`（D:\new_tdx\vipdoc）、`TDX_LOCAL_PRIORITY`（0）、`TDX_LOCAL_MAX_STALE_DAYS`（10）三字段及相邻 Pytdx 字段 |
| `evidence/settings-data-source-tdx-local.html` | 上图对应自包含 HTML（内联编译后生产 CSS） |
| `evidence/settings-data-source-tdx-local-help.png` | `TDX_LOCAL_PATH` 设置帮助弹窗（zh 帮助：用途/取值说明/配置样例/影响范围/注意事项） |
| `evidence/settings-data-source-tdx-local-help.html` | 上图对应自包含 HTML |

## 渲染方式

1. `npx vite build`（apps/dsa-web）产出生产 Tailwind CSS；
2. 临时 vitest 用例挂载真实 `SettingsPage`（保留真实 `SettingsField` / `SettingsSectionCard` / `SettingsCategoryNav`，仅 mock `useSystemConfig` 注入 `data_source` fixture，字段 schema 与 `config_registry.py` 一致）；
3. 断言三字段取值后序列化自包含 HTML；帮助弹窗变体为点击 `TDX_LOCAL_PATH` 的「查看配置说明」按钮后序列化 `document.body`；
4. Playwright + 系统 Edge headless 截图（1440 宽、deviceScaleFactor 2、fullPage）。

生成于 2026-11-05，对应 PR #2429 head 747aca74。
