# Changelog

## [Unreleased]
### Added
- Multi-LLM provider routing (OpenAI, Anthropic, Groq)
- Sector-aware task scheduling
- Live failover and dead-slot detection
- Eval harness for routing decisions

## [0.2.0]
### Added
- Groq streaming provider
- Prometheus /metrics endpoint
- Dead-slot quarantine with auto re-probe
- Priority task queue with deduplication
### Fixed
- Off-by-one in weighted round-robin index
- Provider error log key leakage
