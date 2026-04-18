# Running Your First Analysis

You want to get from a fresh setup to one real Jenkins analysis you can inspect from both the terminal and the browser. The fastest supported path uses Docker Compose so the service, web UI, and supported AI CLIs come up together with the fewest moving parts.

## Prerequisites
- Docker with Docker Compose
- `uv` installed so you can install the `jji` CLI
- A Jenkins URL, username, API token or password, and a build number you want to inspect
- One AI provider credential; the simplest first run is `claude` with `ANTHROPIC_API_KEY`

## Quick Example

```bash
cp .env.example .env
```

```dotenv
# set at least these values in .env
JENKINS_URL=https://jenkins.example.com
JENKINS_USER=your-username
JENKINS_PASSWORD=your-api-token
AI_PROVIDER=claude
AI_MODEL=your-model-name
ANTHROPIC_API_KEY=your-anthropic-api-key
```

```bash
docker compose up -d
uv tool install jenkins-job-insight

export JJI_SERVER=http://localhost:8000
export JJI_USERNAME=jdoe

jji health
jji analyze --job-name test --build-number 123
```

Open `http://localhost:8000`, enter the same username on the register page, and use the dashboard to open the new run. After `jji analyze`, copy the printed `job_id`; `jji status <job_id>` follows the run from the terminal, and the `Poll:` URL is the browser URL for the same stored result.

```text
Job queued: <job_id>
Status: queued
Poll: /results/<job_id>
```

## Step-by-Step

```mermaid
flowchart LR
  A[Set Jenkins and AI values] --> B[docker compose up -d]
  B --> C[Open /register and save a username]
  C --> D[jji analyze --job-name ... --build-number ...]
  D --> E[/status/<job_id> while work is in progress]
  E --> F[/results/<job_id> when analysis is complete]
```

1. Create the server environment file.

```bash
cp .env.example .env
```

```dotenv
JENKINS_URL=https://jenkins.example.com
JENKINS_USER=your-username
JENKINS_PASSWORD=your-api-token
AI_PROVIDER=claude
AI_MODEL=your-model-name
ANTHROPIC_API_KEY=your-anthropic-api-key
```

This is the minimum setup for a Jenkins-backed analysis. Keep the rest of `.env` at the defaults for your first run.

> **Tip:** Use a failed build number for your first run. A passed build finishes cleanly, but there is nothing to analyze.

2. Start the service and point the CLI at it.

```bash
docker compose up -d
uv tool install jenkins-job-insight

export JJI_SERVER=http://localhost:8000
export JJI_USERNAME=jdoe

jji health
```

Use the same `JJI_USERNAME` you plan to save in the browser so future comments and review actions line up under one name. When the service is ready, `jji health` returns `healthy`.

3. Register your browser profile.

Open `http://localhost:8000/`. On a first visit, the app sends you to `/register`.

Enter a username and click **Save**. For a normal first run, leave the API key, GitHub token, Jira email, and Jira token fields empty.

> **Note:** You do not need an admin API key or tracker tokens to run your first analysis. A username is enough.

4. Queue the analysis from the CLI.

```bash
jji analyze --job-name test --build-number 123
```

Replace `test` and `123` with a real Jenkins job and build number. Because Jenkins and AI defaults are already in `.env`, this first command only needs the job name and build number.

The CLI prints three important lines:
- `Job queued`: the new `job_id`
- `Status`: the current stored status, starting as `queued`
- `Poll`: the stored result URL for this run

If the Jenkins build is still running, the stored job can stay in `waiting` before JJI starts the AI analysis.

5. Inspect the run from the CLI.

```bash
jji status <job_id>
jji results show <job_id>
jji results dashboard
```

Use `jji status` while the run is still moving through `waiting`, `pending`, or `running`. Use `jji results show` for a one-run summary, and `jji results dashboard` when you want the recent-analysis list with failure counts and review progress.

6. Inspect the same run in the web UI.

Open the `Poll:` URL from `jji analyze`, or go back to `http://localhost:8000/` and click the row on the dashboard. The UI handles the rest:
- in-progress work opens the status page
- completed work opens the report page
- the status page refreshes every 10 seconds and switches to the final report automatically

Once the run is complete, the report page shows the summary, AI provider/model, grouped failures, and a direct link back to the Jenkins build.

## Advanced Usage

### Save your CLI server profile

If you do not want to export `JJI_SERVER` and `JJI_USERNAME` in every shell, create `~/.config/jji/config.toml`:

```toml
[default]
server = "local"

[servers.local]
url = "http://localhost:8000"
username = "jdoe"
```

After that, `jji health` and `jji analyze ...` use that profile automatically. The same file can also hold Jenkins, AI, and other per-server defaults when you want the CLI to supply them.

### Override Jenkins or AI settings on one run

```bash
jji analyze \
  --job-name test \
  --build-number 123 \
  --jenkins-url https://jenkins.example.com \
  --jenkins-user your-username \
  --jenkins-password your-api-token \
  --provider claude \
  --model your-model-name
```

Use this when you do not want to keep Jenkins credentials or AI defaults in the server environment.

### Switch AI providers

Use one provider at a time and set the matching authentication variable.

| Provider | Example `.env` values |
| --- | --- |
| `claude` | `AI_PROVIDER=claude`, `AI_MODEL=opus-4`, `ANTHROPIC_API_KEY=...` |
| `gemini` | `AI_PROVIDER=gemini`, `AI_MODEL=gemini-2.5-pro`, `GEMINI_API_KEY=...` |
| `cursor` | `AI_PROVIDER=cursor`, `AI_MODEL=gpt-5.4-xhigh`, `CURSOR_API_KEY=...` |

If you want multi-model peer review after your first successful run, see [Adding Peer Review with Multiple AI Models](adding-peer-review-with-multiple-ai-models.html) for details.

### Run from a source checkout instead of Docker

```bash
uv sync
cd frontend && npm install && npm run build
uv run jenkins-job-insight
```

Use this when you want a local process instead of a container. Build the web UI before starting the server, or browser routes will not load.

If you want to analyze JUnit XML or raw failures without Jenkins, see [Analyzing JUnit XML and Raw Failures](analyzing-junit-xml-and-raw-failures.html) for details.

### Make generated links absolute

Set `PUBLIC_BASE_URL` on the server if you want `Poll:` and other generated links to use a full public URL instead of `/results/<job_id>`.

## Troubleshooting

- `Error: No server specified`: export `JJI_SERVER=http://localhost:8000`, pass `--server http://localhost:8000`, or save a CLI server profile.
- The browser keeps sending you to `/register`: save a username first. A normal user does not need a password or API key.
- The browser shows `Frontend not built`: this only happens on a local source checkout. Run `cd frontend && npm install && npm run build`, then restart the server.
- Jenkins certificate errors on the first run: set `JENKINS_SSL_VERIFY=false` in `.env`, or pass `--no-jenkins-ssl-verify` on the CLI.
- The run stays in `waiting`: JJI is still watching Jenkins finish the build. If you do not want that behavior, re-run with `--no-wait`.

## Related Pages

- [Analyzing Jenkins Jobs](analyzing-jenkins-jobs.html)
- [Analyzing JUnit XML and Raw Failures](analyzing-junit-xml-and-raw-failures.html)
- [Monitoring and Re-Running Analyses](monitoring-and-rerunning-analyses.html)
- [CLI Command Reference](cli-command-reference.html)
- [Configuration and Environment Reference](configuration-and-environment-reference.html)