# CLI Command Reference

## Global Options

These options apply to every command. `jji config ...` commands do not require a server connection.

| Name | Type | Default / source | Description |
| --- | --- | --- | --- |
| `--server`, `-s` | string | `JJI_SERVER`, then `[default].server` | Server profile name or full `http://`/`https://` URL. A full URL does not load any other profile keys. |
| `--json` | flag | `false` | Pretty-print JSON instead of text or table output. |
| `--user` | string | `JJI_USERNAME`, then profile `username`, else empty | Username cookie used for comment and review attribution. |
| `--api-key` | string | `JJI_API_KEY`, then profile `api_key`, else empty | Bearer token used for admin and other protected API calls. |
| `--no-verify-ssl` | flag | `JJI_NO_VERIFY_SSL`, then profile `no_verify_ssl`, else `false` | Disable HTTPS certificate verification for the server connection. |
| `--verify-ssl` | flag | unset | Force HTTPS certificate verification on, overriding profile `no_verify_ssl`. |
| `--insecure` | flag | `false` | Alias for `--no-verify-ssl`. |

```bash
jji --server prod --api-key "$JJI_API_KEY" results list --json
jji --server https://jji.example.com --insecure health
```

Effect: The CLI resolves the server, username, SSL behavior, and admin API key before running the selected command.

> **Note:** `--json` works both before the command and after the leaf command, for example `jji --json results list` and `jji results list --json`.


> **Warning:** `--verify-ssl` and `--insecure` are mutually exclusive.


> **Note:** When the server returns `401` or `403`, the CLI prints a hint to use `--api-key` or `JJI_API_KEY`.

## Output Modes

| Mode | Syntax | Behavior |
| --- | --- | --- |
| Text / table | default | Commands print aligned tables or command-specific summary text. Generic table output preserves full values and prints `No results.` for empty datasets. |
| JSON | `--json` | Commands print pretty-formatted JSON with 2-space indentation. |

```bash
jji results list --json
jji --json history test tests.TestA.test_one
```

Effect: JSON mode returns the raw response body for the command. Text mode may show a summary instead of every field.

> **Note:** `jji capabilities` prints JSON even without `--json`.


> **Note:** `jji results show --full` also prints the full stored result document as JSON.

## Config File

`jji` reads its local config file from `$XDG_CONFIG_HOME/jji/config.toml`. When `XDG_CONFIG_HOME` is unset, the path is `~/.config/jji/config.toml`.

### Top-Level Sections

| Section | Keys | Description |
| --- | --- | --- |
| `[default]` | `server` | Name of the default server profile used when `--server` and `JJI_SERVER` are unset. |
| `[defaults]` | any server-profile keys except `server` | Shared values merged into every `[servers.<name>]` entry. |
| `[servers.<name>]` | `url` plus optional profile keys | Named server profile. |

```toml
[default]
server = "dev"

[defaults]
username = "alice"
tests_repo_url = "https://github.com/example/tests"
ai_provider = "claude"
ai_model = "opus-4"

[servers.dev]
url = "http://localhost:8000"
no_verify_ssl = true

[servers.prod]
url = "https://jji.example.com"
api_key = "jji_admin_..."
jira_token = "jira-token"
jira_email = "alice@example.com"
github_repo_url = "https://github.com/example/repo"
```

Effect: The selected profile provides default values for shared connection settings and for commands such as `analyze`, `preview-issue`, `create-issue`, `jira-projects`, and `jira-security-levels`.

> **Warning:** `[defaults].server` is invalid. Put the default profile name in `[default].server`.

### Resolution Rules

| Priority | Source | Notes |
| --- | --- | --- |
| 1 | CLI flags and bound environment variables | Highest precedence. |
| 2 | Selected `[servers.<name>]` entry | Loaded when `--server NAME` or `[default].server` selects a profile. |
| 3 | `[defaults]` section | Merged into the selected server entry before command-specific overrides. |
| 4 | Omitted | Unset fields are not sent by the CLI. |

```bash
jji --server prod health
JJI_SERVER=prod jji health
jji --server https://jji.example.com health
```

Effect: A concrete `http://` or `https://` value for `--server` or `JJI_SERVER` is self-contained; no other profile fields are inherited.

### Profile Keys

