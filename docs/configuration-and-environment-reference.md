# Configuration and Environment Reference

> **Note:** `Settings`-backed variables support a local `.env` file. Variables marked `process env` are read directly with `os.getenv()` and must already be in the real environment when the server or CLI process starts. `docker-compose.yaml` in this repository injects `.env` into the container, so both kinds work there.

## Server Environment Variables

### Analysis Runtime

Default AI selection and timeout settings for analysis requests.

| Name | Type | Default | Loaded by | Description |
| --- | --- | --- | --- | --- |
| `AI_PROVIDER` | string | `unset` | `process env` | Primary analysis provider. Valid values: `claude`, `gemini`, `cursor`. Required unless the request body provides `ai_provider`. |
| `AI_MODEL` | string | `unset` | `process env` | Primary analysis model. Required unless the request body provides `ai_model`. |
| `AI_CLI_TIMEOUT` | integer (minutes) | `10` | `Settings` | Timeout for AI CLI calls. |

```bash
AI_PROVIDER=claude
AI_MODEL=claude-opus-4-1
AI_CLI_TIMEOUT=15
```

Effect: `POST /analyze` and `POST /analyze-failures` use these values when the request body omits them. Missing or invalid `AI_PROVIDER`/`AI_MODEL` returns `400`.

### Jenkins Connection and Artifact Collection

Default Jenkins access, wait behavior, and artifact download limits for Jenkins-backed analysis.

| Name | Type | Default | Loaded by | Description |
| --- | --- | --- | --- | --- |
| `JENKINS_URL` | string | `""` | `Settings` | Default Jenkins base URL for `POST /analyze`. |
| `JENKINS_USER` | string | `""` | `Settings` | Default Jenkins username. |
| `JENKINS_PASSWORD` | string | `""` | `Settings` | Default Jenkins password or API token. |
| `JENKINS_SSL_VERIFY` | boolean | `true` | `Settings` | TLS verification for Jenkins requests. |
| `WAIT_FOR_COMPLETION` | boolean | `true` | `Settings` | Default wait behavior before starting analysis. |
| `POLL_INTERVAL_MINUTES` | integer (minutes) | `2` | `Settings` | Default poll interval while waiting for Jenkins completion. |
| `MAX_WAIT_MINUTES` | integer (minutes) | `0` | `Settings` | Default maximum wait time. `0` means no limit. |
| `GET_JOB_ARTIFACTS` | boolean | `true` | `Settings` | Default artifact download toggle. |
| `JENKINS_ARTIFACTS_MAX_SIZE_MB` | integer (MB) | `500` | `Settings` | Maximum total artifact size processed for AI context. |

```bash
JENKINS_URL=https://jenkins.example.com
JENKINS_USER=svc-jji
JENKINS_PASSWORD=your-api-token
JENKINS_SSL_VERIFY=true
WAIT_FOR_COMPLETION=true
POLL_INTERVAL_MINUTES=2
MAX_WAIT_MINUTES=30
GET_JOB_ARTIFACTS=true
JENKINS_ARTIFACTS_MAX_SIZE_MB=500
```

Effect: These defaults apply only to `POST /analyze`. If `WAIT_FOR_COMPLETION=true` but no Jenkins URL is available after request merge, the server skips the waiting phase. Artifact processing runs only when `GET_JOB_ARTIFACTS=true` and the Jenkins build exposes artifacts.

### Repository Context and Peer Analysis

Default repository cloning and multi-model review settings.

| Name | Type | Default | Loaded by | Description |
| --- | --- | --- | --- | --- |
| `TESTS_REPO_URL` | string | `unset` | `Settings` | Default tests repository URL. `url:ref` syntax is accepted. |
| `ADDITIONAL_REPOS` | string | `""` | `Settings` | Default additional repo list in `name:url,name:url` format. Each URL may also use `url:ref`. |
| `PEER_AI_CONFIGS` | string | `""` | `Settings` | Default peer analysis list in `provider:model,provider:model` format. |
| `PEER_ANALYSIS_MAX_ROUNDS` | integer | `3` | `Settings` | Maximum peer debate rounds. Allowed range: `1`-`10`. |

