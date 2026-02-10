# Project Coding Principles

## Data Integrity

- Never truncate data arbitrarily (no `[:100]` or `[:2000]` slicing)
- Preserve full information; let consumers handle their own limits

## No Dead Code

- Use everything you create: imports, variables, clones, instantiations
- Remove unused code rather than leaving it dormant

## Smart Context Management

- Prefer structured data (test reports, APIs) over raw logs
- When raw data is necessary, extract relevant content (errors, failures, warnings) instead of full dumps

## Parallel Execution

- Run independent, stateless operations in parallel
- Handle failures gracefully: one failure should not crash all parallel tasks
- Capture exceptions and continue processing

## File Handling

- Preserve user edits when modifying files
- Add missing elements rather than replacing entire content
- Never overwrite user customizations

## Communication

- Explain data flow through the system, not just variable locations
- Show how components connect and interact

## Architecture

### CLI-Based AI Integration

This project uses AI CLI tools (Claude CLI, Gemini CLI, Cursor Agent CLI) instead of direct SDK integrations:

- **No SDK dependencies**: AI providers are called via subprocess
- **Provider-agnostic**: Easy to add new AI CLIs (see README)
- **Auth handled externally**: CLIs manage their own authentication
- **Environment-driven**: `AI_PROVIDER` env var selects the provider (`claude`, `gemini`, or `cursor`)

### Key Components

| Component | Purpose |
|-----------|---------|
| `call_ai_cli()` | Single function for all AI CLI calls |
| `get_failure_signature()` | Deduplicates identical test failures |
| `analyze_failure_group()` | Analyzes unique failures, applies to all matches |
| `run_parallel_with_limit()` | Bounded parallel execution |
| `build_result_messages()` | Builds hierarchical result messages from analysis output |

### Failure Deduplication

When multiple tests fail with the same error:
1. Failures are grouped by error signature (MD5 hash of error + stack trace)
2. Only one AI CLI call per unique error type
3. Analysis is applied to all failures with matching signature
4. Reduces redundant API calls and output

### Hierarchical Messages

Analysis results include pre-split `messages` for structured output:
1. Results are split into typed messages: `summary`, `failure_detail`, `child_job`
2. Each message targets under 3K characters with line-boundary splitting
3. `messages` are populated in `analyzer.py` at construction time
4. All consumers (JSON API, callbacks, Slack, text output) use the same messages
5. Slack delivery iterates messages with per-message error handling

### Logging

Uses `python-simple-logger`:
- INFO: Milestones (job started, AI calls, completed)
- DEBUG: Detailed operations (response lengths, extracted data)
- Configured via `LOG_LEVEL` environment variable
