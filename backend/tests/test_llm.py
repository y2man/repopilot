import asyncio
from types import SimpleNamespace

import httpx

from app.services import llm


def test_stream_answer_retries_413_with_smaller_cited_context(monkeypatch):
    payloads = []

    class FakeResponse:
        def __init__(self, status_code, lines=()):
            self.status_code = status_code
            self.lines = lines

        async def aread(self):
            return b"request too large"

        def raise_for_status(self):
            if self.status_code >= 400:
                request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
                response = httpx.Response(self.status_code, request=request)
                raise httpx.HTTPStatusError("provider error", request=request, response=response)

        async def aiter_lines(self):
            for line in self.lines:
                yield line

    class FakeStream:
        def __init__(self, response):
            self.response = response

        async def __aenter__(self):
            return self.response

        async def __aexit__(self, *_):
            return None

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        def stream(self, method, url, **kwargs):
            payloads.append(kwargs["json"])
            return FakeStream(responses.pop(0))

    responses = [
        FakeResponse(413),
        FakeResponse(200, [
            'data: {"choices":[{"delta":{"content":"Grounded answer."}}]}',
            "data: [DONE]",
        ]),
    ]
    monkeypatch.setattr(llm, "get_settings", lambda: SimpleNamespace(
        groq_api_key="test-key",
        groq_model="test-model",
    ))
    monkeypatch.setattr(llm.httpx, "AsyncClient", FakeClient)

    async def collect():
        return [token async for token in llm.stream_answer("Explain authentication", [{
            "path": "src/auth.py",
            "start_line": 1,
            "end_line": 3,
            "content": "x" * 30000,
        }])]

    assert asyncio.run(collect()) == ["Grounded answer."]
    first_evidence = payloads[0]["messages"][1]["content"]
    retried_evidence = payloads[1]["messages"][1]["content"]
    assert len(retried_evidence) < len(first_evidence)
    assert "src/auth.py:1-3" in retried_evidence
