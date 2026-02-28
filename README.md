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

# 3) Set required environment variables
export OPENROUTER_API_KEY=your_openrouter_api_key

# 4) Optional model override
export OPENROUTER_MODEL=openai/gpt-4o-mini

# 5) Optional logging level (INFO or DEBUG)
export LOG_LEVEL=INFO

# 6) Run the server
uvicorn repo_summarizer.main:app --reload
# or: repo-summarizer
```

## Endpoints

- `POST /summarize`
- `GET /languages`


## Extensibility Goal
    
  - Adding a new language only requires:

  1. Add grammar dependency in pyproject.toml (/Users/aymanpatel/Desktop/llm-projects/pyproject.toml)
  2. Add language entry in languages.yaml (/Users/aymanpatel/Desktop/llm-projects/languages.yaml)

  - No core parser/API code changes needed.

  1. If you want, I can add a quick pytest smoke test suite for /languages and /summarize (mocking the LLM call).
