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
