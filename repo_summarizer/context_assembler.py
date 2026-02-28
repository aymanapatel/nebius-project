from __future__ import annotations

import logging
from pathlib import Path

import tiktoken

from repo_summarizer.skeleton_parser import UniversalSkeletonParser

logger = logging.getLogger(__name__)


class ContextAssembler:
    def __init__(
        self,
        parser: UniversalSkeletonParser,
        token_budget: int = 7000,
        encoding_name: str = "cl100k_base",
    ) -> None:
        self._parser = parser
        self._token_budget = token_budget
        self._encoding = tiktoken.get_encoding(encoding_name)

    def build(self, repo_path: Path, prioritized_files: list[Path]) -> tuple[str, list[str]]:
        logger.info(
            "Building context token_budget=%d candidate_files=%d",
            self._token_budget,
            len(prioritized_files),
        )
        chunks: list[str] = []
        included_files: list[str] = []
        tokens_used = 0

        for file_path in prioritized_files:
            raw_text = self._read_text(file_path)
            if not raw_text:
                continue

            summary = self._parser.parse(raw_text, file_path.suffix.lower())
            if not summary:
                continue

            relative_path = file_path.relative_to(repo_path).as_posix()
            section = f"File: {relative_path}\n-----------------------\n{summary.strip()}\n"
            section_tokens = self._count_tokens(section)

            if section_tokens > self._token_budget:
                logger.debug(
                    "Skipping file over budget file=%s section_tokens=%d",
                    relative_path,
                    section_tokens,
                )
                continue
            if tokens_used + section_tokens > self._token_budget:
                logger.debug(
                    "Skipping file due to remaining budget file=%s section_tokens=%d tokens_used=%d",
                    relative_path,
                    section_tokens,
                    tokens_used,
                )
                continue

            tokens_used += section_tokens
            chunks.append(section)
            included_files.append(relative_path)

        logger.info(
            "Context assembly complete included_files=%d tokens_used=%d",
            len(included_files),
            tokens_used,
        )
        logger.debug("Context included files=%s", included_files)
        return "\n".join(chunks).strip(), included_files

    @staticmethod
    def _read_text(file_path: Path) -> str:
        try:
            data = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return ""
        return data[:50000]

    def _count_tokens(self, text: str) -> int:
        return len(self._encoding.encode(text))
