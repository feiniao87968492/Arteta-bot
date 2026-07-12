# Arteta Bot Web Access 三轮改造任务书

本文档替代旧版一轮式 `web_access.py` 重构计划。旧版风险判断基本正确，但把安全漏洞修复、只读工具副作用清理、工具协议升级、事实核验能力重写和模块拆分混在一次改动里，回归与回滚成本过高。

执行顺序固定为三轮：

1. Round 1：Web 安全与副作用收口。
2. Round 2：ToolResult 协议与事实核验。
3. Round 3：模块拆分与搜索后端抽象。

每轮必须独立测试、独立提交、更新 devlog，并在需要时部署到 ECS smoke。

---

## 全局约束

### Python 3.8

线上 Python 版本是 3.8。新增代码和文档示例必须使用 3.8 兼容类型写法：

```python
from typing import List, Optional, Set, Tuple

Optional[Set[int]]
List[SearchHit]
Tuple[str, ...]
```

不得使用 Python 3.9/3.10 才稳定支持的内置泛型下标和 union operator 写法，例如内置集合类型直接下标、或用竖线表达可选类型。

每轮至少运行：

```bash
python3.8 -m py_compile plugins/arteta_agent/tools/web_access.py
```

拆分模块后改为编译对应 `plugins/arteta_agent/tools/web/*.py`。

### 现有协议优先

实施前必须以当前代码为准审计：

```text
plugins/arteta_agent/result.py
plugins/arteta_agent/executor.py
plugins/arteta_agent/runtime/runner.py
plugins/arteta_agent/response/artifacts.py
```

当前 `ToolResult` 是 dataclass，字段包括：

```python
ToolResult(
    name,
    permission,
    status,
    content,
    args,
    pending_action_id,
    markers,
    artifacts,
    duration_ms,
    error_code,
)
```

不得凭空使用未存在的接口，例如：

```python
ToolResult.success(...)
ToolResult.error(...)
Artifact(...)
data=...
```

Round 1 可以继续让 Web handler 返回字符串，由 executor 包装成现有 `ToolResult`。Round 2 才设计最小兼容协议扩展。

### SSRF 安全模型

应用层 DNS 校验不是绝对 SSRF 防护，普通流程：

```text
DNS 解析 -> 检查 IP -> httpx 使用 hostname 建连
```

仍存在 DNS rebinding 的检查与连接时间差。

本项目采用三层模型：

1. 应用层 best-effort：URL credentials 拒绝、scheme/port/长度限制、A/AAAA 全量解析、非全局地址拒绝、禁止自动重定向、逐跳重新校验、响应大小与 Content-Type 限制。
2. 连接层强约束：如需要更强保证，再设计自定义 Resolver/Transport、IP pinning、正确 Host/SNI/证书校验。
3. 生产网络边界：ECS、容器或防火墙必须拒绝 RFC1918、loopback、link-local、metadata endpoint、IPv6 ULA 等内部网段 egress。

GrokSearch `web_fetch` 和自建 X Fetch Bridge 是远程代理 SSRF 边界。本地 URL 校验只能保护本机；远程服务也必须有同等级 URL 校验和网络隔离。

---

## Round 1：Web 安全与副作用收口

目标：在不改公开工具名、不拆大模块、不设计新 ToolResult 协议的前提下，把最高风险行为关掉。

范围原则：

* 主要修改 `plugins/arteta_agent/tools/web_access.py` 和直接测试。
* 不新增截图工具。
* 不重写事实核验系统。
* 不拆目录。
* 不改变 `run_agent_loop`、registry、runtime 等核心架构。

### 1. 测试先行

先补两类测试。

Characterization tests 用于固定暂不改变的兼容行为：

```text
web_search 正常返回
grok_search 未配置
web_fetch 普通 HTML
web_fetch X status 路由
fetch_x_post 全部后备失败
verify_recent_claim 无搜索结果
工具注册名称
```

Security acceptance tests 修复前应失败：

```text
域名解析到私网不会发送请求
重定向到私网不会发送第二跳请求
URL credentials 被拒绝
非 80/443 端口被拒绝
自动截图不再写文件或生成 LinkSnapshot marker
schema 额外字段、超长字符串、越界数字被 handler 前拒绝
deadline 不超过 executor timeout
```

建议文件：

```text
tests/test_arteta_agent_web_security.py
tests/test_arteta_agent_web_search.py
tests/test_arteta_agent_web_verification.py
```

### 2. URL 与 SSRF

