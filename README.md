# Coverage Pages Indexer

`coverage-indexer` builds static coverage dashboards from CI artifacts and publishes them as simple HTML pages.

It is designed for multi-target setups (for example, multiple test jobs/components), keeps branch history, and provides fast visibility into coverage trends.

## Business Value

- Faster release confidence: teams can see coverage health per branch in one place.
- Clear regression signals: `Prev/Diff` and `Vs default branch` make drops visible immediately.
- Better collaboration: PM/QA/engineering can use one shared, linkable dashboard.
- Low operational overhead: static pages are easy to host and cheap to maintain.

## Engineering Value

- Works with 1..N coverage targets from a single config input.
- Stores historical runs per branch and generates dedicated branch history pages.
- Keeps generation logic deterministic and artifact-based (no database required).
- Handles partial misconfiguration safely:
  - invalid targets are skipped with warnings,
  - pipeline fails only if no valid targets remain.

## What It Generates

- Home page: links to all configured coverage targets.
- Target summary page (`/{app}/index.html`):
  - latest run per branch,
  - run date,
  - coverage, previous coverage, diff,
  - comparison against latest default branch coverage.
- Branch history page (`/{app}/branches/{branch-slug}/index.html`):
  - all runs for that branch,
  - run date, commit, pipeline, report link, coverage, `Prev/Diff`.

## Input Contract

`COVERAGE_TARGETS` must be provided from outside as a JSON array:

```json
[
  { "app": "app-a", "name": "APP A", "job_name": "unit_tests_a" },
  { "app": "app-b", "name": "APP B", "job_name": "unit_tests_b" }
]
```

Required fields per target:

- `app`
- `name`
- `job_name`

Validation behavior:

- If a target is missing required fields, it is skipped.
- If at least one valid target exists, job continues and prints a colored warning at the end.
- If no valid targets exist, job fails (`exit 1`).

## Expected CI Environment

Used variables:

- `CI_PROJECT_URL`
- `CI_COMMIT_REF_NAME`
- `CI_COMMIT_SHA`
- `CI_COMMIT_SHORT_SHA`
- `CI_PIPELINE_ID`
- `CI_PIPELINE_CREATED_AT` (optional, fallback: current UTC time)
- `CI_DEFAULT_BRANCH` (optional, fallback: `master`)
- `COVERAGE_TARGETS` (required JSON)

Expected artifact layout per target:

- HTML report: `build/coverage_html_<job_name>/index.html`
- Summary file: `build/coverage-summary_<job_name>.txt` (for `lines XX%`)

## Local Run

```bash
export COVERAGE_TARGETS='[
  {"app":"app-a","name":"APP A","job_name":"unit_tests_a"},
  {"app":"app-b","name":"APP B","job_name":"unit_tests_b"}
]'
python3 indexer.py
```

Output folders:

- `public/` (static pages to publish)
- `.pages-cache/` (manifests + copied reports)

## State Persistence Note

This project intentionally focuses on indexing/rendering logic and does not enforce a single shared-state architecture.

What this means in practice:

- History can be visible from manifests while some HTML report links may be unavailable, depending on how adopters persist `reports/`.
- Under concurrent pipelines, cache-only persistence can produce partial visibility due to synchronization/race behavior.

Adopters are expected to choose their own persistence strategy based on reliability, cost, and platform constraints.

## Docker

Build:

```bash
docker build -t coverage-indexer .
```

Run:

```bash
docker run --rm \
  -e COVERAGE_TARGETS='[{"app":"app-a","name":"APP A","job_name":"unit_tests_a"}]' \
  -v "$PWD:/work" \
  coverage-indexer
```

## Repository Notes

- Main script: [`indexer.py`](https://github.com/aleksandr-kotlyar/coverage-indexer/blob/master/indexer.py)
- Container entrypoint: [`Dockerfile`](https://github.com/aleksandr-kotlyar/coverage-indexer/blob/master/Dockerfile)
- GitLab include example: [`.gitlab-ci-cov.yaml`](https://github.com/aleksandr-kotlyar/coverage-indexer/blob/master/.gitlab-ci-cov.yaml)

## Consulting

If your team wants to adapt this project for enterprise-grade shared storage and concurrency guarantees, I can support design and implementation as a dedicated consulting engagement.