| Key | Type | Default | Used by | Description |
| --- | --- | --- | --- | --- |
| `url` | string | required | all non-`config` commands | Base URL of the JJI server. Must be a non-empty trimmed string. |
| `username` | string | `""` | shared global option | Default username cookie for comment and review actions. |
| `no_verify_ssl` | boolean | `false` | shared global option | Default TLS verification behavior for the server connection. |
| `api_key` | string | `""` | shared global option | Default Bearer token for admin and protected commands. |
| `jenkins_url` | string | `""` | `analyze` | Default Jenkins server URL. |
| `jenkins_user` | string | `""` | `analyze` | Default Jenkins username. |
| `jenkins_password` | string | `""` | `analyze` | Default Jenkins password or API token. |
| `jenkins_ssl_verify` | boolean | unset | `analyze` | Default Jenkins TLS verification flag. |
| `tests_repo_url` | string | `""` | `analyze` | Default tests repository URL. |
| `ai_provider` | string | `""` | `analyze` | Default AI provider. |
| `ai_model` | string | `""` | `analyze` | Default AI model. |
| `ai_cli_timeout` | integer | `0` | `analyze` | Default AI CLI timeout in minutes. `0` means unset in the CLI config. |
| `jira_url` | string | `""` | `analyze` | Default Jira instance URL. |
| `jira_email` | string | `""` | `analyze`, `jira-projects`, `jira-security-levels`, Jira issue preview/create | Default Jira Cloud email. |
| `jira_api_token` | string | `""` | `analyze` | Default Jira Cloud API token for analysis-time Jira lookup. |
| `jira_pat` | string | `""` | `analyze` | Default Jira Server / Data Center personal access token for analysis-time Jira lookup. |
| `jira_token` | string | `""` | `jira-projects`, `jira-security-levels`, Jira issue preview/create | Default Jira token for Jira utility and Jira issue commands. |
| `jira_project_key` | string | `""` | `analyze`, Jira issue preview/create | Default Jira project key. |
| `jira_security_level` | string | `""` | Jira issue preview/create | Default Jira security level name. |
| `jira_ssl_verify` | boolean | unset | `analyze` | Default Jira TLS verification flag. |
| `jira_max_results` | integer | `0` | `analyze` | Default Jira search result limit. `0` means unset in the CLI config. |
| `enable_jira` | boolean | unset | `analyze` | Default Jira integration toggle. |
| `github_token` | string | `""` | `analyze`, GitHub issue preview/create | Default GitHub token. |
| `github_repo_url` | string | `""` | GitHub issue preview/create | Default GitHub repository URL override. |
| `peers` | string | `""` | `analyze` | Default peer-review list in `provider:model[,provider:model...]` format. |
| `peer_analysis_max_rounds` | integer | `0` | `analyze` | Default peer review round limit. `0` means unset in the CLI config. |
| `additional_repos` | string | `""` | `analyze` | Default additional repository list in `name:url[,name:url...]` format. Each URL may append `:ref`. |
| `wait_for_completion` | boolean | unset | `analyze` | Default wait behavior before analysis starts. |
| `poll_interval_minutes` | integer | `0` | `analyze` | Default Jenkins polling interval. `0` means unset in the CLI config. |
| `max_wait_minutes` | integer | `0` | `analyze` | Default maximum wait time. `0` means unset in the CLI config. |

```toml
[servers.dev]
url = "http://localhost:8000"
username = "alice"
jenkins_url = "https://jenkins.example.com"
jira_token = "jira-token"
github_repo_url = "https://github.com/example/repo"
peers = "claude:opus-4,gemini:2.5-pro"
additional_repos = "infra:https://github.com/example/infra:main"
```

Effect: These keys are read only when a named server profile is selected.

> **Note:** `jira_token` is separate from `jira_api_token` and `jira_pat`. `analyze` reads `jira_api_token` / `jira_pat`; Jira utility and Jira issue commands read `jira_token`.


> **Note:** `peers`, `jira_token`, `jira_security_level`, `github_repo_url`, and `additional_repos` must be strings. `peer_analysis_max_rounds` must be an integer.

## Command Groups

| Command | Effect with no leaf subcommand |
| --- | --- |
| `jji` | Prints top-level help. |
| `jji results` | Prints `results` group help. |
| `jji history` | Prints `history` group help. |
| `jji comments` | Prints `comments` group help. |
| `jji classifications` | Prints `classifications` group help. |
| `jji auth` | Prints `auth` group help. |
| `jji admin` | Prints `admin` group help. |
| `jji admin users` | Prints `admin users` group help. |
| `jji config` | Runs `jji config show`. |

