# Dashboard Bot Image Replies Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Dashboard bot chat display the same rendered PNG-style robot replies as QQ group chat, including command-style entries such as `/算法`.

**Architecture:** Keep Dashboard as a FastAPI + React feature, but reuse the existing Arteta rendering pipeline from `plugins.arteta_render`. The API continues returning text for memory, audit, and fallback, and adds a PNG data URL that the React transcript renders as an image.

**Tech Stack:** Python 3.8-compatible FastAPI service code, existing PIL/Playwright renderer, pytest, React + TypeScript.

---

## File Map

- Modify `dashboard/api/services/bot_chat_service.py`
  - Add base64 image response support.
  - Add a small command dispatcher for `/算法`, `算法`, `/代码`, etc.
  - Reuse `plugins.arteta_chat.call_algo_llm` and `plugins.arteta_render` rendering helpers.
- Modify `dashboard/web/src/pages/BotChatPage.tsx`
  - Extend response and transcript types with optional image data.
  - Render assistant images before text fallback.
- Modify `tests/dashboard/test_bot_chat.py`
  - Cover normal chat image rendering.
  - Cover `/算法` command routing and image rendering.
- Modify `docs/dev/developer-dashboard.md`
  - Document that bot chat replies are rendered as PNG images and text remains as fallback.

---

### Task 1: Add failing backend tests for rendered replies

**Files:**
- Modify: `tests/dashboard/test_bot_chat.py`

- [ ] **Step 1: Add imports used by assertions**

Add this import near the top if not already present:

```python
import base64
```

- [ ] **Step 2: Update endpoint fake reply shape**

In `test_bot_chat_endpoint_returns_reply_and_verify_hint`, change the fake result to include image fields:

```python
async def fake_reply(self, message, group_id, user_id, nickname):
    return {
        "reply": "这是网页更衣室回复",
        "reply_format": "image",
        "reply_image": "data:image/png;base64," + base64.b64encode(b"png-bytes").decode("ascii"),
        "group_id": group_id,
        "user_id": user_id,
        "nickname": nickname,
        "favor_delta": 0,
        "favor_level": "青训生",
        "favor": 0,
        "verify_hints": ["chat", "memory", "render"],
    }
```

Then assert:

```python
assert data["reply_format"] == "image"
assert data["reply_image"].startswith("data:image/png;base64,")
assert data["verify_hints"] == ["chat", "memory", "render"]
```

- [ ] **Step 3: Update normal chat service test expectations**

In `test_bot_chat_service_uses_tool_loop_and_strips_favor_marker`, monkeypatch rendering before importing/using `BotChatService`:

```python
def fake_needs_html_render(text):
    return False

def fake_text_to_tactical_board(text):
    assert "信任过程是每天训练出来的。" in text
    return b"normal-chat-png"

monkeypatch.setattr("dashboard.api.services.bot_chat_service.needs_html_render", fake_needs_html_render)
monkeypatch.setattr("dashboard.api.services.bot_chat_service.text_to_tactical_board", fake_text_to_tactical_board)
```

Then assert:

```python
assert result["reply_format"] == "image"
assert result["reply_image"] == "data:image/png;base64," + base64.b64encode(b"normal-chat-png").decode("ascii")
assert result["verify_hints"] == ["chat", "memory", "render"]
```

- [ ] **Step 4: Add `/算法` service test**

Append this test:

```python
@pytest.mark.anyio
async def test_bot_chat_service_routes_algo_command_to_rendered_image(monkeypatch, tmp_path):
    monkeypatch.setenv("ARTETA_DB_PATH", str(tmp_path / "arsenal_data.db"))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "unit-test-deepseek")

    async def fake_algo_llm(system_prompt, user_text):
        assert "技术指导" in system_prompt
        assert user_text == "写一个二分查找"
        return "用二分，把区间每次砍半。\n```python\ndef search():\n    return 1\n```"

    def fake_needs_html_render(text):
        assert "```python" in text
        return True

    async def fake_html_to_image(text):
        assert "```python" in text
        return b"algo-png"

    class FakeMemoryStore:
        def initialize(self):
            pass

        def query_memories(self, group_id, text):
            return []

        def add_memory(self, group_id, user_id, user_msg, assistant_reply, nickname="", aliases=None):
            raise AssertionError("algorithm command should not write normal chat memory")

    monkeypatch.setattr("dashboard.api.services.bot_chat_service.call_algo_llm", fake_algo_llm)
    monkeypatch.setattr("dashboard.api.services.bot_chat_service.needs_html_render", fake_needs_html_render)
    monkeypatch.setattr("dashboard.api.services.bot_chat_service.html_to_image", fake_html_to_image)
    monkeypatch.setattr("dashboard.api.services.bot_chat_service.memory_store", FakeMemoryStore())

    from dashboard.api.services.bot_chat_service import BotChatService

    result = await BotChatService().reply("/算法 写一个二分查找", "dashboard", "dashboard-user", "测试球员")

    assert result["reply"] == "用二分，把区间每次砍半。\n```python\ndef search():\n    return 1\n```"
    assert result["reply_format"] == "image"
    assert result["reply_image"] == "data:image/png;base64," + base64.b64encode(b"algo-png").decode("ascii")
    assert result["favor_delta"] == 0
    assert result["verify_hints"] == ["chat", "render"]
