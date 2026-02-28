from __future__ import annotations

import getpass
import logging
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from repo_summarizer.context_assembler import ContextAssembler
from repo_summarizer.language_registry import LanguageRegistry
from repo_summarizer.llm_client import LLMError, ProjectSummaryLLM
from repo_summarizer.logging_config import configure_logging
from repo_summarizer.models import (
    ErrorResponse,
    LanguageInfo,
    SummarizeRequest,
    SummaryResponse,
    SupportedLanguagesResponse,
)
from repo_summarizer.repository_ingestor import RepositoryCloneError, RepositoryIngestor
from repo_summarizer.skeleton_parser import UniversalSkeletonParser

configure_logging()
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
LANGUAGES_FILE = Path(os.getenv("LANGUAGE_REGISTRY_PATH", ROOT / "languages.yaml"))

# Map file extensions to canonical technology names used for cross-validation.
_EXT_TO_TECH: dict[str, str] = {
    ".py": "Python",
    ".js": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".jsx": "React",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".go": "Go",
    ".java": "Java",
    ".kt": "Kotlin",
    ".rb": "Ruby",
    ".rs": "Rust",
    ".cpp": "C++",
    ".cc": "C++",
    ".c": "C",
    ".cs": "C#",
    ".php": "PHP",
    ".swift": "Swift",
    ".sh": "Shell",
    ".bash": "Shell",
    ".sql": "SQL",
    ".html": "HTML",
    ".css": "CSS",
    ".scss": "CSS",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".json": "JSON",
    ".tf": "Terraform",
    ".dockerfile": "Docker",
}

registry = LanguageRegistry(LANGUAGES_FILE)
parser = UniversalSkeletonParser(registry=registry)
ingestor = RepositoryIngestor(registry=registry)
assembler = ContextAssembler(parser=parser, token_budget=7000)

app = FastAPI(title="Repository Summarizer", version="0.1.0")


def _cross_validate_technologies(
    llm_technologies: list[str],
    included_files: list[str],
) -> list[str]:
    """Merge LLM-claimed technologies with those evidenced by file extensions.

    Logs a warning for any LLM technology that cannot be correlated to an
    observed file extension, and always injects extension-derived technologies
    that the LLM may have missed.
    """
    observed_extensions = {Path(f).suffix.lower() for f in included_files}
    # Technologies inferred directly from file extensions in the repo.
    evidence_based: set[str] = {
        tech for ext, tech in _EXT_TO_TECH.items() if ext in observed_extensions
    }
    llm_set = {t.strip() for t in llm_technologies if t.strip()}

    # Warn about any technology the LLM claims with no file-level evidence.
    for tech in sorted(llm_set):
        canonical_names = {v.lower() for v in _EXT_TO_TECH.values()}
        # Only warn if the claimed technology is a "known" one we can validate.
        if tech.lower() in canonical_names and tech not in evidence_based:
            logger.warning(
                "LLM claimed technology '%s' but no matching files were found in the repository",
                tech,
            )

    # Return LLM list augmented with any extension-based technologies it missed.
    merged = list(llm_set | evidence_based)
    merged.sort()
    return merged


@app.on_event("startup")
async def startup_event() -> None:
    logger.info("Startup with API_PROVIDER=nebius")


@app.exception_handler(HTTPException)
async def http_exception_handler(_, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(message=str(exc.detail)).model_dump(),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=ErrorResponse(message=str(exc)).model_dump(),
    )


@app.exception_handler(Exception)
async def general_exception_handler(_, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(message=f"Internal server error: {exc}").model_dump(),
    )


@app.post(
    "/summarize",
    response_model=SummaryResponse,
    responses={
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def summarize_repository(payload: SummarizeRequest) -> SummaryResponse:
    github_url = str(payload.github_url)
    logger.info("Received summarize request github_url=%s", github_url)

    with TemporaryDirectory(prefix="repo-summarizer-") as temp_dir:
        checkout_path = Path(temp_dir) / "checkout"
        logger.debug("Using temporary checkout path=%s", checkout_path)

        try:
            repo_path = ingestor.clone(github_url=github_url, destination=checkout_path)
        except RepositoryCloneError as exc:
            logger.exception("Repository clone failed github_url=%s", github_url)
            reason = getattr(exc, "reason", "unknown")
            if reason == "network":
                raise HTTPException(
                    status_code=503,
                    detail="Network error while cloning repository. Please retry.",
                ) from exc
            if reason == "private":
                raise HTTPException(
                    status_code=403,
                    detail="Repository appears to be private or requires authentication.",
                ) from exc
            if reason == "not_found_or_private":
                raise HTTPException(
                    status_code=404,
                    detail="Repository not found or is private.",
                ) from exc
            if reason == "invalid":
                raise HTTPException(
                    status_code=400,
                    detail="Invalid GitHub repository URL or repository is not accessible.",
                ) from exc

            raise HTTPException(
                status_code=400,
                detail=f"Failed to clone repository: {exc}",
            ) from exc

        logger.info("Repository cloned repo_path=%s", repo_path)
        candidate_files = ingestor.scan_files(repo_path)
        if not candidate_files:
            logger.warning("Repository appears empty or unreadable github_url=%s", github_url)
            raise HTTPException(
                status_code=400,
                detail="Repository is empty or contains only ignored/binary files",
            )

        prioritized_files = ingestor.prioritize(candidate_files, repo_path=repo_path)
        context, included_files = assembler.build(repo_path=repo_path, prioritized_files=prioritized_files)
        logger.info(
            "Repository processed candidate_files=%d prioritized_files=%d included_files=%d",
            len(candidate_files),
            len(prioritized_files),
            len(included_files),
        )
        logger.debug("Included files sample=%s", included_files[:20])

        if not included_files or not context:
            logger.warning("No readable files found for summarization github_url=%s", github_url)
            raise HTTPException(status_code=400, detail="No readable source files found to summarize")

        try:
            llm = ProjectSummaryLLM()
            logger.info(
                "Calling LLM summarize provider=%s model=%s context_chars=%d included_files=%d",
                llm.provider,
                llm.model,
                len(context),
                len(included_files),
            )
            result = llm.summarize(context)
        except LLMError as exc:
            logger.exception("LLM summarization failed github_url=%s", github_url)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        if not result["summary"] or not result["structure"]:
            logger.error("LLM returned incomplete payload keys=%s", sorted(result.keys()))
            raise HTTPException(status_code=500, detail="LLM returned an incomplete summary payload")

        # Cross-validate technologies against observed file extensions.
        result["technologies"] = _cross_validate_technologies(
            result["technologies"], included_files
        )

        logger.info("Summarize request completed github_url=%s", github_url)
        return SummaryResponse(**result)


@app.get("/languages", response_model=SupportedLanguagesResponse)
def list_supported_languages() -> SupportedLanguagesResponse:
    languages = [
        LanguageInfo(name=config.name, extensions=list(config.extensions))
        for config in registry.supported_languages()
    ]
    logger.debug("Returning supported languages count=%d", len(languages))
    return SupportedLanguagesResponse(languages=languages)


def run() -> None:
    uvicorn.run(
        "repo_summarizer.main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        reload=False,
    )


if __name__ == "__main__":
    run()
