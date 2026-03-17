# Jenkins Job Insight

A containerized webhook service that analyzes Jenkins job failures, classifies them as code issues or product bugs, and provides actionable suggestions. This service operates without a UI, receiving requests via webhooks and delivering results through callbacks.

## Overview

Jenkins Job Insight uses AI to analyze failed Jenkins builds and determine whether failures are caused by:

- **Code Issues**: Problems in test code such as incorrect assertions, setup issues, or flaky tests
- **Product Bugs**: Actual bugs in the product being tested that the tests correctly identified

For each failure, the service provides detailed explanations and either fix suggestions (for code issues) or structured bug reports (for product bugs).

## Features

- **Async and sync analysis modes**: Submit jobs for background processing or wait for immediate results
- **AI-powered classification**: Distinguishes between test code issues and product bugs
- **Multiple AI providers**: Supports Claude CLI, Gemini CLI, and Cursor Agent CLI
- **Optional Jira integration**: Searches Jira for matching bugs on PRODUCT BUG failures with AI-powered relevance filtering
- **SQLite result storage**: Persists analysis results for later retrieval
- **Callback webhooks**: Delivers results to your specified endpoint with custom headers
- **HTML report output**: Generate self-contained, dark-themed HTML failure reports viewable in any browser
- **Direct failure analysis**: Analyze raw test failures without Jenkins via `POST /analyze-failures`
- **pytest JUnit XML integration**: Enrich JUnit XML reports with AI analysis via a pytest plugin
- **Raw XML analysis**: Accept raw JUnit XML via API, extract failures, analyze, and return enriched XML

## Quick Start

> **Note:** The `data` directory must exist on the host before starting the container. Docker creates mounted directories as root, but the container runs as a non-root user for security.

```bash
# Create data directory for SQLite persistence (required)
mkdir -p data

docker run -d \
  -p 8000:8000 \
  -v ./data:/data \
  -e JENKINS_URL=https://jenkins.example.com \
  -e JENKINS_USER=your-username \
  -e JENKINS_PASSWORD=your-api-token \
  -e AI_PROVIDER=claude \
  -e AI_MODEL=your-model-name \
  jenkins-job-insight
```

## Configuration

Configure the service using environment variables. The service is tied to a single Jenkins instance via `JENKINS_URL`.

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| **Jenkins** | | | |
| `JENKINS_URL` | Yes | - | Jenkins server URL (service is tied to this instance) |
| `JENKINS_USER` | Yes | - | Jenkins username |
| `JENKINS_PASSWORD` | Yes | - | Jenkins password or API token |
| `JENKINS_SSL_VERIFY` | No | `true` | Enable SSL certificate verification (set to `false` for self-signed certs) |
| **AI Provider** | | | |
| `AI_PROVIDER` | Yes | - | AI provider to use (`claude`, `gemini`, or `cursor`) |
| `AI_MODEL` | Yes | - | Model for the AI provider |
| `AI_CLI_TIMEOUT` | No | `10` | Timeout for AI CLI calls in minutes (increase for slower models) |
| `LOG_LEVEL` | No | `INFO` | Log verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `CALLBACK_URL` | No | - | Default callback URL for results (can be overridden per-request) |
| `CALLBACK_HEADERS` | No | - | Default callback headers as JSON (can be overridden per-request) |
| **Other** | | | |
| `TESTS_REPO_URL` | No | - | Default tests repository URL (can be overridden per-request) |
| `HTML_REPORT` | No | `true` | Generate HTML reports (set to `false` to disable) |
| `DEBUG` | No | `false` | Enable debug mode with hot reload for development |
| **Jira (Optional)** | | | |
| `ENABLE_JIRA` | No | *(auto-detect)* | Explicitly enable/disable Jira integration (overrides auto-detection) |
| `JIRA_URL` | No | - | Jira instance URL (enables Jira integration) |
| `JIRA_EMAIL` | No | - | Email for Jira Cloud authentication (if set, Cloud auth is used; if not set, Server/DC auth is used) |
| `JIRA_API_TOKEN` | No | - | API token for Jira Cloud (kept for backward compatibility; prefer `JIRA_PAT`) |
| `JIRA_PAT` | No | - | Personal Access Token (works for both Cloud and Server/DC) |
| `JIRA_PROJECT_KEY` | No | - | Scope Jira searches to a specific project |
| `JIRA_SSL_VERIFY` | No | `true` | SSL certificate verification for Jira |
| `JIRA_MAX_RESULTS` | No | `5` | Maximum Jira results per search |
| **Build Artifact Analysis (Optional)** | | | |
| `GET_JOB_ARTIFACTS` | No | `true` | Download all build artifacts for AI artifacts context |
| `JENKINS_ARTIFACTS_MAX_SIZE_MB` | No | `500` | Maximum size per downloaded artifact in MB |
| `JENKINS_ARTIFACTS_CONTEXT_LINES` | No | `200` | Maximum artifacts context lines for AI prompt |
| **GitHub** | | | |
| `GITHUB_TOKEN` | No | - | GitHub API token for private repo PR status in comments |

