# plugins/arteta_image.py
import nonebot
from nonebot import on_command, on_message
from nonebot.rule import startswith
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, MessageSegment
from nonebot.exception import FinishedException
import httpx
import io
import base64
from PIL import Image

driver = nonebot.get_driver()

try:
    config = driver.config.model_dump()
except AttributeError:
    config = driver.config.dict()

IMAGE_API_KEY = str(config.get("image_api_key", "")).strip('"\'')
IMAGE_API_URL = str(config.get("image_api_url", "https://www.boxying.com")).strip('"\'')
IMAGE_MODEL = str(config.get("image_model", "gpt-image-2")).strip('"\'')

draw_cmd = on_command("画图", priority=10, block=True)


def preprocess_reference_image(image_bytes: bytes) -> bytes:
    """转换参考图为 1024x1024 PNG，白底居中补边。"""
    img = Image.open(io.BytesIO(image_bytes))
    sz = max(img.width, img.height)
    sq = Image.new("RGB", (sz, sz), (255, 255, 255))
    sq.paste(img, ((sz - img.width) // 2, (sz - img.height) // 2))
    sq = sq.resize((1024, 1024), Image.LANCZOS)
    buf = io.BytesIO()
    sq.save(buf, format="PNG")
    return buf.getvalue()


@draw_cmd.handle()
async def handle_draw(bot: Bot, event: MessageEvent):
    prompt = event.get_message().extract_plain_text().strip()

    if not prompt:
        await draw_cmd.finish("把你想画的内容写在「画图」后面，比如：画图一只红色的猫")

    await draw_cmd.send("正在生成图片（gpt-image-2），可能需要等待...")

    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(
                f"{IMAGE_API_URL}/v1/images/generations",
                headers={"Authorization": f"Bearer {IMAGE_API_KEY}"},
                json={
                    "model": IMAGE_MODEL,
                    "prompt": prompt,
                    "n": 1,
                    "size": "1024x1024",
                },
            )

            if resp.status_code == 200:
                try:
                    body = resp.json()
                except Exception:
                    await draw_cmd.finish(f"API 返回了非 JSON 内容：{resp.text[:200]}")
                    return
                if "data" not in body or not body["data"]:
                    await draw_cmd.finish(f"API 响应缺少 data 字段：{str(body)[:300]}")
                    return
                item = body["data"][0]

                if "url" in item:
                    img_resp = await client.get(item["url"])
                    if img_resp.status_code == 200:
                        img_bytes = io.BytesIO(img_resp.content)
                    else:
                        await draw_cmd.finish(f"图片下载失败：{img_resp.status_code}")
                        return
                elif "b64_json" in item:
                    img_bytes = io.BytesIO(base64.b64decode(item["b64_json"]))
                else:
                    await draw_cmd.finish(f"未知的响应格式：{list(item.keys())}")
                    return

                await draw_cmd.finish(MessageSegment.image(img_bytes))
            else:
                body = resp.text
                if resp.status_code == 503 and "No available channel" in body:
                    await draw_cmd.finish("图片生成被拒绝了（提示词可能触发了安全过滤，请尝试换一种描述方式）")
                elif resp.status_code == 401:
                    await draw_cmd.finish("图片生成服务认证失败，请联系管理员检查 API 配置")
                else:
                    await draw_cmd.finish(f"生成失败：{resp.status_code}")
    except FinishedException:
        raise
    except Exception as e:
        import traceback
        with open("/tmp/imgerr.log", "a") as f:
            f.write(f"[{__import__('time').time()}] {type(e).__name__}: {e}\n")
            traceback.print_exc(file=f)
        err_str = str(e)
        if "timeout" in err_str.lower() or "ReadTimeout" in err_str or "timed out" in err_str:
            await draw_cmd.finish("图片生成超时（当前队列较长或提示词过于复杂，请稍后重试）")
        else:
            await draw_cmd.finish(f"出错了：{err_str}")


# --- 图生图（img2img）：引用图片 + 提示词生成新图片 ---
img2img_cmd = on_message(rule=startswith("图生图"), priority=10, block=True)


@img2img_cmd.handle()
async def handle_img2img(bot: Bot, event: MessageEvent):
    text = event.get_message().extract_plain_text().strip()
    # 处理前缀 "图生图"
    for prefix in ["图生图", "图生图 "]:
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
            break
    prompt = text if text else ""

    if not prompt:
        await img2img_cmd.finish("把你想修改的内容写在「图生图」后面，比如「图生图 把这只猫变成红色」。需要回复或附带一张图片。")

    # 提取参考图片 URL（优先从回复消息中找，其次当前消息）
    img_url = None
    for seg in event.get_message():
        if seg.type == "reply":
            try:
                reply_id = seg.data.get("id")
                if reply_id:
                    msg_data = await bot.get_msg(message_id=int(reply_id))
                    raw_msg = msg_data.get("message", [])
                    if isinstance(raw_msg, list):
                        for s in raw_msg:
                            if s.get("type") == "image":
                                img_url = s.get("data", {}).get("url")
                                break
            except Exception:
                pass
            break

    if not img_url:
        for seg in event.get_message():
            if seg.type == "image":
                img_url = seg.data.get("url")
                break

    if not img_url:
        await img2img_cmd.finish("没有找到图片！请回复一张图片，或在消息中附带图片。")

    await img2img_cmd.send("正在处理图片，请稍候...")

    try:
        async with httpx.AsyncClient(timeout=180.0) as c:
            # 下载参考图片
            r = await c.get(img_url)
            if r.status_code != 200:
                await img2img_cmd.finish("下载参考图片失败")
                return

            # 转换为 PNG + 裁剪为正方形 + 缩放到 1024x1024
            png_data = preprocess_reference_image(r.content)

            # 调用 /v1/images/edits 图生图接口
            resp = await c.post(
                f"{IMAGE_API_URL}/v1/images/edits",
                headers={"Authorization": f"Bearer {IMAGE_API_KEY}"},
                data={"model": IMAGE_MODEL, "prompt": prompt, "n": 1, "size": "1024x1024"},
                files={"image": ("input.png", png_data, "image/png")},
            )

            if resp.status_code == 200:
                item = resp.json()["data"][0]

                if "b64_json" in item:
                    out = io.BytesIO(base64.b64decode(item["b64_json"]))
                elif "url" in item:
                    ir = await c.get(item["url"])
                    if ir.status_code == 200:
                        out = io.BytesIO(ir.content)
                    else:
                        await img2img_cmd.finish("下载生成结果失败")
                        return
                else:
                    await img2img_cmd.finish(f"未知响应格式：{list(item.keys())}")
                    return

                await img2img_cmd.finish(MessageSegment.image(out))
            else:
                body = resp.text
                if "No available channel" in body:
                    await img2img_cmd.finish("图片生成被拒绝了（提示词可能触发了安全过滤，请尝试换一种描述方式）")
                elif resp.status_code == 401:
                    await img2img_cmd.finish("图片生成服务认证失败，请联系管理员")
                else:
                    await img2img_cmd.finish(f"生成失败：{resp.status_code}")
    except FinishedException:
        raise
    except Exception as e:
        await img2img_cmd.finish(f"出错了：{str(e)}")