```

- [ ] **Step 5: Run backend tests and verify failure**

Run:

```bash
python -m pytest tests/dashboard/test_bot_chat.py -v
```

Expected before implementation: failures mentioning missing `reply_format`, missing `reply_image`, or missing monkeypatch targets in `dashboard.api.services.bot_chat_service`.

---

### Task 2: Implement backend rendered image response

**Files:**
- Modify: `dashboard/api/services/bot_chat_service.py`

- [ ] **Step 1: Add imports**

Add these imports:

```python
import base64

from plugins.arteta_chat import call_algo_llm
from plugins.arteta_render import html_to_image, needs_html_render, text_to_tactical_board
```

Keep Python 3.8-compatible typing; do not use `dict[str, object]` or `str | None`.

- [ ] **Step 2: Add command prefix constant**

Near `FAVOR_LEVEL_THRESHOLDS`, add:

```python
ALGO_COMMAND_PREFIXES = ("/算法", "算法", "/代码", "代码", "/leetcode", "leetcode", "/战术演练", "战术演练", "/算法题", "算法题", "/amath", "amath", "/物理", "物理", "/数学", "数学", "/计算", "计算")
```

- [ ] **Step 3: Add image data helper methods inside `BotChatService`**

Add methods before `reply()`:

```python
    def _image_data_url(self, img_bytes: bytes) -> str:
        return "data:image/png;base64," + base64.b64encode(img_bytes).decode("ascii")

    async def _render_reply_image(self, answer: str) -> str:
        if needs_html_render(answer):
            html_answer = answer.replace("[red]", '<span class="arsenal-red">')
            html_answer = html_answer.replace("[/red]", "</span>")
            html_answer = html_answer.replace("[blue]", '<span class="arsenal-blue">')
            html_answer = html_answer.replace("[/blue]", "</span>")
            try:
                img_bytes = await html_to_image(html_answer)
            except Exception:
                img_bytes = text_to_tactical_board(answer)
        else:
            img_bytes = text_to_tactical_board(answer)
        return self._image_data_url(img_bytes)

    def _extract_command_text(self, message: str, prefixes: Tuple[str, ...]) -> Optional[str]:
        stripped = message.strip()
        for prefix in prefixes:
            if stripped.lower().startswith(prefix.lower()):
                return stripped[len(prefix):].strip()
        return None
```

- [ ] **Step 4: Add algorithm command handler inside `BotChatService`**

Add before `reply()`:

```python
    async def _reply_algo(self, clean_message: str, clean_group_id: str, clean_user_id: str, clean_nickname: str) -> Dict[str, object]:
        raw_text = self._extract_command_text(clean_message, ALGO_COMMAND_PREFIXES)
        if raw_text is None:
            raise ValueError("not an algorithm command")
        if not raw_text:
            answer = "把你需要解决的问题写在白板上！"
        else:
            algo_prompt = (
                "【技术指导】对方提交了技术问题，用教练指导球员口头说话的方式解答。\n"
                "【数学公式硬性规定】短公式/行内公式用单个 $ 包裹（如 $f(x) = x^2$），"
                "长公式/独立公式用双 $$ 包裹（如 $$\\int_a^b f(x)dx$$、$$\\frac{{dy}}{{dx}}$$）。"
                "这是死命令，不遵守会让球员看不懂战术板！\n"
                "【代码硬性规定】如果涉及代码，用 ``` 代码块包裹展示。\n"
                "绝对不要加小标题和列表符：\n" + raw_text
            )
            answer = await call_algo_llm(algo_prompt, raw_text)
        reply_image = await self._render_reply_image(answer)
        return {
            "reply": answer,
            "reply_format": "image",
            "reply_image": reply_image,
            "group_id": clean_group_id,
            "user_id": clean_user_id,
            "nickname": clean_nickname,
            "favor_delta": 0,
            "favor_level": "青训生",
            "favor": 0,
            "verify_hints": ["chat", "render"],
        }