### Jenkins Configuration

The `JENKINS_URL` environment variable defines which Jenkins instance the service connects to. API requests specify only the job name and build number; the service constructs the full URL internally.

### AI CLI Configuration

The service uses AI CLI tools for analysis. Set `AI_PROVIDER` to choose your provider.

#### Claude CLI

##### Option 1: API Key (simplest)

```bash
AI_PROVIDER=claude
ANTHROPIC_API_KEY=your-anthropic-api-key
```

##### Option 2: Vertex AI

```bash
AI_PROVIDER=claude
CLAUDE_CODE_USE_VERTEX=1
CLOUD_ML_REGION=us-east5
ANTHROPIC_VERTEX_PROJECT_ID=your-project-id
```

#### Gemini CLI

##### Option 1: API Key

```bash
AI_PROVIDER=gemini
GEMINI_API_KEY=your-gemini-api-key
```

##### Option 2: OAuth

```bash
AI_PROVIDER=gemini
# Authenticate with: gemini auth login
```

#### Cursor Agent CLI

The CLI command is `agent`.

##### Option 1: API Key

```bash
AI_PROVIDER=cursor
CURSOR_API_KEY=your-cursor-api-key

# Specify the model
AI_MODEL=claude-3.5-sonnet
```

##### Option 2: Web Login (Docker)

For web-based authentication inside a container, run:

```bash
docker exec <container-name> agent login
```

### Adding a New AI CLI Provider

The CLI-based architecture makes it easy to add new AI providers. To add a new CLI:

#### 1. Update `analyzer.py`

Add a command builder function and register it in the `PROVIDER_CONFIG` dictionary:

```python
def _build_openai_cmd(
    binary: str, model: str, prompt: str, _cwd: Path | None
) -> list[str]:
    return [binary, "--model", model, "-p", prompt]

PROVIDER_CONFIG["openai"] = ProviderConfig(
    binary="openai", build_cmd=_build_openai_cmd
)
```

If the CLI manages its own working directory (like Cursor), set `uses_own_cwd=True`:

```python
PROVIDER_CONFIG["openai"] = ProviderConfig(
    binary="openai", uses_own_cwd=True, build_cmd=_build_openai_cmd
)
```

#### 2. Update Dockerfile

Install the CLI tool in the Dockerfile (after `USER appuser`):

```dockerfile
# Example: Install via npm
RUN npm install -g @openai/cli

# Example: Install via pip
RUN pip install --user mistral-cli

# Example: Install via curl
RUN curl -fsSL https://example.com/install.sh | bash
```

#### 3. Update Environment Variables

Add the provider's auth environment variables to:
- `.env.example`
- `docker-compose.yaml`
- `README.md` (AI CLI Configuration section)

#### 4. That's It!

All existing functionality works automatically:
- Logging
- Failure deduplication
- Parallel execution
- Output formatting
- Error handling with timeouts

### Logging

Control log verbosity with `LOG_LEVEL`:

- `DEBUG` - Detailed operation logs
- `INFO` - Milestones and important events (default)
- `WARNING` - Warnings only
- `ERROR` - Errors only

### Request Override Priority

All configuration fields can be overridden per-request in the webhook payload. Required fields (`AI_PROVIDER`, `AI_MODEL`) must be set via environment variable or per-request:

| Environment Variable | Request Field        | Required | Endpoints              | Description                                                    |
|----------------------|----------------------|----------|------------------------|----------------------------------------------------------------|
| **AI Provider**      |                      |          |                        |                                                                |
| `AI_PROVIDER`        | `ai_provider`        | Yes      | Both                   | AI provider to use (`claude`, `gemini`, or `cursor`)           |
| `AI_MODEL`           | `ai_model`           | Yes      | Both                   | Model for the AI provider                                      |
| `AI_CLI_TIMEOUT`     | `ai_cli_timeout`     | No       | Both                   | AI CLI timeout in minutes (default: 10)                        |
| --                   | `raw_xml`            | No       | `/analyze-failures`    | Raw JUnit XML content (alternative to `failures`)              |
| --                   | `failures`           | No*      | `/analyze-failures`    | Raw test failure objects (alternative to `raw_xml`)             |
| **General**          |                      |          |                        |                                                                |
| `TESTS_REPO_URL`     | `tests_repo_url`     | No       | Both                   | Repository URL for test context                                |
| --                   | `raw_prompt`         | No       | Both                   | Additional AI instructions (overrides repo-level prompt file)  |
| `CALLBACK_URL`       | `callback_url`       | No       | `/analyze`             | Callback webhook URL for results                               |
| `CALLBACK_HEADERS`   | `callback_headers`   | No       | `/analyze`             | Headers for callback requests                                  |
| `HTML_REPORT`        | `html_report`        | No       | `/analyze`             | Generate HTML report (default: true)                           |
| **Jenkins**          |                      |          |                        |                                                                |
| `JENKINS_URL`        | `jenkins_url`        | Yes*     | `/analyze`             | Jenkins server URL                                             |
| `JENKINS_USER`       | `jenkins_user`       | Yes*     | `/analyze`             | Jenkins username                                               |
| `JENKINS_PASSWORD`   | `jenkins_password`   | Yes*     | `/analyze`             | Jenkins password or API token                                  |
| `JENKINS_SSL_VERIFY` | `jenkins_ssl_verify` | No       | `/analyze`             | Jenkins SSL certificate verification (default: true)           |
| **Jira**             |                      |          |                        |                                                                |
| `ENABLE_JIRA`        | `enable_jira`        | No       | Both                   | Enable/disable Jira bug search (default: auto-detect)          |
| `JIRA_URL`           | `jira_url`           | No       | Both                   | Jira instance URL                                              |
| `JIRA_EMAIL`         | `jira_email`         | No       | Both                   | Email for Jira Cloud (determines auth mode: set = Cloud, unset = Server/DC) |
| `JIRA_API_TOKEN`     | `jira_api_token`     | No       | Both                   | Backward-compatible alias for `JIRA_PAT`                       |
| `JIRA_PAT`           | `jira_pat`           | No       | Both                   | Personal Access Token (works for both Cloud and Server/DC)     |
| `JIRA_PROJECT_KEY`   | `jira_project_key`   | No       | Both                   | Scope Jira searches to a specific project                      |
| `JIRA_SSL_VERIFY`    | `jira_ssl_verify`    | No       | Both                   | SSL certificate verification for Jira (default: true)          |
| `JIRA_MAX_RESULTS`   | `jira_max_results`   | No       | Both                   | Maximum Jira results per search (default: 5)                   |
| **Build Artifact Analysis** |                    |          |                        |                                                                |
| `GET_JOB_ARTIFACTS` | `get_job_artifacts` | No | `/analyze` | Download all build artifacts for AI context (default: true) |
| `JENKINS_ARTIFACTS_MAX_SIZE_MB` | `jenkins_artifacts_max_size_mb` | No       | `/analyze`             | Maximum size per downloaded artifact in MB (default: 500) |
| `JENKINS_ARTIFACTS_CONTEXT_LINES` | `jenkins_artifacts_context_lines` | No       | `/analyze`             | Maximum context lines for AI prompt (default: 200)             |
| **GitHub**           |                      |          |                        |                                                                |
| `GITHUB_TOKEN`       | `github_token`       | No       | Both                   | GitHub API token for private repo PR status in comments        |

*Jenkins fields are required for `/analyze` but must be configured in at least one place (environment variable or request body). *Either `failures` or `raw_xml` must be provided for `/analyze-failures` (mutually exclusive).

**Server-level only** (no per-request equivalent):
- `DEBUG` — server reload toggle
- `LOG_LEVEL` — server log verbosity

**Priority**: Request values take precedence over environment variable defaults. "Both" means the field works with `/analyze` and `/analyze-failures` endpoints.

### Jira Integration (Optional)

When the AI classifies a failure as **PRODUCT BUG**, the service can optionally search Jira for existing matching bugs. This helps teams avoid filing duplicate bug reports.

#### How It Works

1. The AI analysis includes `jira_search_keywords` in the product bug report
2. After analysis completes, the service searches Jira for Bug-type issues using those keywords
3. AI evaluates each Jira candidate by reading its summary and description to determine actual relevance
4. Only relevant matches are attached to the response as `jira_matches`
5. HTML reports render matches as clickable links
6. JUnit XML reports include matches as properties

Jira integration works with all analysis endpoints: `/analyze`, `/analyze?sync=true`, and `/analyze-failures`.

#### Jira Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `JIRA_URL` | Yes* | - | Jira instance URL (Cloud or Server/DC) |
| `JIRA_PAT` | Yes* | - | Personal Access Token (works for both Cloud and Server/DC) |
| `JIRA_EMAIL` | No | - | Email for Jira Cloud — determines auth mode: if set, Cloud auth (Basic with email:PAT); if not set, Server/DC auth (Bearer PAT) |
| `JIRA_API_TOKEN` | No | - | Kept for backward compatibility (prefer `JIRA_PAT`) |
| `JIRA_PROJECT_KEY` | No | - | Scope searches to a specific project |
| `JIRA_SSL_VERIFY` | No | `true` | SSL certificate verification |
| `JIRA_MAX_RESULTS` | No | `5` | Maximum Jira results per search |

*Required only if you want to enable Jira integration. The feature is completely optional.

**Jira Cloud:**