```bash
jji --help
jji results --help
jji config
```

Effect: Group commands are navigation points; the executable work happens in the leaf commands below.

> **Tip:** `--help` is available on the root command, every command group, and every leaf command.

## Core Commands

### `jji health`

Checks server health.

Parameters/options: shared global options only.

```bash
jji health
```

Effect: Default output is a one-row status table. `--json` returns the raw health object.

### `jji analyze`

Queues a Jenkins build for analysis.

#### Required parameters

| Name | Type | Default / source | Description |
| --- | --- | --- | --- |
| `--job-name`, `-j` | string | required | Jenkins job name. |
| `--build-number`, `-b` | integer | required | Build number to analyze. Must be greater than `0`. |

#### Analysis selection and AI options

| Name | Type | Default / source | Description |
| --- | --- | --- | --- |
| `--provider` | string | profile `ai_provider`, else unset | AI provider name. |
| `--model` | string | profile `ai_model`, else unset | AI model name. |
| `--jira` / `--no-jira` | flag pair | profile `enable_jira`, else unset | Enable or disable Jira integration for this request. |
| `--raw-prompt` | string | unset | Extra instructions appended to the AI prompt. |
| `--peers` | string | profile `peers`, else unset | Peer-review list in `provider:model[,provider:model...]` format. |
| `--peer-analysis-max-rounds` | integer | profile `peer_analysis_max_rounds`, else unset | Peer-review round limit. Must be between `1` and `10`. |

#### Jenkins, repository, Jira, and GitHub options

| Name | Type | Default / source | Description |
| --- | --- | --- | --- |
| `--jenkins-url` | string | `JENKINS_URL`, then profile `jenkins_url`, else unset | Jenkins server URL. |
| `--jenkins-user` | string | `JENKINS_USER`, then profile `jenkins_user`, else unset | Jenkins username. |
| `--jenkins-password` | string | `JENKINS_PASSWORD`, then profile `jenkins_password`, else unset | Jenkins password or API token. |
| `--jenkins-ssl-verify` / `--no-jenkins-ssl-verify` | flag pair | profile `jenkins_ssl_verify`, else unset | Jenkins TLS verification flag. |
| `--jenkins-artifacts-max-size-mb` | integer | unset | Maximum Jenkins artifact size in MB. Must be greater than `0`. |
| `--get-job-artifacts` / `--no-get-job-artifacts` | flag pair | unset | Download or skip downloading all build artifacts for AI context. |
| `--tests-repo-url` | string | `TESTS_REPO_URL`, then profile `tests_repo_url`, else unset | Tests repository URL. |
| `--jira-url` | string | `JIRA_URL`, then profile `jira_url`, else unset | Jira instance URL. |
| `--jira-email` | string | `JIRA_EMAIL`, then profile `jira_email`, else unset | Jira Cloud email. |
| `--jira-api-token` | string | `JIRA_API_TOKEN`, then profile `jira_api_token`, else unset | Jira Cloud API token for analysis-time lookup. |
| `--jira-pat` | string | `JIRA_PAT`, then profile `jira_pat`, else unset | Jira Server / Data Center personal access token for analysis-time lookup. |
| `--jira-project-key` | string | `JIRA_PROJECT_KEY`, then profile `jira_project_key`, else unset | Jira project key. |
| `--jira-ssl-verify` / `--no-jira-ssl-verify` | flag pair | profile `jira_ssl_verify`, else unset | Jira TLS verification flag. |
| `--jira-max-results` | integer | profile `jira_max_results`, else unset | Maximum Jira search results. Must be greater than `0`. |
| `--github-token` | string | `GITHUB_TOKEN`, then profile `github_token`, else unset | GitHub token. |
| `--additional-repos` | string | profile `additional_repos`, else unset | Additional repositories in `name:url[,name:url...]` format. Each URL may append `:ref`. |

#### Monitoring options

| Name | Type | Default / source | Description |
| --- | --- | --- | --- |
| `--wait` / `--no-wait` | flag pair | profile `wait_for_completion`, else unset | Wait or do not wait for Jenkins completion before analysis begins. |
| `--poll-interval` | integer | profile `poll_interval_minutes`, else unset | Jenkins polling interval in minutes. Must be greater than `0`. |
| `--max-wait` | integer | profile `max_wait_minutes`, else unset | Maximum wait time in minutes. Must be `0` or greater. |

