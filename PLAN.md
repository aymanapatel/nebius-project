# Plan.md


Build a simple API service that takes a GitHub repository URL and returns a human-readable summary of the project: what it does, what technologies are used, and how it's structured.

The interesting part of this task is **how to handle the repository contents before sending them to the LLM**:

- Repositories can be large — you can't just send everything to the LLM
- You need to decide which files are important and which can be ignored (e.g., binary files, lock files, `node_modules/`, etc.)
- The LLM has a limited context window — you need a strategy for fitting the most relevant information
- Think about what gives the LLM the best understanding of a project: README? Directory tree? Key source files? Config files?

Here is the Implementation Plan:

---

### 🏛️ System Architecture: The Polyglot Engine

The system now consists of three distinct layers:
1.  **Language Registry:** A configuration map that links file extensions to parsing rules.
2.  **Generic AST Parser:** A single parser engine that uses the registry to decide *how* to extract signatures.
3.  **Summarization Pipeline:** The logic that feeds the extracted skeletons to the LLM.

---

### 📋 Phase 1: The Language Registry (Configuration Layer)
**Goal:** Define "What defines a function/class?" for different languages without rewriting the parsing logic.

**Tasks:**
1.  **Create a `languages.yaml` Configuration:**
    *   Map file extensions to Tree-sitter language packages.
    *   Map language-specific AST node types that represent "Skeletons" (Classes, Functions, Imports).
    *   *Example Entry:*
        ```yaml
        python:
          extensions: [".py"]
          grammar: "tree_sitter_python"
          nodes:
            function: "function_definition"
            class: "class_definition"
            import: "import_statement"
        javascript:
          extensions: [".js", ".jsx"]
          grammar: "tree_sitter_javascript"
          nodes:
            function: ["function_declaration", "arrow_function"]
            class: "class_declaration"
            import: "import_statement"
        go:
          extensions: [".go"]
          grammar: "tree_sitter_go"
          nodes:
            function: "function_declaration"
            # Go uses specific structs, can be added later
        ```
2.  **Dynamic Grammar Loading:**
    *   Write a Python loader that reads this YAML and dynamically imports the necessary `tree-sitter` grammar libraries only when needed.

### 📋 Phase 2: The Generic AST Parser (Core Engine)
**Goal:** A single parser class that works for *any* language defined in the registry.

**Tasks:**
1.  **Develop `UniversalSkeletonParser`:**
    *   **Input:** `file_content`, `file_extension`.
    *   **Process:**
        1.  Look up the configuration for the given extension.
        2.  Initialize the specific Tree-sitter grammar.
        3.  Traverse the AST recursively.
        4.  **Generic Match:** When the parser hits a node type listed in `nodes` (e.g., "function_definition"), it extracts the signature.
    2.  **Signature Extraction Logic:**
        *   Instead of hardcoding "get function name", use heuristics valid for most C-style languages:
            *   Extract the first identifier child (usually the name).
            *   Extract parameter list nodes.
            *   Replace the body (block statements) with a placeholder.
    3.  **Fallback Mechanism:**
        *   If a language is not supported (e.g., a `.md` or `.txt` file), the parser should return the first N lines (truncation strategy) instead of AST parsing.

### 📋 Phase 3: Repository Ingestion (The Multi-Linguist)
**Goal:** Handle mixed-language repositories (e.g., a Python backend with a React frontend).

**Tasks:**
1.  **Extension-Based Filtering:**
    *   Scan the repository directory tree.
    *   Group files by language based on the registry.
2.  **Intelligent Prioritization:**
    *   If the context window is limited, which files do we keep?
    *   **Strategy:** Prioritize "Entry Point" files (e.g., `main.py`, `index.js`, `app.go`) and files in `src/` or `lib/`. Deprioritize test files (`_test.go`, `.test.js`).
3.  **Agnostic Ignore List:**
    *   Expand the ignore list to include environment-specific folders for all languages (`venv`, `node_modules`, `target`, `build`, `dist`, `.git`).

### 📋 Phase 4: Context Assembly (The "Bucket")
**Goal:** Assemble a multi-language prompt for the LLM.

**Tasks:**
1.  **Token Budgeting:**
    *   Use `tiktoken` to enforce a hard limit (e.g., 7000 tokens).
2.  **Assembly Logic:**
    *   Iterate through prioritized files.
    *   Call `UniversalSkeletonParser`.
    *   Append the output to the prompt buffer with a generic header:
        ```text
        File: src/api/handler.py
        -----------------------
        def handle_request(request: Request) -> Response: ...
        
        File: src/components/Button.jsx
        -----------------------
        const Button = ({ onClick }) => { ... };
        export default Button;
        ```
3.  **LLM Prompt:**
    *   Update the system prompt to be language-agnostic:
        *   *"You are an expert software architect. Analyze the following code signatures from a mixed-language repository. Identify the project's purpose, main components, and how they interact."*

### 📋 Phase 5: API & Infrastructure
**Goal:** Deliver the functionality.

**Tasks:**
1.  **Endpoint Design:**
    *   `POST /summarize`: Accepts `repo_url`.
    *   `GET /languages`: Returns a list of supported languages in the registry.
2.  **Dependency Management:**
    *   Since we are supporting multiple languages, the `requirements.txt` or `pyproject.toml` must include all desired tree-sitter grammars:
        ```text
        tree-sitter
        tree-sitter-python
        tree-sitter-javascript
        tree-sitter-go
        # etc...
        ```


### API Schema

### `POST /summarize`

Accepts a GitHub repository URL, fetches the repository contents, and returns a summary generated by an LLM.

**Request body:**

```json
{
  "github_url": "https://github.com/psf/requests"
}
```

|Field|Type|Required|Description|
|---|---|---|---|
|`github_url`|string|yes|URL of a public GitHub repository|

**Response:**

```json
{
  "summary": "**Requests** is a popular Python library for making HTTP requests...",
  "technologies": ["Python", "urllib3", "certifi"],
  "structure": "The project follows a standard Python package layout with the main source code in `src/requests/`, tests in `tests/`, and documentation in `docs/`."
}
```


|Field|Type|Description|
|---|---|---|
|`summary`|string|A human-readable description of what the project does|
|`technologies`|string[]|List of main technologies, languages, and frameworks used|
|`structure`|string|Brief description of the project structure|

On error, return an appropriate HTTP status code and:

```json
{
  "status": "error",
  "message": "Description of what went wrong"
}
```



---

### 🛠️ Generic Tech Stack

| Component | Library/Tool | Purpose |
| :--- | :--- | :--- |
| **AST Engine** | `tree-sitter` | Universal parsing core |
| **Grammars** | `tree-sitter-python`, `tree-sitter-java`, etc. | Language-specific definitions |
| **Config** | `PyYAML` | Loading the Language Registry |
| **Git** | `GitPython` | Repo cloning |
| **Tokenizer** | `tiktoken` | Token counting |
| **Web** | `FastAPI` | API Server |



Make sure that API is **extensible**. If I need to support Rust next week, I simply add `tree-sitter-rust` to dependencies and add 5 lines to `languages.yaml`— no core code changes required.
