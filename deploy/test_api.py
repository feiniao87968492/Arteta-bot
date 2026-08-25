import os
import httpx, json


api_key = os.environ.get("IMAGE_API_KEY", "")
if not api_key:
    raise SystemExit("IMAGE_API_KEY is required")

resp = httpx.post(
    "https://api.duckcoding.ai/v1/images/generations",
    headers={"Authorization": f"Bearer {api_key}"},
    json={"model": "gpt-image-1.5", "prompt": "a red cat playing football", "n": 1, "size": "1024x1024"},
    timeout=30,
)
print(f"Status: {resp.status_code}")
data = resp.json()
print(f"Top keys: {list(data.keys())}")
if "data" in data and len(data["data"]) > 0:
    print(f"Data[0] keys: {list(data['data'][0].keys())}")
    print(json.dumps(data["data"][0], indent=2, ensure_ascii=False)[:1000])
else:
    print(json.dumps(data, indent=2, ensure_ascii=False)[:1000])