```bash
JIRA_URL=https://your-org.atlassian.net
JIRA_EMAIL=your-email@example.com
JIRA_PAT=your-personal-access-token
```

**Jira Server/DC:**

```bash
JIRA_URL=https://jira.your-company.com
JIRA_PAT=your-personal-access-token
```

`JIRA_EMAIL` is the switch that determines which authentication mode is used. When `JIRA_EMAIL` is set, the service uses Basic authentication (email:PAT) for Jira Cloud. When `JIRA_EMAIL` is omitted, the service uses Bearer token authentication (PAT) for Jira Server/DC.

#### Error Handling

Jira failures never crash the analysis pipeline:
- **Not configured** — feature is silently disabled
- **Auth failure** — warning logged, empty matches returned
- **Network error** — error logged, empty matches returned
- **No keywords from AI** — Jira search skipped for that failure

#### Jira in API Requests

To control Jira integration per-request, use the `enable_jira` field:

```bash
# Enable Jira search for this request
curl -X POST "http://localhost:8000/analyze?sync=true" \
  -H "Content-Type: application/json" \
  -d '{
    "job_name": "my-project",
    "build_number": 123,
    "ai_provider": "claude",
    "ai_model": "sonnet",
    "enable_jira": true
  }'
```

When Jira finds matching bugs, the response includes `jira_matches` in the product bug report:

```json
{
  "analysis": {
    "classification": "PRODUCT BUG",
    "product_bug_report": {
      "title": "Authentication endpoint rejects valid credentials",
      "severity": "high",
      "component": "auth-service",
      "description": "...",
      "evidence": "...",
      "jira_search_keywords": ["authentication", "401", "valid credentials"],
      "jira_matches": [
        {
          "key": "AUTH-456",
          "summary": "Login fails with valid credentials after session timeout",
          "status": "Open",
          "priority": "High",
          "url": "https://jira.example.com/browse/AUTH-456",
          "score": 0.85
        }
      ]
    }
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `enable_jira` | bool or null | `true` to enable, `false` to disable, omit to auto-detect from environment |

When omitted, Jira integration is automatically enabled if `JIRA_URL` and authentication are configured via environment variables.

### Per-Failure Comments & Review Tracking

Each analyzed test failure supports user comments and a "Reviewed" checkbox for team collaboration.

#### Capabilities

- **Comments**: Add free-text comments to any failed test (bug links, PR links, notes). Comments are threaded with timestamps and persist across page loads.
- **Reviewed Checkbox**: Mark individual failures as reviewed so team members know which failures have been triaged.
- **Review Status Badges**: Review progress badges ("Fully Reviewed", "X/Y Reviewed", "Needs Review") and comment counts appear on the dashboard cards, the report page header, child job cards, and individual bug cards.
- **Dashboard Status**: The dashboard shows review progress per job with the same badges.
- **Comment Enrichment**: GitHub PR URLs and Jira ticket keys in comments are automatically detected and display live status badges (Merged, Open, Closed, etc.).
- **AI Context**: Historical comments from previous analyses of similar failures are fed to the AI, helping it reference existing bugs and PRs instead of suggesting duplicates.
- **Git Log Regression Check**: For CODE ISSUE classifications, the AI checks the test repo's recent git log for commits that may have caused a regression.

#### API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `GET` | `/results/{job_id}/comments` | Get all comments and review states for a job |
| `POST` | `/results/{job_id}/comments` | Add a comment to a test failure |
| `PUT` | `/results/{job_id}/reviewed` | Toggle reviewed state for a test failure |
| `GET` | `/results/{job_id}/review-status` | Get review summary (for dashboard) |
| `POST` | `/results/{job_id}/enrich-comments` | Fetch live PR/Jira statuses for comments |

#### Comment Request Body

```json
{
  "test_name": "tests.network.TestDNS.test_lookup",
  "child_job_name": "",
  "child_build_number": 0,
  "comment": "Opened bug: OCPBUGS-12345"
}
```

#### Comment Enrichment Settings

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GITHUB_TOKEN` | No | - | GitHub API token for fetching PR status from private repositories. Public repositories work without a token. This value can also be set per-request via the `github_token` field in the payload. |

Jira enrichment reuses existing Jira configuration (`JIRA_URL`, `JIRA_PAT`, and optionally `JIRA_EMAIL` for Cloud auth).

### SSL Verification

For Jenkins servers with self-signed SSL certificates, disable certificate verification:

```bash
JENKINS_SSL_VERIFY=false
```

This allows the service to connect to Jenkins instances that use self-signed or untrusted certificates. In production, it is recommended to use properly signed certificates and keep `JENKINS_SSL_VERIFY=true` (the default).

### Custom Analysis Prompt

You can customize the AI analysis behavior by placing a `JOB_INSIGHT_PROMPT.md` file in the root of your tests repository. When the service clones the tests repo (via `TESTS_REPO_URL` or the per-request `tests_repo_url` field), it automatically looks for this file and appends its content as additional instructions to the AI prompt.

