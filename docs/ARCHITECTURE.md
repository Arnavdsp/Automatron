# Automatron Architecture

```
User / API
  |
  v
 Task Queue (Priority Heap)
  |
  v
 Router (Weighted RR + Latency Cache)
  |        |         |
  v        v         v
Groq   Anthropic  OpenAI
  |        |         |
  +--------+---------+
  |
  v
 Response Aggregator -> User
```
