Sync and classify all jobs from the LinkedIn Jobs Tracker, then display results.

## What this command does

1. Run `python main.py fetch --cdp` to pull ALL tracked jobs from LinkedIn and save raw data to SQLite.
   - The tracker is bot-protected (PerimeterX) and paginates 10/page, so we drive the user's real Chrome over CDP. Prereq: the user launches Chrome with `--remote-debugging-port=9222 --user-data-dir="$HOME/li-chrome-profile"` and is logged into LinkedIn. If CDP isn't available, tell the user to launch it (see lib/browser.py / memory `jobs-tracker-pagination`).
2. Read the JSON output of unclassified jobs (only jobs new to the DB need classifying).
3. For each unclassified job, classify it using the rules below.
4. **For visa: look the company up in the UK sponsor register** (see Visa section) — this requires a lookup for every company not already in the DB.
5. Run `python main.py save-labels-batch` with the classifications.
6. Run `python main.py list` to display the final table.

Notes on sync behaviour:
- Existing jobs: scraped fields are refreshed; classification labels are **preserved** (only `category IS NULL` jobs get classified).
- Jobs no longer in your saved list are soft-marked `status='removed'` (labels kept), and re-appear as `active` if you re-save them. Pruning only happens on a full `--cdp` sync and is skipped if the fetch looks partial.
- `list` hides removed jobs by default (`--include-removed` / `--removed-only` to see them).

## Classification rules

### Category (based on company name, staff count, company type, founded year)
- `big_tech`: FAANG-level or major tech (Google, Meta, Apple, Microsoft, Amazon, Netflix, OpenAI, Anthropic, DeepMind, NVIDIA, Stripe, Salesforce, Adobe, Uber, Airbnb, Waymo, etc.)
- `mid_size`: Established company, typically 1,000–50,000 employees
- `startup`: Small company (<1,000 employees) or founded <10 years ago — use judgment

### Visa — determine by JD text AND the UK sponsor register (not just the JD)
For any company not already classified in the DB, check whether it is a licensed UK visa sponsor. The authoritative source is the **UK Register of Licensed Sponsors (Workers)**:
1. Get the current CSV URL from `https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers` (grep the page for the `assets.publishing.service.gov.uk/...csv` link — the filename changes daily).
2. Download it once and match company names (normalise: lowercase, strip Ltd/Limited/Inc/UK/Group/etc., punctuation; watch for legal-name variants e.g. Compare the Market = "BGL Group", and false positives on common single words like "reflection"/"flawless").

Labels (only 3 values):
- `not_available`: JD explicitly states no sponsorship or requires existing right to work. (JD overrides the register.)
- `likely`: the company **is on the sponsor register** (or is a well-known multinational that clearly sponsors, e.g. Apple/Roche/JPMorgan/Spotify/Revolut), OR the JD explicitly offers sponsorship. (JDs that offer sponsorship are folded into `likely` for simplicity.)
- `maybe`: company is **not** found on the register (or can't be confidently matched) and the JD is silent.

### Type (based on JD CONTENT, not job title)
- `mle`: Traditional ML engineering — training pipelines, MLOps, model serving, feature stores.
- `agentic_ai`: LLM/agentic systems — LLM APIs, RAG, agents, tool use, AI products built on top of models.
- `ml_scientist`: Research-heavy — novel methods, publications, less deployment.
- `ai_ml_mixed`: Clear blend of two or more of the above.
- `data_scientist`: Analytics + ML blend — A/B testing, dashboards, SQL, business metrics.
- `swe`: General software engineering — the JD is backend/platform/data-engineering with no real ML modelling, even if the title says "AI"/"ML". Classify by JD content, not the title.

### Leetcode (based on company interview culture knowledge — don't be too lenient)
- `hard`: FAANG+ and big tech (Google, Meta, Amazon, Apple, Microsoft, NVIDIA, Adobe, Bloomberg, Waymo), quant/HFT (Jane Street, Two Sigma, Citadel, Jump, quant funds, Graham Capital, WorldQuant), AND established product/consumer tech that runs FAANG-style algorithmic loops (Spotify, Revolut, Deliveroo, Roku, Yelp, Reddit, Databricks, Canva, Sony, Arm, JPMorgan, etc.).
- `medium`: Second-tier established companies and well-known startups/AI labs with a moderate bar (Cohere, Mistral, Anthropic, JetBrains, Darktrace, GSK, Sky, etc.).
- `low`: Early startups, research labs, and non-tech-first companies (standard / non-competitive-coding interviews).

## After classifying

Output the labels as a JSON array to pass to save-labels-batch:
```
python main.py save-labels-batch << 'EOF'
[
  {"job_id": "...", "category": "...", "visa": "...", "type": "...", "leetcode": "..."},
  ...
]
EOF
```

## Common filters after sync

```bash
python main.py list --visa likely --leetcode medium,low
python main.py list --type mle agentic_ai
python main.py list --category big_tech --visa likely
python main.py list --type swe          # general SWE roles
```