This allows test repository maintainers to provide project-specific context such as:
- Domain-specific classification rules
- Known failure patterns and their categories
- Product-specific terminology and components
- Custom analysis priorities

**Example `JOB_INSIGHT_PROMPT.md`:**

```markdown
## Project Context

This is a network storage product. Common components include:
- NFS server (nfs-ganesha)
- Block storage (rbd)
- Object storage (rgw)

## Classification Rules

- Timeout errors in NFS tests are usually PRODUCT BUGs in nfs-ganesha
- Import errors are always CODE ISSUEs
- "HEALTH_WARN" in logs indicates a PRODUCT BUG in the storage cluster
```

Alternatively, you can pass a `raw_prompt` field in the request body to provide custom instructions per-request. When both are present, the request `raw_prompt` takes priority over the repo-level file.

**Example with `raw_prompt`:**

```bash
curl -X POST "http://localhost:8000/analyze?sync=true" \
  -H "Content-Type: application/json" \
  -d '{
    "job_name": "my-test-job",
    "build_number": 42,
    "ai_provider": "claude",
    "ai_model": "claude-sonnet-4-6",
    "raw_prompt": "This is an MTV product test suite. Timeout errors in migration tests are usually PRODUCT BUGs in the forklift operator. Import errors are always CODE ISSUEs."
  }'
```

**Example with `raw_prompt` from a file:**

```bash
curl -X POST "http://localhost:8000/analyze?sync=true" \
  -H "Content-Type: application/json" \
  -d "$(jq -n \
    --arg prompt "$(cat my-prompt.md)" \
    '{
      "job_name": "my-test-job",
      "build_number": 42,
      "ai_provider": "claude",
      "ai_model": "claude-sonnet-4-6",
      "raw_prompt": $prompt
    }')"
```

No server configuration is needed — the prompt file lives in your tests repository and is picked up automatically.

### Build Artifact Analysis

By default, the service downloads all build artifacts from the Jenkins build and uses them as additional artifacts context for AI analysis. This happens automatically without any extra configuration.

#### How It Works

1. The service lists all artifacts from the Jenkins build API
2. Each artifact is downloaded using existing Jenkins credentials
3. Archive files (tar.gz, zip) are automatically extracted; non-archive files are stored as-is
4. Artifacts are exposed as `build-artifacts/` in the AI workspace:
   - **With test repo configured**: artifacts are symlinked as `build-artifacts/` inside the cloned test repo directory
   - **Without test repo**: the artifacts directory itself becomes the AI working directory
5. Specific artifact types are scanned (log files for errors/warnings, event files for warnings, YAML/JSON for status issues) and an artifacts summary is injected into the AI prompt
6. The AI can directly explore the full artifact files under `build-artifacts/` for additional evidence during analysis

#### Usage

No special configuration is needed. All build artifacts are downloaded by default:

```bash
curl -X POST "http://localhost:8000/analyze?sync=true" \
  -H "Content-Type: application/json" \
  -d '{
    "job_name": "my-test-job",
    "build_number": 42,
    "ai_provider": "claude",
    "ai_model": "sonnet"
  }'
```

To disable artifact download entirely:

```bash
# Disable artifact download
curl -X POST "http://localhost:8000/analyze?sync=true" \
  -H "Content-Type: application/json" \
  -d '{
    "job_name": "my-test-job",
    "build_number": 42,
    "ai_provider": "claude",
    "ai_model": "sonnet",
    "get_job_artifacts": false
  }'
```

#### What Gets Analyzed

The service extracts and summarizes:
- **Log files** (`*.log`): Error, warning, and exception lines
- **Warning events**: Events indicating abnormal conditions
- **Status indicators**: Abnormal status conditions in artifacts data

This context helps the AI distinguish between test infrastructure issues (CODE ISSUE) and actual product problems (PRODUCT BUG).

#### Build Artifact Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `GET_JOB_ARTIFACTS` | `true` | Download all build artifacts (set `false` to disable) |
| `JENKINS_ARTIFACTS_MAX_SIZE_MB` | `500` | Maximum size per downloaded artifact in MB |
| `JENKINS_ARTIFACTS_CONTEXT_LINES` | `200` | Maximum lines of artifacts context included in AI prompt |

## API Endpoints

| Endpoint                 | Method | Description                                       |
|--------------------------|--------|---------------------------------------------------|
| `/analyze`               | POST   | Submit analysis job (async, returns 202)          |
| `/analyze?sync=true`     | POST   | Submit and wait for result (returns JSON)         |
| `/results/{job_id}`      | GET    | Retrieve stored result (JSON)                     |
| `/results/{job_id}.html` | GET    | Retrieve stored result as an HTML report (supports `?refresh=1`) |
| `/dashboard`             | GET    | HTML dashboard listing all analysis reports       |
| `/results`               | GET    | List recent analysis jobs (default: 50, max: 100) |
| `/health`                | GET    | Health check endpoint                             |
| `/favicon.ico`           | GET    | Application favicon (SVG)                         |
| `/analyze-failures`      | POST   | Analyze raw test failures directly (no Jenkins)   |

