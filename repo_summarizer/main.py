from __future__ import annotations

import logging
import os
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

registry = LanguageRegistry(LANGUAGES_FILE)
parser = UniversalSkeletonParser(registry=registry)
ingestor = RepositoryIngestor(registry=registry)
assembler = ContextAssembler(parser=parser, token_budget=7000)

app = FastAPI(title="Repository Summarizer", version="0.1.0")


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
    responses={400: {"model": ErrorResponse}, 422: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
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
            raise HTTPException(status_code=400, detail=f"Failed to clone repository: {exc}") from exc

        logger.info("Repository cloned repo_path=%s", repo_path)
        candidate_files = ingestor.scan_files(repo_path)
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
            llm = ProjectSummaryLLM(model=os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini"))
            logger.info(
                "Calling LLM summarize model=%s context_chars=%d included_files=%d",
                os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini"),
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
