# LinkedIn Jobs Tracker

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

### Fetch jobs from LinkedIn

```bash
python main.py fetch --cdp
```

This fetches ALL saved jobs from LinkedIn using Chrome DevTools Protocol (more reliable than standard methods).

### List jobs

```bash
python main.py list
```

Display your saved jobs with filters and sorting options.

## Job Classification

### Visa Sponsorship

Jobs are classified as:
- **likely** — Sponsor register indicates likely sponsorship
- **maybe** — Uncertain sponsorship availability  
- **not_available** — Known not to sponsor

Classification uses the UK sponsor register rather than job titles.

### Role Type

- **swe** — Software Engineering (all non-ML engineering roles)
- **ml** — Machine Learning / AI roles
- **other** — Non-engineering roles

Classification is based on job descriptions, not titles.

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