```bash
jji analyze \
  --job-name ocp-e2e \
  --build-number 142 \
  --provider claude \
  --model opus-4 \
  --jenkins-url https://jenkins.example.com \
  --tests-repo-url https://github.com/example/tests \
  --wait \
  --poll-interval 5
```

Effect: Queues an analysis request. Default output prints `Job queued`, `Status`, and `Poll`; `--json` returns the queued response, including `job_id` and `result_url`.

> **Note:** `--peers` accepts `provider:model[,provider:model...]`. `--additional-repos` accepts `name:url[,name:url...]`, and each URL may append `:ref` after the repository path.


> **Warning:** Invalid `--peers`, invalid `--additional-repos`, out-of-range `--peer-analysis-max-rounds`, or invalid numeric bounds exit with status `1`.

### `jji re-analyze JOB_ID`

Re-runs a stored analysis with the same settings.

| Name | Type | Default / source | Description |
| --- | --- | --- | --- |
| `JOB_ID` | string | required | Stored analysis job id to re-run. |

```bash
jji re-analyze old-job-1
```

Effect: Queues a new analysis. Default output prints the new `job_id`, `status`, and poll URL; `--json` returns the queued response.

### `jji status JOB_ID`

Checks the current status of an analysis job.

| Name | Type | Default / source | Description |
| --- | --- | --- | --- |
| `JOB_ID` | string | required | Stored analysis job id. |

```bash
jji status abc-123
```

Effect: Default output prints only `job_id` and `status`. `--json` returns the full stored result object when available.

## Results Commands

### `jji results list`

Lists recent analyzed jobs.

| Name | Type | Default / source | Description |
| --- | --- | --- | --- |
| `--limit`, `-l` | integer | `50` | Maximum number of jobs to return. |

```bash
jji results list --limit 10
```

Effect: Default output shows `job_id`, `status`, `jenkins_url`, and `created_at`. `--json` returns the raw list.

### `jji results dashboard`

Lists jobs with dashboard metadata.

Parameters/options: shared global options only.

```bash
jji results dashboard
```

Effect: Default output shows `job_id`, `job_name`, `build_number`, `status`, `failure_count`, `reviewed_count`, `comment_count`, and `created_at`. `--json` returns the raw list.

### `jji results show JOB_ID`

Shows a stored analysis result.

| Name | Type | Default / source | Description |
| --- | --- | --- | --- |
| `JOB_ID` | string | required | Stored analysis job id. |
| `--full`, `-f` | flag | `false` | Print the full stored result document as JSON. |

```bash
jji results show abc-123
jji results show abc-123 --full
```

Effect: Default output is a summary row with `job_id`, `status`, `summary`, `failures`, `children`, `ai_provider`, and `created_at`. `--full` or `--json` prints the full stored result document.

### `jji results delete JOB_ID`

Deletes a stored job and related data.

| Name | Type | Default / source | Description |
| --- | --- | --- | --- |
| `JOB_ID` | string | required | Stored analysis job id to delete. |

```bash
jji results delete abc-123
```

Effect: Default output prints `Deleted job <job_id>`. `--json` returns the API response.

### `jji results review-status JOB_ID`

Shows review progress for a stored analysis.

| Name | Type | Default / source | Description |
| --- | --- | --- | --- |
| `JOB_ID` | string | required | Stored analysis job id. |

```bash
jji results review-status job-1
```

Effect: Default output is a one-row table with `total_failures`, `reviewed_count`, and `comment_count`. `--json` returns the raw response object.

### `jji results set-reviewed JOB_ID`

Sets or clears the reviewed state for a test failure.

| Name | Type | Default / source | Description |
| --- | --- | --- | --- |
| `JOB_ID` | string | required | Stored analysis job id. |
| `--test`, `-t` | string | required | Fully qualified test name. |
| `--reviewed` / `--not-reviewed` | flag pair | required | Choose the reviewed state to apply. |
| `--child-job` | string | `""` | Optional child job name. |
| `--child-build` | integer | `0` | Optional child build number. Must be non-negative. Values greater than `0` require `--child-job`. |

```bash
jji results set-reviewed job-1 --test tests.TestA.test_one --reviewed
```

Effect: Default output prints `Marked as reviewed` or `Marked as not reviewed`, optionally with `reviewed_by`. `--json` returns the API response.

