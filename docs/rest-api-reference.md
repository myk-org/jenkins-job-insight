# REST API Reference

> **Note:** `server default` in request tables means the field inherits the running server configuration when omitted. See [Configuration and Environment Reference](configuration-and-environment-reference.html) for the exact defaults and feature flags.


> **Tip:** CLI wrappers for these endpoints are documented in [CLI Command Reference](cli-command-reference.html).

## Conventions

### Authentication Inputs

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `Authorization` | `Bearer <token>` header | none | Admin bootstrap key or admin user API key. |
| `jji_session` | cookie | none | Admin session cookie set by `POST /api/auth/login`. |
| `jji_username` | cookie | none | Username context used for token storage, comments, reviews, and issue attribution. |

Most read and analysis endpoints are accessible without authentication. Admin-only endpoints are under `/api/admin/*` and `DELETE /results/{job_id}`.

### Common Status Codes

| Code | Meaning | Notes |
| --- | --- | --- |
| `200` | Success | Some integration endpoints also use `200` for partial/soft failures and put details in the JSON body. |
| `201` | Created | Used for comments, classifications, and issue creation. |
| `202` | Accepted / in progress | Returned when a job is queued or when a referenced analysis is still pending, waiting, or running. |
| `400` | Invalid request | Used for invalid JSON, missing required fields in object-parsed endpoints, or invalid integration/config state. |
| `401` | Authentication failed | Used for invalid tracker credentials or missing username on user-token endpoints. |
| `403` | Forbidden | Used for admin-only or disabled feature endpoints. |
| `404` | Not found | Missing job, comment, user, or admin account. |
| `409` | Conflict | Used when an endpoint targets a stored analysis that finished with `status="failed"`. |
| `422` | Validation failed | FastAPI/Pydantic body or query validation error. |
| `502` | Upstream tracker failure | GitHub or Jira API error/unreachable response during issue creation. |

### Child Failure Targeting

Many failure-targeting request bodies accept `child_job_name` and `child_build_number`.

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `child_job_name` | `string` | `""` | Child pipeline job name. Empty string targets top-level failures. |
| `child_build_number` | `integer >= 0` | `0` | Child build number. `0` means “no specific build” and works as a wildcard for lookup-oriented endpoints. |

> **Note:** `PUT /results/{job_id}/override-classification` is stricter than the shared validator: when `child_job_name` is set, it requires a non-zero `child_build_number`.

### Progress Phases

`GET /results/{job_id}` may expose `result.progress_phase` and `result.progress_log`.

| Phase | Description |
| --- | --- |
| `waiting_for_jenkins` | Waiting for the Jenkins build to finish before analysis starts. |
| `analyzing` | AI analysis is running. |
| `enriching_jira` | Jira post-processing is running for `PRODUCT BUG` results. |
| `saving` | Final result persistence is running. |

### Sensitive Stored Request Fields

Public result responses strip secret values from `result.request_params`.

| Stripped key |
| --- |
| `jenkins_password` |
| `jenkins_user` |
| `jira_api_token` |
| `jira_pat` |
| `jira_email` |
| `jira_token` |
| `github_token` |
| `reportportal_api_token` |

## Shared Schemas

### `AiConfigEntry`

One peer-review AI configuration.

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `ai_provider` | `claude \| gemini \| cursor` | required | Peer AI provider. |
| `ai_model` | `string` | required | Peer AI model identifier. Blank values are rejected. |

Effect: one entry in `peer_ai_configs`.

```json
{
  "ai_provider": "gemini",
  "ai_model": "gemini-2.5-pro"
}
```

### `AdditionalRepo`

