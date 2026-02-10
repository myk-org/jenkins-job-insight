# Jenkins Job Insight

A containerized webhook service that analyzes Jenkins job failures, classifies them as code issues or product bugs, and provides actionable suggestions. This service operates without a UI, receiving requests via webhooks and delivering results through callbacks or Slack notifications.

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
- **Slack notifications**: Sends formatted analysis summaries to Slack channels
- **Hierarchical result messages**: Pre-split analysis output into structured messages (summary, failure details, child jobs) for any consumer

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
| **Notifications** | | | |
| `SLACK_WEBHOOK_URL` | No | - | Default Slack incoming webhook URL |
| `CALLBACK_URL` | No | - | Default callback URL for results (can be overridden per-request) |
| `CALLBACK_HEADERS` | No | - | Default callback headers as JSON (can be overridden per-request) |
| **Other** | | | |
| `TESTS_REPO_URL` | No | - | Default tests repository URL (can be overridden per-request) |
| `PROMPT_FILE` | No | `/app/PROMPT.md` | Path to custom analysis prompt file |
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

```bash
AI_PROVIDER=cursor
CURSOR_API_KEY=your-cursor-api-key

# Specify the model
AI_MODEL=claude-3.5-sonnet
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

| Environment Variable | Request Field | Required | Description |
|----------------------|---------------|----------|-------------|
| `AI_PROVIDER` | `ai_provider` | Yes | AI provider to use (`claude`, `gemini`, or `cursor`) |
| `AI_MODEL` | `ai_model` | Yes | Model for the AI provider |
| `TESTS_REPO_URL` | `tests_repo_url` | No | Repository URL for test context |
| `CALLBACK_URL` | `callback_url` | No | Callback webhook URL for results |
| `CALLBACK_HEADERS` | `callback_headers` | No | Headers for callback requests |
| `SLACK_WEBHOOK_URL` | `slack_webhook_url` | No | Slack notification URL |

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

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/analyze` | POST | Submit analysis job with job name and build number (async, returns 202) |
| `/analyze?sync=true` | POST | Submit and wait for result |
| `/results/{job_id}` | GET | Retrieve stored result by job ID |
| `/results` | GET | List recent analysis jobs (default: 50, max: 100) |
| `/health` | GET | Health check endpoint |

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
    "slack_webhook_url": "https://hooks.slack.com/services/xxx/yyy/zzz"
  }'
```

For jobs inside folders, use the folder path: `"job_name": "folder/subfolder/my-project"`

**Response (202 Accepted):**

```json
{
  "status": "queued",
  "message": "Analysis job queued. Results will be delivered to callback/slack."
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
  "jenkins_url": "https://jenkins.example.com/job/my-project/123/",
  "status": "completed",
  "summary": "2 failure(s) analyzed (2 unique error type(s))",
  "failures": [
    {
      "test_name": "test_user_login",
      "error": "AssertionError: expected 200 but got 401",
      "analysis": "=== CLASSIFICATION ===\nPRODUCT BUG\n\n=== ANALYSIS ===\nThe authentication endpoint returns 401..."
    },
    {
      "test_name": "test_timeout_handling",
      "error": "TimeoutError: operation timed out after 5s",
      "analysis": "=== CLASSIFICATION ===\nCODE ISSUE\n\n=== ANALYSIS ===\nThe test timeout is too short..."
    }
  ],
  "child_job_analyses": [],
  "messages": [
    {
      "type": "summary",
      "text": "Job URL: https://jenkins.example.com/job/my-project/123/\nStatus: completed\n..."
    },
    {
      "type": "failure_detail",
      "text": "[1] (1 test(s) with same error)\nTest: test_user_login\nError: AssertionError..."
    },
    {
      "type": "failure_detail",
      "text": "[2] (1 test(s) with same error)\nTest: test_timeout_handling\nError: TimeoutError..."
    }
  ]
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
  "job_name": "my-project",
  "build_number": 123,
  "status": "completed",
  "result": { ... },
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

### Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `job_id` | string | Unique identifier for the analysis job |
| `jenkins_url` | string | URL of the analyzed Jenkins build |
| `status` | string | Analysis status: `pending`, `running`, `completed`, or `failed` |
| `summary` | string | Summary of the analysis findings |
| `failures` | array | List of analyzed failures with `test_name`, `error`, and `analysis` |
| `child_job_analyses` | array | Analyses of failed child jobs in pipelines (recursive) |
| `messages` | array | Pre-built result messages for hierarchical output |

#### Hierarchical Messages

The `messages` field contains pre-split, structured text sections that any consumer can use. Each message has a `type` and `text`:

| Message Type | Description |
|-------------|-------------|
| `summary` | Job overview: URL, status, AI provider info, failure/child job counts |
| `failure_detail` | One per unique failure group (deduplicated by analysis text) |
| `child_job` | One per child job analysis |

Messages target under 3K characters each, with automatic line-boundary splitting for oversized content. Slack delivery uses these messages directly; other consumers (callbacks, UIs, CLI tools) can use them for structured display.

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
                        │  6. Deliver via callback webhook / Slack     │
                        └──────────────────────────────────────────────┘
                                         │
                                         ▼
                        ┌────────────────┴────────────────┐
                        │                                 │
                        ▼                                 ▼
                ┌───────────────┐                 ┌───────────────┐
                │  Callback     │                 │  Slack        │
                │  Webhook      │                 │  Notification │
                └───────────────┘                 └───────────────┘
```

### Analysis Flow

1. **Receive request**: Accept webhook or API request containing the job name and build number
2. **Fetch Jenkins data**: Retrieve console output and build information from the configured Jenkins instance
3. **Clone repository** (optional): Clone the source repository for additional context
4. **AI analysis**: Send collected data to the configured AI provider (Claude, Gemini, or Cursor)
5. **Classify failures**: AI determines if each failure is a code issue or product bug
6. **Store result**: Save analysis to SQLite database for retrieval
7. **Deliver result**: Send to callback URL and/or Slack webhook

## License

MIT
