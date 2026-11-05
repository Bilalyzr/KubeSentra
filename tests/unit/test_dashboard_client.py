"""Unit tests: the dashboard's API client with a mocked transport.

Verifies URLs/params, the approval-token header, and that error bodies are
surfaced verbatim (never swallowed or faked).
"""

import json

import httpx
import pytest

from dashboard.services import api


@pytest.fixture
def mock_api(monkeypatch):
    """Patch the client factory to use a MockTransport capturing requests."""
    calls: list[httpx.Request] = []
    responses: list[httpx.Response] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if responses:
            return responses.pop(0)
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)

    real_client = httpx.Client

    def make_client(**kwargs):
        kwargs.pop("base_url", None)
        return real_client(transport=transport,
                           base_url="http://testserver", **kwargs)

    class _HttpxShim:
        @staticmethod
        def Client(**kwargs):
            return make_client(**kwargs)

    # replace the NAME BINDING inside the dashboard api module (do not touch
    # the real httpx module - that would recurse)
    monkeypatch.setattr(api, "httpx", _HttpxShim)
    return {"calls": calls, "responses": responses}


def test_get_incidents_adds_params(mock_api):
    result = api.get_json("/incidents", {"status": "resolved", "limit": 5})
    req = mock_api["calls"][0]
    assert req.url.params["status"] == "resolved"
    assert result == {"ok": True}


def test_post_decision_sends_token_and_body(mock_api, monkeypatch):
    from common.config import get_settings

    monkeypatch.setenv("APPROVAL_TOKEN", "unit-test-token")
    get_settings.cache_clear()
    code, body = api.post_decision("abc", "edited", [{"name": "rollout_undo"}],
                                   "tester")
    req = mock_api["calls"][0]
    assert req.headers["X-Approval-Token"] == "unit-test-token"
    sent = json.loads(req.content)
    assert sent == {"status": "edited",
                    "approver": "tester",
                    "plan": [{"name": "rollout_undo"}]}
    assert code == 200
    get_settings.cache_clear()


def test_post_decision_surfaces_error_verbatim(mock_api):
    mock_api["responses"].append(
        httpx.Response(400, json={"detail": {"validation_error":
                                             "replicas 99 outside 1..5"}}))
    code, body = api.post_decision("abc", "edited", [{"name": "scale",
                                                      "params": {"replicas": 99}}],
                                   "tester")
    assert code == 400
    assert "replicas 99" in json.dumps(body)
