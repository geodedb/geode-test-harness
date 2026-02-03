"""Base protocol for LLM providers.

Providers implementing this protocol are responsible for generating
additional test case argument arrays based on a prompt. The protocol
accepts a prompt string, a maximum number of cases to generate, and an
optional seed to allow deterministic outputs. It returns a list of
argument lists (each argument is a string) to be executed by the test
runner.

For Geode testing, providers may also implement Geode-specific patterns
for generating GQL queries, authentication scenarios, and database
operations.
"""

from __future__ import annotations

from typing import List, Optional, Protocol


class LLMProvider(Protocol):
    """Protocol that all LLM providers must implement."""

    def fuzz(self, prompt: str, max_cases: int, seed: Optional[int]) -> List[List[str]]:
        """Generate additional argument arrays based on the prompt.

        Parameters
        ----------
        prompt:
            The prompt describing how to generate argument arrays.
        max_cases:
            Maximum number of argument arrays to return.
        seed:
            Optional seed to make generation deterministic. Providers
            should honour this if they support determinism.

        Returns
        -------
        List[List[str]]
            A list of argument lists. Each inner list represents a full
            invocation (excluding the binary itself).
        """
        raise NotImplementedError

    def supports_geode_patterns(self) -> bool:
        """Return whether this provider supports Geode-specific patterns.

        Returns
        -------
        bool
            True if the provider can generate Geode-specific test cases.
        """
        return False

    def generate_gql_queries(
        self, max_queries: int, complexity: str = "simple", seed: Optional[int] = None
    ) -> List[str]:
        """Generate GQL queries for testing.

        Parameters
        ----------
        max_queries:
            Maximum number of queries to generate.
        complexity:
            Complexity level: "simple", "medium", "complex".
        seed:
            Optional seed for deterministic generation.

        Returns
        -------
        List[str]
            List of GQL query strings.
        """
        # Default implementation returns empty list
        return []