The service connects to the Jenkins instance configured via the `JENKINS_URL` environment variable. All analysis requests specify only the job name and build number.

## Request/Response Examples

### Submit Analysis (Async)

**Request:**

```bash
curl -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "job_name": "my-project",
    "build_number": 123,
    "ai_provider": "claude",
    "ai_model": "sonnet",
    "tests_repo_url": "https://github.com/org/my-project",
    "callback_url": "https://my-service.example.com/webhook",
    "callback_headers": {"Authorization": "Bearer my-token"},
    "enable_jira": true,
    "jira_project_key": "MYPROJ"
  }'
```

For jobs inside folders, use the folder path: `"job_name": "folder/subfolder/my-project"`

**Response (202 Accepted):**

```json
{
  "status": "queued",
  "message": "Analysis job queued. Poll /results/{job_id} for status.",
  "job_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

### Submit Analysis (Sync)

**Request:**

```bash
curl -X POST "http://localhost:8000/analyze?sync=true" \
  -H "Content-Type: application/json" \
  -d '{
    "job_name": "my-project",
    "build_number": 123,
    "ai_provider": "claude",
    "ai_model": "sonnet",
    "tests_repo_url": "https://github.com/org/my-project"
  }'
```

**Response (200 OK):**

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "job_name": "my-project",
  "build_number": 123,
  "jenkins_url": "https://jenkins.example.com/job/my-project/123/",
  "status": "completed",
  "summary": "2 failure(s) analyzed",
  "ai_provider": "claude",
  "ai_model": "sonnet",
  "failures": [
      {
        "test_name": "test_user_login",
        "error": "AssertionError: expected 200 but got 401",
        "analysis": {
          "classification": "PRODUCT BUG",
          "affected_tests": ["test_user_login"],
          "details": "The authentication endpoint returns 401...",
          "product_bug_report": {
            "title": "Authentication endpoint rejects valid credentials",
            "severity": "high",
            "component": "auth-service",
            "description": "...",
            "evidence": "..."
          }
        }
      }
    ],
  "child_job_analyses": [],
  "html_report_url": "/results/550e8400-e29b-41d4-a716-446655440000.html"
}
```

### Get Stored Result

**Request:**

```bash
curl http://localhost:8000/results/550e8400-e29b-41d4-a716-446655440000
```

**Response:**

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "jenkins_url": "https://jenkins.example.com/job/my-project/123/",
  "status": "completed",
  "result": {
    "job_id": "550e8400-e29b-41d4-a716-446655440000",
    "job_name": "my-project",
    "build_number": 123,
    "jenkins_url": "https://jenkins.example.com/job/my-project/123/",
    "status": "completed",
    "summary": "2 failure(s) analyzed",
    "ai_provider": "claude",
    "ai_model": "sonnet",
    "failures": [
      {
        "test_name": "test_user_login",
        "error": "AssertionError: expected 200 but got 401",
        "analysis": {
          "classification": "PRODUCT BUG",
          "affected_tests": ["test_user_login"],
          "details": "The authentication endpoint returns 401...",
          "product_bug_report": {
            "title": "Authentication endpoint rejects valid credentials",
            "severity": "high",
            "component": "auth-service",
            "description": "...",
            "evidence": "..."
          }
        }
      }
    ],
    "child_job_analyses": []
  },
  "created_at": "2024-01-15T10:30:00"
}
```

### List Recent Jobs

**Request:**

```bash
curl "http://localhost:8000/results?limit=10"
```

**Response:**

```json
[
  {
    "job_id": "550e8400-e29b-41d4-a716-446655440000",
    "job_name": "my-project",
    "build_number": 123,
    "status": "completed",
    "created_at": "2024-01-15T10:30:00"
  }
]
```

### Analyze Raw Test Failures (No Jenkins)

Analyze test failures directly without Jenkins. Accepts either raw failure data or raw JUnit XML content.

**Option 1: Raw failures (existing)**

```bash
curl -X POST http://localhost:8000/analyze-failures \
  -H "Content-Type: application/json" \
  -d '{
    "failures": [
      {
        "test_name": "tests/test_auth.py::test_login",
        "error_message": "AssertionError: expected 200 but got 401",
        "stack_trace": "...",
        "duration": 1.5,
        "status": "FAILED"
      }
    ],
    "ai_provider": "claude",
    "ai_model": "sonnet",
    "enable_jira": true,
    "ai_cli_timeout": 15
  }'
