# 开发者功能验证

`tools/verify_features.py` 是本地开发验收脚本，用来快速检查当前实现的关键链路是否还能工作。它偏向安全、离线、可复现的开发者验证，不替代完整的 NoneBot + NapCat 实机联调。

## 用途

- 验证渲染链路：PIL 战术板、HTML/Markdown 图片渲染、引用图预处理。
- 验证数据链路：SQLite、ChromaDB 向量记忆、本地知识库查询。
- 验证对话与命令基础健康状态：关键词判断、好感度标记、插件导入、帮助文本和点赞额度 helper。
- 可选验证在线依赖配置与连通性，同时默认阻止真实 QQ 副作用。

## 模式

- 默认模式：运行 `core` suite，离线、无真实 QQ 副作用。
- `--suite <name>`：选择 suite，可重复传入；支持 `core`、`render`、`memory`、`chat`、`commands`、`online`、`all`。
- `--case <name>`：只运行已选 suite 中的指定 case，可重复传入。
- `--online`：在所选 suite 后追加 `online` suite，用于外部依赖检查。
- `--allow-side-effects`：仅解除在线 suite 的副作用门禁提示；当前脚本没有自动执行真实 QQ 操作。
- `--list-suites`：列出可用 suite 和 case。
- `--json-only`：只输出 JSON 摘要，适合脚本调用。

## 常用命令

```bash
python tools/verify_features.py
python tools/verify_features.py --suite all
python tools/verify_features.py --suite core --online
python tools/verify_features.py --suite render --case html_to_image
python tools/verify_features.py --list-suites
```

## 输出

每次运行会创建 `artifacts/verify/<timestamp>/`，包含：

- `report.json`：机器可读报告，包含 suite、case、状态、耗时、产物路径和详情。
- `summary.txt`：人工可读摘要。
- `artifacts/`：图片、文本、SQLite/Chroma 临时数据、错误 traceback 等 case 产物。

状态含义：

- `passed`：case 验证通过。
- `failed`：case 执行失败或结果不符合预期，命令退出码为 1。
- `skipped`：缺少可选配置或当前环境无法安全执行。
- `manual_required`：需要人工明确允许或实机验证；不会自动执行真实 QQ 副作用。

## 隔离与环境前提

- 验证脚本会在每次运行前自动设置隔离路径，避免默认写入正式开发数据：
  - `ARTETA_DB_PATH`
  - `ARTETA_CHROMA_DIR`
  - `ARTETA_SWEARS_FILE`
- `render/html_to_image` 依赖 Playwright Chromium；未安装时该 case 会标记为 `skipped`。
- 如需实际验证 HTML/Markdown 图片渲染，先执行：

```bash
python -m playwright install chromium
```

## 建议使用方式

- 日常修改后先跑：`python tools/verify_features.py`。
- 修改渲染、记忆、命令等局部功能时，优先跑对应 suite 或 case。
- 发版前跑：`python tools/verify_features.py --suite all`，并按需追加 `--online` 检查外部依赖。
- 遇到失败时先查看终端输出，再打开本次 `report.json`、`summary.txt` 和相关 artifact。常见环境阻塞包括缺少 `chromadb`、Playwright Chromium 未安装、在线 API Key 未配置。
