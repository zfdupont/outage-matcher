"""Offline fakes for the agent tests: a SQL-ish connection and hit builders."""

from types import SimpleNamespace

from outage_matcher.search import SearchHit

DOCS = {
    1: ("Load balancer config push", "https://x.test/lb", "network"),
    2: ("Primary database failover", "https://x.test/db", "database"),
}
CHUNKS = {
    1: [("summary", "A bad config push broke the load balancers."), ("root_cause", "Bad regex.")],
    2: [("root_cause", "Split brain after a partition.")],
}


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class FakeConn:
    """Answers the handful of queries the tools issue."""

    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def execute(self, sql, params=()):
        if "DISTINCT system_type" in sql:
            return FakeResult([(t,) for t in sorted({d[2] for d in DOCS.values()})])
        if "FROM postmortems WHERE id" in sql:
            return FakeResult([DOCS[params[0]]] if params[0] in DOCS else [])
        if "FROM chunks WHERE postmortem_id" in sql:
            return FakeResult(CHUNKS.get(params[0], []))
        if "FROM postmortems WHERE system_type" in sql:
            return FakeResult(
                [(i, d[0], d[1]) for i, d in DOCS.items() if d[2] == params[0]][: params[1]]
            )
        raise AssertionError(f"unexpected SQL: {sql}")


def make_hit(doc_id: int, section: str = "root_cause", score: float = 0.8) -> SearchHit:
    title, url, system_type = DOCS[doc_id]
    return SearchHit(title, section, score, url, system_type, f"text of doc {doc_id}", doc_id)


# ----- fake Anthropic client ------------------------------------------------------------------


def text_block(text: str = "done"):
    return SimpleNamespace(type="text", text=text)


def tool_block(name: str, input, id: str = "tu_1"):
    return SimpleNamespace(type="tool_use", id=id, name=name, input=input)


def response(*blocks, stop_reason: str | None = None, tokens: tuple[int, int] = (10, 5)):
    stop = stop_reason or ("tool_use" if any(b.type == "tool_use" for b in blocks) else "end_turn")
    usage = SimpleNamespace(input_tokens=tokens[0], output_tokens=tokens[1])
    return SimpleNamespace(content=list(blocks), stop_reason=stop, usage=usage)


class FakeAnthropic:
    """Scripted `client.messages.create`. Responses are queued per role.

    Roles: "retrieve" (tools offered, no forced choice), and the forced tool names
    "submit_grades", "submit_query", "submit_answer". An exhausted queue repeats its last item.
    """

    def __init__(self, **scripts):
        self.scripts = {role: list(items) for role, items in scripts.items()}
        self.calls: list[dict] = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        import copy

        self.calls.append(copy.deepcopy({k: v for k, v in kwargs.items() if k != "tools"}))
        choice = kwargs.get("tool_choice")
        role = choice["name"] if choice else "retrieve"
        queue = self.scripts.get(role)
        if not queue:
            raise AssertionError(f"unscripted LLM call for role {role!r}")
        return queue.pop(0) if len(queue) > 1 else queue[0]

    def calls_for(self, role: str) -> list[dict]:
        return [
            c for c in self.calls if (c.get("tool_choice") or {}).get("name", "retrieve") == role
        ]