```bash
TESTS_REPO_URL=https://github.com/acme/tests:release-1.2
ADDITIONAL_REPOS=infra:https://github.com/acme/infra:main,product:https://github.com/acme/product
PEER_AI_CONFIGS=cursor:gpt-5.4-xhigh,gemini:gemini-2.5-pro
PEER_ANALYSIS_MAX_ROUNDS=3
```

Effect: `TESTS_REPO_URL` is cloned into the analysis workspace. `ADDITIONAL_REPOS` entries are cloned into named subdirectories. Malformed repo or peer strings fail when the request resolves them.

### Jira Analysis and Issue Toggles

Default Jira connection settings for analysis-time enrichment and Jira issue operations.

| Name | Type | Default | Loaded by | Description |
| --- | --- | --- | --- | --- |
| `JIRA_URL` | string | `unset` | `Settings` | Jira base URL. |
| `JIRA_EMAIL` | string | `unset` | `Settings` | Jira Cloud email. When present, Jira auth resolves in Cloud mode. |
| `JIRA_API_TOKEN` | string | `unset` | `Settings` | Jira Cloud API token. |
| `JIRA_PAT` | string | `unset` | `Settings` | Jira Server/DC personal access token. |
| `JIRA_PROJECT_KEY` | string | `unset` | `Settings` | Default Jira project key for search and issue targeting. |
| `JIRA_SSL_VERIFY` | boolean | `true` | `Settings` | TLS verification for Jira requests. |
| `JIRA_MAX_RESULTS` | integer | `5` | `Settings` | Maximum Jira results returned per search. |
| `ENABLE_JIRA` | boolean | `unset` | `Settings` | Analysis-time Jira enrichment toggle. |
| `ENABLE_JIRA_ISSUES` | boolean | `unset` | `Settings` | Jira preview/create toggle. `false` disables Jira issue endpoints. |

```bash
JIRA_URL=https://acme.atlassian.net
JIRA_EMAIL=triage@example.com
JIRA_API_TOKEN=your-jira-token
JIRA_PROJECT_KEY=PROJ
JIRA_SSL_VERIFY=true
JIRA_MAX_RESULTS=5
ENABLE_JIRA=true
ENABLE_JIRA_ISSUES=true
```

Effect: Analysis-time Jira enrichment runs only when `ENABLE_JIRA` is not `false` and Jira URL, credentials, and project key are all present. Jira issue preview/create is controlled independently by `ENABLE_JIRA_ISSUES`. Auth resolution is:
- with `JIRA_EMAIL`: Cloud mode, token preference `JIRA_API_TOKEN` then `JIRA_PAT`
- without `JIRA_EMAIL`: Server/DC mode, token preference `JIRA_PAT` then `JIRA_API_TOKEN`

### GitHub Issue Creation

Default GitHub credential and feature toggle settings.

| Name | Type | Default | Loaded by | Description |
| --- | --- | --- | --- | --- |
| `GITHUB_TOKEN` | string | `unset` | `Settings` | Default server GitHub token. |
| `ENABLE_GITHUB_ISSUES` | boolean | `unset` | `Settings` | GitHub preview/create toggle. `false` disables GitHub issue endpoints. |

```bash
GITHUB_TOKEN=ghp_your_token
ENABLE_GITHUB_ISSUES=true
```

Effect: `ENABLE_GITHUB_ISSUES=false` blocks GitHub issue preview/create. When the toggle is not `false`, `/api/capabilities` reports server token presence separately through `server_github_token`.

### Report Portal and Public URLs

Default Report Portal connection settings and absolute-link base URL.

| Name | Type | Default | Loaded by | Description |
| --- | --- | --- | --- | --- |
| `REPORTPORTAL_URL` | string | `unset` | `Settings` | Report Portal base URL. |
| `REPORTPORTAL_API_TOKEN` | string | `unset` | `Settings` | Report Portal API token. |
| `REPORTPORTAL_PROJECT` | string | `unset` | `Settings` | Report Portal project name. |
| `REPORTPORTAL_VERIFY_SSL` | boolean | `true` | `Settings` | TLS verification for Report Portal requests. |
| `ENABLE_REPORTPORTAL` | boolean | `unset` | `Settings` | Explicit Report Portal toggle. `false` disables the integration. |
| `PUBLIC_BASE_URL` | string | `unset` | `Settings` | Trusted external base URL used when building absolute links. Trailing `/` is stripped. |

