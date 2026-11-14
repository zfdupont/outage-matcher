# Agent run

- Date: 2026-11-13
- Model: claude-haiku-5-5

## Question

our primary database failed over and for a few minutes two nodes both accepted writes, afterwards some records were missing

## Steps

- tool `search_incidents` {"query": "primary database failover, two nodes accepted writes simultaneously (split brain), records missing afterwards", "system_type": "database", "k": 5}: ok, doc_ids [59, 109, 167]
- tool `get_postmortem` {"doc_id": 109}: ok, doc_ids [109]
- grade: 2 of 6 chunks relevant

## Answer

```
Likely cause: Multi-AZ failover of the primary RDS MySQL instance led to replication breakdown and split-brain-like behavior: for a few minutes two nodes accepted writes. The failover caused replication to crash on the replicas, and the database ended up missing about 5 seconds of transactional data that the application had already logged as written, which matches the reported missing records. The excerpts describe the same pattern (failover, replication failure on replicas, missing records versus application trace logs), but they do not explicitly describe the mechanism that allowed two nodes to accept writes at once, nor why the lost writes were not replicated to the new primary. That part is only partly covered.
Suggested fix: Reconcile the lost data by matching application trace logs and binary logs for the failover window and replaying the missing transactions. Investigate why the old primary kept accepting writes during failover, and fence it (for example, make the application or a proxy stop routing writes to the old primary and enforce read-only mode on it) so that only one writable node exists. Review the replication setup and failover handling with the vendor, since the excerpts say this kind of replication crash during Multi-AZ failover is unusual. Consider semi-synchronous replication or other safeguards so that acknowledged writes are not lost during failover.
Citations:
  [109] The Day of the RDS Multi-AZ Failover - Razorpay Tech (other)
      https://web.archive.org/web/20250207075402/https://razorpay.com/blog/day-of-rds-multi-az-failover/
```

Usage: 5 LLM calls, 12573 input tokens, 1068 output tokens, 0 query rewrites