Additional repository cloned into the analysis workspace.

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `name` | `string` | required | Directory name used for the clone. Must be non-blank, must not contain `/`, `\`, `..`, or start with `.`, and must not use reserved names. |
| `url` | `string (URL)` | required | Repository URL. |
| `ref` | `string` | `""` | Branch or tag to check out. Empty string uses the remote default branch. |

Effect: adds extra repository context for AI analysis.

```json
{
  "name": "product-repo",
  "url": "https://github.com/acme/product.git",
  "ref": "main"
}
```

### `TestFailure`

Raw failure input for direct analysis.

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `test_name` | `string` | required | Fully qualified test name. |
| `error_message` | `string` | `""` | Failure message. |
| `stack_trace` | `string` | `""` | Full stack trace. |
| `duration` | `number` | `0.0` | Test duration in seconds. |
| `status` | `string` | `"FAILED"` | Original test status label. |

Effect: one input failure for `POST /analyze-failures`.

```json
{
  "test_name": "tests.api.test_login.test_admin_login",
  "error_message": "AssertionError: expected 200 got 500",
  "stack_trace": "Traceback...",
  "duration": 1.24,
  "status": "FAILED"
}
```

### `BaseAnalysisRequest`

Fields shared by Jenkins-backed and direct-failure analysis.

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `tests_repo_url` | `string \| null` | `null` | Tests repository URL override. A `:ref` suffix is parsed and later exposed as `tests_repo_ref` in stored `request_params`. |
| `ai_provider` | `claude \| gemini \| cursor \| null` | `null` | Main AI provider override. |
| `ai_model` | `string \| null` | `null` | Main AI model override. |
| `enable_jira` | `boolean \| null` | `null` | Enable Jira bug search during analysis. |
| `ai_cli_timeout` | `integer > 0 \| null` | `null` | AI CLI timeout in minutes. |
| `jira_url` | `string \| null` | `null` | Jira base URL override. |
| `jira_email` | `string \| null` | `null` | Jira Cloud email override. |
| `jira_api_token` | `string \| null` | `null` | Jira Cloud API token override. |
| `jira_pat` | `string \| null` | `null` | Jira Server/Data Center PAT override. |
| `jira_project_key` | `string \| null` | `null` | Jira project key override. |
| `jira_ssl_verify` | `boolean \| null` | `null` | Jira SSL verification override. |
| `jira_max_results` | `integer > 0 \| null` | `null` | Maximum Jira search matches per failure. |
| `raw_prompt` | `string \| null` | `null` | Extra prompt text appended to the analysis prompt. |
| `github_token` | `string \| null` | `null` | GitHub token override for private-repo enrichment. |
| `peer_ai_configs` | `array<AiConfigEntry> \| null` | `null` | Peer-review configs. Omit to inherit the server setting; send `[]` to disable peer review for this request. |
| `peer_analysis_max_rounds` | `integer 1-10` | `server default (schema default: 3)` | Maximum peer debate rounds. |
| `additional_repos` | `array<AdditionalRepo> \| null` | `null` | Additional repositories for analysis context. Omit to inherit the server setting; send `[]` to disable. |

Effect: baseline analysis configuration persisted into `result.request_params`.

```json
{
  "ai_provider": "claude",
  "ai_model": "sonnet",
  "tests_repo_url": "https://github.com/acme/tests.git:main",
  "peer_ai_configs": [
    {
      "ai_provider": "gemini",
      "ai_model": "gemini-2.5-pro"
    }
  ],
  "additional_repos": [
    {
      "name": "product-repo",
      "url": "https://github.com/acme/product.git",
      "ref": "main"
    }
  ]
}
```

### `AnalyzeRequest`

Jenkins-backed analysis request. Includes all `BaseAnalysisRequest` fields plus the fields below.

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `job_name` | `string` | required | Jenkins job name. Folder paths are allowed. |
| `build_number` | `integer` | required | Jenkins build number. |
| `wait_for_completion` | `boolean` | `server default (schema default: true)` | Wait for Jenkins completion before analysis. |
| `poll_interval_minutes` | `integer > 0` | `server default (schema default: 2)` | Jenkins polling interval while waiting. |
| `max_wait_minutes` | `integer >= 0` | `server default (schema default: 0)` | Maximum wait time. `0` means no limit. |
| `jenkins_url` | `string \| null` | `null` | Jenkins base URL override. |
| `jenkins_user` | `string \| null` | `null` | Jenkins username override. |
| `jenkins_password` | `string \| null` | `null` | Jenkins password or API token override. |
| `jenkins_ssl_verify` | `boolean \| null` | `null` | Jenkins SSL verification override. |
| `jenkins_artifacts_max_size_mb` | `integer > 0 \| null` | `null` | Artifact download size cap in MB. |
| `get_job_artifacts` | `boolean \| null` | `null` | Download build artifacts for AI context. |

Effect: request body for `POST /analyze`.

```json
{
  "job_name": "folder/job-name",
  "build_number": 123,
  "wait_for_completion": true,
  "poll_interval_minutes": 2,
  "tests_repo_url": "https://github.com/acme/tests.git:main",
  "ai_provider": "claude",
  "ai_model": "sonnet"
}
```

### `AnalyzeFailuresRequest`

Direct failure-analysis request. Includes all `BaseAnalysisRequest` fields plus the fields below.

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `failures` | `array<TestFailure> \| null` | `null` | Raw failures to analyze. |
| `raw_xml` | `string \| null` | `null` | Raw JUnit XML. Maximum length: `50000000` characters. |

Effect: exactly one of `failures` or `raw_xml` must be provided.

```json
{
  "failures": [
    {
      "test_name": "tests.api.test_login.test_admin_login",
      "error_message": "AssertionError: expected 200 got 500",
      "stack_trace": "Traceback..."
    }
  ],
  "ai_provider": "claude",
  "ai_model": "sonnet"
}
```

### `PreviewIssueRequest`

Preview body for GitHub or Jira issue content.

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `test_name` | `string` | required | Failure test name to preview. |
| `child_job_name` | `string` | `""` | Child pipeline job name. |
| `child_build_number` | `integer >= 0` | `0` | Child build number. |
| `include_links` | `boolean` | `false` | Include report and Jenkins links when `PUBLIC_BASE_URL` is configured. |
| `ai_provider` | `string` | `""` | Issue-content generation provider override. Empty string uses the current server default. |
| `ai_model` | `string` | `""` | Issue-content generation model override. Empty string uses the current server default. |
| `github_token` | `string` | `""` | GitHub token used for duplicate search. |
| `jira_token` | `string` | `""` | Jira token used for duplicate search. |
| `jira_email` | `string` | `""` | Jira Cloud email paired with `jira_token`. |
| `jira_project_key` | `string` | `""` | Jira project override for duplicate search. |
| `jira_security_level` | `string` | `""` | Jira security level name. Not used by preview generation. |
| `github_repo_url` | `string` | `""` | GitHub repository override for duplicate search. |

Effect: selects the target failure and optional tracker credentials used during preview.

```json
{
  "test_name": "tests.api.test_login.test_admin_login",
  "include_links": true,
  "github_repo_url": "https://github.com/acme/tests",
  "github_token": "ghp_example"
}
```

### `CreateIssueRequest`

Create body for GitHub or Jira issue creation.

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `test_name` | `string` | required | Failure test name to file. |
| `title` | `string` | required | Final issue title. Blank values are rejected. |
| `body` | `string` | required | Final issue body text. |
| `child_job_name` | `string` | `""` | Child pipeline job name. |
| `child_build_number` | `integer >= 0` | `0` | Child build number. |
| `github_token` | `string` | `""` | GitHub token used for issue creation. |
| `jira_token` | `string` | `""` | Jira token used for bug creation. |
| `jira_email` | `string` | `""` | Jira Cloud email paired with `jira_token`. |
| `jira_project_key` | `string` | `""` | Jira project override. |
| `jira_security_level` | `string` | `""` | Jira security level name. |
| `github_repo_url` | `string` | `""` | GitHub repository override. |

Effect: final payload for `POST /results/{job_id}/create-github-issue` and `POST /results/{job_id}/create-jira-bug`.

```json
{
  "test_name": "tests.api.test_login.test_admin_login",
  "title": "Admin login fails with HTTP 500",
  "body": "## Failure\n`tests.api.test_login.test_admin_login`\n\n## Observed error\nAssertionError: expected 200 got 500",
  "github_repo_url": "https://github.com/acme/tests",
  "github_token": "ghp_example"
}
```

### `AnalysisDetail`

Structured AI output inside each failure result.

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `classification` | `string` | `""` | `CODE ISSUE`, `PRODUCT BUG`, or `INFRASTRUCTURE`. |
| `affected_tests` | `array<string>` | `[]` | Related test names. |
| `details` | `string` | `""` | Main analysis text. |
| `artifacts_evidence` | `string` | `""` | Verbatim artifact evidence. |
| `code_fix` | `object \| false \| null` | `false` | Present for `CODE ISSUE`. Shape: `{file, line, change}`. |
| `product_bug_report` | `object \| false \| null` | `false` | Present for `PRODUCT BUG`. Shape: `{title, severity, component, description, evidence, jira_search_keywords, jira_matches}`. |

Nested object shapes:

| Object | Fields |
| --- | --- |
| `code_fix` | `file`, `line`, `change` |
| `product_bug_report` | `title`, `severity`, `component`, `description`, `evidence`, `jira_search_keywords[]`, `jira_matches[]` |
| `jira_matches[]` item | `key`, `summary`, `status`, `priority`, `url`, `score` |

Effect: the core classification and evidence payload returned by analysis endpoints.

```json
{
  "classification": "CODE ISSUE",
  "affected_tests": [
    "tests.api.test_login.test_admin_login"
  ],
  "details": "The failure is caused by a missing null-check in the auth handler.",
  "artifacts_evidence": "ERROR auth/login.py:42 NoneType has no attribute 'id'",
  "code_fix": {
    "file": "auth/login.py",
    "line": "42",
    "change": "Guard the user lookup before reading user.id."
  }
}
```

### `PeerDebate`

Optional peer-review trail attached to a failure result.

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `consensus_reached` | `boolean` | required | Whether the debate converged. |
| `rounds_used` | `integer` | required | Number of rounds actually used. |
| `max_rounds` | `integer` | required | Maximum rounds allowed for the debate. |
| `ai_configs` | `array<AiConfigEntry>` | required | Peer configs that participated. |
| `rounds` | `array<object>` | required | Debate contributions. Each item has `round`, `ai_provider`, `ai_model`, `role`, `classification`, `details`, and `agrees_with_orchestrator`. |

Effect: present in `FailureAnalysis.peer_debate` only when peer analysis was used.

```json
{
  "consensus_reached": true,
  "rounds_used": 1,
  "max_rounds": 3,
  "ai_configs": [
    {
      "ai_provider": "gemini",
      "ai_model": "gemini-2.5-pro"
    }
  ],
  "rounds": [
    {
      "round": 1,
      "ai_provider": "claude",
      "ai_model": "sonnet",
      "role": "orchestrator",
      "classification": "CODE ISSUE",
      "details": "Primary analysis.",
      "agrees_with_orchestrator": null
    },
    {
      "round": 1,
      "ai_provider": "gemini",
      "ai_model": "gemini-2.5-pro",
      "role": "peer",
      "classification": "CODE ISSUE",
      "details": "Agrees with the null-check diagnosis.",
      "agrees_with_orchestrator": true
    }
  ]
}
```

### `FailureAnalysis`

One analyzed failure.

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `test_name` | `string` | required | Failed test name. |
| `error` | `string` | required | Failure message or exception text. |
| `analysis` | `AnalysisDetail` | required | Structured AI output. |
| `error_signature` | `string` | `""` | SHA-256 deduplication signature. |
| `peer_debate` | `PeerDebate \| null` | `null` | Peer-review trail when enabled. |

Effect: repeated in `AnalysisResult.failures`, `ChildJobAnalysis.failures`, and `FailureAnalysisResult.failures`.

```json
{
  "test_name": "tests.api.test_login.test_admin_login",
  "error": "AssertionError: expected 200 got 500",
  "analysis": {
    "classification": "CODE ISSUE",
    "details": "The auth handler dereferences a null user."
  },
  "error_signature": "4f9f8a0f..."
}
```

### `ChildJobAnalysis`

Recursive pipeline child-job result.

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `job_name` | `string` | required | Child job name. |
| `build_number` | `integer` | required | Child build number. |
| `jenkins_url` | `string \| null` | `null` | Child build URL. |
| `summary` | `string \| null` | `null` | Child summary text. |
| `failures` | `array<FailureAnalysis>` | `[]` | Failures for this child. |
| `failed_children` | `array<ChildJobAnalysis>` | `[]` | Nested failed child jobs. |
| `note` | `string \| null` | `null` | Extra note such as recursion depth limits. |

Effect: appears inside `AnalysisResult.child_job_analyses`.

```json
{
  "job_name": "pipeline/component-tests",
  "build_number": 42,
  "jenkins_url": "https://jenkins.example.com/job/pipeline/job/component-tests/42/",
  "summary": "1 PRODUCT BUG in child job",
  "failures": [
    {
      "test_name": "tests.component.test_ui.test_checkout",
      "error": "TimeoutError",
      "analysis": {
        "classification": "PRODUCT BUG",
        "details": "Checkout API never responds."
      },
      "error_signature": "a1b2c3..."
    }
  ],
  "failed_children": []
}
```

### `AnalysisResult`

Completed Jenkins-backed analysis result.

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `job_id` | `string` | required | Analysis job identifier. |
| `job_name` | `string` | `""` | Jenkins job name. |
| `build_number` | `integer` | `0` | Jenkins build number. |
| `jenkins_url` | `string \| null` | `null` | Jenkins build URL. |
| `status` | `pending \| waiting \| running \| completed \| failed` | required | Analysis state stored in the result body. |
| `summary` | `string` | required | Result summary. |
| `ai_provider` | `string` | `""` | AI provider used. |
| `ai_model` | `string` | `""` | AI model used. |
| `failures` | `array<FailureAnalysis>` | `[]` | Top-level analyzed failures. |
| `child_job_analyses` | `array<ChildJobAnalysis>` | `[]` | Recursive child-job analyses. |

Effect: returned in `ResultEnvelope.result` for completed Jenkins-backed analyses.

```json
{
  "job_id": "9f5d0a0c-32c0-4f3f-b5c4-3a5c3d35d4d0",
  "job_name": "folder/job-name",
  "build_number": 123,
  "jenkins_url": "https://jenkins.example.com/job/folder/job-name/123/",
  "status": "completed",
  "summary": "1 CODE ISSUE",
  "ai_provider": "claude",
  "ai_model": "sonnet",
  "failures": [
    {
      "test_name": "tests.api.test_login.test_admin_login",
      "error": "AssertionError: expected 200 got 500",
      "analysis": {
        "classification": "CODE ISSUE",
        "details": "Null-check missing in auth handler."
      },
      "error_signature": "4f9f8a0f..."
    }
  ],
  "child_job_analyses": []
}
```

### `FailureAnalysisResult`

Completed direct-failure analysis result.

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `job_id` | `string` | required | Analysis job identifier. |
| `status` | `completed \| failed` | required | Direct-analysis status. |
| `summary` | `string` | required | Result summary. |
| `ai_provider` | `string` | `""` | AI provider used. |
| `ai_model` | `string` | `""` | AI model used. |
| `failures` | `array<FailureAnalysis>` | `[]` | Analyzed failures. |
| `enriched_xml` | `string \| null` | `null` | Enriched JUnit XML when `raw_xml` input was used. |

Effect: returned directly by `POST /analyze-failures` and via `GET /results/{job_id}` for completed direct analyses.

```json
{
  "job_id": "14a2b5d1-3d67-4d4d-92f8-8b2bc0d1a8a0",
  "status": "completed",
  "summary": "1 CODE ISSUE",
  "ai_provider": "claude",
  "ai_model": "sonnet",
  "failures": [
    {
      "test_name": "tests.api.test_login.test_admin_login",
      "error": "AssertionError: expected 200 got 500",
      "analysis": {
        "classification": "CODE ISSUE",
        "details": "Null-check missing in auth handler."
      },
      "error_signature": "4f9f8a0f..."
    }
  ],
  "enriched_xml": "<testsuite>...</testsuite>"
}
```

### `ResultEnvelope`

Stored result wrapper returned by `GET /results/{job_id}`.

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `job_id` | `string` | required | Analysis job identifier. |
| `jenkins_url` | `string` | required | Stored Jenkins URL or empty string for direct-failure analyses. |
| `status` | `string` | required | Top-level persisted job status. |
| `result` | `object` | required | Result payload. Completed Jenkins analyses use `AnalysisResult`; completed direct analyses use `FailureAnalysisResult`; in-progress and failed rows return partial objects. |
| `created_at` | `string` | required | Row creation timestamp. |
| `completed_at` | `string \| null` | `null` | Completion timestamp when available. |
| `analysis_started_at` | `string \| null` | `null` | Analysis start timestamp when available. |
| `capabilities` | `object` | required | Same shape as `GET /api/capabilities`. |
| `base_url` | `string` | required | `PUBLIC_BASE_URL` when configured, otherwise `""`. |
| `result_url` | `string` | required | Absolute URL when `base_url` is set, otherwise a relative `/results/{job_id}` path. |

Additional `result` fields seen in stored rows:

| Field | Type | Description |
| --- | --- | --- |
| `request_params` | `object` | Effective request settings used for the analysis. Mirrors the applicable request schema plus derived `tests_repo_ref`; public responses redact secret keys. |
| `progress_phase` | `string` | Current progress phase for in-flight work. |
| `progress_log` | `array<object>` | Phase history entries shaped like `{phase, timestamp}`. |
| `error` | `string` | Failure message for `status="failed"` rows. |

Effect: canonical polling and retrieval response for stored jobs.

```json
{
  "job_id": "9f5d0a0c-32c0-4f3f-b5c4-3a5c3d35d4d0",
  "jenkins_url": "https://jenkins.example.com/job/folder/job-name/123/",
  "status": "completed",
  "result": {
    "job_id": "9f5d0a0c-32c0-4f3f-b5c4-3a5c3d35d4d0",
    "job_name": "folder/job-name",
    "build_number": 123,
    "status": "completed",
    "summary": "1 CODE ISSUE",
    "ai_provider": "claude",
    "ai_model": "sonnet",
    "failures": [],
    "child_job_analyses": [],
    "request_params": {
      "ai_provider": "claude",
      "ai_model": "sonnet",
      "tests_repo_url": "https://github.com/acme/tests.git",
      "tests_repo_ref": "main",
      "peer_ai_configs": [],
      "additional_repos": []
    },
    "progress_phase": "saving",
    "progress_log": [
      {
        "phase": "analyzing",
        "timestamp": 1711111111.0
      }
    ]
  },
  "created_at": "2026-04-18 10:20:30",
  "completed_at": "2026-04-18 10:22:01",
  "analysis_started_at": "2026-04-18 10:20:31",
  "capabilities": {
    "github_issues_enabled": true,
    "jira_issues_enabled": true,
    "server_github_token": false,
    "server_jira_token": true,
    "server_jira_email": true,
    "server_jira_project_key": "PROJ",
    "reportportal": false,
    "reportportal_project": ""
  },
  "base_url": "https://jji.example.com",
  "result_url": "https://jji.example.com/results/9f5d0a0c-32c0-4f3f-b5c4-3a5c3d35d4d0"
}
```

### `PreviewIssueResponse`

Preview response for GitHub and Jira issue content.

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `title` | `string` | required | Generated title. |
| `body` | `string` | required | Generated markdown/body text. |
| `similar_issues` | `array<object>` | `[]` | Best-effort duplicate matches. Each item may include `number`, `key`, `title`, `url`, and `status`. |

Effect: returned by the preview endpoints.

```json
{
  "title": "Admin login fails with HTTP 500",
  "body": "## Summary\nThe auth handler dereferences a null user.\n",
  "similar_issues": [
    {
      "number": 42,
      "key": "",
      "title": "Login API returns 500 on missing user",
      "url": "https://github.com/acme/tests/issues/42",
      "status": "open"
    }
  ]
}
```

### `CreateIssueResponse`

Issue creation response for GitHub and Jira.

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `url` | `string` | required | Created issue URL. |
| `key` | `string` | `""` | Jira issue key. Empty for GitHub. |
| `number` | `integer` | `0` | GitHub issue number. `0` for Jira. |
| `title` | `string` | required | Created issue title. |
| `comment_id` | `integer` | `0` | Auto-created comment linking the issue back to the analysis. |

Effect: returned by both creation endpoints.

```json
{
  "url": "https://github.com/acme/tests/issues/57",
  "key": "",
  "number": 57,
  "title": "Admin login fails with HTTP 500",
  "comment_id": 12
}
```

### `ReportPortalPushResult`

Report Portal push result.

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `pushed` | `integer` | required | Number of Report Portal items updated. |
| `unmatched` | `array<string>` | `[]` | Report Portal item names that were not matched or could not be mapped. |
| `errors` | `array<string>` | `[]` | User-facing integration errors. |
| `launch_id` | `integer \| null` | `null` | Matched Report Portal launch ID when found. |

Effect: returned by `POST /results/{job_id}/push-reportportal`.

```json
{
  "pushed": 3,
  "unmatched": [
    "tests.api.test_misc.test_unmapped"
  ],
  "errors": [],
  "launch_id": 1042
}
```

## Analysis Endpoints

### `POST /analyze`

Queue a Jenkins build for analysis.

| Name | In | Type | Default | Description |
| --- | --- | --- | --- | --- |
| `body` | body | `AnalyzeRequest` | required | Jenkins-backed analysis request. |

Return value/effect: queues a background analysis job and returns `{status, job_id, message, base_url, result_url}`.

Status codes: `202` queued; `400` invalid AI or peer configuration; `422` request validation failed.

```bash
curl -sS -X POST "$BASE_URL/analyze" \
  -H "Content-Type: application/json" \
  -d '{
    "job_name": "folder/job-name",
    "build_number": 123,
    "wait_for_completion": true,
    "ai_provider": "claude",
    "ai_model": "sonnet"
  }'