```bash
REPORTPORTAL_URL=https://rp.example.com
REPORTPORTAL_API_TOKEN=rp-token
REPORTPORTAL_PROJECT=e2e
REPORTPORTAL_VERIFY_SSL=true
ENABLE_REPORTPORTAL=true
PUBLIC_BASE_URL=https://jji.example.com
```

Effect: Report Portal is enabled only when `ENABLE_REPORTPORTAL` is not `false` and URL, token, and project are all set. `PUBLIC_BASE_URL` controls absolute `result_url` values and is required for `POST /results/{job_id}/push-reportportal`. When `PUBLIC_BASE_URL` is unset, the server returns relative URLs.

> **Note:** Request headers do not change `PUBLIC_BASE_URL`. When unset, `base_url` is `""` and `result_url` is relative.

### Authentication and Secret Handling

Bootstrap admin authentication, cookie security, and at-rest encryption.

| Name | Type | Default | Loaded by | Description |
| --- | --- | --- | --- | --- |
| `ADMIN_KEY` | string | `""` | `Settings` | Bootstrap admin secret. `POST /api/auth/login` accepts it only with username `admin`. Bearer `Authorization: Bearer <ADMIN_KEY>` also authenticates as admin. |
| `ALLOWED_USERS` | string | `""` | `Settings` | Comma-separated list of usernames allowed to create/modify data (analyses, comments, reviews, classifications). Empty = open access (all users allowed). Admin users always bypass. Case-insensitive. |
| `SECURE_COOKIES` | boolean | `true` | `Settings` | `Secure` attribute for `jji_session` and `jji_username` cookies. |
| `JJI_ENCRYPTION_KEY` | string | `unset` | `process env` | Secret used to encrypt stored sensitive values and HMAC-hash stored admin API keys. |
| `XDG_DATA_HOME` | path | `~/.local/share` | `process env` | Base directory for the fallback encryption key file when `JJI_ENCRYPTION_KEY` is unset. |

```bash
ADMIN_KEY=change-this-admin-secret
ALLOWED_USERS=alice,bob,carol
SECURE_COOKIES=true
JJI_ENCRYPTION_KEY=change-this-encryption-secret
XDG_DATA_HOME=/var/lib/jji
```

Effect: Request auth order is `jji_session` cookie, then Bearer token, then `jji_username` cookie. Admin login sets:
- `jji_session`: `HttpOnly`, `SameSite=Strict`, `max-age=8h`
- `jji_username`: `SameSite=Lax`, `max-age=1 year`

If `JJI_ENCRYPTION_KEY` is unset, the server creates and reuses `$XDG_DATA_HOME/jji/.encryption_key` or `~/.local/share/jji/.encryption_key` with mode `0600`.

> **Warning:** Changing `JJI_ENCRYPTION_KEY` invalidates stored API key hashes and can leave previously stored encrypted request values undecryptable.

### Storage and Process Runtime

Database location, bind port, reload mode, and log level.

| Name | Type | Default | Loaded by | Description |
| --- | --- | --- | --- | --- |
| `DB_PATH` | path | `/data/results.db` | `process env` | SQLite database path. |
| `PORT` | integer | `8000` | `process env` | Application port. Valid range: `1`-`65535`. |
| `DEBUG` | boolean | `false` | `process env` | Enables `uvicorn` reload when the app is started through `jenkins_job_insight.main:run`. |
| `LOG_LEVEL` | string | `INFO` | `process env` | Process-wide log level. |

```bash
DB_PATH=/var/lib/jji/results.db
PORT=8000
DEBUG=false
LOG_LEVEL=INFO
```

Effect: `PORT` is used both for server binding and for the app's internal self-references. Invalid `PORT` values stop startup.

### Provider CLI Passthrough and Container Dev Mode

Provider-specific auth variables and container-only dev-mode switches.

