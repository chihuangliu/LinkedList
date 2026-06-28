# LinkedList 

A command-line tool to fetch, classify, and filter your saved LinkedIn job postings.

## Features

- **Fetch jobs** from LinkedIn saved jobs using Chrome DevTools Protocol (CDP)
- **Classify jobs** by visa sponsorship availability and role type (SWE vs. non-SWE)
- **Filter and display** jobs with customizable views
- **Track job status** with soft-delete support
- **Difficulty calibration** (Leetcode-style) for interview preparation

## Installation

Requires Python 3.12+

```bash
uv sync
```

## Usage

### Sync jobs from LinkedIn

CDP mode drives your real Chrome session and reliably bypasses bot detection. First, launch Chrome with remote debugging enabled:

```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/li-chrome-profile"
```

Log into LinkedIn in that window, then run:

```bash
python main.py fetch --cdp
```

This fetches all saved jobs, updates the local SQLite database, and prints any unclassified jobs as JSON for classification.

### List jobs

```bash
python main.py list
```

Filter by label:

```bash
python main.py list --visa likely --leetcode medium,low
python main.py list --type mle agentic_ai
python main.py list --category big_tech --visa likely
```

Show a single job in full detail:

```bash
python main.py show <job_id>
```

## Job Classification

### Visa Sponsorship

Jobs are classified as:
- **likely** — Sponsor register indicates likely sponsorship
- **maybe** — Uncertain sponsorship availability  
- **not_available** — Known not to sponsor

Classification uses the UK sponsor register rather than job titles.

### Role Type

- **swe** — General software engineering (backend/platform/data-eng with no real ML)
- **mle** — Traditional ML engineering (training pipelines, MLOps, model serving)
- **agentic_ai** — LLM/agentic systems (RAG, agents, LLM APIs)
- **ml_scientist** — Research-heavy (novel methods, publications)
- **ai_ml_mixed** — Clear blend of two or more of the above
- **data_scientist** — Analytics + ML blend (A/B testing, SQL, business metrics)

Classification is based on job description content, not the job title.

## Data Management

- Active jobs are marked with `status: active`
- Removed jobs are marked with `status: removed`
- The `fetch --cdp` command prunes previously saved jobs that are no longer saved on LinkedIn
- List commands hide removed jobs by default

## Dependencies

- `click` — CLI framework
- `pyyaml` — YAML configuration
- `requests` — HTTP library
- `tabulate` — Pretty-print tables