```

### `POST /analyze-failures`

Analyze raw failures or raw JUnit XML without Jenkins.

| Name | In | Type | Default | Description |
| --- | --- | --- | --- | --- |
| `body` | body | `AnalyzeFailuresRequest` | required | Direct-failure analysis request. |

Return value/effect: returns a stored `FailureAnalysisResult`. When `raw_xml` is supplied, `enriched_xml` is included in the response.

Status codes: `200` result returned; `400` invalid XML or invalid analysis configuration; `422` request validation failed.

```bash
curl -sS -X POST "$BASE_URL/analyze-failures" \
  -H "Content-Type: application/json" \
  -d '{
    "failures": [
      {
        "test_name": "tests.api.test_login.test_admin_login",
        "error_message": "AssertionError: expected 200 got 500",
        "stack_trace": "Traceback..."
      }
    ],
    "ai_provider": "claude",
    "ai_model": "sonnet"
  }'
```

### `POST /re-analyze/{job_id}`

Queue a new Jenkins-backed analysis using a previous job’s stored request parameters, optionally overriding selected analysis fields.

| Name | In | Type | Default | Description |
| --- | --- | --- | --- | --- |
| `job_id` | path | `string` | required | Existing stored result to reconstruct from. |
| `body` | body | `BaseAnalysisRequest` | required | Override fields to apply on top of the stored request parameters. |

Return value/effect: reconstructs the original Jenkins request, applies only the fields explicitly present in the body, and queues a new job with a fresh `job_id`.

Status codes: `202` queued; `400` stored request parameters cannot be reconstructed or original job has no `request_params`; `404` source result not found; `422` validation failed.

```bash
curl -sS -X POST "$BASE_URL/re-analyze/$JOB_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "ai_provider": "gemini",
    "ai_model": "gemini-2.5-pro",
    "peer_ai_configs": []
  }'
