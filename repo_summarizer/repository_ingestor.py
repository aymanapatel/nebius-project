from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from repo_summarizer.language_registry import LanguageRegistry


IGNORED_DIRS = {
    ".git",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".idea",
    ".vscode",
    "node_modules",
    "venv",
    ".venv",
    "target",
    "build",
    "dist",
    ".next",
}

IGNORED_FILENAMES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "Pipfile.lock",
    "Cargo.lock",
}

IGNORED_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".svg",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
    ".so",
    ".dll",
    ".exe",
    ".bin",
    ".class",
    ".jar",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".map",
}

ENTRYPOINT_FILENAMES = {
    "main.py",
    "app.py",
    "server.py",
    "index.js",
    "app.js",
    "main.go",
    "cmd.go",
}

PRIORITY_SEGMENTS = {"/src/", "/lib/", "/app/", "/server/", "/cmd/"}
logger = logging.getLogger(__name__)


class RepositoryCloneError(RuntimeError):
    pass


class RepositoryIngestor:
    def __init__(self, registry: LanguageRegistry) -> None:
        self._registry = registry

    def clone(self, github_url: str, destination: Path) -> Path:
        logger.info("Cloning repository github_url=%s destination=%s", github_url, destination)
        command = [
            "git",
            "clone",
            "--depth",
            "1",
            github_url,
            str(destination),
        ]
        try:
            result = subprocess.run(command, check=False, capture_output=True, text=True)
        except OSError as exc:
            raise RepositoryCloneError(f"Failed to run git: {exc}") from exc

        if result.returncode != 0:
            message = (result.stderr or result.stdout or "git clone failed").strip()
            raise RepositoryCloneError(message)
        logger.debug("Clone command succeeded destination=%s", destination)

        return destination

    def scan_files(self, repo_path: Path) -> list[Path]:
        discovered: list[Path] = []

        for root, dirs, files in os.walk(repo_path):
            dirs[:] = [item for item in dirs if item not in IGNORED_DIRS]
            root_path = Path(root)

            for filename in files:
                file_path = root_path / filename
                if self._should_ignore(file_path):
                    continue
                discovered.append(file_path)

        logger.info("Scanned repository files discovered=%d repo_path=%s", len(discovered), repo_path)
        return discovered

    def prioritize(self, files: list[Path], repo_path: Path) -> list[Path]:
        prioritized = sorted(files, key=lambda item: self._priority_score(item, repo_path), reverse=True)
        logger.info("Prioritized files total=%d", len(prioritized))
        logger.debug("Top prioritized files=%s", [p.relative_to(repo_path).as_posix() for p in prioritized[:20]])
        return prioritized

    def _priority_score(self, file_path: Path, repo_path: Path) -> int:
        score = 0
        relative = f"/{file_path.relative_to(repo_path).as_posix().lower()}"
        filename = file_path.name.lower()
        extension = file_path.suffix.lower()

        if filename in {"readme.md", "readme.rst", "readme"}:
            score += 120
        if filename in ENTRYPOINT_FILENAMES:
            score += 90
        if any(segment in relative for segment in PRIORITY_SEGMENTS):
            score += 60
        if filename in {"pyproject.toml", "package.json", "go.mod", "setup.py", "requirements.txt"}:
            score += 70
        if self._registry.language_for_extension(extension):
            score += 35
        if "/tests/" in relative or filename.startswith("test_") or filename.endswith("_test.go"):
            score -= 55
        if "/docs/" in relative:
            score -= 25
        if filename.endswith(".test.js") or filename.endswith(".spec.js"):
            score -= 45

        # Keep stable ordering across files with similar scores.
        score -= len(relative) // 50
        return score

    def _should_ignore(self, file_path: Path) -> bool:
        lower_name = file_path.name.lower()
        if lower_name in IGNORED_FILENAMES:
            return True
        if file_path.suffix.lower() in IGNORED_EXTENSIONS:
            return True
        return self._is_likely_binary(file_path)

    @staticmethod
    def _is_likely_binary(file_path: Path) -> bool:
        try:
            sample = file_path.read_bytes()[:2048]
        except OSError:
            return True
        return b"\x00" in sample
