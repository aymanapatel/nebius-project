# Repository Summarizer

FastAPI service that ingests a GitHub repository, builds an AST-first context, and asks an LLM for:

- `summary`
- `technologies`
- `structure`

## Run

```bash
# 1) Create and activate a virtual environment (Python 3.10+)
python3.11 -m venv .venv
source .venv/bin/activate

# 2) Install the project
python -m pip install --upgrade pip
python -m pip install -e .

# 4) Run the server
uvicorn repo_summarizer.main:app --reload

# 5) Enter API provider and API Key
Select API provider [nebius/openrouter/openai] (default: nebius): nebius
Enter API key for provider=openrouter: <API-KEY>


```

On startup (interactive terminal), the app prompts for:

- API provider: `openrouter`, `openai`, or `nebius`
- API key for the selected provider
- Nebius endpoint is hardcoded by default (`https://api.studio.nebius.com/v1`)

To disable prompts (for CI/non-interactive runs):

```bash
export DISABLE_STARTUP_PROMPT=1
```

Then set env vars directly:

- `API_PROVIDER=nebius` + `NEBIUS_API_KEY`
- `API_PROVIDER=openrouter` + `OPENROUTER_API_KEY`
- `API_PROVIDER=openai` + `OPENAI_API_KEY`


Optional Nebius overrides:

- `NEBIUS_API_BASE_URL`
- `NEBIUS_MODEL`

## Endpoints

- `POST /summarize`
- `GET /languages`

## Extensibility Goal

Adding a new language only requires:

1. Add grammar dependency in `pyproject.toml`.
2. Add language entry in `languages.yaml`.

No core parser or API endpoint code changes are required.