### `jji results enrich-comments JOB_ID`

Refreshes comment metadata such as live PR or ticket status.

| Name | Type | Default / source | Description |
| --- | --- | --- | --- |
| `JOB_ID` | string | required | Stored analysis job id. |

```bash
jji results enrich-comments job-1
```

Effect: Default output prints `Enriched N comment(s).` `--json` returns the raw response object.

## History Commands

### `jji history test TEST_NAME`

Shows failure history for one test.

| Name | Type | Default / source | Description |
| --- | --- | --- | --- |
| `TEST_NAME` | string | required | Fully qualified test name. |
| `--limit`, `-l` | integer | `20` | Maximum number of recent runs to include. |
| `--job-name`, `-j` | string | `""` | Restrict history to one Jenkins job name. |
| `--exclude-job-id` | string | `""` | Exclude one stored analysis job id from the history query. |

```bash
jji history test tests.TestA.test_one --limit 10
```

Effect: Default output prints summary fields plus optional `Recent runs` and `Comments` tables. `--json` returns the full history document.

### `jji history search`

Finds tests that share an error signature.

| Name | Type | Default / source | Description |
| --- | --- | --- | --- |
| `--signature`, `-s` | string | required | Error signature hash. |
| `--exclude-job-id` | string | `""` | Exclude one stored analysis job id from the search. |

```bash
jji history search --signature sig-abc123
```

Effect: Default output prints signature totals and a test occurrence table. `--json` returns the full search response.

### `jji history stats JOB_NAME`

Shows aggregate statistics for one Jenkins job.

| Name | Type | Default / source | Description |
| --- | --- | --- | --- |
| `JOB_NAME` | string | required | Jenkins job name. |
| `--exclude-job-id` | string | `""` | Exclude one stored analysis job id from the stats query. |

```bash
jji history stats ocp-e2e
```

Effect: Default output prints aggregate counts plus an optional `Most common failures` table. `--json` returns the full stats object.

### `jji history failures`

Lists paginated failure history.

| Name | Type | Default / source | Description |
| --- | --- | --- | --- |
| `--limit`, `-l` | integer | `50` | Page size. |
| `--offset`, `-o` | integer | `0` | Page offset. |
| `--search`, `-s` | string | `""` | Test-name search text. |
| `--classification`, `-c` | string | `""` | Classification filter. |
| `--job-name`, `-j` | string | `""` | Jenkins job-name filter. |

```bash
jji history failures --classification "PRODUCT BUG" --job-name ocp-e2e --limit 25
```

Effect: Default output prints a `Total:` line and a failure table. `--json` returns the paginated response object.

## Classification Commands

### `jji classify TEST_NAME`

Creates a manual classification for a failure.

| Name | Type | Default / source | Description |
| --- | --- | --- | --- |
| `TEST_NAME` | string | required | Fully qualified test name. |
| `--type`, `-t` | string | required | Manual classification. The CLI uppercases the value before sending it. CLI help lists `FLAKY`, `REGRESSION`, `INFRASTRUCTURE`, `KNOWN_BUG`, and `INTERMITTENT`. |
| `--job-id` | string | required | Stored analysis job id this classification applies to. |
| `--reason`, `-r` | string | `""` | Free-form reason text. |
| `--job-name`, `-j` | string | `""` | Parent job name when no child job is supplied. |
| `--references` | string | `""` | Bug URLs or ticket keys. |
| `--child-job` | string | `""` | Optional child job name. |
| `--child-build` | integer | `0` | Optional child build number. |

```bash
jji classify tests.TestA.test_one --type FLAKY --job-id job-123 --reason "intermittent DNS"
```

Effect: Default output prints the created record id. `--json` returns the created classification object.

### `jji classifications list`

Lists stored manual classifications.

| Name | Type | Default / source | Description |
| --- | --- | --- | --- |
| `--job-id` | string | `""` | Filter by stored analysis job id. |
| `--test-name`, `-t` | string | `""` | Filter by fully qualified test name. |
| `--type`, `-c` | string | `""` | Classification filter. The CLI uppercases the value before sending it. |
| `--job-name`, `-j` | string | `""` | Filter by job name. |
| `--parent-job-name` | string | `""` | Filter by parent job name. |

```bash
jji classifications list --type flaky --parent-job-name pipeline-parent
```

