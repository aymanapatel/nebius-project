from __future__ import annotations

from typing import Any

from repo_summarizer.language_registry import LanguageConfig, LanguageRegistry


class UniversalSkeletonParser:
    def __init__(self, registry: LanguageRegistry, fallback_lines: int = 40) -> None:
        self._registry = registry
        self._fallback_lines = fallback_lines

    def parse(self, file_content: str, file_extension: str) -> str:
        config = self._registry.language_for_extension(file_extension)
        if config is None:
            return self._fallback(file_content)

        try:
            return self._parse_with_tree_sitter(file_content, config)
        except Exception:
            return self._fallback(file_content)

    def _parse_with_tree_sitter(self, file_content: str, config: LanguageConfig) -> str:
        try:
            from tree_sitter import Parser
        except ImportError as exc:
            raise RuntimeError("tree_sitter is not installed") from exc

        parser = Parser()
        language = self._registry.grammar_for_language(config.name)
        self._set_parser_language(parser, language)

        source_bytes = file_content.encode("utf-8", errors="ignore")
        tree = parser.parse(source_bytes)
        node_map = config.node_type_to_kind()

        extracted: list[str] = []
        stack: list[Any] = [tree.root_node]

        while stack:
            node = stack.pop()
            kind = node_map.get(node.type)
            if kind:
                signature = self._extract_signature(node=node, kind=kind, source_bytes=source_bytes)
                if signature:
                    extracted.append(signature)
            stack.extend(reversed(node.children))

        if extracted:
            return "\n".join(dict.fromkeys(extracted))
        return self._fallback(file_content)

    @staticmethod
    def _set_parser_language(parser: Any, language: object) -> None:
        if hasattr(parser, "set_language"):
            parser.set_language(language)  # type: ignore[arg-type]
            return
        parser.language = language  # type: ignore[attr-defined]

    def _extract_signature(self, node: Any, kind: str, source_bytes: bytes) -> str | None:
        snippet = source_bytes[node.start_byte : node.end_byte].decode("utf-8", errors="ignore")
        lines = [line.strip() for line in snippet.splitlines() if line.strip()]
        if not lines:
            return None

        if kind == "import":
            return self._truncate_line(lines[0], limit=180)

        first_line = lines[0]
        first_line = first_line.rstrip("{").strip()
        if first_line and not first_line.endswith("..."):
            if first_line.endswith(":"):
                first_line = f"{first_line} ..."
            else:
                first_line = f"{first_line} ..."

        if first_line != "...":
            return self._truncate_line(first_line, limit=220)

        identifier = self._first_identifier(node, source_bytes)
        parameters = self._parameter_list(node, source_bytes)
        if identifier:
            return f"{kind} {identifier}{parameters}: ..."
        return None

    def _fallback(self, file_content: str) -> str:
        lines = file_content.splitlines()
        return "\n".join(lines[: self._fallback_lines]).strip()

    @staticmethod
    def _truncate_line(line: str, limit: int) -> str:
        if len(line) <= limit:
            return line
        return f"{line[: limit - 3]}..."

    def _first_identifier(self, node: Any, source_bytes: bytes) -> str:
        identifier_types = {
            "identifier",
            "type_identifier",
            "property_identifier",
            "field_identifier",
        }
        stack: list[Any] = [node]
        while stack:
            current = stack.pop()
            if current.type in identifier_types:
                return source_bytes[current.start_byte : current.end_byte].decode(
                    "utf-8", errors="ignore"
                )
            stack.extend(reversed(current.children))
        return ""

    def _parameter_list(self, node: Any, source_bytes: bytes) -> str:
        stack: list[Any] = [node]
        while stack:
            current = stack.pop()
            if "parameter" in current.type:
                text = source_bytes[current.start_byte : current.end_byte].decode(
                    "utf-8", errors="ignore"
                )
                return text.replace("\n", " ").strip()
            stack.extend(reversed(current.children))
        return "()"
