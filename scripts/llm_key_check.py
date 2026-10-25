"""Do the free LLM keys work, which models exist, what are the rate limits, can the model return structured JSON?
Never prints a key. Run via the llm-key-check workflow (the sandbox cannot reach these APIs)."""
import json
import os
import time

import requests

PROVIDERS = {
    "NVIDIA": ("NVIDIA_API_KEY", "https://integrate.api.nvidia.com/v1", ["nvidia/nemotron-3-ultra-550b-a55b"]),
    "GROQ": ("GROQ_API_KEY", "https://api.groq.com/openai/v1", ["openai/gpt-oss-120b"]),
}
PROMPT = ('You are a trading analyst. Stock XYZ closed above its 20-day high on rising volume, but is below its 100-day '
          'average. Reply with ONLY JSON: {"action":"BUY|HOLD|SELL","confidence":0..1,"reason":"<=20 words"}')


TIMEOUT_S = 600   # big reasoning models (550B) can take minutes to answer
ATTEMPTS = 3      # retry timeouts / 429 / 5xx with backoff


def post_with_retry(base, headers, model):
    """Returns (response, seconds) or (None, seconds). Never raises; prints each failed attempt."""
    t0 = time.time()
    for attempt in range(1, ATTEMPTS + 1):
        try:
            r = requests.post(f"{base}/chat/completions", headers=headers, timeout=TIMEOUT_S, json={
                "model": model, "max_tokens": 3000, "temperature": 0.2,
                "messages": [{"role": "user", "content": PROMPT}]})
            if r.status_code not in (429, 500, 502, 503, 504):
                return r, time.time() - t0
            print(f"{model}: attempt {attempt} HTTP {r.status_code}, retrying")
        except requests.exceptions.RequestException as e:
            print(f"{model}: attempt {attempt} {type(e).__name__} after {time.time() - t0:.0f}s, retrying")
        time.sleep(10 * attempt)
    print(f"{model}: gave up after {ATTEMPTS} attempts ({time.time() - t0:.0f}s)")
    return None, time.time() - t0


def check(name, env, base, models):
    key = os.environ.get(env, "")
    print(f"\n=== {name}: key {'SET' if key else 'MISSING'} ({len(key)} chars) ===")
    if not key:
        return
    h = {"Authorization": f"Bearer {key}"}
    try:
        r = requests.get(f"{base}/models", headers=h, timeout=30)
        ids = [m["id"] for m in r.json().get("data", [])] if r.ok else []
        print(f"models endpoint: HTTP {r.status_code}, {len(ids)} models; nemotron/gpt-oss examples: "
              f"{[i for i in ids if 'nemotron' in i.lower() or 'gpt-oss' in i.lower()][:8]}")
    except Exception as e:
        print(f"models endpoint failed: {type(e).__name__}")
    for model in models:
        r, dt = post_with_retry(base, h, model)
        if r is None:
            continue
        print(f"{model}: HTTP {r.status_code} in {dt:.1f}s")
        lim = {k: v for k, v in r.headers.items() if "ratelimit" in k.lower() or "credit" in k.lower()}
        print("rate/credit headers:", lim or "none")
        if r.ok:
            j = r.json()
            msg = j["choices"][0]["message"]
            print("usage:", j.get("usage"))
            text = (msg.get("content") or "").strip()
            print("reply:", text[:300].replace("\n", " "))
            try:
                json.loads(text[text.index("{"):text.rindex("}") + 1])
                print("structured JSON: OK")
            except Exception:
                print("structured JSON: FAILED")
        else:
            print("error body:", r.text[:300])


if __name__ == "__main__":
    for n, (e, b, m) in PROVIDERS.items():
        check(n, e, b, m)