```

- [ ] **Step 5: Route algorithm commands at the start of `reply()`**

After computing `clean_message`, `clean_group_id`, `clean_user_id`, and `clean_nickname`, add:

```python
        if self._extract_command_text(clean_message, ALGO_COMMAND_PREFIXES) is not None:
            return await self._reply_algo(clean_message, clean_group_id, clean_user_id, clean_nickname)
```

- [ ] **Step 6: Add image fields to normal chat return**

Before the final `return` in normal chat, add:

```python
        rendered_answer = answer
        if favor_delta > 0:
            rendered_answer += "\n\n[red]【信任度上升{}点】[/red]".format(abs(favor_delta))
        elif favor_delta < 0:
            rendered_answer += "\n\n[red]【信任度下降{}点】[/red]".format(abs(favor_delta))
        else:
            rendered_answer += "\n\n[red]【信任度无变化】[/red]"
        reply_image = await self._render_reply_image(rendered_answer)
```

Then include in the return object:

```python
            "reply_format": "image",
            "reply_image": reply_image,
            "verify_hints": ["chat", "memory", "render"],
```

- [ ] **Step 7: Run backend tests**

Run:

```bash
python -m pytest tests/dashboard/test_bot_chat.py -v
```

Expected: all tests in this file pass.

---

### Task 3: Update frontend transcript to display returned images

**Files:**
- Modify: `dashboard/web/src/pages/BotChatPage.tsx`

- [ ] **Step 1: Extend TypeScript types**

Change `ChatResponse` to include:

```typescript
  reply_format: 'image' | 'text';
  reply_image?: string;
```

Change `ChatLine` to include:

```typescript
  image?: string;
```

- [ ] **Step 2: Store assistant image in transcript**

In the assistant line object inside `setLines`, add:

```typescript
          image: result.reply_image,
```

- [ ] **Step 3: Render image before text fallback**

Replace:

```tsx
            <p>{line.text}</p>
```

with:

```tsx
            {line.image ? <img className="chat-rendered-image" src={line.image} alt={line.text || '阿尔特塔回复'} /> : <p>{line.text}</p>}
```

- [ ] **Step 4: Run frontend build**

Run:

```bash
npm --prefix dashboard/web run build
```

Expected: build completes without TypeScript errors.

---

### Task 4: Add minimal CSS for rendered image replies

**Files:**
- Modify: `dashboard/web/src/styles.css`

- [ ] **Step 1: Add image styling near chat bubble styles**

Add:

```css
.chat-rendered-image {
  display: block;
  max-width: 100%;
  border-radius: 16px;
  border: 1px solid rgba(255, 255, 255, 0.16);
  background: rgba(255, 255, 255, 0.04);
}
```

- [ ] **Step 2: Re-run frontend build**

Run:

```bash
npm --prefix dashboard/web run build
```

Expected: build completes without CSS or TypeScript errors.

---

### Task 5: Update Dashboard developer docs

**Files:**
- Modify: `docs/dev/developer-dashboard.md`

- [ ] **Step 1: Update feature list**

Add a bullet under 功能模块:

```markdown
- Bot Chat：在 Dashboard 后端调用阿尔特塔对话/命令链路，返回文本 fallback 与 PNG data URL；前端优先显示与 QQ 群聊一致的渲染图片。
```

- [ ] **Step 2: Update verification section**

Add:

```markdown
机器人对话渲染测试：

```bash
python -m pytest tests/dashboard/test_bot_chat.py -v
npm --prefix dashboard/web run build
```
```

---

### Task 6: Final verification

**Files:**
- Verify only; no file edits unless a prior test exposes a defect.

- [ ] **Step 1: Run backend dashboard tests**

Run:

```bash
python -m pytest tests/dashboard -v
```

Expected: dashboard tests pass.

- [ ] **Step 2: Run frontend build**

Run:

```bash
npm --prefix dashboard/web run build
```

Expected: build passes.

- [ ] **Step 3: Manual run if environment allows**

Run API:

```bash
python -m uvicorn dashboard.api.main:app --reload --port 8765
```

Run frontend:

```bash
npm --prefix dashboard/web run dev
```

Open the Dashboard, send `塔子，今天训练怎么样？` and `/算法 写一个二分查找`. Expected: assistant replies render as images in the transcript.

---

## Self-Review

- Spec coverage: normal chat image rendering, command-style `/算法` support, frontend image display, tests, and docs are all mapped to tasks.
- Placeholder scan: no TBD/TODO/fill-in placeholders remain.
- Type consistency: backend uses `reply_format` and `reply_image`; frontend uses the same names; tests assert the same response shape.
- Python compatibility: plan uses `Dict`, `Optional`, and `Tuple` imports already present in `bot_chat_service.py`, and avoids Python 3.9+ generic syntax.