| Name | Type | Default | Loaded by | Description |
| --- | --- | --- | --- | --- |
| `ANTHROPIC_API_KEY` | string | `unset` | `process env` | Claude CLI API key. |
| `CLAUDE_CODE_USE_VERTEX` | boolean/string | `unset` | `process env` | Enables Claude CLI Vertex mode when set. |
| `CLOUD_ML_REGION` | string | `unset` | `process env` | Claude Vertex region. |
| `ANTHROPIC_VERTEX_PROJECT_ID` | string | `unset` | `process env` | Claude Vertex project ID. |
| `GEMINI_API_KEY` | string | `unset` | `process env` | Gemini CLI API key. |
| `CURSOR_API_KEY` | string | `unset` | `process env` | Cursor CLI API key. |
| `DEV_MODE` | boolean | `unset` | `process env` | Container entrypoint dev mode. Starts the Vite dev server and adds `uvicorn --reload` behavior. |

```bash
ANTHROPIC_API_KEY=your-anthropic-key
# or Claude via Vertex:
CLAUDE_CODE_USE_VERTEX=1
CLOUD_ML_REGION=us-east5
ANTHROPIC_VERTEX_PROJECT_ID=my-gcp-project

GEMINI_API_KEY=your-gemini-key
CURSOR_API_KEY=your-cursor-key
DEV_MODE=true
```

Effect: These variables are not parsed by `Settings`; they are consumed by installed provider CLIs or by `entrypoint.sh`. In the container, `DEV_MODE=true` starts the frontend dev server on port `5173` and appends `--reload --reload-dir /app/src` to `uvicorn`.

## Docker Compose

### `docker-compose.yaml` Service: `jenkins-job-insight`

Repository-provided container settings for the combined API and web UI service.

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `services.jenkins-job-insight.build.context` | path | `.` | Build context. |
| `services.jenkins-job-insight.build.dockerfile` | path | `Dockerfile` | Dockerfile path. |
| `services.jenkins-job-insight.container_name` | string | `jenkins-job-insight` | Container name. |
| `services.jenkins-job-insight.ports` | list | `["8000:8000"]` | Publishes the combined web UI and API port. |
| `services.jenkins-job-insight.volumes` | list | `["./data:/data"]` | Persists SQLite data on the host. |
| `services.jenkins-job-insight.env_file` | list | `[".env"]` | Injects environment variables from `.env`. |
| `services.jenkins-job-insight.restart` | string | `unless-stopped` | Restart policy. |
| `services.jenkins-job-insight.healthcheck.test` | array | `["CMD","curl","-f","http://localhost:8000/health"]` | Health check command. |
| `services.jenkins-job-insight.healthcheck.interval` | duration | `30s` | Health check interval. |
| `services.jenkins-job-insight.healthcheck.timeout` | duration | `10s` | Health check timeout. |
| `services.jenkins-job-insight.healthcheck.retries` | integer | `3` | Health check retry count. |
| `services.jenkins-job-insight.healthcheck.start_period` | duration | `10s` | Health check start period. |

```yaml
services:
  jenkins-job-insight:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: jenkins-job-insight
    ports:
      - "8000:8000"
    volumes:
      - ./data:/data
    env_file:
      - .env
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s
```

Effect: The service stores its database under the host `./data` directory and exposes both the React UI and API on port `8000`.

> **Note:** `docker-compose.yaml` includes commented optional settings for:
> - `5173:5173` frontend HMR port publishing
> - `./src:/app/src` and `./frontend:/app/frontend` source mounts
> - `~/.config/gcloud:/home/appuser/.config/gcloud:ro` for Claude Vertex credentials

## CLI Configuration File

### File Location and Sections

Named server profiles for the `jji` CLI.

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| ``$XDG_CONFIG_HOME/jji/config.toml`` | path | `~/.config/jji/config.toml` | Main CLI config file location. |
| `[default].server` | string | `""` | Default server profile name. |
| `[defaults]` | mapping | `{}` | Shared values merged into every server profile. |
| `[servers.<name>]` | mapping | required per profile | Named server profiles. Each profile requires `url`. |

```toml
[default]
server = "prod"

[defaults]
ai_provider = "claude"
ai_model = "claude-opus-4-1"

[servers.prod]
url = "https://jji.example.com"
username = "alice"
no_verify_ssl = false
```

Effect: `[defaults]` values are merged first, then `[servers.<name>]` overrides them. `[defaults].server` is not supported. `servers.<name>.url` and `[default].server` must be non-empty trimmed strings.

### Connection Profile Fields