```

**Option 2: Raw JUnit XML (new)**

```bash
curl -X POST http://localhost:8000/analyze-failures \
  -H "Content-Type: application/json" \
  -d '{
    "raw_xml": "<?xml version=\"1.0\"?><testsuite name=\"tests\" tests=\"1\" failures=\"1\"><testcase classname=\"tests.test_auth\" name=\"test_login\"><failure message=\"assert False\">traceback here</failure></testcase></testsuite>",
    "ai_provider": "claude",
    "ai_model": "sonnet"
  }'
```

**Sending an XML file via curl:**

```bash
jq -n --rawfile xml report.xml \
  '{raw_xml: $xml, ai_provider: "claude", ai_model: "sonnet"}' \
  | curl -X POST http://localhost:8000/analyze-failures \
    -H "Content-Type: application/json" \
    -d @-
```

**Sending an XML file via Python:**

```python
import requests
from pathlib import Path

response = requests.post(
    "http://localhost:8000/analyze-failures",
    json={
        "raw_xml": Path("report.xml").read_text(),
        "ai_provider": "claude",
        "ai_model": "sonnet",
    },
    timeout=600,
)
result = response.json()
print(result["enriched_xml"])  # Enriched XML with analysis injected
```

When `raw_xml` is provided, the server extracts failures from the XML, runs analysis, and returns `enriched_xml` in the response with analysis results injected back into the XML.

**Response (200 OK):**

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "summary": "Analyzed 1 test failures (1 unique errors). 1 analyzed successfully.",
  "ai_provider": "claude",
  "ai_model": "sonnet",
  "failures": [
    {
      "test_name": "tests.test_auth.test_login",
      "error": "assert False",
      "analysis": {
        "classification": "PRODUCT BUG",
        "affected_tests": ["tests.test_auth.test_login"],
        "details": "The authentication endpoint returns 401...",
        "product_bug_report": {
          "title": "Authentication endpoint rejects valid credentials",
          "severity": "high",
          "component": "auth-service",
          "description": "...",
          "evidence": "..."
        }
      }
    }
  ],
  "enriched_xml": "<?xml version='1.0' encoding='utf-8'?>..."
}
```

Note: `enriched_xml` is only present when `raw_xml` was provided in the request. Provide either `failures` or `raw_xml`, not both.

### Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `job_id` | string | Unique identifier for the analysis job |
| `jenkins_url` | string | URL of the analyzed Jenkins build |
| `status` | string | Analysis status: `pending`, `running`, `completed`, or `failed` |
| `summary` | string | Summary of the analysis findings |
| `html_report_url` | string | URL to view the HTML report (only present when `html_report` is enabled) |

For the full result (via `/results/{job_id}`), each failure contains:

| Field | Type | Description |
|-------|------|-------------|
| `test_name` | string | Name of the failed test |
| `error` | string | Error message or exception |
| `analysis.classification` | string | `CODE ISSUE` or `PRODUCT BUG` |
| `analysis.details` | string | Detailed AI analysis text |
| `analysis.code_fix` | object | Code fix suggestion (file, line, change) — present only for CODE ISSUE |
| `analysis.product_bug_report` | object | Bug report (title, severity, component, description, evidence) — present only for PRODUCT BUG |

## Output Formats

By default, HTML reports are automatically generated and saved alongside JSON results. The sync response includes an `html_report_url` field with the link. Set `html_report` to `false` to disable HTML generation.

### JSON

```bash
# Sync analysis — returns JSON
curl -X POST "http://localhost:8000/analyze?sync=true" \
  -H "Content-Type: application/json" \
  -d '{"job_name": "my-project", "build_number": 123, "ai_provider": "claude", "ai_model": "sonnet"}'
```

### HTML Report

Retrieve an analysis as a self-contained HTML report with a dark theme and collapsible failure details. While the analysis is still running, the HTML endpoint serves a status page that auto-refreshes every 10 seconds:

```bash
curl http://localhost:8000/results/550e8400-e29b-41d4-a716-446655440000.html -o report.html

# Open in browser
open report.html  # macOS
xdg-open report.html  # Linux
```

By default, HTML reports are served from disk cache once generated. To force regeneration of the report from stored data, append the `?refresh=1` query parameter:

```bash
curl http://localhost:8000/results/550e8400-e29b-41d4-a716-446655440000.html?refresh=1 -o report.html
```

This is useful after server code updates when cached reports may be stale and need to reflect the latest rendering logic.

The HTML report includes:

- **Sticky header** with job name, build number, and failure count badge
- **Root cause analysis cards** grouped by bug, with BUG-ID, classification, and severity badges
- **Collapsible bug cards** with AI analysis, code fix or product bug report details, affected tests list, and error details
- **All failures table** listing every failure with test name, error, classification, and bug reference
- **Key takeaway** callout summarizing the analysis

The report is fully self-contained (no external CSS/JS) and can be shared as a single file.

