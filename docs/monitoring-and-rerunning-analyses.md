# Monitoring and Re-Running Analyses

Track queued analyses until they finish, then launch another pass when the first run fails, times out, or needs different AI settings. This lets you recover from transient problems and compare reruns without losing the original result.

## Prerequisites
- A running JJI server that you can reach from the web app or the `jji` CLI.
- An analysis you want to follow, or permission to start one. See [Running Your First Analysis](quickstart.html).
- For the web app, a saved username/profile so you can open the Dashboard.

> **Note:** This page covers queued Jenkins-backed analyses. For direct XML or raw failure analysis, see [Analyzing JUnit XML and Raw Failures](analyzing-junit-xml-and-raw-failures.html).

## Quick Example

```bash
jji analyze --job-name "folder/job-name" --build-number 123 --provider claude --model "<model>"
jji status <job-id>
jji re-analyze <job-id>
```

Use the `job_id` printed by the first command. The rerun keeps the same Jenkins job and build, but creates a new JJI job ID so the original result stays intact.

> **Warning:** `jji re-analyze` reruns with the original settings. If you need to change timeout, model, peer review, repository context, Jira search, or artifact collection, use the web UI's `Re-Analyze` button instead.

## Step-by-Step

1. Queue the analysis and keep the job ID.

   ```bash
   jji analyze --job-name "folder/job-name" --build-number 123 --provider claude --model "<model>"
   ```

   The response is immediately `queued` and includes a poll link you can open in the browser.

   > **Note:** `queued` is the submit response. Once the run is stored, you will normally see `pending` or `waiting`, then `running`, and finally `completed` or `failed`.

   ```mermaid
   flowchart LR
     Submit[Submit analysis] --> Queued[queued]
     Queued --> Pending[pending]
     Queued --> Waiting[waiting]
     Pending --> Running[running]
     Waiting --> Running[running]
     Running --> Completed[completed]
     Running --> Failed[failed]
     Waiting --> Failed[failed]
     Completed --> Rerun[Re-Analyze]
     Failed --> Rerun
     Rerun --> Queued
   ```

2. Monitor the run from the CLI or the Dashboard.

   ```bash
   jji status <job-id>
   jji results dashboard
   ```

   Use `jji status` when you care about one run. Use `jji results dashboard` or the web Dashboard when you want a live overview of multiple jobs, including failure counts, review progress, comments, and child-job counts.

   | What you see | Where you see it | What to do next |
   | --- | --- | --- |
   | `queued` | Submit or rerun response | Save the `job_id` and start monitoring |
   | `pending` | Dashboard, status page, `jji status` | JJI has accepted the job and has not started AI work yet |
   | `waiting` | Dashboard, status page, `jji status` | JJI is waiting for Jenkins to finish before analysis starts |
   | `running` | Dashboard, status page, `jji status` | AI analysis is in progress |
   | `completed` | Dashboard, report page, `jji status` | Open the finished report |
   | `failed` | Dashboard, status page, `jji status` | Read the error and decide whether to rerun |
   | `Timed Out` | Web UI only | The AI analysis timed out; rerun with a higher AI timeout |

   > **Tip:** The Dashboard and status page refresh automatically, so they are the easiest way to follow a live run.

3. Open the finished result.

   ```bash
   jji results show <job-id>
   ```

   In the browser, click the row in the Dashboard. Active jobs open the status view; completed jobs open the full report.

   See [Reviewing, Commenting, and Reclassifying Failures](reviewing-commenting-and-reclassifying-failures.html) for what to do after the report is ready.

4. Rerun the same analysis quickly.

   ```bash
   jji re-analyze <job-id>
   ```

   This is the fastest retry path when you want another pass with the same settings. JJI creates a brand-new analysis record and leaves the original one untouched.

5. Rerun with adjusted settings from the web UI.

   - Open the failed run's status page or the completed run's report page.
   - Click `Re-Analyze`.
   - Change only the fields you need, such as AI provider or model, AI CLI timeout, raw prompt, peer review, repository context, Jira search, or artifact collection.
   - Submit the rerun and monitor the new job from the Dashboard or the status page.

   > **Tip:** The `Re-Analyze` dialog starts from the original run's settings, so you usually only need to change the field that caused the rerun, such as a higher AI timeout or a different model.

   See [Improving Analysis with Repository Context](improving-analysis-with-repository-context.html) for repository, prompt, and artifact guidance. See [Adding Peer Review with Multiple AI Models](adding-peer-review-with-multiple-ai-models.html) for peer analysis settings.

## Advanced Usage

| If you need to... | Best option |
| --- | --- |
| Retry immediately with the same settings | Run `jji re-analyze <job-id>` |
| Change AI provider, model, or AI timeout | Use `Re-Analyze` in the web UI |
| Add or change repo context, prompt, Jira search, or artifact download settings | Use `Re-Analyze` in the web UI |
| Enable or retune peer review | Use `Re-Analyze` in the web UI |
| Change Jenkins wait behavior such as wait/no-wait, poll interval, or max wait | Start a fresh analysis with new analyze options |

The live status page can show more than a single state. On longer or more complex runs, it can step through waiting for Jenkins, failure analysis, child-job analysis, Jira search, peer review rounds, and the final save step.

> **Warning:** Re-analysis does not change Jenkins wait behavior. If the error says it timed out waiting for Jenkins, submit a new analysis with different wait settings instead of relying on `Re-Analyze`.

## Troubleshooting

- `Re-Analyze` is missing or unavailable: the job is still active, or the original result does not have reusable saved settings.
- The web UI shows `Timed Out`, but the CLI shows `failed`: that is expected. `Timed Out` is a web UI label for AI-analysis timeouts.
- The run says it timed out waiting for Jenkins: that is a Jenkins wait timeout, not an AI timeout. Start a fresh analysis with different wait settings.
- A rerun did not help: make sure you changed the setting that matches the failure. Raise AI timeout for AI stalls, switch model/provider for weak analysis, or update repository context when the model lacked enough code or artifact evidence.
- The server restarted while a job was live: jobs that were still waiting on Jenkins resume automatically, but jobs already in `pending` or `running` are marked failed and should be rerun.

## Related Pages

- [Analyzing Jenkins Jobs](analyzing-jenkins-jobs.html)
- [Reviewing, Commenting, and Reclassifying Failures](reviewing-commenting-and-reclassifying-failures.html)
- [Improving Analysis with Repository Context](improving-analysis-with-repository-context.html)
- [Adding Peer Review with Multiple AI Models](adding-peer-review-with-multiple-ai-models.html)
- [Running Your First Analysis](quickstart.html)