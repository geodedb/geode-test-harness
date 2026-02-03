"""OpenAI‑compatible provider implementation.

This provider sends a chat completion request to an OpenAI‑compatible API
endpoint using httpx. It expects the model to return argument arrays
encoded as JSON lists on separate lines. The provider honours the
temperature and top_p parameters as specified in the requirements.

For Geode testing, this provider can generate both general CLI test cases
and Geode-specific GQL queries and database operations.
"""

from __future__ import annotations

import json
import os
from typing import List, Optional

import httpx


class OpenAICompatProvider:
    """LLM provider that talks to an OpenAI‑compatible API over HTTP."""

    def __init__(self, model: Optional[str] = None) -> None:
        self.model = model or os.environ.get("OPENAI_MODEL", "gpt-3.5-turbo")

    def fuzz(self, prompt: str, max_cases: int, seed: Optional[int]) -> List[List[str]]:
        """Generate fuzz cases using OpenAI-compatible API."""
        if max_cases <= 0:
            return []

        # Enhance prompt with Geode-specific context
        enhanced_prompt = self._build_geode_prompt(prompt, max_cases)

        try:
            response_text = self._call_api(enhanced_prompt, seed)
            return self._parse_response(response_text, max_cases)
        except Exception as exc:
            raise RuntimeError(f"OpenAI API request failed: {exc}")

    def supports_geode_patterns(self) -> bool:
        """OpenAI provider supports Geode patterns through enhanced prompts."""
        return True

    def generate_gql_queries(
        self, max_queries: int, complexity: str = "simple", seed: Optional[int] = None
    ) -> List[str]:
        """Generate GQL queries using the OpenAI API."""
        if max_queries <= 0:
            return []

        prompt = self._build_gql_prompt(complexity, max_queries)

        try:
            response_text = self._call_api(prompt, seed)
            # Parse response expecting one query per line
            queries = []
            for line in response_text.splitlines():
                line = line.strip()
                if line and not line.startswith("#") and not line.startswith("//"):
                    # Remove quotes if present
                    if line.startswith('"') and line.endswith('"'):
                        line = line[1:-1]
                    queries.append(line)
                    if len(queries) >= max_queries:
                        break
            return queries
        except Exception as exc:
            raise RuntimeError(f"OpenAI API request failed: {exc}")

    def _call_api(self, prompt: str, seed: Optional[int]) -> str:
        """Make API call to OpenAI-compatible endpoint."""
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable is not set")

        base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com").rstrip("/")
        url = f"{base_url}/v1/chat/completions"

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        messages = [
            {
                "role": "system",
                "content": "You are a helpful assistant that generates test cases for CLI applications. Focus on providing valid, well-formed responses.",
            },
            {
                "role": "user",
                "content": prompt,
            },
        ]

        body = {
            "model": self.model,
            "messages": messages,
            "temperature": 0 if seed is not None else 0.3,
            "top_p": 1.0,
            "max_tokens": 2000,
        }

        # Set seed if provided (OpenAI supports this for some models)
        if seed is not None:
            body["seed"] = seed

        with httpx.Client(timeout=30) as client:
            response = client.post(url, headers=headers, json=body)
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

    def _build_geode_prompt(self, base_prompt: str, max_cases: int) -> str:
        """Build a Geode-specific prompt for general CLI fuzzing."""
        return f"""
{base_prompt}

You are generating test cases for the Geode graph database CLI. Geode supports:
- Graph Query Language (GQL) - ISO/IEC 39075:2024 standard
- QUIC+TLS transport with authentication
- Server management (serve, shell, query commands)
- User and role management (auth, user, role commands)
- Backup and restore operations

Generate {max_cases} test cases as JSON arrays of command line arguments.
Each line should be a valid JSON array of strings representing CLI arguments.

Examples:
["query", "RETURN 1 AS result"]
["serve", "--listen", "127.0.0.1:8443"]
["user", "create", "alice", "alice@example.com"]
["auth", "login", "--user", "admin"]

Focus on realistic usage patterns, edge cases, and error conditions.
Include both valid and invalid arguments to test error handling.
Do not include shell metacharacters or dangerous commands.
"""

    def _build_gql_prompt(self, complexity: str, max_queries: int) -> str:
        """Build a prompt specifically for GQL query generation."""
        complexity_desc = {
            "simple": "basic RETURN, MATCH, and CREATE statements with simple patterns",
            "medium": "queries with WHERE clauses, aggregations, and simple path patterns",
            "complex": "advanced queries with complex path patterns, subqueries, and multiple clauses",
        }

        return f"""
Generate {max_queries} Graph Query Language (GQL) queries following ISO/IEC 39075:2024 standard.
Complexity level: {complexity} - {complexity_desc.get(complexity, "mixed complexity")}

Return one valid GQL query per line. Do not include quotes around queries.
Focus on realistic graph database operations.

Example patterns for reference:
- RETURN 1 AS result
- MATCH (n:Person) RETURN n.name
- CREATE (a:Person {{name: 'Alice'}})
- MATCH (a)-[r:KNOWS]->(b) RETURN a.name, b.name
- MATCH (n) WHERE n.age > 25 RETURN count(n)

Ensure all queries are syntactically valid GQL.
"""

    def _parse_response(self, response_text: str, max_cases: int) -> List[List[str]]:
        """Parse API response into argument arrays."""
        cases: List[List[str]] = []

        for line in response_text.splitlines():
            trimmed = line.strip()
            if not trimmed:
                continue

            # Attempt to parse any line that looks like a JSON list
            if not (trimmed.startswith("[") and trimmed.endswith("]")):
                continue

            try:
                arr = json.loads(trimmed)
            except json.JSONDecodeError:
                continue

            if isinstance(arr, list) and all(isinstance(x, str) for x in arr):
                cases.append(arr)
                if len(cases) >= max_cases:
                    break

        return cases
