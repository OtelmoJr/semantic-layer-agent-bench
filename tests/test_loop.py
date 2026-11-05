import asyncio

from slab.agent.loop import run_question
from slab.agent.providers.base import ProviderError, ToolCall, ToolSpec, Turn


class FakeBackend:
    def __init__(self):
        self.calls = []

    async def list_tools(self):
        return [ToolSpec("run_sql", "run", {"type": "object", "properties": {"sql": {"type": "string"}}})]

    async def call(self, name, arguments):
        self.calls.append((name, arguments))
        return '{"rows": [[1]]}', False


class Scripted:
    name, model = "fake", "fake-1"

    def __init__(self, script):
        self.script = list(script)
        self.seen_tools = []

    def model_digest(self):
        return "x"

    def complete(self, system, messages, tools, context):
        self.seen_tools.append([t.name for t in tools])
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def call(name, **args):
    return Turn("", [ToolCall("id-" + name, name, args)], 10, 2)


def run(provider, backend=None, **kw):
    return asyncio.run(run_question(provider, backend or FakeBackend(), "A", "q", "question?", **kw))


def test_submit_after_exploration():
    p = Scripted([call("run_sql", sql="select 1"), call("submit_sql", sql="select 1")])
    att = run(p)
    assert att.status == "submitted" and att.submission["payload"] == {"sql": "select 1"}
    assert (att.tool_calls, att.llm_calls, att.input_tokens) == (1, 2, 20)


def test_text_only_answer_is_no_answer():
    att = run(Scripted([Turn("the answer is 42", [], 5, 5)]))
    assert att.status == "no_answer" and att.submission is None


def test_budget_then_final_round_warns_and_stops_on_more_exploration():
    p = Scripted([call("run_sql", sql="1")] * 3 + [call("run_sql", sql="again")])
    att = run(p, max_tool_calls=3)
    assert att.status == "max_steps"
    assert att.tool_calls == 3
    # tool list is stable across turns; the last user message announces the budget
    assert p.seen_tools[0] == p.seen_tools[-1]
    assert att.transcript[-2]["role"] == "user" and "budget exhausted" in att.transcript[-2]["text"]


def test_final_round_can_still_submit():
    p = Scripted([call("run_sql", sql="1")] * 2 + [call("submit_sql", sql="select 2")])
    att = run(p, max_tool_calls=2)
    assert att.status == "submitted"


def test_unknown_tool_is_a_protocol_error_reported_back():
    b = FakeBackend()
    p = Scripted([call("drop_everything"), call("refuse", reason="x")])
    att = run(p, b)
    assert att.protocol_errors == 1 and att.status == "refused" and b.calls == []


def test_wrong_arm_submit_tool_is_not_accepted():
    # arm A cannot submit a metric query; it is treated as an unknown tool
    p = Scripted([call("submit_metric_query", metrics=["x"]), call("submit_sql", sql="select 1")])
    att = run(p)
    assert att.protocol_errors == 1 and att.status == "submitted"


def test_provider_error_is_recorded():
    att = run(Scripted([ProviderError("boom")]))
    assert att.status == "provider_error" and "boom" in att.error


def test_timeout():
    class Slow(Scripted):
        def complete(self, *a):
            import time
            time.sleep(2)
            return call("refuse", reason="late")

    att = run(Slow([]), timeout_s=0.5)
    assert att.status == "timeout"