Fields used to connect the CLI to a JJI server.

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `url` | string | none | Base URL of the JJI server. Required for each profile. |
| `username` | string | `""` | Username cookie sent by the CLI for user-scoped actions such as comments and reviews. |
| `no_verify_ssl` | boolean | `false` | Disable TLS verification for CLI HTTP requests. |
| `api_key` | string | `""` | Admin API key sent as a Bearer token by the CLI. |

```toml
[servers.prod]
url = "https://jji.example.com"
username = "alice"
no_verify_ssl = false
api_key = "admin-api-key"
```

Effect: If `--server` or `JJI_SERVER` is a full URL, the CLI does not inherit any other values from `config.toml`.

### Analysis Default Fields

Client-side defaults that `jji analyze` can send when you omit CLI flags.

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `jenkins_url` | string | `""` | Default Jenkins URL. |
| `jenkins_user` | string | `""` | Default Jenkins username. |
| `jenkins_password` | string | `""` | Default Jenkins password or API token. |
| `jenkins_ssl_verify` | boolean | `unset` | Default Jenkins TLS verification. |
| `tests_repo_url` | string | `""` | Default tests repo URL. |
| `ai_provider` | string | `""` | Default AI provider. |
| `ai_model` | string | `""` | Default AI model. |
| `ai_cli_timeout` | integer | `0` | CLI sentinel for "use server default". |
| `jira_url` | string | `""` | Default Jira URL. |
| `jira_email` | string | `""` | Default Jira email. |
| `jira_api_token` | string | `""` | Default Jira API token. |
| `jira_pat` | string | `""` | Default Jira PAT. |
| `jira_project_key` | string | `""` | Default Jira project key. |
| `jira_ssl_verify` | boolean | `unset` | Default Jira TLS verification. |
| `jira_max_results` | integer | `0` | CLI sentinel for "use server default". |
| `enable_jira` | boolean | `unset` | Default Jira enrichment toggle. |
| `github_token` | string | `""` | Default GitHub token. |
| `peers` | string | `""` | Default peer configs in `provider:model,provider:model` format. |
| `peer_analysis_max_rounds` | integer | `0` | CLI sentinel for "use server default". |
| `additional_repos` | string | `""` | Default additional repo list in `name:url,name:url` format. |
| `wait_for_completion` | boolean | `unset` | Default wait toggle. |
| `poll_interval_minutes` | integer | `0` | CLI sentinel for "use server default". |
| `max_wait_minutes` | integer | `0` | CLI sentinel for "use server default". |

```toml
[defaults]
jenkins_url = "https://jenkins.example.com"
tests_repo_url = "https://github.com/acme/tests"
ai_provider = "claude"
ai_model = "claude-opus-4-1"
wait_for_completion = true
poll_interval_minutes = 2
max_wait_minutes = 30
peers = "cursor:gpt-5.4-xhigh,gemini:gemini-2.5-pro"
peer_analysis_max_rounds = 3
additional_repos = "infra:https://github.com/acme/infra:main"
```

Effect: The CLI sends populated values to the server only when they are set in the profile and not overridden by CLI flags.

> **Note:** In `config.toml`, empty strings and `0` values are treated as unset. `0` is the sentinel for `ai_cli_timeout`, `jira_max_results`, `peer_analysis_max_rounds`, `poll_interval_minutes`, and `max_wait_minutes`.

### Issue Helper Fields

Client-side defaults for issue-related CLI commands.

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `jira_token` | string | `""` | Default Jira token for issue-related CLI commands that accept `--jira-token`. |
| `jira_security_level` | string | `""` | Default Jira security level name for restricted Jira issues. |
| `github_repo_url` | string | `""` | Default GitHub repository URL for CLI commands that accept `--github-repo-url`. |

```toml
[servers.prod]
url = "https://jji.example.com"
jira_token = "jira-user-token"
jira_security_level = "Internal"
github_repo_url = "https://github.com/acme/tests"
```

Effect: These fields are CLI-side defaults only. They do not change the server's own environment configuration.

### CLI Environment Variables

Global CLI environment variables.

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `JJI_SERVER` | string | `unset` | Server profile name or full URL. |
| `JJI_USERNAME` | string | `""` | Username sent as the CLI's `jji_username` cookie. |
| `JJI_API_KEY` | string | `""` | Admin API key sent as a Bearer token. |
| `JJI_NO_VERIFY_SSL` | boolean | `unset` | Disable CLI TLS verification. |