```

## Result Endpoints

### `GET /results/{job_id}`

Get the stored result for an analysis job.

| Name | In | Type | Default | Description |
| --- | --- | --- | --- | --- |
| `job_id` | path | `string` | required | Analysis job identifier. |

Return value/effect: returns a `ResultEnvelope`.

Status codes: `200` completed or failed result; `202` job is still pending, waiting, or running; `404` job not found.

> **Note:** Use `Accept: application/json` for API reads. Browser-style HTML requests are handled by the frontend and can redirect in-progress jobs to `/status/{job_id}`.

```bash
curl -sS "$BASE_URL/results/$JOB_ID" \
  -H "Accept: application/json"
```

### `GET /results`

List recent analysis jobs.

| Name | In | Type | Default | Description |
| --- | --- | --- | --- | --- |
| `limit` | query | `integer <= 100` | `50` | Maximum number of rows to return. |

Return value/effect: returns an array of summary objects shaped like `{job_id, jenkins_url, status, created_at}`, ordered newest first.

Status codes: `200` success; `422` invalid query value.

```bash
curl -sS "$BASE_URL/results?limit=25"
```

### `GET /api/dashboard`

Get dashboard-ready result summaries.

Parameters: none.

Return value/effect: returns up to 500 newest rows. Each row always includes `job_id`, `jenkins_url`, `status`, `created_at`, `completed_at`, `analysis_started_at`, `reviewed_count`, and `comment_count`. When parsed result data exists, rows also include `job_name`, `build_number`, `failure_count`, optional `child_job_count`, optional `summary`, and optional `error`.

Status codes: `200` success.

```bash
curl -sS "$BASE_URL/api/dashboard"
```

### `DELETE /results/{job_id}`

Delete an analysis job and all related stored data.

| Name | In | Type | Default | Description |
| --- | --- | --- | --- | --- |
| `job_id` | path | `string` | required | Analysis job identifier. |

Return value/effect: admin-only delete. Removes the result row plus comments, failure reviews, failure history, and test classifications for the job.

Status codes: `200` deleted; `403` admin access required; `404` job not found.

```bash
curl -sS -X DELETE "$BASE_URL/results/$JOB_ID" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