在原文件中实现 Python 3.8 兼容的 DNS-aware 校验：

```python
@dataclass(frozen=True)
class _ValidatedURL(object):
    url: str
    hostname: str
    port: int
    resolved_ips: Tuple[str, ...]
```

规则：

```text
scheme 只能是 http/https
禁止 username/password
hostname 非空
URL 长度不超过 2048
端口默认只允许 80/443
禁止 localhost、.local、.internal、.lan、单标签主机名
解析全部 A/AAAA
全部 IP 必须是 ip.is_global
禁止私网、回环、链路本地、保留、组播、未指定、共享地址
```

`_fetch_url()` 必须关闭 httpx 的自动重定向，改为逐跳手动处理。每一跳在请求前重新执行 URL 校验和 DNS 校验。测试桩必须证明不安全目标没有收到请求。

### 3. 响应资源限制

当前已有 `_read_limited_response()` 和 `MAX_FETCH_BYTES`。Round 1 不从零重写，只补行为：

* 测试现有流式限制；
* `Content-Length` 明显超限时可提前拒绝；
* 超过读取上限时停止读取，并在返回结构中标记 `truncated=True`；
* 添加 Content-Type 白名单。

默认允许：

```text
text/html
text/plain
application/xhtml+xml
application/json
```

默认拒绝或转交：

```text
application/pdf
image/*
audio/*
video/*
application/octet-stream
archive 类型
```

### 4. 删除自动截图副作用

Round 1 只删除搜索工具的自动截图行为：

```text
web_search 不调用 _grok_source_snapshot_marker
grok_search 不调用 _grok_source_snapshot_marker
verify_recent_claim 不追加 [LinkSnapshotImage: ...]
搜索工具不写 PNG
搜索工具不启动 Playwright
```

不要在本轮新增 `capture_web_snapshot`。截图能力涉及新工具注册、权限、Artifact、安全、配额和清理任务，应作为独立需求。

### 5. 严格 Schema

Web 工具 schema 增加边界：

```text
additionalProperties: false
string minLength/maxLength
integer minimum/maximum
URL 最大长度
freshness enum
```

虽然 registry 当前会自动补 `additionalProperties: false`，工具自身仍应显式声明关键边界，便于模型和审计理解。

校验失败必须发生在 handler 前，不得创建 PendingAction，不得进入权限确认，不得执行 handler。

### 6. Deadline 收口

Round 1 只实现 Web 工具私有预算，不抽通用框架：

```python
class _TimeBudget(object):
    def __init__(self, total_seconds):
        self._deadline = asyncio.get_event_loop().time() + total_seconds

    def remaining(self):
        return max(0.0, self._deadline - asyncio.get_event_loop().time())
```

要求：

* 搜索后备链共享同一个剩余预算；
* 单个后备 timeout 不能超过剩余预算；
* `ToolSpec.timeout_seconds` 必须大于内部预算并留安全余量；
* 超时时稳定返回，不编造成功。

### 7. 最小语义修正

`verify_recent_claim` 本轮只做最小修正：

* 删除“阿根廷、佛得角、世界杯”等具体任务残留硬编码；
* 不再输出“已找到可核查来源”这类过度确定措辞；
* 改为“已找到候选来源，但工具尚未判断该来源支持或反驳该说法”；
* 保持公开工具名 `verify_recent_claim` 不变。

真正的 `support/refute/unclear` 放到 Round 2。

### Round 1 验收

至少运行：

```bash
python -m pytest tests/test_arteta_agent_web_security.py -q
python -m pytest tests/test_arteta_agent_registry.py -q
python -m pytest tests -q
python -m compileall -q plugins tests tools dashboard
```

Python 3.8 环境额外运行：

```bash
python3.8 -m py_compile plugins/arteta_agent/tools/web_access.py
```

---

## Round 2：ToolResult 协议与事实核验

目标：在 Round 1 安全边界稳定后，再升级协议和核验正确性。

### 1. 协议审计

先输出字段流转图，覆盖：

```text
handler return
executor wrapping
runtime observation
provider tool history
response artifact extraction
legacy marker adapter
```

再决定是否需要新增：

```text
ToolResult.data
Artifact 结构
success/error 工厂方法
structured web metadata
```

新增字段必须保持旧字符串 handler 兼容。

### 2. Web 工具逐个迁移

按顺序迁移，不一次切换全部：

```text
web_fetch
web_search
grok_search
fetch_x_post
verify_recent_claim
```

