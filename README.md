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
- **SQLite result storage**: Persists analysis results for later retrieval
- **Callback webhooks**: Delivers results to your specified endpoint with custom headers
- **HTML report output**: Generate self-contained, dark-themed HTML failure reports viewable in any browser
- **Direct failure analysis**: Analyze raw test failures without Jenkins via `POST /analyze-failures`
- **pytest JUnit XML integration**: Enrich JUnit XML reports with AI analysis using a standalone conftest.py

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
| `PROMPT_FILE` | No | `/app/PROMPT.md` | Path to custom analysis prompt file |
| `HTML_REPORT` | No | `true` | Generate HTML reports (set to `false` to disable) |
| `DEBUG` | No | `false` | Enable debug mode with hot reload for development |

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

| Environment Variable | Request Field      | Required | Description                                                                |
|----------------------|--------------------|----------|----------------------------------------------------------------------------|
| `AI_PROVIDER`        | `ai_provider`      | Yes      | AI provider to use (`claude`, `gemini`, or `cursor`)                       |
| `AI_MODEL`           | `ai_model`         | Yes      | Model for the AI provider                                                  |
| `TESTS_REPO_URL`     | `tests_repo_url`   | No       | Repository URL for test context                                            |
| `CALLBACK_URL`       | `callback_url`     | No       | Callback webhook URL for results                                           |
| `CALLBACK_HEADERS`   | `callback_headers` | No       | Headers for callback requests                                              |
| `HTML_REPORT`        | `html_report`      | No       | Generate HTML report (default: true)                                       |

**Priority**: Request values take precedence over environment variable defaults. Required fields must be configured in at least one place (environment variable or request body).

### SSL Verification

For Jenkins servers with self-signed SSL certificates, disable certificate verification:

```bash
JENKINS_SSL_VERIFY=false
```

This allows the service to connect to Jenkins instances that use self-signed or untrusted certificates. In production, it is recommended to use properly signed certificates and keep `JENKINS_SSL_VERIFY=true` (the default).

### Custom Analysis Prompt

You can customize the AI analysis behavior by mounting a custom `PROMPT.md` file. The service looks for the prompt at the path specified by `PROMPT_FILE` (default: `/app/PROMPT.md`). If the file exists, its content is used as the system prompt for AI analysis; otherwise, the built-in default prompt is used.

**Docker run example:**

```bash
docker run -d \
  -p 8000:8000 \
  -v ./data:/data \
  -v ./my-prompt.md:/app/PROMPT.md:ro \
  -e JENKINS_URL=https://jenkins.example.com \
  -e JENKINS_USER=your-username \
  -e JENKINS_PASSWORD=your-api-token \
  -e AI_PROVIDER=claude \
  jenkins-job-insight
```

**Docker Compose example:**

```yaml
services:
  jenkins-job-insight:
    image: jenkins-job-insight
    ports:
      - "8000:8000"
    volumes:
      - ./data:/data
      - ./PROMPT.md:/app/PROMPT.md:ro  # Mount custom prompt (read-only)
    env_file:
      - .env
```

The custom prompt should include instructions for the AI on how to analyze Jenkins failures and format the JSON response. Refer to the built-in default prompt as a starting point.

## API Endpoints

| Endpoint                 | Method | Description                                       |
|--------------------------|--------|---------------------------------------------------|
| `/analyze`               | POST   | Submit analysis job (async, returns 202)          |
| `/analyze?sync=true`     | POST   | Submit and wait for result (returns JSON)         |
| `/results/{job_id}`      | GET    | Retrieve stored result (JSON)                     |
| `/results/{job_id}.html` | GET    | Retrieve stored result as an HTML report          |
| `/results`               | GET    | List recent analysis jobs (default: 50, max: 100) |
| `/health`                | GET    | Health check endpoint                             |
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
    "callback_headers": {"Authorization": "Bearer my-token"}
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

Analyze test failures directly without Jenkins. Accepts raw failure data and returns AI analysis.

**Request:**

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
    "ai_model": "sonnet"
  }'
```

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
      "test_name": "tests/test_auth.py::test_login",
      "error": "AssertionError: expected 200 but got 401",
      "analysis": {
        "classification": "PRODUCT BUG",
        "affected_tests": ["tests/test_auth.py::test_login"],
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
  ]
}
```

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

Retrieve a completed analysis as a self-contained HTML report with a dark theme and collapsible failure details:

```bash
curl http://localhost:8000/results/550e8400-e29b-41d4-a716-446655440000.html -o report.html

# Open in browser
open report.html  # macOS
xdg-open report.html  # Linux
```

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
4. Create a `.env` file or set environment variables:

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
2. At session finish, the plugin parses the XML for `<failure>` and `<error>` elements
3. Failures are POSTed to the `/analyze-failures` endpoint
4. AI analysis results are injected back into the XML as `<properties>` and `<system-out>`
5. No global state or runtime collection -- works with pytest-xdist parallel execution

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
