from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

import pathspec

from repo_summarizer.language_registry import LanguageRegistry

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
    def __init__(self, message: str, *, reason: str = "unknown") -> None:
        super().__init__(message)
        self.reason = reason


class RepositoryIngestor:
    def __init__(self, registry: LanguageRegistry) -> None:
        self._registry = registry
        self._gitignore_spec: pathspec.PathSpec | None = None

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
            result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired as exc:
            raise RepositoryCloneError(
                "git clone timed out after 120 seconds (repository may be too large)",
                reason="network",
            ) from exc
        except OSError as exc:
            raise RepositoryCloneError(f"Failed to run git: {exc}", reason="network") from exc

        if result.returncode != 0:
            message = (result.stderr or result.stdout or "git clone failed").strip()
            reason = self._classify_clone_failure(message)
            raise RepositoryCloneError(message, reason=reason)
        logger.debug("Clone command succeeded destination=%s", destination)

        return destination

    def scan_files(self, repo_path: Path) -> list[Path]:
        self._gitignore_spec = self._load_gitignore(repo_path)
        discovered: list[Path] = []

        for root, dirs, files in os.walk(repo_path):
            root_path = Path(root)

            # Prune directories matched by .gitignore (always skip .git itself)
            dirs[:] = [
                d for d in dirs
                if d != ".git"
                and not (root_path / d).is_symlink()
                and not self._is_ignored(root_path / d, repo_path, is_dir=True)
            ]

            for filename in files:
                file_path = root_path / filename
                # Skip symlinks to avoid loops and out-of-tree reads.
                if file_path.is_symlink():
                    logger.debug("Skipping symlink file_path=%s", file_path)
                    continue
                if self._should_ignore(file_path, repo_path):
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

    def _should_ignore(self, file_path: Path, repo_path: Path) -> bool:
        if self._is_ignored(file_path, repo_path, is_dir=False):
            return True
        return self._is_likely_binary(file_path)

    def _is_ignored(self, file_path: Path, repo_path: Path, *, is_dir: bool) -> bool:
        if self._gitignore_spec is None:
            return False
        relative = file_path.relative_to(repo_path).as_posix()
        if is_dir:
            relative += "/"
        return self._gitignore_spec.match_file(relative)

    @staticmethod
    def _load_gitignore(repo_path: Path) -> pathspec.PathSpec | None:
        gitignore_path = repo_path / ".gitignore"
        if not gitignore_path.is_file():
            logger.debug("No .gitignore found at repo_path=%s", repo_path)
            return None
        try:
            patterns = gitignore_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            logger.warning("Failed to read .gitignore at %s", gitignore_path)
            return None
        spec = pathspec.PathSpec.from_lines("gitwildmatch", patterns.splitlines())
        logger.info("Loaded .gitignore with %d patterns", len(spec.patterns))
        return spec

    @staticmethod
    def _is_likely_binary(file_path: Path) -> bool:
        try:
            sample = file_path.read_bytes()[:2048]
        except OSError:
            return True
        return b"\x00" in sample

    @staticmethod
    def _classify_clone_failure(message: str) -> str:
        lower = message.lower()

        network_markers = (
            "could not resolve host",
            "failed to connect",
            "connection timed out",
            "operation timed out",
            "network is unreachable",
            "connection reset",
            "tls",
            "ssl",
        )
        if any(marker in lower for marker in network_markers):
            return "network"

        if "repository not found" in lower or "not found" in lower:
            return "not_found_or_private"

        private_markers = (
            "authentication failed",
            "could not read username",
            "access denied",
            "permission denied",
        )
        if any(marker in lower for marker in private_markers):
            return "private"

        invalid_markers = (
            "not a git repository",
            "unable to access",
            "does not appear to be a git repository",
            "invalid",
        )
        if any(marker in lower for marker in invalid_markers):
            return "invalid"

        return "unknown"