工具正文中的伪造 marker 不得产生 artifact、权限状态或错误状态。

### 3. 事实核验子系统

设计并实现：

```text
SearchHit
PageEvidence
ClaimEvidence
VerificationResult
support/refute/unclear
来源冲突处理
时间有效性
多来源抓取
```

原则：

* 搜索摘要只能作为线索，不能单独得出 supported/refuted；
* 单一普通网页默认 unclear；
* 官方或一手来源可提高置信度；
* 来源冲突返回 unclear；
* 页面正文始终作为不可信数据进入分类器；
* LLM 分类器如果使用，必须 JSON-only、低温、限长、无工具权限。

### 4. 远程 Fetch 隐私边界

调整 `web_fetch`：

```text
本地安全抓取
-> 正文为空、JS 页面或反爬失败
-> 根据策略决定是否使用远程 Fetch
```

默认：

```python
allow_remote_fetch_proxy = False
```

含 `token`、`key`、`signature`、`auth` 等敏感查询参数的 URL 不得发送到 GrokSearch 或 Fetch Bridge。

### Round 2 验收

新增测试至少覆盖：

```text
ToolResult 结构化字段兼容
正文伪造 marker 不生效
官方来源支持 Claim
官方来源反驳 Claim
普通来源不足时 unclear
来源冲突 unclear
搜索摘要不能单独确认
远程代理默认不使用
敏感 URL 不发给远程代理
```

---

## Round 3：模块拆分与搜索后端抽象

目标：行为和协议稳定后，再降低 `web_access.py` 复杂度。

### 1. 目标结构

```text
plugins/arteta_agent/tools/web/
├── __init__.py
├── models.py
├── security.py
├── fetcher.py
├── search_backends.py
├── verification.py
├── source_ranking.py
├── x_reader.py
├── formatting.py
├── registration.py
└── parsers/
    ├── __init__.py
    ├── page.py
    ├── bing.py
    ├── duckduckgo.py
    └── grok.py
```

原 `web_access.py` 保留兼容 re-export：

```python
from .web.registration import register_tools
from .web.handlers import (
    web_search,
    grok_search,
    web_fetch,
    fetch_x_post,
    verify_recent_claim,
)
```

### 2. SearchBackend 抽象

Python 3.8 兼容写法：

```python
class SearchBackend(Protocol):
    name: str

    async def search(
        self,
        query: str,
        max_results: int,
        freshness: str,
        budget: TimeBudget,
    ) -> List[SearchHit]:
        ...
```

实现：

```text
GrokSearchBackend
BingHtmlBackend
DuckDuckGoHtmlBackend
JinaSearchBackend
DDGSBackend
```

### 3. X provenance

X 读取必须区分：

```text
official_api
official_embed
configured_bridge
third_party_mirror
generated_extraction
```

GrokSearch 只能作为读取方式，不得伪造成作者名。

### 4. 日志与可观测性

替换无声吞异常：

```python
except Exception:
    pass
```

为脱敏结构化日志。不得记录 API Key、Cookie、Authorization、完整敏感 URL、全文网页正文或完整用户 prompt。

### Round 3 验收

要求：

```text
web_access.py 只保留兼容入口
模块无明显循环依赖
单模块职责清晰
搜索后端可单测
X provenance 可单测
日志脱敏
所有旧工具名仍可注册
```

---

## 最终验收

完成三轮后运行：

```bash
python -m pytest tests/test_arteta_agent_web_security.py -q
python -m pytest tests/test_arteta_agent_web_search.py -q
python -m pytest tests/test_arteta_agent_web_verification.py -q
python -m pytest tests/test_arteta_agent_x_reader.py -q
python -m pytest tests/test_arteta_agent_runtime.py -q
python -m pytest tests/test_arteta_agent_registry.py -q
python -m pytest tests -q
python -m compileall -q plugins tests tools dashboard
```

部署后 smoke：

```bash
./venv/bin/python tools/verify_features.py --suite chat
./venv/bin/python tools/verify_features.py --suite agent_registry --suite agent_permissions
./venv/bin/python tools/verify_features.py --suite agent_loop
```

最终完成条件：

```text
应用层 SSRF best-effort 防护已测试
生产 egress 要求已记录
搜索 safe_read 无隐式文件写入
Web 工具 schema 有边界
工具状态不依赖正文 marker
事实核验可返回 support/refute/unclear
远程 fetch 默认受策略约束
web_access.py 只剩兼容入口
所有测试与 ECS smoke 通过
```