## pytest Integration

Enrich JUnit XML reports with AI-powered failure analysis. After tests complete, the plugin parses the JUnit XML for failures, sends them to the jenkins-job-insight server, and injects analysis results back into the XML.

**Safety**: The plugin never fails pytest or corrupts the original JUnit XML. All operations are wrapped in error handling with XML backup/restore.

### Setup

1. Copy `examples/pytest-junitxml/conftest_junit_ai.py` and `examples/pytest-junitxml/conftest_junit_ai_utils.py` to your project root
2. Rename `conftest_junit_ai.py` to `conftest.py`
3. Install dependencies: `pip install requests python-dotenv`
3. Create a `.env` file or set environment variables:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `JJI_SERVER_URL` | Yes | - | Jenkins Job Insight server URL |
| `JJI_AI_PROVIDER` | No | `claude` | AI provider: claude, gemini, or cursor |
| `JJI_AI_MODEL` | No | `claude-opus-4-6[1m]` | AI model to use |
| `JJI_TIMEOUT` | No | `600` | Request timeout in seconds |

### Usage

```bash
# Run tests with AI analysis
pytest --junitxml=report.xml --analyze-with-ai

# Without the flag, the plugin is inactive (zero overhead)
pytest --junitxml=report.xml
```

### How It Works

1. pytest runs tests and generates JUnit XML as usual
2. At session finish, the conftest reads the raw XML file
3. `jenkins_job_insight.xml_enrichment` sends the XML to the `/analyze-failures` endpoint
4. The server extracts failures, runs AI analysis, and returns enriched XML
5. The conftest writes the enriched XML back to the same file
6. No global state or runtime collection -- works with pytest-xdist parallel execution

### What Gets Injected

For each failed test case, the JUnit XML is enriched with:

**`<properties>`** (machine-readable, for CI tool parsing):
- `ai_classification` -- "CODE ISSUE" or "PRODUCT BUG"
- `ai_details` -- detailed analysis text
- `ai_affected_tests` -- related tests with the same root cause
- Code fix or product bug report fields

**`<system-out>`** (human-readable, visible in Jenkins test details):
- Formatted analysis text with classification, details, and fix/bug information

## Development

### Prerequisites

- Python 3.11 or higher
- Git

### Setup

```bash
# Clone the repository
git clone https://github.com/your-org/jenkins-job-insight.git
cd jenkins-job-insight

# Install with development dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run locally with hot reload
DEBUG=true jenkins-job-insight
```

### Environment File

Create a `.env` file for local development:

```bash
JENKINS_URL=https://jenkins.example.com
JENKINS_USER=your-username
JENKINS_PASSWORD=your-api-token
AI_PROVIDER=claude
AI_MODEL=your-model-name
LOG_LEVEL=INFO
```

## Docker Build

```bash
# Build the image
docker build -t jenkins-job-insight .

# Create data directory for SQLite persistence (required)
mkdir -p data

# Run with volume mount for persistent storage
docker run -d \
  -p 8000:8000 \
  -v ./data:/data \
  -e JENKINS_URL=https://jenkins.example.com \
  -e JENKINS_USER=your-username \
  -e JENKINS_PASSWORD=your-api-token \
  -e AI_PROVIDER=claude \
  -e AI_MODEL=your-model-name \
  jenkins-job-insight
```

> **Note:** The `data` directory must exist on the host before starting the container. Docker creates mounted directories as root, but the container runs as a non-root user for security.

The `/data` volume mount ensures SQLite database persistence across container restarts.

## Architecture

```text
┌─────────────────┐     ┌──────────────────────────────────────────────┐
│  Jenkins        │     │  Jenkins Job Insight                         │
│  Webhook/       │────▶│                                              │
│  API Request    │     │  1. Receive request with job name + build #  │
└─────────────────┘     │  2. Fetch console log and build info         │
                        │  3. Optionally clone repo for context        │
                        │  4. Send to AI for classification            │
                        │  5. Store result in SQLite                   │
                        │  6. Deliver via callback webhook             │
                        └──────────────────────────────────────────────┘
                                         │
                                         ▼
                                 ┌───────────────┐
                                 │  Callback     │
                                 │  Webhook      │
                                 └───────────────┘
```

### Analysis Flow

1. **Receive request**: Accept webhook or API request containing the job name and build number
2. **Fetch Jenkins data**: Retrieve console output and build information from the configured Jenkins instance
3. **Clone repository** (optional): Clone the source repository for additional context
4. **AI analysis**: Send collected data to the configured AI provider (Claude, Gemini, or Cursor)
5. **Classify failures**: AI determines if each failure is a code issue or product bug
6. **Store result**: Save analysis to SQLite database for retrieval
7. **Generate HTML report**: Save self-contained HTML report to disk (if enabled)
8. **Deliver result**: Send to callback URL

## License

MIT
