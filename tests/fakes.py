"""Offline fakes for the agent tests: a SQL-ish connection and hit builders."""

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
