from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class LanguageConfig:
    name: str
    extensions: tuple[str, ...]
    grammar: str
    nodes: dict[str, tuple[str, ...]]

    def node_type_to_kind(self) -> dict[str, str]:
        node_map: dict[str, str] = {}
        for kind, node_types in self.nodes.items():
            for node_type in node_types:
                node_map[node_type] = kind
        return node_map


class LanguageRegistry:
    def __init__(self, config_path: Path) -> None:
        self._config_path = config_path
        self._languages: dict[str, LanguageConfig] = {}
        self._by_extension: dict[str, LanguageConfig] = {}
        self._grammar_cache: dict[str, Any] = {}
        self._load()

    def supported_languages(self) -> list[LanguageConfig]:
        return sorted(self._languages.values(), key=lambda item: item.name)

    def language_for_extension(self, extension: str) -> LanguageConfig | None:
        return self._by_extension.get(extension.lower())

    def grammar_for_language(self, language_name: str) -> Any:
        config = self._languages.get(language_name)
        if config is None:
            raise KeyError(f"Language '{language_name}' is not present in {self._config_path}")

        if config.grammar in self._grammar_cache:
            return self._grammar_cache[config.grammar]

        grammar = self._load_grammar_module(config.grammar)
        self._grammar_cache[config.grammar] = grammar
        return grammar

    def _load(self) -> None:
        payload = yaml.safe_load(self._config_path.read_text(encoding="utf-8")) or {}
        if not isinstance(payload, dict):
            raise ValueError(f"{self._config_path} must contain a mapping of languages")

        for language_name, config_data in payload.items():
            if not isinstance(config_data, dict):
                raise ValueError(f"Language '{language_name}' config must be a mapping")

            extensions = tuple(str(value).lower() for value in config_data.get("extensions", []))
            grammar = str(config_data.get("grammar", "")).strip()
            raw_nodes = config_data.get("nodes", {})

            if not extensions:
                raise ValueError(f"Language '{language_name}' has no extensions")
            if not grammar:
                raise ValueError(f"Language '{language_name}' has no grammar module")
            if not isinstance(raw_nodes, dict):
                raise ValueError(f"Language '{language_name}' nodes must be a mapping")

            nodes: dict[str, tuple[str, ...]] = {}
            for kind, node_types in raw_nodes.items():
                if isinstance(node_types, str):
                    normalized = (node_types,)
                elif isinstance(node_types, list) and all(isinstance(item, str) for item in node_types):
                    normalized = tuple(node_types)
                else:
                    raise ValueError(
                        f"Language '{language_name}' kind '{kind}' must be a string or list of strings"
                    )
                nodes[str(kind)] = normalized

            language = LanguageConfig(
                name=str(language_name),
                extensions=extensions,
                grammar=grammar,
                nodes=nodes,
            )
            self._languages[language.name] = language

            for extension in extensions:
                self._by_extension[extension] = language

    @staticmethod
    def _load_grammar_module(module_name: str) -> Any:
        try:
            from tree_sitter import Language
        except ImportError as exc:
            raise ImportError(
                "tree_sitter is not installed. Install dependencies with "
                "'python -m pip install -e .' to enable AST parsing."
            ) from exc

        try:
            module = importlib.import_module(module_name)
        except ImportError as exc:
            raise ImportError(
                f"Could not import grammar module '{module_name}'. "
                "Install the matching tree-sitter grammar package."
            ) from exc

        candidates: list[Any] = []
        if hasattr(module, "LANGUAGE"):
            candidates.append(getattr(module, "LANGUAGE"))
        if hasattr(module, "language"):
            candidates.append(getattr(module, "language")())

        for candidate in candidates:
            if isinstance(candidate, Language):
                return candidate
            try:
                return Language(candidate)
            except (TypeError, ValueError):
                continue

        raise RuntimeError(
            f"Grammar module '{module_name}' does not expose a compatible Tree-sitter language object."
        )
