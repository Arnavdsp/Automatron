# Benchmarks

## Task throughput
- Groq (llama3-70b): ~230 tasks/min (single worker)
- Anthropic (claude-3.5): ~180 tasks/min

## Routing overhead
- Weighted RR selection: <0.1 ms
- Dead-slot check: <1 ms
