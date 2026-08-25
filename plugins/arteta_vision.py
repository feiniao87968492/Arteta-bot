# plugins/arteta_vision.py
# Pure Vision API layer shared by bot, dashboard, and tests.

import base64
import io
import os
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import httpx
from PIL import Image


SILICONFLOW_API_KEY = os.environ.get("SILICONFLOW_API_KEY", "")
SILICONFLOW_VISION_MODEL = "Qwen/Qwen3-VL-32B-Instruct"
DEFAULT_VISION_TIMEOUT = 60.0


@dataclass
class VisionConfig:
    vision_api_key: str = ""
    vision_api_url: str = ""
    vision_model: str = "gpt-4o-mini"
    siliconflow_api_key: str = SILICONFLOW_API_KEY
    siliconflow_model: str = SILICONFLOW_VISION_MODEL
    vision_timeout: float = DEFAULT_VISION_TIMEOUT

    def configured_api_key(self) -> str:
        return self.vision_api_key

    def configured_api_url(self) -> str:
        return self.vision_api_url

    def fallback_api_key(self) -> str:
        return self.siliconflow_api_key

    def fallback_api_url(self) -> str:
        return "https://api.siliconflow.cn"


def detect_image_format(data: bytes) -> str:
    if data.startswith(b"\xff\xd8"):
        return "jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "webp"
    if data.startswith(b"\x00\x00\x01\x00") or data.startswith(b"\x00\x00\x00\x1cftyp"):
        return "heic"
    return "jpeg"


_MAX_IMAGE_DIM = 2048
_JPEG_QUALITY = 85


def _normalize_image_data_url(data_url: str) -> str:
    """Resize oversized images and output a JPEG data URL for predictable API cost."""
    _media_type, b64 = _split_data_url(data_url)
    raw = base64.b64decode(b64)
    img = Image.open(io.BytesIO(raw))
    w, h = img.size
    if max(w, h) <= _MAX_IMAGE_DIM:
        return data_url
    ratio = _MAX_IMAGE_DIM / max(w, h)
    new_size = (int(w * ratio), int(h * ratio))
    img = img.resize(new_size, Image.LANCZOS)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=_JPEG_QUALITY)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _is_anthropic_vision_url(api_url: str) -> bool:
    return api_url.rstrip("/").endswith("/anthropic")


def _is_xiaomi_vision_url(api_url: str) -> bool:
    return "xiaomimimo.com" in api_url


def _split_data_url(data_url: str) -> Tuple[str, str]:
    header, data = data_url.split(",", 1)
    media_type = header[5:].split(";", 1)[0]
    return media_type, data


def _join_vision_api_path(api_url: str, path: str) -> str:
    base_url = api_url.rstrip("/")
    if base_url.endswith("/v1") and path.startswith("/v1/"):
        path = path[3:]
    return f"{base_url}{path}"


def _build_vision_api_request(api_url: str, api_key: str, model: str, data_url: str) -> Tuple[str, Dict[str, str], Dict]:
    base_url = api_url.rstrip("/")
    prompt = "请用中文详细描述这张图片的内容，包括主要对象、场景、文字、表情等信息。"
    if _is_anthropic_vision_url(base_url):
        media_type, image_data = _split_data_url(data_url)
        return (
            _join_vision_api_path(base_url, "/v1/messages"),
            {"x-api-key": api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
            {
                "model": model,
                "messages": [{"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_data}},
                    {"type": "text", "text": prompt},
                ]}],
                "max_tokens": 2048,
            },
        )
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": data_url}},
            {"type": "text", "text": prompt},
        ]}],
    }
    if _is_xiaomi_vision_url(base_url):
        payload["messages"].insert(0, {"role": "system", "content": "You are MiMo, an AI assistant developed by Xiaomi."})
        payload["max_completion_tokens"] = 1024
    else:
        payload["max_tokens"] = 2048
    return (
        _join_vision_api_path(base_url, "/v1/chat/completions"),
        {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        payload,
    )


def _extract_vision_api_response(api_url: str, body: Dict) -> str:
    if _is_anthropic_vision_url(api_url):
        for item in body.get("content", []):
            if item.get("type") == "text" and item.get("text"):
                return item["text"].strip()
        return ""
    message = body["choices"][0]["message"]
    content = (message.get("content") or "").strip()
    if content:
        return content
    return (message.get("reasoning_content") or "").strip()


def _is_error_response(resp: str) -> bool:
    return resp.startswith("[图片识别失败") or resp.startswith("[图片识别异常")


async def _call_vision_api(api_url: str, api_key: str, model: str, data_url: str, timeout: float = DEFAULT_VISION_TIMEOUT) -> str:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            url, headers, payload = _build_vision_api_request(api_url, api_key, model, data_url)
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code == 200:
                return _extract_vision_api_response(api_url, resp.json())
            try:
                body = resp.text[:200]
            except Exception:
                body = "(无法读取响应体)"
            return f"[图片识别失败：HTTP {resp.status_code} body={body}]"
    except Exception as exc:
        print(f"[Vision API Error] {api_url} model={model} {type(exc).__name__}: {exc}")
        return f"[图片识别异常：{type(exc).__name__}: {exc}]"


async def analyze_image_base64(data_url: str, config: Optional[VisionConfig] = None) -> str:
    cfg = config or VisionConfig()
    data_url = _normalize_image_data_url(data_url)

    configured_url = cfg.configured_api_url()
    configured_key = cfg.configured_api_key()
    if configured_url and configured_key:
        result = await _call_vision_api(
            configured_url,
            configured_key,
            cfg.vision_model,
            data_url,
            cfg.vision_timeout,
        )
        if result and not _is_error_response(result):
            return result
        print(f"[Vision] Configured service failed ({result[:200]}), fallback to SiliconFlow")

    fallback_url = cfg.fallback_api_url()
    fallback_key = cfg.fallback_api_key()
    if not fallback_url or not fallback_key:
        return "[图片识别失败（无可用备用 Vision 服务）]"
    fallback = await _call_vision_api(
        fallback_url,
        fallback_key,
        cfg.siliconflow_model,
        data_url,
        cfg.vision_timeout,
    )
    if fallback and not _is_error_response(fallback):
        return fallback
    print(f"[Vision] SiliconFlow also failed: {fallback[:200]}")
    return "[图片识别失败（配置服务和 SiliconFlow 均失败）]"
