"""Deterministic mock implementation of the LLM provider protocol.

This provider is used during tests to ensure reproducible fuzzing behaviour
without requiring network access. It returns a fixed sequence of
predefined argument arrays regardless of the prompt. If more cases are
requested than available, it simply truncates the list.

The mock provider includes Geode-specific test patterns for comprehensive
testing of the database functionality.
"""

from __future__ import annotations

from typing import List, Optional


class MockProvider:
    """Mock LLM provider returning a deterministic set of argument arrays."""

    # Predefined fuzz cases for general CLI testing
    _general_cases: List[List[str]] = [
        ["--help"],
        ["--version"],
        ["serve", "--help"],
        ["query", "--help"],
        ["shell", "--help"],
    ]

    # Geode-specific test cases focusing on database operations
    _geode_cases: List[List[str]] = [
        # Basic query operations
        ["query", "RETURN 1 AS result"],
        ["query", "MATCH (n) RETURN count(n) AS node_count"],
        ["query", "CREATE (n:TestNode {name: 'test'}) RETURN n"],
        # Server management
        ["serve", "--data-dir", "/tmp/geode-test", "--listen", "127.0.0.1:9443"],
        # Authentication testing
        ["auth", "login", "--user", "admin"],
        ["auth", "logout"],
        # User management
        ["user", "create", "testuser", "test@example.com"],
        ["user", "list"],
        # Shell operations
        ["shell", "--server", "127.0.0.1:8443", "--format", "json"],
        # Edge cases and error conditions
        ["query", "INVALID GQL SYNTAX"],
        ["query", "--server", "nonexistent:9999", "RETURN 1"],
        ["unknown-command"],
        # Complex queries
        ["query", "MATCH (a)-[r]->(b) RETURN a, r, b LIMIT 10"],
        ["query", "CREATE (a:Person {name: 'Alice'})-[:KNOWS]->(b:Person {name: 'Bob'}) RETURN a, b"],
        # Format testing
        ["query", "--format", "table", "RETURN 1, 2, 3"],
        ["query", "--format", "csv", "MATCH (n) RETURN n.name LIMIT 5"],
        # Backup and restore (if implemented)
        ["backup", "--dest", "/tmp/backup.gql"],
        ["restore", "--source", "/tmp/backup.gql"],
    ]

    # GQL queries for specialized testing
    _gql_queries: List[str] = [
        "RETURN 1",
        "MATCH (n) RETURN n LIMIT 1",
        "CREATE (n:Test) RETURN n",
        "MATCH (n:Test) DELETE n",
        "MATCH (a)-[r]-(b) RETURN type(r), count(*)",
        "CREATE (a:Person {name: 'Alice', age: 30})",
        "MATCH (p:Person) WHERE p.age > 25 RETURN p.name",
        "CREATE (a:Person {name: 'Bob'})-[:FRIENDS_WITH]->(b:Person {name: 'Carol'})",
        "MATCH path = (a)-[:FRIENDS_WITH*1..3]-(b) RETURN path",
        "MATCH (n) SET n.timestamp = timestamp() RETURN count(n)",
    ]

    def fuzz(self, prompt: str, max_cases: int, seed: Optional[int]) -> List[List[str]]:
        """Generate deterministic fuzz cases.

        The mock provider combines general CLI cases with Geode-specific cases
        to provide comprehensive test coverage.
        """
        if max_cases <= 0:
            return []

        # Combine general and Geode-specific cases
        all_cases = self._general_cases + self._geode_cases

        # Use seed to provide some variation in ordering if desired
        if seed is not None:
            import random

            # Create a local random instance to avoid affecting global state
            local_random = random.Random(seed)
            # Shuffle a copy of the cases
            shuffled_cases = all_cases.copy()
            local_random.shuffle(shuffled_cases)
            return shuffled_cases[:max_cases]

        return all_cases[:max_cases]

    def supports_geode_patterns(self) -> bool:
        """Mock provider supports Geode patterns."""
        return True

    def generate_gql_queries(
        self, max_queries: int, complexity: str = "simple", seed: Optional[int] = None
    ) -> List[str]:
        """Generate mock GQL queries based on complexity level."""
        if max_queries <= 0:
            return []

        # Filter queries by complexity
        if complexity == "simple":
            queries = [q for q in self._gql_queries if len(q.split()) <= 5]
        elif complexity == "complex":
            queries = [q for q in self._gql_queries if len(q.split()) > 8]
        else:  # medium
            queries = [q for q in self._gql_queries if 5 < len(q.split()) <= 8]

        # Fallback to all queries if filtering results in empty list
        if not queries:
            queries = self._gql_queries

        # Apply seed for deterministic ordering
        if seed is not None:
            import random

            local_random = random.Random(seed)
            queries = queries.copy()
            local_random.shuffle(queries)

        return queries[:max_queries]
