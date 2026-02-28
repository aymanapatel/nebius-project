# Repository Summarizer

A FastAPI service that generates human-readable summaries of GitHub repositories using LLMs. The service extracts code skeletons (functions, classes, imports) from source files and uses them to generate concise project summaries, identify technologies, and describe project structure.

## Design Decisions

### Why Code Skeletons?

Full source code often exceeds LLM context limits. By extracting only signatures using the AST and Tree-sitter (function names, parameters, class definitions), we:
- Fit more files within the token budget
- Provide the LLM with structural understanding
- Reduce noise from implementation details

### Token Budget Strategy

- **Default**: 7000 tokens (leaves room for system prompt and response)
- **Greedy Selection**: Prioritized files added until budget exhausted
- **Per-file Limits**: Files exceeding budget skipped individually

### Multi-Language Support

The Tree-sitter based parser supports any language with a grammar module. Adding new languages requires only YAML configuration—no code changes needed.

## Running the Project




```bash
# 1) Create and activate a virtual environment (Python 3.10+)
python3.11 -m venv .venv
source .venv/bin/activate

# 2) Install the project
python -m pip install --upgrade pip
python -m pip install -e .

# 4) Run the server
NEBIUS_API_KEY="your-api-key" uvicorn repo_summarizer.main:app --host 0.0.0.0 --port 8000 --workers 4
```

## API call

Sample API call

```curl
curl -sS -X POST "http://127.0.0.1:8000/summarize" \
    -H "Content-Type: application/json" \
    -d '{"github_url":"https://github.com/pytorch/pytorch"}'
```

## Architecture

## System Prompt

The system prompt can be find in [here](repo_summarizer/prompts/system_prompt.txt).

### Overview

The Repository Summarizer follows a multi-layered architecture designed to handle repositories of any size efficiently while working within LLM context window limitations.

```
┌─────────────────────────────────────────────────────────────────┐
│                        API Layer                                │
│                       ┌───────────────┐                         │
│                       │POST /summarize|                         │
│                       └──────┬────────┘                         │
└──────────────────────────────┼──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Processing Pipeline                           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│  │   Repository │─▶│  File Scan & │─▶│   Context    │           │
│  │     Clone    │  │  Prioritize  │  │  Assembly    │           │
│  └──────────────┘  └──────────────┘  └──────┬───────┘           │
│                                              │                  │
│                                              ▼                  │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────┐         │
│  │  LLM Client  │◀─│   Skeleton   │◀─│Universal Parser│         │
│  │  (OpenAI     │  │   Summary    │  │   with.        │         │
│  │   format)    │  │   Response   │  │  Treesitter    |         │         
│  └──────────────┘  └──────────────┘  └────────────────┘         │
└─────────────────────────────────────────────────────────────────┘
```

### Core Components

#### 1. Language Registry ([`language_registry.py`](repo_summarizer/language_registry.py))

A configuration-driven language support system that defines how to parse different programming languages.

- **Purpose**: Maps file extensions to Tree-sitter grammars and AST node types
- **Configuration**: [`languages.yaml`](languages.yaml) defines supported languages and their parsing rules
- **Supported Languages**: Python, JavaScript/JSX, Go and many more (extensible via YAML)

```yaml
python:
  extensions: [".py"]
  grammar: "tree_sitter_python"
  nodes:
    function: "function_definition"
    class: "class_definition"
    import: ["import_statement", "import_from_statement"]
```

#### 2. Universal Skeleton Parser ([`skeleton_parser.py`](repo_summarizer/skeleton_parser.py))

A generic AST parser that extracts code signatures (function/class definitions) from source files.

- **Strategy**: Uses Tree-sitter for accurate AST parsing
- **Signature Extraction**: Extracts function/class signatures while replacing body content with placeholders
- **Fallback**: For unsupported files, returns first N lines as plain text


#### 3. Repository Ingestor ([`repository_ingestor.py`](repo_summarizer/repository_ingestor.py))

Handles repository cloning and intelligent file selection.

- **Clone**: Uses `git clone --depth 1` for shallow clones (faster)
- **Ignore Rules**: Respects `.gitignore` patterns to skip irrelevant files
- **Prioritization Algorithm**:
  1. **Entry Points**: `main.py`, `app.py`, `index.js`, `main.go`, etc.
  2. **Source Directories**: Files in `/src/`, `/lib/`, `/app/`, `/server/`, `/cmd/`
  3. **Test Deprioritization**: Test files ranked lower (`*_test.go`, `*.test.js`)

#### 4. Context Assembler ([`context_assembler.py`](repo_summarizer/context_assembler.py))

Builds LLM prompts within a fixed token budget (default: 7000 tokens).

- **Token Budgeting**: Uses `tiktoken` for accurate token counting
- **Greedy Inclusion**: Iteratively adds files until budget exhausted

#### 5. LLM Client ([`llm_client.py`](repo_summarizer/llm_client.py))

LLM integration using OpenAI-compatible API format.

- **Provider**: Nebius Token Factory (hardcoded)
- **Configuration**: Environment variables for API key and model selection
- **Prompt Strategy**: System prompt loaded from [`repo_summarizer/prompts/system_prompt.txt`](repo_summarizer/prompts/system_prompt.txt)

Prompt:

```
See [`repo_summarizer/prompts/system_prompt.txt`](repo_summarizer/prompts/system_prompt.txt)
```

### Data Flow

1. **Request**: `POST /summarize` with GitHub URL
2. **Clone**: Repository cloned to temporary directory
3. **Scan**: Files discovered and filtered by extension
4. **Prioritize**: Entry points and source files ranked highest
5. **Parse**: Code skeletons extracted via Tree-sitter AST
6. **Assemble**: Context built within token budget
7. **Generate**: LLM produces summary, technologies, structure
8. **Response**: JSON returned to client

## Project Structure

```
repo-summarizer/
├── repo_summarizer/           # Main package
│   ├── __init__.py
│   ├── main.py               # FastAPI application & endpoints
│   ├── models.py             # Pydantic request/response models
│   ├── language_registry.py  # Language configuration loader
│   ├── skeleton_parser.py    # Universal AST parser
│   ├── repository_ingestor.py # Git clone & file prioritization
│   ├── context_assembler.py  # Token-budgeted context builder
│   ├── llm_client.py         # LLM provider integration
│   ├── prompts/
│   │   └── system_prompt.txt # LLM system prompt loaded at runtime
│   └── logging_config.py     # Logging configuration
├── languages.yaml            # Language definitions
├── pyproject.toml            # Project metadata & dependencies
├── setup.py                  # Package setup
└── README.md                 # This file
```