### `GET /results/{job_id}/comments`

Get all comments and review states for a stored job.

| Name | In | Type | Default | Description |
| --- | --- | --- | --- | --- |
| `job_id` | path | `string` | required | Analysis job identifier. |

Return value/effect: returns `{"comments": [...], "reviews": {...}}`.

Comment item shape:

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `id` | `integer` | required | Comment ID. |
| `job_id` | `string` | required | Analysis job identifier. |
| `test_name` | `string` | required | Failure test name. |
| `child_job_name` | `string` | `""` | Child job scope. |
| `child_build_number` | `integer` | `0` | Child build scope. |
| `comment` | `string` | required | Comment text. |
| `error_signature` | `string` | `""` | Deduplication signature copied from the stored failure when available. |
| `username` | `string` | `""` | Username context stored with the comment. |
| `created_at` | `string` | required | Comment timestamp. |

Review map value shape:

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `reviewed` | `boolean` | required | Current reviewed state. |
| `username` | `string` | `""` | Username that last updated the review state. |
| `updated_at` | `string` | required | Last update timestamp. |

Review map keys use `test_name` for top-level failures and `child_job_name#child_build_number::test_name` for child failures.

Status codes: `200` success.

```bash
curl -sS "$BASE_URL/results/$JOB_ID/comments"
```

### `POST /results/{job_id}/comments`

Add a comment to a failure in a stored result.

| Name | In | Type | Default | Description |
| --- | --- | --- | --- | --- |
| `job_id` | path | `string` | required | Analysis job identifier. |
| `test_name` | body | `string` | required | Failure test name. |
| `comment` | body | `string` | required | Comment text. |
| `child_job_name` | body | `string` | `""` | Child job scope. |
| `child_build_number` | body | `integer >= 0` | `0` | Child build scope. |

Return value/effect: creates a comment row and returns `{"id": <comment_id>}`. The server looks up `error_signature` from the stored result and stores the current username when available.

Status codes: `201` created; `202` target job still pending/waiting/running; `400` invalid child scope; `404` job or failure not found; `409` target job failed; `422` validation failed.

```bash
curl -sS -X POST "$BASE_URL/results/$JOB_ID/comments" \
  -H "Content-Type: application/json" \
  -H "Cookie: jji_username=alice" \
  -d '{
    "test_name": "tests.api.test_login.test_admin_login",
    "comment": "Fails only when the auth fixture runs after cache warm-up."
  }'
```

### `DELETE /results/{job_id}/comments/{comment_id}`

Delete a comment.

| Name | In | Type | Default | Description |
| --- | --- | --- | --- | --- |
| `job_id` | path | `string` | required | Analysis job identifier. |
| `comment_id` | path | `integer` | required | Comment identifier. |

Return value/effect: returns `{"status": "deleted"}`. Admins can delete any comment; non-admin users can delete only their own comments.

Status codes: `200` deleted; `401` username required; `404` comment not found or not owned by the caller.

```bash
curl -sS -X DELETE "$BASE_URL/results/$JOB_ID/comments/12" \
  -H "Cookie: jji_username=alice"
```

### `PUT /results/{job_id}/reviewed`

Set the reviewed state for a failure.

| Name | In | Type | Default | Description |
| --- | --- | --- | --- | --- |
| `job_id` | path | `string` | required | Analysis job identifier. |
| `test_name` | body | `string` | required | Failure test name. |
| `reviewed` | body | `boolean` | required | New reviewed state. |
| `child_job_name` | body | `string` | `""` | Child job scope. |
| `child_build_number` | body | `integer >= 0` | `0` | Child build scope. |

Return value/effect: returns `{"status": "ok", "reviewed_by": "<username-or-empty>"}`.

Status codes: `200` updated; `202` target job still pending/waiting/running; `400` invalid child scope; `404` job or failure not found; `409` target job failed; `422` validation failed.

```bash
curl -sS -X PUT "$BASE_URL/results/$JOB_ID/reviewed" \
  -H "Content-Type: application/json" \
  -H "Cookie: jji_username=alice" \
  -d '{
    "test_name": "tests.api.test_login.test_admin_login",
    "reviewed": true
  }'
```

### `GET /results/{job_id}/review-status`

Get review counters for a job.

| Name | In | Type | Default | Description |
| --- | --- | --- | --- | --- |
| `job_id` | path | `string` | required | Analysis job identifier. |

Return value/effect: returns `{total_failures, reviewed_count, comment_count}`.

Status codes: `200` success.

```bash
curl -sS "$BASE_URL/results/$JOB_ID/review-status"
```

### `POST /results/{job_id}/enrich-comments`

Resolve live GitHub and Jira statuses mentioned in stored comments.

| Name | In | Type | Default | Description |
| --- | --- | --- | --- | --- |
| `job_id` | path | `string` | required | Analysis job identifier. |

Return value/effect: returns `{"enrichments": {...}}`, where each key is a comment ID string and each value is an array of objects shaped like `{type, key, status}`. `type` is `github_pr`, `github_issue`, or `jira`.

Status codes: `200` success.

```bash
curl -sS -X POST "$BASE_URL/results/$JOB_ID/enrich-comments"
```

### `PUT /results/{job_id}/override-classification`

Override a stored failure classification.

| Name | In | Type | Default | Description |
| --- | --- | --- | --- | --- |
| `job_id` | path | `string` | required | Analysis job identifier. |
| `test_name` | body | `string` | required | Representative test in the signature group to override. |
| `classification` | body | `CODE ISSUE \| PRODUCT BUG \| INFRASTRUCTURE` | required | New classification. |
| `child_job_name` | body | `string` | `""` | Child job scope. |
| `child_build_number` | body | `integer >= 0` | `0` | Child build scope. Must be non-zero when `child_job_name` is set. |

Return value/effect: returns `{"status": "ok", "classification": "<new value>"}`. The override is mirrored into stored history, applied to the matching failure group within the same job, and patched into stored `result_json` for future reads.

Status codes: `200` updated; `202` target job still pending/waiting/running; `400` invalid child scope; `404` job or failure not found; `409` target job failed; `422` validation failed.

```bash
curl -sS -X PUT "$BASE_URL/results/$JOB_ID/override-classification" \
  -H "Content-Type: application/json" \
  -H "Cookie: jji_username=alice" \
  -d '{
    "test_name": "tests.api.test_login.test_admin_login",
    "classification": "CODE ISSUE"
  }'
```

## History Endpoints

### `GET /history/failures`

Get paginated failure history.

| Name | In | Type | Default | Description |
| --- | --- | --- | --- | --- |
| `search` | query | `string` | `""` | Free-text search across `test_name`, `error_message`, and `job_name`. |
| `job_name` | query | `string` | `""` | Exact top-level job-name filter. |
| `classification` | query | `string` | `""` | Exact classification filter. |
| `limit` | query | `integer <= 200` | `50` | Maximum rows to return. |
| `offset` | query | `integer >= 0` | `0` | Pagination offset. |