Effect: Default output prints classification rows or `No classifications found.` `--json` returns the full `{classifications:[...]}` payload.

### `jji override-classification JOB_ID`

Overrides a failure classification in a stored result.

| Name | Type | Default / source | Description |
| --- | --- | --- | --- |
| `JOB_ID` | string | required | Stored analysis job id. |
| `--test`, `-t` | string | required | Fully qualified test name. |
| `--classification`, `-c` | string | required | Override value. CLI help lists `CODE ISSUE`, `PRODUCT BUG`, and `INFRASTRUCTURE`. |
| `--child-job` | string | `""` | Optional child job name. |
| `--child-build` | integer | `0` | Optional child build number. |

```bash
jji override-classification job-1 --test tests.TestA.test_one --classification "PRODUCT BUG"
```

Effect: Default output prints the new classification. `--json` returns the API response.

## Comment Commands

> **Note:** Comment and review commands use the shared `--user` option or the selected profile `username` for attribution.

### `jji comments list JOB_ID`

Lists comments for one stored analysis job.

| Name | Type | Default / source | Description |
| --- | --- | --- | --- |
| `JOB_ID` | string | required | Stored analysis job id. |

```bash
jji comments list job-1
```

Effect: Default output prints comment rows or `No comments for this job.` `--json` returns the full response, including `comments` and `reviews`.

### `jji comments add JOB_ID`

Adds a comment to one failure.

| Name | Type | Default / source | Description |
| --- | --- | --- | --- |
| `JOB_ID` | string | required | Stored analysis job id. |
| `--test`, `-t` | string | required | Fully qualified test name. |
| `--message`, `-m` | string | required | Comment text. |
| `--child-job` | string | `""` | Optional child job name. |
| `--child-build` | integer | `0` | Optional child build number. |

```bash
jji comments add job-1 --test tests.TestA.test_one --message "Opened JIRA-123"
```

Effect: Default output prints `Comment added (id: ...)`. `--json` returns the created comment object.

### `jji comments delete JOB_ID COMMENT_ID`

Deletes a comment.

| Name | Type | Default / source | Description |
| --- | --- | --- | --- |
| `JOB_ID` | string | required | Stored analysis job id. |
| `COMMENT_ID` | integer | required | Comment id to delete. |

```bash
jji comments delete job-1 42
```

Effect: Default output prints `Comment deleted.` `--json` returns the API response.

## Tracker and Automation Commands

> **Note:** `preview-issue` and `create-issue` send only the credentials for the selected `--type`. GitHub runs ignore Jira credentials; Jira runs ignore GitHub credentials.

### `jji capabilities`

Shows server-supported post-analysis automation features.

Parameters/options: shared global options only.

```bash
jji capabilities
```

Effect: Prints the capability object. Text mode and JSON mode both emit JSON, including fields such as `github_issues_enabled` and `jira_issues_enabled`.

### `jji jira-projects`

Lists available Jira projects.

| Name | Type | Default / source | Description |
| --- | --- | --- | --- |
| `--query` | string | `""` | Optional search text used to filter projects. |
| `--jira-token` | string | profile `jira_token`, else unset | Jira token. |
| `--jira-email` | string | profile `jira_email`, else unset | Jira Cloud email. |

```bash
jji jira-projects --query platform
```

Effect: Default output prints `key` / `name` rows or `No Jira projects found.` `--json` returns the raw list.

### `jji jira-security-levels PROJECT_KEY`

Lists Jira security levels for one project.

| Name | Type | Default / source | Description |
| --- | --- | --- | --- |
| `PROJECT_KEY` | string | required | Jira project key. |
| `--jira-token` | string | profile `jira_token`, else unset | Jira token. |
| `--jira-email` | string | profile `jira_email`, else unset | Jira Cloud email. |

```bash
jji jira-security-levels PROJ
```

Effect: Default output prints `name` / `description` rows or `No security levels found.` `--json` returns the raw list.

### `jji ai-configs`

Lists known AI provider/model pairs from completed analyses.

Parameters/options: shared global options only.

```bash
jji ai-configs
```

Effect: Default output prints `ai_provider` and `ai_model` rows. If no completed analyses exist, the CLI prints `No AI configurations found from completed analyses.` and exits successfully. `--json` returns the raw list.

### `jji preview-issue JOB_ID`

Previews generated issue content for GitHub or Jira.

