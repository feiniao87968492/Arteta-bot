# 引用消息链提取 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single-layer quote handling in `process_chat()` with a recursive `fetch_quoted_chain()` that extracts up to 3 layers of quoted message chain and passes it as context to the LLM.

**Architecture:** Add a single async recursive function `fetch_quoted_chain()` that calls `bot.get_msg()` to walk the reply chain up to depth 2 (3 layers total). Each level extracts sender info + text content, skipping image/voice segments. The formatted chain is inserted into the system prompt's background section.

**Tech Stack:** Python 3.8+, NoneBot2, OneBot V11 protocol

**Modifies:** `plugins/arteta_chat.py` — replace lines 401-424 with new recursive function + updated caller

---

### Task 1: Add `fetch_quoted_chain()` function and update `process_chat()`

**Files:**
- Modify: `plugins/arteta_chat.py` — replace lines 401-424, add new function before `process_chat()`

- [ ] **Step 1: Remove old quoted_text block and add `fetch_quoted_chain` function**

Replace lines 401-424 (the old `quoted_text` detection loop) with a new recursive function placed just above `process_chat()`, and update the call site in `process_chat()`.

Old code to remove (lines 401-424):
```python
    # 检测引用回复：如果消息引用了某条历史消息，获取被引用的内容
    quoted_text = ""
    for seg in event.get_message():
        if seg.type == "reply":
            reply_id = seg.data.get("id")
            if reply_id:
                try:
                ...
                except Exception as e:
                    quoted_text = f"\n[引用消息获取失败：{e}]"
            break
```

Add this new function after line 391 (after `init_db_safely()` and before `process_chat()`):
```python
# --- 递归引用消息链提取 ---
async def fetch_quoted_chain(bot: Bot, message_id: int, depth: int = 0) -> str:
    """递归提取引用消息链，最多 3 层（depth 0, 1, 2）。返回由旧到新的缩进格式文本。"""
    indent = "  " * depth
    prefix = "原始消息" if depth == 0 else "↳"
    try:
        msg_data = await bot.get_msg(message_id=message_id)
        sender = msg_data.get("sender", {})
        sender_name = sender.get("card") or sender.get("nickname") or "未知"
        sender_qq = sender.get("user_id", "")

        # 提取纯文本段，跳过图片/语音等
        raw_msg = msg_data.get("message", [])
        if isinstance(raw_msg, list):
            text_parts = [
                s.get("data", {}).get("text", "")
                for s in raw_msg if s.get("type") == "text"
            ]
            text_content = "".join(text_parts).strip()
        else:
            text_content = str(raw_msg).strip()

        if not text_content:
            text_content = "[仅含非文本内容]"

        current_line = f"{indent}{prefix} {sender_name}({sender_qq})：{text_content}"

        # 检测嵌套引用
        nested_text = ""
        for seg in raw_msg if isinstance(raw_msg, list) else []:
            if seg.get("type") == "reply" and depth < 2:
                nested_id = seg.get("data", {}).get("id")
                if nested_id:
                    nested_text = await fetch_quoted_chain(bot, int(nested_id), depth + 1)
                break

        if nested_text:
            return f"{nested_text}\n{current_line}"
        return current_line

    except Exception as e:
        return f"{indent}{prefix} [消息获取失败：{e}]"
```

- [ ] **Step 2: Update the call site in `process_chat()`**

Replace the old `quoted_text` block (lines 401-424) with:
```python
    # 检测引用回复链：递归提取最多 3 层引用消息
    quoted_text = ""
    for seg in event.get_message():
        if seg.type == "reply":
            reply_id = seg.data.get("id")
            if reply_id:
                quoted_text = "\n\n【引用消息链（由旧到新）】：\n" + \
                    await fetch_quoted_chain(bot, int(reply_id))
            break
```

And update line 451 to include `quoted_text` in the prompt. This line doesn't need to change — it already interpolates `{quoted_text}`. But verify it's still there:
```python
    final_prompt = f"{ARTETA_PROMPT}\n\n【背景信息供参考，别照本宣科】：\n{intel_section}{quoted_text}\n当前提问球员：{nickname}，身份：{lvl}，当前信任度：{fav}。\n"
```

- [ ] **Step 3: Verify the change compiles**

Run: `python -c "import plugins.arteta_chat"` (activate venv first)
Expected: No import errors

- [ ] **Step 4: Manual test plan — Start the bot and test**

1. Start bot: `python bot.py`
2. In a QQ group, send a test chain:
   - User A sends "我觉得阿森纳今年能夺冠"
   - User B replies to A: "同意，萨卡状态很好"
   - User C replies to B, with "A 分析一下"
3. Verify the bot responds with analysis that references all 3 layers of the chain

- [ ] **Step 5: Commit**

```bash
git add plugins/arteta_chat.py docs/superpowers/specs/2026-04-26-quoted-chain-design.md docs/superpowers/plans/2026-04-26-quoted-chain-plan.md
git commit -m "feat: recursive quoted message chain extraction (max 3 layers)"
```