Return value/effect: returns `{"failures": [...], "total": <int>}`. Each row includes `id`, `job_id`, `job_name`, `build_number`, `test_name`, `error_message`, `error_signature`, `classification`, `child_job_name`, `child_build_number`, and `analyzed_at`.

Status codes: `200` success; `422` invalid query value.

```bash
curl -sS "$BASE_URL/history/failures?job_name=folder/job-name&classification=CODE%20ISSUE&limit=20"
```

### `GET /history/test/{test_name:path}`

Get recent history for one test.

| Name | In | Type | Default | Description |
| --- | --- | --- | --- | --- |
| `test_name` | path | `string` | required | Full test name. Path form allows embedded slashes. |
| `limit` | query | `integer <= 100` | `20` | Maximum `recent_runs` rows to return. |
| `job_name` | query | `string` | `""` | Exact top-level job-name filter. |
| `exclude_job_id` | query | `string` | `""` | Exclude one analysis job from the result. |

Return value/effect: returns an object with `test_name`, `total_runs`, `failures`, `passes`, `failure_rate`, `first_seen`, `last_seen`, `last_classification`, `classifications`, `recent_runs`, `comments`, `consecutive_failures`, and `note`.

Field notes:

| Field | Type | Description |
| --- | --- | --- |
| `classifications` | `object` | Count map keyed by classification. |
| `recent_runs` | `array<object>` | Rows with `job_id`, `job_name`, `build_number`, `error_message`, `error_signature`, `classification`, `child_job_name`, `child_build_number`, and `analyzed_at`. |
| `comments` | `array<object>` | Related comments shaped like `{comment, username, created_at}`. |
| `passes` | `integer \| null` | `null` when `job_name` is omitted, because only failures are stored. |
| `failure_rate` | `number \| null` | `null` when `job_name` is omitted. |

Status codes: `200` success; `422` invalid query value.

```bash
curl -sS "$BASE_URL/history/test/tests.api.test_login.test_admin_login?limit=10&job_name=folder/job-name"
```

### `GET /history/search`

Find tests sharing an error signature.

| Name | In | Type | Default | Description |
| --- | --- | --- | --- | --- |
| `signature` | query | `string` | required | Error signature hash to search for. |
| `exclude_job_id` | query | `string` | `""` | Exclude one analysis job from the result. |

Return value/effect: returns `{signature, total_occurrences, unique_tests, tests, last_classification, comments}`. `tests` items are `{test_name, occurrences}`. `comments` items are `{comment, username, created_at}`.

Status codes: `200` success; `422` missing or invalid query value.

```bash
curl -sS "$BASE_URL/history/search?signature=4f9f8a0f..."
```

### `GET /history/stats/{job_name:path}`

Get aggregate statistics for a top-level job.

| Name | In | Type | Default | Description |
| --- | --- | --- | --- | --- |
| `job_name` | path | `string` | required | Top-level Jenkins job name. Path form allows embedded slashes. |
| `exclude_job_id` | query | `string` | `""` | Exclude one analysis job from the calculation. |

Return value/effect: returns `{job_name, total_builds_analyzed, builds_with_failures, overall_failure_rate, most_common_failures, recent_trend}`. `most_common_failures` items are `{test_name, count, classification}`. `recent_trend` is `improving`, `worsening`, or `stable`.

Status codes: `200` success.

```bash
curl -sS "$BASE_URL/history/stats/folder/job-name"
```

### `POST /history/classify`

Store a history-domain classification for a test.

| Name | In | Type | Default | Description |
| --- | --- | --- | --- | --- |
| `test_name` | body | `string` | required | Test name to classify. Blank-after-trim is rejected. |
| `classification` | body | `FLAKY \| REGRESSION \| INFRASTRUCTURE \| KNOWN_BUG \| INTERMITTENT` | required | History classification. Input is normalized to uppercase. |
| `reason` | body | `string` | `""` | Free-text reasoning. |
| `job_name` | body | `string` | `""` | Child job name context. Empty string means top-level. |
| `references` | body | `string` | `""` | External references. Required for `KNOWN_BUG`. |
| `job_id` | body | `string` | required | Analysis job identifier used to scope the classification. |
| `child_build_number` | body | `integer >= 0` | `0` | Child build scope. |

Return value/effect: creates a classification row and returns `{"id": <classification_id>}`.

Status codes: `201` created; `400` invalid business rule such as blank `test_name` or missing `references` for `KNOWN_BUG`; `422` validation failed.

> **Note:** Requests with a username context are stored as human-authored and immediately visible. Requests without a username context are stored as `created_by="ai"` and remain hidden until the related analysis makes them visible.

```bash
curl -sS -X POST "$BASE_URL/history/classify" \
  -H "Content-Type: application/json" \
  -H "Cookie: jji_username=alice" \
  -d '{
    "test_name": "tests.api.test_login.test_admin_login",
    "classification": "FLAKY",
    "reason": "Intermittent timeout in shared CI",
    "job_id": "'"$JOB_ID"'"
  }'
```

### `GET /history/classifications`

Read visible primary override classifications.

| Name | In | Type | Default | Description |
| --- | --- | --- | --- | --- |
| `test_name` | query | `string` | `""` | Exact test-name filter. |
| `classification` | query | `string` | `""` | Exact primary classification filter. |
| `job_name` | query | `string` | `""` | Exact child-job-name filter stored with the classification. |
| `parent_job_name` | query | `string` | `""` | Exact top-level job-name filter. |
| `job_id` | query | `string` | `""` | Exact analysis job filter. |

Return value/effect: returns `{"classifications": [...]}`. Each row includes `id`, `test_name`, `job_name`, `parent_job_name`, `classification`, `reason`, `references_info`, `created_by`, `job_id`, `child_build_number`, and `created_at`.

Status codes: `200` success.

> **Note:** This reader intentionally returns only visible primary classifications (`CODE ISSUE`, `PRODUCT BUG`, `INFRASTRUCTURE`). History labels from `POST /history/classify` are not returned here.

```bash
curl -sS "$BASE_URL/history/classifications?test_name=tests.api.test_login.test_admin_login"
```

## Issue and Integration Endpoints

### `POST /results/{job_id}/preview-github-issue`

Generate GitHub issue content for a stored failure.

| Name | In | Type | Default | Description |
| --- | --- | --- | --- | --- |
| `job_id` | path | `string` | required | Analysis job identifier. |
| `body` | body | `PreviewIssueRequest` | required | Preview request. |

Return value/effect: returns `PreviewIssueResponse`. The server resolves the effective stored classification first, so manual overrides affect the generated content. Duplicate search is best-effort and only runs when a target repo URL and GitHub token are available.

Status codes: `200` preview returned; `202` target job still pending/waiting/running; `400` target repository URL cannot be resolved or test lookup is invalid; `403` GitHub issue creation disabled; `404` job or failure not found; `409` target job failed; `422` validation failed.

```bash
curl -sS -X POST "$BASE_URL/results/$JOB_ID/preview-github-issue" \
  -H "Content-Type: application/json" \
  -d '{
    "test_name": "tests.api.test_login.test_admin_login",
    "include_links": true,
    "github_repo_url": "https://github.com/acme/tests",
    "github_token": "ghp_example"
  }'
```

### `POST /results/{job_id}/preview-jira-bug`

Generate Jira bug content for a stored failure.