| Name | Type | Default / source | Description |
| --- | --- | --- | --- |
| `JOB_ID` | string | required | Stored analysis job id. |
| `--test`, `-t` | string | required | Fully qualified test name. |
| `--type` | string | required | Target tracker. Allowed values: `github`, `jira`. |
| `--child-job` | string | `""` | Optional child job name. |
| `--child-build` | integer | `0` | Optional child build number. |
| `--include-links` | flag | `false` | Include clickable URLs in the generated body. |
| `--ai-provider` | string | unset | AI provider override for issue-content generation. |
| `--ai-model` | string | unset | AI model override for issue-content generation. |
| `--github-token` | string | profile `github_token`, else unset | GitHub token for GitHub issue preview. |
| `--github-repo-url` | string | profile `github_repo_url`, else unset | GitHub repository URL override. |
| `--jira-token` | string | profile `jira_token`, else unset | Jira token for Jira bug preview. |
| `--jira-email` | string | profile `jira_email`, else unset | Jira Cloud email for Jira bug preview. |
| `--jira-project-key` | string | profile `jira_project_key`, else unset | Jira project key override. |
| `--jira-security-level` | string | profile `jira_security_level`, else unset | Jira security level name. |

```bash
jji preview-issue job-1 \
  --test tests.TestA.test_one \
  --type github \
  --include-links \
  --ai-provider claude \
  --ai-model opus-4
```

Effect: Default output prints `Title`, `Body`, and any `Similar issues`. `--json` returns the preview object.

### `jji create-issue JOB_ID`

Creates a GitHub issue or Jira bug from a stored failure.

| Name | Type | Default / source | Description |
| --- | --- | --- | --- |
| `JOB_ID` | string | required | Stored analysis job id. |
| `--test`, `-t` | string | required | Fully qualified test name. |
| `--type` | string | required | Target tracker. Allowed values: `github`, `jira`. |
| `--title` | string | required | Final issue title. |
| `--body` | string | required | Final issue body. |
| `--child-job` | string | `""` | Optional child job name. |
| `--child-build` | integer | `0` | Optional child build number. |
| `--github-token` | string | profile `github_token`, else unset | GitHub token for GitHub issue creation. |
| `--github-repo-url` | string | profile `github_repo_url`, else unset | GitHub repository URL override. |
| `--jira-token` | string | profile `jira_token`, else unset | Jira token for Jira bug creation. |
| `--jira-email` | string | profile `jira_email`, else unset | Jira Cloud email for Jira bug creation. |
| `--jira-project-key` | string | profile `jira_project_key`, else unset | Jira project key override. |
| `--jira-security-level` | string | profile `jira_security_level`, else unset | Jira security level name. |

```bash
jji create-issue job-1 \
  --test tests.TestA.test_one \
  --type jira \
  --title "DNS timeout in ocp-e2e" \
  --body "Reproduced in multiple runs."
```

Effect: Default output prints the created issue key or number, the URL, and any `comment_id` added to the JJI record. `--json` returns the created issue object.

### `jji validate-token {github|jira}`

Validates a tracker token.

| Name | Type | Default / source | Description |
| --- | --- | --- | --- |
| `{github\|jira}` | string | required | Token type. Allowed values: `github`, `jira`. |
| `--token` | string | interactive prompt | Token value to validate. Input is hidden when prompted. |
| `--email` | string | `""` | Jira Cloud email. Used only for Jira validation. |

```bash
jji validate-token jira --token jira-token --email user@example.com
```

Effect: Valid tokens exit with status `0` and print `Valid`; invalid tokens exit with status `1` and print `Invalid`. `--json` returns the validation object.

### `jji push-reportportal JOB_ID` / `jji push-rp JOB_ID`

Pushes stored classifications into Report Portal. `push-rp` is a hidden alias.

| Name | Type | Default / source | Description |
| --- | --- | --- | --- |
| `JOB_ID` | string | required | Stored analysis job id. |
| `--child-job-name` | string | unset | Optional child job name for pipeline child pushes. |
| `--child-build-number` | integer | unset | Optional child build number for pipeline child pushes. |

```bash
jji push-rp job-123
```

Effect: Default output prints the pushed count, optional launch id, unmatched tests, and any errors. `--json` returns the raw response object.

## Auth and Admin Commands

> **Note:** `jji auth login` validates credentials only. It does not persist authentication between CLI invocations. For later commands, use the shared `--api-key`, `JJI_API_KEY`, or profile `api_key`.


