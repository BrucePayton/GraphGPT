import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from graphgpt import LangfuseEvaluationAdapter
from graphgpt.domain.ir import DecisionIR, GraphIR, NodeIR
from graphgpt.tracing import trace_metadata

GRAPH = GraphIR(
    "evaluation",
    "graphgpt.dev/v1alpha1",
    "dict",
    (),
    (NodeIR("decide", decision=DecisionIR("p", {"type": "predicate"}, "answer")),),
    (),
)
TIME_RANGE = {
    "from_start_time": datetime(2026, 11, 1, tzinfo=UTC),
    "to_start_time": datetime(2026, 11, 5, tzinfo=UTC),
}


def test_real_sdk_observation_query_via_mock_http() -> None:
    pytest.importorskip("langfuse")
    import httpx
    from langfuse.api.client import LangfuseAPI

    requests = []

    def respond(request):
        requests.append(request)
        assert request.url.path == "/api/public/v2/observations"
        filters = json.loads(request.url.params["filter"])
        assert {f["column"] for f in filters} == {"metadata", "startTime", "name"}
        assert request.url.params["fields"] == "core,basic,io,metadata"
        assert "parseIoAsJson" not in request.url.params
        if "cursor" not in request.url.params:
            return httpx.Response(200, json={"data": [], "meta": {"cursor": "continue"}})
        assert request.url.params["cursor"] == "continue"
        data = []
        for i, (level, end, output) in enumerate(
            [
                ("DEFAULT", "2026-11-02T00:00:01Z", '{"answer": true}'),
                ("ERROR", "2026-11-02T00:00:01Z", '{"answer": true}'),
                ("DEFAULT", None, None),
                ("DEFAULT", "2026-11-02T00:00:01Z", "not-json"),
            ]
        ):
            data.append(
                {
                    "id": str(i),
                    "traceId": "trace",
                    "projectId": "project",
                    "type": "SPAN",
                    "name": "decide",
                    "level": level,
                    "startTime": "2026-11-02T00:00:00Z",
                    "endTime": end,
                    "metadata": trace_metadata(GRAPH, node_id="decide"),
                    "output": output,
                }
            )
        return httpx.Response(200, json={"data": data, "meta": {"cursor": None}})

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        api = LangfuseAPI(
            base_url="https://langfuse.invalid",
            username="pk-test",
            password="sk-test",
            httpx_client=http,
        )
        adapter = LangfuseEvaluationAdapter(SimpleNamespace(api=api))
        rows = list(adapter.evaluate(GRAPH, **TIME_RANGE, node_id="decide"))
    assert len(requests) == 2
    assert [r["status"] for r in rows if r["check"] == "execution_succeeded"] == [
        "passed",
        "failed",
        "pending",
        "passed",
    ]
    assert [r["status"] for r in rows if r["check"] == "typed_decision"] == [
        "passed",
        "failed",
        "not_evaluated",
        "failed",
    ]
    assert {r["trace_id"] for r in rows} == {"trace"}


def adapter_for(get_many):
    return LangfuseEvaluationAdapter(
        SimpleNamespace(api=SimpleNamespace(observations=SimpleNamespace(get_many=get_many)))
    )


def test_cursor_safeguards_and_limit() -> None:
    repeating = adapter_for(
        lambda **_: SimpleNamespace(data=[], meta=SimpleNamespace(cursor="same"))
    )
    with pytest.raises(RuntimeError, match="repeated"):
        list(repeating.evaluate(GRAPH, **TIME_RANGE))
    with pytest.raises(RuntimeError, match="max_pages"):
        list(repeating.evaluate(GRAPH, **TIME_RANGE, max_pages=1))
    calls = []

    def get_many(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            data=[SimpleNamespace(metadata={})] * 2, meta=SimpleNamespace(cursor="more")
        )

    assert list(adapter_for(get_many).evaluate(GRAPH, **TIME_RANGE, limit=1)) == []
    assert len(calls) == 1 and calls[0]["limit"] == 1


@pytest.mark.parametrize(
    "time_range",
    [
        {"from_start_time": datetime(2026, 11, 1), "to_start_time": TIME_RANGE["to_start_time"]},
        {
            "from_start_time": TIME_RANGE["to_start_time"],
            "to_start_time": TIME_RANGE["from_start_time"],
        },
    ],
)
def test_invalid_time_range(time_range) -> None:
    with pytest.raises(ValueError, match="time range"):
        list(adapter_for(None).evaluate(GRAPH, **time_range))


def test_api_failures_are_not_reported_as_empty_success() -> None:
    def fail(**kwargs):
        raise RuntimeError("API unavailable")

    with pytest.raises(RuntimeError, match="API unavailable"):
        list(adapter_for(fail).evaluate(GRAPH, **TIME_RANGE))