| Name | In | Type | Default | Description |
| --- | --- | --- | --- | --- |
| `job_id` | path | `string` | required | Analysis job identifier. |
| `body` | body | `PreviewIssueRequest` | required | Preview request. |

Return value/effect: returns `PreviewIssueResponse`. Duplicate search is best-effort and runs only when usable Jira credentials and a Jira project key are available.

Status codes: `200` preview returned; `202` target job still pending/waiting/running; `400` Jira URL not configured or target lookup invalid; `403` Jira issue creation disabled; `404` job or failure not found; `409` target job failed; `422` validation failed.

```bash
curl -sS -X POST "$BASE_URL/results/$JOB_ID/preview-jira-bug" \
  -H "Content-Type: application/json" \
  -d '{
    "test_name": "tests.api.test_login.test_admin_login",
    "include_links": true,
    "jira_token": "jira_example",
    "jira_email": "alice@example.com",
    "jira_project_key": "PROJ"
  }'
```

### `POST /results/{job_id}/create-github-issue`

Create a GitHub issue for a stored failure.

| Name | In | Type | Default | Description |
| --- | --- | --- | --- | --- |
| `job_id` | path | `string` | required | Analysis job identifier. |
| `body` | body | `CreateIssueRequest` | required | Final issue payload and optional tracker overrides. |

Return value/effect: returns `CreateIssueResponse`. When a username context exists, the server appends reporter attribution to the issue body and creates a matching comment on the analysis report.

Status codes: `201` created; `202` target job still pending/waiting/running; `400` missing GitHub token or target repository URL, or invalid repository URL; `401` GitHub token invalid or expired; `403` GitHub issue creation disabled; `404` job or failure not found; `409` target job failed; `422` validation failed; `502` GitHub API error or unreachable response.

```bash
curl -sS -X POST "$BASE_URL/results/$JOB_ID/create-github-issue" \
  -H "Content-Type: application/json" \
  -H "Cookie: jji_username=alice" \
  -d '{
    "test_name": "tests.api.test_login.test_admin_login",
    "title": "Admin login fails with HTTP 500",
    "body": "## Failure\n`tests.api.test_login.test_admin_login`\n\n## Error\nAssertionError: expected 200 got 500",
    "github_repo_url": "https://github.com/acme/tests",
    "github_token": "ghp_example"
  }'
```

### `POST /results/{job_id}/create-jira-bug`

Create a Jira bug for a stored failure.

| Name | In | Type | Default | Description |
| --- | --- | --- | --- | --- |
| `job_id` | path | `string` | required | Analysis job identifier. |
| `body` | body | `CreateIssueRequest` | required | Final bug payload and optional tracker overrides. |

Return value/effect: returns `CreateIssueResponse`. When a username context exists, the server appends reporter attribution to the Jira description and creates a matching comment on the analysis report.

Status codes: `201` created; `202` target job still pending/waiting/running; `400` Jira URL not configured, missing Jira project key, or missing Jira credentials; `401` Jira token invalid or expired; `403` Jira issue creation disabled; `404` job or failure not found; `409` target job failed; `422` validation failed; `502` Jira API error or unreachable response.

```bash
curl -sS -X POST "$BASE_URL/results/$JOB_ID/create-jira-bug" \
  -H "Content-Type: application/json" \
  -H "Cookie: jji_username=alice" \
  -d '{
    "test_name": "tests.api.test_login.test_admin_login",
    "title": "Admin login fails with HTTP 500",
    "body": "Failure observed in CI pipeline build 123.",
    "jira_token": "jira_example",
    "jira_email": "alice@example.com",
    "jira_project_key": "PROJ",
    "jira_security_level": "Internal"
  }'
```

### `POST /results/{job_id}/push-reportportal`

Push stored classifications into Report Portal.

| Name | In | Type | Default | Description |
| --- | --- | --- | --- | --- |
| `job_id` | path | `string` | required | Analysis job identifier. |
| `child_job_name` | query | `string \| null` | `null` | Child job name for a scoped push. |
| `child_build_number` | query | `integer \| null` | `null` | Child build number for a scoped push. Required when `child_job_name` is supplied. |

Return value/effect: returns `ReportPortalPushResult`.

Status codes: `200` result returned; `400` Report Portal disabled/not configured, invalid child scope, or `PUBLIC_BASE_URL` missing; `404` job not found; `422` validation failed.

> **Note:** Many integration problems remain HTTP `200` and are reported in `errors[]`. Use the body, not only the status code, to determine success.

```bash
curl -sS -X POST "$BASE_URL/results/$JOB_ID/push-reportportal"
```

### `GET /api/capabilities`

Get server feature toggles and credential availability.

Parameters: none.

Return value/effect: returns an object with the fields below.

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `github_issues_enabled` | `boolean` | required | Whether GitHub issue creation is enabled. |
| `jira_issues_enabled` | `boolean` | required | Whether Jira issue creation is enabled. |
| `server_github_token` | `boolean` | required | Whether the server has its own GitHub token configured. |
| `server_jira_token` | `boolean` | required | Whether the server has Jira credentials configured. |
| `server_jira_email` | `boolean` | required | Whether the server has a Jira Cloud email configured. |
| `server_jira_project_key` | `string` | required | Configured default Jira project key, or `""`. |
| `reportportal` | `boolean` | required | Whether Report Portal integration is enabled and configured. |
| `reportportal_project` | `string` | required | Configured Report Portal project, or `""`. |

Status codes: `200` success.

```bash
curl -sS "$BASE_URL/api/capabilities"
```

### `POST /api/jira-projects`

List Jira projects visible to the supplied Jira credentials.

| Name | In | Type | Default | Description |
| --- | --- | --- | --- | --- |
| `jira_token` | body | `string` | `""` | Jira token. |
| `jira_email` | body | `string` | `""` | Jira Cloud email. |
| `query` | body | `string` | `""` | Free-text project filter. |

Return value/effect: returns an array of `{key, name}` objects. If no user token is supplied, the endpoint returns only the server-configured project key when available.

Status codes: `200` success.

```bash
curl -sS -X POST "$BASE_URL/api/jira-projects" \
  -H "Content-Type: application/json" \
  -d '{
    "jira_token": "jira_example",
    "jira_email": "alice@example.com",
    "query": "PROJ"
  }'
```

### `POST /api/jira-security-levels`

List Jira security levels for a project.

| Name | In | Type | Default | Description |
| --- | --- | --- | --- | --- |
| `jira_token` | body | `string` | `""` | Jira token. |
| `jira_email` | body | `string` | `""` | Jira Cloud email. |
| `project_key` | body | `string` | required | Jira project key. |

Return value/effect: returns an array of `{id, name, description}` objects. Failures are swallowed and returned as `[]`.

Status codes: `200` success; `422` validation failed.

```bash
curl -sS -X POST "$BASE_URL/api/jira-security-levels" \
  -H "Content-Type: application/json" \
  -d '{
    "jira_token": "jira_example",
    "jira_email": "alice@example.com",
    "project_key": "PROJ"
  }'
```

### `POST /api/validate-token`

Validate a GitHub or Jira token.

| Name | In | Type | Default | Description |
| --- | --- | --- | --- | --- |
| `token_type` | body | `github \| jira` | required | Tracker type to validate. |
| `token` | body | `string` | required | Tracker token. |
| `email` | body | `string` | `""` | Jira Cloud email. Ignored for GitHub. |

