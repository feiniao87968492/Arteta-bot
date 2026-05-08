import httpx, asyncio, time

async def test():
    api_key = "sk-5fdiT7sPpX36NkvLykAo5MxKiWftOldkCfMX8kjfrr8VI1kb"
    base = "https://api.duckcoding.ai"

    async with httpx.AsyncClient(timeout=180.0) as c:
        # Test with kissing prompt
        print("=== Test: kissing prompt ===")
        t0 = time.time()
        try:
            r = await c.post(
                base + "/v1/images/generations",
                headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
                json={"model": "gpt-image-1.5", "prompt": "两个人接吻的插画, anime style", "n": 1, "size": "1024x1024"},
            )
            elapsed = time.time() - t0
            print(f"Elapsed: {elapsed:.1f}s")
            print("Status:", r.status_code)
            if r.status_code == 200:
                data = r.json()
                item = data["data"][0]
                print("Keys:", list(item.keys()))
                if "url" in item:
                    img_r = await c.get(item["url"])
                    print("Download:", img_r.status_code, len(img_r.content), "bytes")
                elif "b64_json" in item:
                    print("b64_json length:", len(item["b64_json"]), "- decoded:", len(__import__('base64').b64decode(item["b64_json"])), "bytes")
            else:
                print("Error:", r.text[:500])
        except Exception as e:
            elapsed = time.time() - t0
            print(f"Failed after {elapsed:.1f}s:", type(e).__name__, str(e)[:300])

        # Test with a less potentially NSFW kissing prompt
        print("\n=== Test: family kiss (cheek) ===")
        t0 = time.time()
        try:
            r = await c.post(
                base + "/v1/images/generations",
                headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
                json={"model": "gpt-image-1.5", "prompt": "A mother kissing her baby on the cheek, watercolor style", "n": 1, "size": "1024x1024"},
            )
            elapsed = time.time() - t0
            print(f"Elapsed: {elapsed:.1f}s")
            print("Status:", r.status_code)
            if r.status_code != 200:
                print("Error:", r.text[:500])
            else:
                data = r.json()
                item = data["data"][0]
                print("Success! Keys:", list(item.keys()))
        except Exception as e:
            elapsed = time.time() - t0
            print(f"Failed after {elapsed:.1f}s:", type(e).__name__, str(e)[:300])

asyncio.run(test())