> **Warning:** `jji admin users create`, `jji admin users rotate-key`, and `jji admin users change-role USER admin` may print API keys only once.

### `jji auth login`

Validates admin credentials.

| Name | Type | Default / source | Description |
| --- | --- | --- | --- |
| `--username`, `-u` | string | required | Admin username. |
| `--api-key`, `-k` | string | required | Admin API key to validate. |

```bash
jji auth login --username admin --api-key jji_admin_key
```

Effect: Default output prints `username`, `role`, and `admin` status. `--json` returns the auth object.

### `jji auth logout`

Sends the logout request.

Parameters/options: shared global options only.

```bash
jji auth logout --json
```

Effect: Sends the logout request. Use `--json` to inspect returned fields.

### `jji auth whoami`

Shows current authenticated user info.

Parameters/options: shared global options only.

```bash
jji auth whoami
```

Effect: Default output prints `username`, `role`, and `is_admin`. `--json` returns the same fields as a JSON object.

### `jji admin users list`

Lists all users.

Parameters/options: shared global options only.

```bash
jji admin users list
```

Effect: Default output prints user rows or `No users found.` `--json` returns `{users:[...]}`.

### `jji admin users create USERNAME`

Creates a new admin user.

| Name | Type | Default / source | Description |
| --- | --- | --- | --- |
| `USERNAME` | string | required | Username for the new admin user. |

```bash
jji admin users create newadmin
```

Effect: Default output prints the created username and the new API key once. `--json` returns the same response object.

### `jji admin users delete USERNAME`

Deletes an admin user.

| Name | Type | Default / source | Description |
| --- | --- | --- | --- |
| `USERNAME` | string | required | Username to delete. |
| `--force`, `-f` | flag | `false` | Skip the confirmation prompt. |

```bash
jji admin users delete oldadmin --force
```

Effect: Prompts for confirmation unless `--force` is set. Default output prints `Deleted admin user: <name>`; `--json` returns the API response.

### `jji admin users rotate-key USERNAME`

Rotates an admin user's API key.

| Name | Type | Default / source | Description |
| --- | --- | --- | --- |
| `USERNAME` | string | required | Username whose key should be rotated. |

```bash
jji admin users rotate-key myuser
```

Effect: Default output prints the username and the new API key once. `--json` returns the same response object.

### `jji admin users change-role USERNAME ROLE`

Changes a user's role.

| Name | Type | Default / source | Description |
| --- | --- | --- | --- |
| `USERNAME` | string | required | Username to update. |
| `ROLE` | string | required | New role. CLI help lists `admin` and `user`. |

```bash
jji admin users change-role myuser admin
```

Effect: Default output prints the new role. If the API returns a new key during promotion to `admin`, the CLI prints it once. `--json` returns the same response object.

## Config Commands

Config commands use the local config file only and do not contact the server.

### `jji config` / `jji config show`

Shows the current local config file summary. `jji config` is the same command as `jji config show`.

Parameters/options: none.

```bash
jji config
```

Effect: If the config file exists, the CLI prints the resolved file path, the selected default server, and one summary line per server. If the file is missing, the CLI prints the resolved path and a bootstrap snippet.

### `jji config completion [SHELL]`

Prints shell-completion setup instructions.

| Name | Type | Default / source | Description |
| --- | --- | --- | --- |
| `SHELL` | string | `zsh` | Shell type. Allowed values: `bash`, `zsh`. |

```bash
jji config completion bash
```

Effect: Prints shell setup instructions that call `jji --show-completion bash` or `jji --show-completion zsh`. Unsupported shell values exit with status `1`.

### `jji config servers`

Lists configured server profiles.

Parameters/options: shared `--json` only.

```bash
jji config servers
jji config servers --json
```

Effect: Default output prints a table with `name`, `url`, `username`, `no_verify_ssl`, and a `*` marker for the default server. `--json` returns an object keyed by server name with `url`, `username`, `no_verify_ssl`, and `default`.

## Related Pages

- [Configuration and Environment Reference](configuration-and-environment-reference.html)
- [REST API Reference](rest-api-reference.html)
- [Running Your First Analysis](quickstart.html)
- [Analyzing Jenkins Jobs](analyzing-jenkins-jobs.html)
- [Managing Admin Users and API Keys](managing-admin-users-and-api-keys.html)