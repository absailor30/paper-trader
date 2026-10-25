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


WANT = ("nemotron", "llama-3.3", "llama-3.1-405", "llama-4", "gpt-oss", "deepseek", "qwen", "mistral", "kimi", "glm", "minimax")
SKIP = ("embed", "safety", "guard", "reward", "parse", "rerank", "vl", "vision", "clip", "retriev", "translate", "nvclip", "audio", "asr", "tts", "-4b", "-1b", "-8b")
TOOL = {"type": "function", "function": {"name": "get_close", "description": "Latest closing price of a ticker",
                                         "parameters": {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}}}


def candidate_models(ids):
    return [i for i in ids if any(w in i.lower() for w in WANT) and not any(w in i.lower() for w in SKIP)]


def probe_tools(base, headers, model, timeout=150):
    """One request with a tool attached (TradingAgents binds tools to every analyst). Returns (status, called_tool, seconds)."""
    t0 = time.time()
    try:
        r = requests.post(f"{base}/chat/completions", headers=headers, timeout=timeout, json={
            "model": model, "max_tokens": 600, "temperature": 0.1, "tools": [TOOL], "tool_choice": "auto",
            "messages": [{"role": "user", "content": "What is the latest close of GLD? Use the tool."}]})
    except requests.exceptions.RequestException as e:
        return type(e).__name__, False, time.time() - t0
    called = False
    if r.ok:
        try:
            called = bool(r.json()["choices"][0]["message"].get("tool_calls"))
        except Exception:
            pass
    return r.status_code, called, time.time() - t0


def probe_nvidia():
    key = os.environ.get("NVIDIA_API_KEY", "")
    if not key:
        return
    base, h = PROVIDERS["NVIDIA"][1], {"Authorization": f"Bearer {key}"}
    ids = [m["id"] for m in requests.get(f"{base}/models", headers=h, timeout=30).json().get("data", [])]
    print(f"\nNVIDIA catalog ({len(ids)} ids): {sorted(ids)}")
    print("\n=== tool-calling probe (status, called_tool, seconds) ===")
    for m in candidate_models(ids)[:30]:
        st, called, dt = probe_tools(base, h, m)
        print(f"{m:55s} {st!s:>6} tool_call={'YES' if called else 'no '} {dt:5.1f}s")


if __name__ == "__main__":
    for n, (e, b, m) in PROVIDERS.items():
        check(n, e, b, m)
    probe_nvidia()
