import pytest
import requests

from weekly_focus.client import TrelloClient, TrelloError


class FakeResponse:
    def __init__(self, status, text="{}", headers=None):
        self.status_code, self.text, self.headers = status, text, headers or {}

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        import json
        return json.loads(self.text)


class FakeSession:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def request(self, method, url, params, headers, timeout):
        self.calls.append((method, url, params, headers))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def client(*responses):
    sleeps = []
    c = TrelloClient("k", "t", session=FakeSession(*responses), max_retries=2, sleep=sleeps.append)
    return c, sleeps


def test_credentials_in_header_never_in_url():
    c, _ = client(FakeResponse(200, '{"id": "x"}'))
    assert c.request("GET", "/cards/x", fields="name") == {"id": "x"}
    method, url, params, headers = c.session.calls[0]
    assert url == "https://api.trello.com/1/cards/x"
    assert params == {"fields": "name"}
    assert headers == {"Authorization": 'OAuth oauth_consumer_key="k", oauth_token="t"'}


def test_network_error_is_retried_then_reported_without_secrets():
    url_with_token = "https://api.trello.com/1/x?key=k&token=t"
    c, sleeps = client(requests.ConnectionError(url_with_token),
                       requests.ConnectionError(url_with_token),
                       requests.Timeout(url_with_token))
    with pytest.raises(TrelloError) as e:
        c.request("GET", "/x")
    assert e.value.status is None
    assert str(e.value) == "GET /x -> network error: Timeout"
    assert e.value.__cause__ is None and e.value.__suppress_context__
    assert sleeps == [1, 2]


def test_network_error_then_success():
    c, sleeps = client(requests.ConnectionError("down"), FakeResponse(200, "[]"))
    assert c.request("GET", "/x") == []
    assert sleeps == [1]


def test_retries_on_429_with_retry_after():
    c, sleeps = client(FakeResponse(429, headers={"Retry-After": "3"}), FakeResponse(200, "[]"))
    assert c.request("GET", "/x") == []
    assert sleeps == [3.0]


def test_retries_on_5xx_with_backoff_then_gives_up():
    c, sleeps = client(FakeResponse(502), FakeResponse(503), FakeResponse(500, "boom"))
    with pytest.raises(TrelloError) as e:
        c.request("GET", "/x")
    assert e.value.status == 500
    assert sleeps == [1, 2]


def test_no_retry_on_4xx():
    c, sleeps = client(FakeResponse(401, "invalid token"))
    with pytest.raises(TrelloError):
        c.request("GET", "/x")
    assert sleeps == []


def test_card_returns_none_on_404():
    c, _ = client(FakeResponse(404, "not found"))
    assert c.card("x", "name") is None


def test_update_card_sends_booleans_as_lowercase():
    c, _ = client(FakeResponse(200))
    c.update_card("x", closed=True, dueComplete=False)
    params = c.session.calls[0][2]
    assert params["closed"] == "true" and params["dueComplete"] == "false"


def test_empty_body_returns_none():
    c, _ = client(FakeResponse(200, ""))
    assert c.delete_card("x") is None
