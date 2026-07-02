# CI Integration — trigger auto-healing when a nightly run fails

The auto-healer plugs into **any** CI system with the same three-step pattern:

```
1. Run your tests with traces enabled  (don't fail the job yet)
2. If tests failed  ->  run the auto-healer on the trace results
3. The healer fixes broken locators, validates, and opens a PR
```

That's it. The healer reads the Playwright `trace.zip` files your suite already
produces, so **no change to your tests is required** — only a couple of extra CI steps.

## What you add to your pipeline

| Step | Command |
|---|---|
| Run tests (traces on) | `npx playwright test --trace on` — allow it to fail |
| Install healer | `pip install ai-auto-healer` |
| Heal on failure | `auto-healer heal test-results --auto-pr` |

Set these as CI secrets/env vars:

```
AI_MODE=azure-openai
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_ENDPOINT=...
AZURE_OPENAI_DEPLOYMENT=...
```

## Install channels

Pick whichever fits your runner — all install the same `auto-healer` CLI:

| Channel | Use it when | How |
|---|---|---|
| **PyPI** | Python is available (most CI) | `pip install ai-auto-healer` |
| **Composite Action** | GitHub Actions | `uses: bunnycodec/auto_healing_framework@v1` |
| **Container image** | No Python / want hermetic | `ghcr.io/bunnycodec/ai-auto-healer:1` |

### GitHub Actions — one step (composite action)

```yaml
- name: Run tests
  id: tests
  continue-on-error: true
  run: npx playwright test --grep @smoke --trace on
- name: Auto-heal
  if: steps.tests.outcome == 'failure'
  uses: bunnycodec/auto_healing_framework@v1
  with:
    results-dir: test-results
    mode: azure-openai
  env:
    AZURE_OPENAI_API_KEY: ${{ secrets.AZURE_OPENAI_API_KEY }}
    AZURE_OPENAI_ENDPOINT: ${{ secrets.AZURE_OPENAI_ENDPOINT }}
    AZURE_OPENAI_DEPLOYMENT: ${{ secrets.AZURE_OPENAI_DEPLOYMENT }}
```

## Ready-to-use templates (copy into your TEST repo)

| File | System |
|---|---|
| [github-actions-nightly.yml](github-actions-nightly.yml) | GitHub Actions (scheduled) |
| [azure-pipelines-nightly.yml](azure-pipelines-nightly.yml) | Azure DevOps (scheduled) |
| [Jenkinsfile](Jenkinsfile) | Jenkins (cron trigger) |

## Option B — Docker (no Python/Node setup on the runner)

If you'd rather not install anything on the runner, use the published image. The
healer image only needs the `test-results` folder mounted:

```bash
# after your tests ran and produced test-results/
docker run --rm \
  -v "$PWD:/work" -w /work \
  -e AI_MODE=azure-openai \
  -e AZURE_OPENAI_API_KEY="$AZURE_OPENAI_API_KEY" \
  -e AZURE_OPENAI_ENDPOINT="$AZURE_OPENAI_ENDPOINT" \
  -e AZURE_OPENAI_DEPLOYMENT="$AZURE_OPENAI_DEPLOYMENT" \
  ghcr.io/bunnycodec/ai-auto-healer heal test-results --auto-pr
```

## Recommended modes

| Mode | Command | When |
|---|---|---|
| **PR mode** (safest) | `auto-healer heal test-results --auto-pr` | Production nightly — human reviews the fix |
| **Report-only** | `auto-healer heal test-results --dry-run` | First rollout — see suggestions without changes |
| **Auto-commit** | `auto-healer heal test-results --auto-commit` | Trusted suites — commit the fix to a branch |

## Why "don't fail the job yet"

Most CI runners stop the job on the first non-zero exit. You want the test step to
*record* the failure but keep going so the heal step can run:

- GitHub Actions: `continue-on-error: true` + `if: steps.tests.outcome == 'failure'`
- Azure DevOps:   `continueOnError: true` + `condition: failed()`
- Jenkins:        capture the exit code with `returnStatus: true`

## What happens on a green night

If the suite passes, there are no failure traces, so the heal step is skipped entirely.
The healer only does work when there's something broken to fix.

## End-to-end result

A locator drifts (e.g. a button label changes) -> the nightly suite goes red ->
the healer detects the broken locator from the trace, asks the LLM for the correct
one, patches the page object, re-runs to confirm it passes, and **opens a PR**. You
wake up to a reviewable fix instead of a red build.