Return value/effect: returns `{valid, username, message}`. For GitHub, `username` is the GitHub login. For Jira, `username` is the display name.

Status codes: `200` validation result; `422` validation failed.

> **Note:** Invalid tokens, missing tokens, and unreachable trackers still return HTTP `200`; inspect `valid` and `message`.

```bash
curl -sS -X POST "$BASE_URL/api/validate-token" \
  -H "Content-Type: application/json" \
  -d '{
    "token_type": "github",
    "token": "ghp_example"
  }'
```

## Authentication and User Endpoints

### `POST /api/auth/login`

Authenticate using the bootstrap admin key or an admin user API key.

| Name | In | Type | Default | Description |
| --- | --- | --- | --- | --- |
| `username` | body | `string` | required | Login username. Use literal `admin` when authenticating with the bootstrap admin key. |
| `api_key` | body | `string` | required | Bootstrap admin key or stored admin user API key. |

Return value/effect: returns `{username, role, is_admin}` and sets `jji_session` plus `jji_username` cookies.

Status codes: `200` logged in; `400` invalid JSON body or missing fields; `401` invalid credentials.

```bash
curl -i -sS -X POST "$BASE_URL/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "api_key": "'"$ADMIN_KEY"'"
  }'
```

### `POST /api/auth/logout`

Log out the current admin session.

Parameters: none.

Return value/effect: returns `{"ok": true}` and clears the `jji_session` cookie. The `jji_username` cookie is not removed.

Status codes: `200` success.

```bash
curl -sS -X POST "$BASE_URL/api/auth/logout" \
  -H "Cookie: jji_session=$SESSION_TOKEN"
```

### `GET /api/auth/me`

Get the current request identity.

Parameters: none.

Return value/effect: returns `{username, role, is_admin}`. Unauthenticated requests return `{"username": "", "role": "user", "is_admin": false}`.

Status codes: `200` success.

```bash
curl -sS "$BASE_URL/api/auth/me" \
  -H "Cookie: jji_username=alice"
```

### `GET /api/user/tokens`

Get the saved personal GitHub and Jira tokens for the current username context.

Parameters: none.

Return value/effect: returns `{github_token, jira_email, jira_token}` and sends `Cache-Control: no-store`. If the current username is not tracked in the local user table, all values are returned as empty strings.

Status codes: `200` success; `401` username required.

```bash
curl -sS "$BASE_URL/api/user/tokens" \
  -H "Cookie: jji_username=alice"
```

### `PUT /api/user/tokens`

Save personal tracker credentials for the current username context.

| Name | In | Type | Default | Description |
| --- | --- | --- | --- | --- |
| `github_token` | body | `string` | omitted | GitHub token. Empty string clears the stored value. |
| `jira_email` | body | `string` | omitted | Jira Cloud email. Empty string clears the stored value. |
| `jira_token` | body | `string` | omitted | Jira token. Empty string clears the stored value. |

Return value/effect: updates only the fields present in the JSON object. Omitted fields are left unchanged. Returns `{"ok": true}`.

Status codes: `200` saved; `400` invalid JSON body or non-object body; `401` username required; `404` user not found.

```bash
curl -sS -X PUT "$BASE_URL/api/user/tokens" \
  -H "Content-Type: application/json" \
  -H "Cookie: jji_username=alice" \
  -d '{
    "github_token": "ghp_example",
    "jira_email": "alice@example.com",
    "jira_token": "jira_example"
  }'
```

## Admin Endpoints

### `POST /api/admin/users`

Create a new admin user.

| Name | In | Type | Default | Description |
| --- | --- | --- | --- | --- |
| `username` | body | `string` | required | New admin username. Must be 2-50 characters, start alphanumeric, and then use only alphanumerics, `.`, `_`, or `-`. `admin` is reserved. |

Return value/effect: returns `{username, api_key, role}` with `role="admin"` and sends `Cache-Control: no-store`.

Status codes: `200` created; `400` invalid JSON, invalid username, or duplicate username; `403` admin access required.

```bash
curl -sS -X POST "$BASE_URL/api/admin/users" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "release-manager"
  }'
```

### `GET /api/admin/users`

List all tracked users.

Parameters: none.

Return value/effect: returns `{"users": [...]}`. Each user row includes `id`, `username`, `role`, `created_at`, and `last_seen`.

Status codes: `200` success; `403` admin access required.

```bash
curl -sS "$BASE_URL/api/admin/users" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

### `DELETE /api/admin/users/{username}`

Delete an admin user.

| Name | In | Type | Default | Description |
| --- | --- | --- | --- | --- |
| `username` | path | `string` | required | Admin username to delete. |

Return value/effect: returns `{"deleted": "<username>"}`. Active sessions for that user are removed.

Status codes: `200` deleted; `400` cannot delete your own account or the last admin; `403` admin access required; `404` admin user not found.

```bash
curl -sS -X DELETE "$BASE_URL/api/admin/users/release-manager" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

### `PUT /api/admin/users/{username}/role`

Change a user’s role.

| Name | In | Type | Default | Description |
| --- | --- | --- | --- | --- |
| `username` | path | `string` | required | Username to update. |
| `role` | body | `admin \| user` | required | New role. |

Return value/effect: returns `{username, role}` and, when promoting to admin, also returns `api_key`. Responses use `Cache-Control: no-store`. Demotion removes the stored API key and invalidates that user’s sessions.

Status codes: `200` updated; `400` invalid JSON, invalid role, same role, self-change, reserved `admin`, or last-admin demotion; `403` admin access required; `404` user not found.

```bash
curl -sS -X PUT "$BASE_URL/api/admin/users/alice/role" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "role": "admin"
  }'
```

### `POST /api/admin/users/{username}/rotate-key`

Rotate an admin user API key.

| Name | In | Type | Default | Description |
| --- | --- | --- | --- | --- |
| `username` | path | `string` | required | Admin username whose key will be rotated. |
| `new_key` | body | `string \| omitted` | omitted | Optional replacement API key. Must be at least 16 characters when supplied. If omitted, the server generates a new key. |

Return value/effect: returns `{username, new_api_key}` and sends `Cache-Control: no-store`. Existing sessions for that user are invalidated.

Status codes: `200` rotated; `400` invalid JSON, non-object body, or invalid custom key; `403` admin access required; `404` admin user not found.

```bash
curl -sS -X POST "$BASE_URL/api/admin/users/alice/rotate-key" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "new_key": "jji_custom_admin_key_123456"
  }'
```

## Service Endpoints

### `GET /ai-configs`

List distinct AI provider/model pairs found in completed stored analyses.

Parameters: none.

Return value/effect: returns an array of objects shaped like `{ai_provider, ai_model}`.

Status codes: `200` success.

```bash
curl -sS "$BASE_URL/ai-configs"
```

### `GET /health`

Basic health check.

Parameters: none.

Return value/effect: returns `{"status": "healthy"}`.

Status codes: `200` success.

```bash
curl -sS "$BASE_URL/health"
```

## Related Pages

- [CLI Command Reference](cli-command-reference.html)
- [Configuration and Environment Reference](configuration-and-environment-reference.html)
- [Analyzing Jenkins Jobs](analyzing-jenkins-jobs.html)
- [Analyzing JUnit XML and Raw Failures](analyzing-junit-xml-and-raw-failures.html)
- [Managing Admin Users and API Keys](managing-admin-users-and-api-keys.html)