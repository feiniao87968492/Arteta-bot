import base64

import pytest
from fastapi.testclient import TestClient

from dashboard.api.main import create_app
from dashboard.api.security import create_access_token


def _auth_headers(monkeypatch):
    monkeypatch.setenv("DASHBOARD_SECRET_KEY", "unit-test-secret")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "unit-test-deepseek")
    token = create_access_token({"sub": "admin"})
    return {"Authorization": "Bearer " + token}


def test_bot_chat_endpoint_returns_reply_and_verify_hint(monkeypatch):
    async def fake_reply(self, message, group_id, user_id, nickname, images=None):
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

    monkeypatch.setattr("dashboard.api.services.bot_chat_service.BotChatService.reply", fake_reply)
    client = TestClient(create_app())

    response = client.post(
        "/api/bot-chat/messages",
        json={"message": "塔子，今天训练怎么样？", "group_id": "g1", "user_id": "u1", "nickname": "测试球员"},
        headers=_auth_headers(monkeypatch),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["reply"] == "这是网页更衣室回复"
    assert data["reply_format"] == "image"
    assert data["reply_image"].startswith("data:image/png;base64,")
    assert data["group_id"] == "g1"
    assert data["verify_hints"] == ["chat", "memory", "render"]


def test_bot_chat_endpoint_rejects_empty_message(monkeypatch):
    client = TestClient(create_app())

    response = client.post(
        "/api/bot-chat/messages",
        json={"message": "   "},
        headers=_auth_headers(monkeypatch),
    )

    assert response.status_code == 400


@pytest.mark.anyio
async def test_bot_chat_service_uses_tool_loop_and_strips_favor_marker(monkeypatch, tmp_path):
    monkeypatch.setenv("ARTETA_DB_PATH", str(tmp_path / "arsenal_data.db"))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "unit-test-deepseek")

    async def fake_tool_loop(messages):
        assert messages[-1] == {"role": "user", "content": "你好"}
        assert "当前提问球员：测试球员" in messages[0]["content"]
        return "信任过程是每天训练出来的。\n【好感度+】"

    class FakeMemoryStore:
        def query_memories(self, group_id, text):
            return ["旧记忆：喜欢训练"]

        def add_memory(self, group_id, user_id, user_msg, assistant_reply, nickname="", aliases=None):
            self.saved = (group_id, user_id, user_msg, assistant_reply, nickname)

    def fake_needs_html_render(text):
        return False

    def fake_text_to_tactical_board(text):
        assert "信任过程是每天训练出来的。" in text
        return b"normal-chat-png"

    monkeypatch.setattr("dashboard.api.services.bot_chat_service.run_tool_loop", fake_tool_loop)
    monkeypatch.setattr("dashboard.api.services.bot_chat_service.needs_html_render", fake_needs_html_render)
    monkeypatch.setattr("dashboard.api.services.bot_chat_service.text_to_tactical_board", fake_text_to_tactical_board)
    monkeypatch.setattr("dashboard.api.services.bot_chat_service.memory_store", FakeMemoryStore())

    from dashboard.api.services.bot_chat_service import BotChatService

    result = await BotChatService().reply("你好", "dashboard", "dashboard-user", "测试球员")

    assert result["reply"] == "信任过程是每天训练出来的。"
    assert result["reply_format"] == "image"
    assert result["reply_image"] == "data:image/png;base64," + base64.b64encode(b"normal-chat-png").decode("ascii")
    assert result["favor_delta"] > 0
    assert result["verify_hints"] == ["chat", "memory", "render"]


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


@pytest.mark.anyio
async def test_bot_chat_service_describes_uploaded_images(monkeypatch, tmp_path):
    monkeypatch.setenv("ARTETA_DB_PATH", str(tmp_path / "arsenal_data.db"))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "unit-test-deepseek")

    captured_messages = {}

    async def fake_tool_loop(messages):
        captured_messages["messages"] = messages
        return "看了你这张白板，理解了。"

    async def fake_describe(data_url):
        return "这是一张测试图片"

    class FakeMemoryStore:
        def query_memories(self, group_id, text):
            return []

        def add_memory(self, group_id, user_id, user_msg, assistant_reply, nickname="", aliases=None):
            captured_messages["memory_user_msg"] = user_msg

    def fake_needs_html_render(text):
        return False

    def fake_text_to_tactical_board(text):
        return b"img-chat-png"

    monkeypatch.setattr("dashboard.api.services.bot_chat_service.run_tool_loop", fake_tool_loop)
    monkeypatch.setattr("dashboard.api.services.bot_chat_service.needs_html_render", fake_needs_html_render)
    monkeypatch.setattr("dashboard.api.services.bot_chat_service.text_to_tactical_board", fake_text_to_tactical_board)
    monkeypatch.setattr("dashboard.api.services.bot_chat_service.memory_store", FakeMemoryStore())
    monkeypatch.setattr("dashboard.api.services.bot_chat_service._analyze_image_base64", fake_describe)

    from dashboard.api.services.bot_chat_service import BotChatService

    one_pixel_png = base64.b64encode(b"\x89PNG\r\n\x1a\n").decode("ascii")
    data_url = "data:image/png;base64," + one_pixel_png
    result = await BotChatService().reply("看看这个", "g-img", "u-img", "图片球员", images=[data_url])

    assert result["reply"] == "看了你这张白板，理解了。"
    user_content = captured_messages["messages"][-1]["content"]
    assert "看看这个" in user_content
    assert "【用户发送的图片内容】：这是一张测试图片" in user_content
    assert "这是一张测试图片" in captured_messages["memory_user_msg"]


def test_bot_chat_endpoint_rejects_invalid_image(monkeypatch):
    client = TestClient(create_app())

    response = client.post(
        "/api/bot-chat/messages",
        json={"message": "你好", "images": ["not-a-data-url"]},
        headers=_auth_headers(monkeypatch),
    )

    assert response.status_code == 400


def test_bot_chat_endpoint_accepts_image_only_request(monkeypatch):
    async def fake_reply(self, message, group_id, user_id, nickname, images=None):
        assert images and images[0].startswith("data:image/png;base64,")
        return {
            "reply": "图已收到",
            "reply_format": "image",
            "reply_image": "data:image/png;base64," + base64.b64encode(b"png").decode("ascii"),
            "group_id": group_id,
            "user_id": user_id,
            "nickname": nickname,
            "favor_delta": 0,
            "favor_level": "青训生",
            "favor": 0,
            "verify_hints": ["chat", "memory", "render"],
        }

    monkeypatch.setattr("dashboard.api.services.bot_chat_service.BotChatService.reply", fake_reply)
    client = TestClient(create_app())

    one_pixel_png = base64.b64encode(b"\x89PNG\r\n\x1a\n").decode("ascii")
    response = client.post(
        "/api/bot-chat/messages",
        json={"message": "", "images": ["data:image/png;base64," + one_pixel_png]},
        headers=_auth_headers(monkeypatch),
    )

    assert response.status_code == 200
    assert response.json()["data"]["reply"] == "图已收到"
