from setuptools import find_packages, setup


setup(
    name="repo-summarizer",
    version="0.1.0",
    description="FastAPI service that summarizes GitHub repositories from prioritized AST skeletons.",
    packages=find_packages(include=["repo_summarizer", "repo_summarizer.*"]),
    include_package_data=True,
    python_requires=">=3.10",
    install_requires=[
        "fastapi>=0.111.0",
        "uvicorn[standard]>=0.30.0",
        "pydantic>=2.7.0",
        "PyYAML>=6.0.1",
        "tiktoken>=0.7.0",
        "tree-sitter>=0.23.0",
        "tree-sitter-python>=0.23.0",
        "tree-sitter-javascript>=0.23.0",
        "tree-sitter-go>=0.23.0",
        "openai>=1.30.0",
    ],
    extras_require={
        "dev": [
            "pytest>=8.0.0",
            "httpx>=0.27.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "repo-summarizer=repo_summarizer.main:run",
        ]
    },
)
