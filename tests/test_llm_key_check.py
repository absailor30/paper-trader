import requests

import scripts.llm_key_check as k


class Resp:
    def __init__(self, code):
        self.status_code = code


def test_retries_timeouts_then_succeeds(monkeypatch):
    calls = []

    def fake_post(*a, **kw):
        calls.append(kw["timeout"])
        if len(calls) < 3:
            raise requests.exceptions.ReadTimeout()
        return Resp(200)

    monkeypatch.setattr(k.requests, "post", fake_post)
    monkeypatch.setattr(k.time, "sleep", lambda s: None)
    r, _ = k.post_with_retry("http://x", {}, "m")
    assert r.status_code == 200 and len(calls) == 3 and calls[0] == k.TIMEOUT_S == 600


def test_retries_429_and_gives_up_cleanly(monkeypatch):
    monkeypatch.setattr(k.requests, "post", lambda *a, **kw: Resp(429))
    monkeypatch.setattr(k.time, "sleep", lambda s: None)
    r, _ = k.post_with_retry("http://x", {}, "m")
    assert r is None


def test_auth_error_is_not_retried(monkeypatch):
    calls = []
    monkeypatch.setattr(k.requests, "post", lambda *a, **kw: calls.append(1) or Resp(401))
    r, _ = k.post_with_retry("http://x", {}, "m")
    assert r.status_code == 401 and len(calls) == 1


def test_candidate_models_filters_junk():
    ids = ["nvidia/nemotron-3-embed-1b", "nvidia/llama-3.1-nemotron-safety-guard-8b-v3", "nvidia/nemotron-3-super-120b-a12b",
           "meta/llama-3.3-70b-instruct", "baai/bge-m3", "openai/gpt-oss-120b"]
    assert k.candidate_models(ids) == ["nvidia/nemotron-3-super-120b-a12b", "meta/llama-3.3-70b-instruct", "openai/gpt-oss-120b"]


def test_probe_tools_detects_tool_call(monkeypatch):
    class R:
        ok, status_code = True, 200
        def json(self):
            return {"choices": [{"message": {"tool_calls": [{"id": "1"}]}}]}
    monkeypatch.setattr(k.requests, "post", lambda *a, **kw: R())
    assert k.probe_tools("http://x", {}, "m")[:2] == (200, True)

    class NotFound:
        ok, status_code = False, 404
    monkeypatch.setattr(k.requests, "post", lambda *a, **kw: NotFound())
    assert k.probe_tools("http://x", {}, "m")[:2] == (404, False)