```bash
export JJI_SERVER=prod
export JJI_USERNAME=alice
export JJI_API_KEY=admin-api-key
export JJI_NO_VERIFY_SSL=false

jji health
```

Effect: `JJI_SERVER` can be either a profile name or a full URL. Full URLs bypass profile inheritance.

> **Note:** `jji analyze` also accepts these client-side environment defaults: `JENKINS_URL`, `JENKINS_USER`, `JENKINS_PASSWORD`, `TESTS_REPO_URL`, `JIRA_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`, `JIRA_PAT`, `JIRA_PROJECT_KEY`, and `GITHUB_TOKEN`.

## Per-Request Override Behavior

> **Note:** For `POST /analyze` and `POST /analyze-failures`, omitted JSON fields do not override server defaults. Some request models have JSON defaults, but the server applies those defaults as overrides only when the field is actually present in the request body.


> **Note:** `POST /results/{job_id}/preview-github-issue`, `POST /results/{job_id}/preview-jira-bug`, `POST /results/{job_id}/create-github-issue`, and `POST /results/{job_id}/create-jira-bug` do not use the analysis override merge described below.

### Common Analysis Override Fields

Fields accepted by both `POST /analyze` and `POST /analyze-failures`.

| Name | Applies to | Type | Default When Omitted | Description |
| --- | --- | --- | --- | --- |
| `tests_repo_url` | both | string or `null` | server default | Override tests repo URL. `url:ref` syntax is accepted. |
| `ai_provider` | both | string or `null` | `AI_PROVIDER` | Override the primary AI provider. |
| `ai_model` | both | string or `null` | `AI_MODEL` | Override the primary AI model. |
| `enable_jira` | both | boolean or `null` | server default | Override Jira enrichment for this request. |
| `ai_cli_timeout` | both | integer or `null` | `AI_CLI_TIMEOUT` | Override AI CLI timeout in minutes. |
| `jira_url` | both | string or `null` | `JIRA_URL` | Override Jira URL. |
| `jira_email` | both | string or `null` | `JIRA_EMAIL` | Override Jira email. |
| `jira_api_token` | both | string or `null` | `JIRA_API_TOKEN` | Override Jira API token. |
| `jira_pat` | both | string or `null` | `JIRA_PAT` | Override Jira PAT. |
| `jira_project_key` | both | string or `null` | `JIRA_PROJECT_KEY` | Override Jira project key. |
| `jira_ssl_verify` | both | boolean or `null` | `JIRA_SSL_VERIFY` | Override Jira TLS verification. |
| `jira_max_results` | both | integer or `null` | `JIRA_MAX_RESULTS` | Override Jira search result limit. |
| `raw_prompt` | both | string or `null` | `unset` | Append request-specific AI instructions. |
| `github_token` | both | string or `null` | `GITHUB_TOKEN` | Override the GitHub token used during analysis-time GitHub operations. |
| `peer_ai_configs` | both | array or `null` | server default | Override peer analysis configs. Omit or send `null` to inherit; send `[]` to disable. |
| `peer_analysis_max_rounds` | both | integer | server default | Override max peer rounds. Allowed range: `1`-`10`. Applied only when the field is present. |
| `additional_repos` | both | array or `null` | server default | Override additional repos. Omit or send `null` to inherit; send `[]` to disable. |

```json
{
  "tests_repo_url": "https://github.com/acme/tests:release-1.2",
  "ai_provider": "gemini",
  "ai_model": "gemini-2.5-pro",
  "enable_jira": false,
  "raw_prompt": "Focus on networking regressions first.",
  "peer_ai_configs": [],
  "additional_repos": [
    {
      "name": "infra",
      "url": "https://github.com/acme/infra",
      "ref": "main"
    }
  ]
}
```

Effect: Omitted fields inherit the server defaults. `peer_ai_configs=[]` disables peer analysis for that request. `additional_repos=[]` disables additional repo cloning for that request.

### Jenkins-Only Override Fields

Fields accepted only by `POST /analyze`.

