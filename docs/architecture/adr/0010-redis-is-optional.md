# ADR-0010: Redis is optional

- **Status:** Accepted
- **Date:** 2026-10-30

## Context

The platform uses short-lived shared state: rate limit windows (sign-in, sign-up, scan
requests), the dashboard cache and its version counters. The programme's stack includes
Redis "when the project needs it". A self-hosted tool is easier to adopt when it runs on
Postgres alone, and nothing correctness-critical should depend on a cache that may evict.

## Decision

Everything that would use Redis goes through a small `KV` protocol (`core/kv.py`) with two
backends: `RedisKV` when `REDIS_URL` is set, and `MemoryKV` (an LRU bounded by entries and
bytes, with fixed window counters) otherwise. Everything durable, including the scan queue,
sessions, revocations, lockouts and incidents, lives in Postgres. A Redis error while
reading or writing the cache is treated as a miss; `/readyz` reports Redis as `degraded`,
not unready. The Compose stacks and the AWS environments run Redis.

## Consequences

**Good**
- `DATABASE_URL` alone is enough to run the platform.
- A Redis outage or eviction costs recomputation, never data.

**Bad / caveats**
- Without Redis, limits and caches are per process: with several API replicas, each has its
  own rate windows, and the worker's dashboard invalidation does not reach the API, so a new
  result shows within the 30 second cache TTL instead of at once
  ([HLD.md](../HLD.md#caching)). Run Redis with more than one replica.
- Memory mode uses fixed windows rather than Redis's sliding window, so bursts at a window
  boundary can reach twice the limit.

## Alternatives considered

- **Redis required**: simpler code, one more mandatory service for a small install.
- **Rate limits and cache in Postgres**: possible, but it puts high-churn writes on the
  database that holds the queue.