| Name | Applies to | Type | Default When Omitted | Description |
| --- | --- | --- | --- | --- |
| `jenkins_url` | `POST /analyze` | string or `null` | `JENKINS_URL` | Override Jenkins URL. |
| `jenkins_user` | `POST /analyze` | string or `null` | `JENKINS_USER` | Override Jenkins username. |
| `jenkins_password` | `POST /analyze` | string or `null` | `JENKINS_PASSWORD` | Override Jenkins password or API token. |
| `jenkins_ssl_verify` | `POST /analyze` | boolean or `null` | `JENKINS_SSL_VERIFY` | Override Jenkins TLS verification. |
| `jenkins_artifacts_max_size_mb` | `POST /analyze` | integer or `null` | `JENKINS_ARTIFACTS_MAX_SIZE_MB` | Override artifact size cap. |
| `get_job_artifacts` | `POST /analyze` | boolean or `null` | `GET_JOB_ARTIFACTS` | Override artifact download behavior. |
| `wait_for_completion` | `POST /analyze` | boolean | server default | Override wait behavior. Applied only when the field is present. |
| `poll_interval_minutes` | `POST /analyze` | integer | server default | Override poll interval. Applied only when the field is present. |
| `max_wait_minutes` | `POST /analyze` | integer | server default | Override wait timeout. Applied only when the field is present. `0` means no limit. |

```json
{
  "jenkins_url": "https://jenkins.internal.example.com",
  "jenkins_user": "svc-jji",
  "jenkins_password": "your-api-token",
  "jenkins_ssl_verify": false,
  "get_job_artifacts": true,
  "jenkins_artifacts_max_size_mb": 250,
  "wait_for_completion": true,
  "poll_interval_minutes": 5,
  "max_wait_minutes": 0
}
```

Effect: `wait_for_completion`, `poll_interval_minutes`, and `max_wait_minutes` override only when the JSON field is present. Sending `max_wait_minutes: 0` explicitly sets unlimited waiting for that request.

### Direct Failure Input Source

Input-source fields accepted by `POST /analyze-failures`.

| Name | Applies to | Type | Default When Omitted | Description |
| --- | --- | --- | --- | --- |
| `failures` | `POST /analyze-failures` | array or `null` | `unset` | Raw failures to analyze directly. |
| `raw_xml` | `POST /analyze-failures` | string or `null` | `unset` | JUnit XML input. Maximum length: `50,000,000` characters. |

```json
{
  "raw_xml": "<?xml version=\"1.0\" encoding=\"UTF-8\"?><testsuite>...</testsuite>",
  "ai_provider": "claude",
  "ai_model": "claude-opus-4-1"
}
```

Effect: Exactly one of `failures` or `raw_xml` is required. When `raw_xml` is supplied, the response includes `enriched_xml`.

## Feature Toggle and Capability Reporting

### `GET /api/capabilities`

Returns server-level feature toggles and credential presence.

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `None` | n/a | n/a | This endpoint takes no query parameters or request body. |

| Response Field | Type | Description |
| --- | --- | --- |
| `github_issues_enabled` | boolean | GitHub issue toggle state. |
| `jira_issues_enabled` | boolean | Jira issue toggle state. |
| `server_github_token` | boolean | Whether a server GitHub token is configured. |
| `server_jira_token` | boolean | Whether a server Jira token (`JIRA_API_TOKEN` or `JIRA_PAT`) is configured. |
| `server_jira_email` | boolean | Whether a server Jira email is configured. |
| `server_jira_project_key` | string | Configured Jira project key, or `""`. |
| `reportportal` | boolean | Actual Report Portal enabled state. |
| `reportportal_project` | string | Configured Report Portal project, or `""`. |

```json
{
  "github_issues_enabled": true,
  "jira_issues_enabled": true,
  "server_github_token": true,
  "server_jira_token": false,
  "server_jira_email": false,
  "server_jira_project_key": "PROJ",
  "reportportal": true,
  "reportportal_project": "e2e"
}
```

Effect: This endpoint reports server configuration only. It does not apply per-request analysis overrides. `reportportal` reflects actual enablement after validating Report Portal URL, token, and project.

## Related Pages

- [Running Your First Analysis](quickstart.html)
- [CLI Command Reference](cli-command-reference.html)
- [REST API Reference](rest-api-reference.html)
- [Improving Analysis with Repository Context](improving-analysis-with-repository-context.html)
- [Managing Admin Users and API Keys](managing-admin-users-and-api-keys.html)