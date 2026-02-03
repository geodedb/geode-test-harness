"""Geode-specific AI provider for enhanced database testing.

This provider specializes in generating test cases specifically tailored for
Geode graph database functionality. It can generate complex GQL queries,
authentication scenarios, schema operations, and performance testing patterns
that are particularly relevant for graph database testing.

The provider can work with any OpenAI-compatible API but uses enhanced prompts
and post-processing to ensure generated test cases are appropriate for Geode's
specific features and constraints.
"""

from __future__ import annotations

import json
import os
import random
from typing import List, Optional

import httpx


class GeodeAIProvider:
    """Specialized LLM provider for Geode graph database test generation."""

    def __init__(self, model: Optional[str] = None) -> None:
        self.model = model or os.environ.get("OPENAI_MODEL", "gpt-4")

        # Geode-specific patterns and templates
        self.gql_patterns = {
            "simple": [
                "RETURN {value} AS {alias}",
                "MATCH (n:{label}) RETURN n",
                "CREATE (n:{label} {{{property}: '{value}'}}) RETURN n",
                "MATCH (n) RETURN count(n) AS total",
            ],
            "medium": [
                "MATCH (n:{label}) WHERE n.{property} {operator} {value} RETURN n",
                "MATCH (a:{label1})-[r:{rel_type}]->(b:{label2}) RETURN a, r, b",
                "CREATE (a:{label1})-[r:{rel_type}]->(b:{label2}) RETURN a, r, b",
                "MATCH (n:{label}) SET n.{property} = {value} RETURN n",
                "MATCH (n) WITH n.{property} AS prop RETURN prop, count(*) ORDER BY count(*) DESC",
            ],
            "complex": [
                "MATCH path = (a:{label1})-[*1..{depth}]->(b:{label2}) RETURN path",
                "MATCH (n:{label}) CALL {{ WITH n MATCH (n)-[r]->(m) RETURN m }} RETURN n, collect(m)",
                "WITH range(1, {count}) AS nums UNWIND nums AS num CREATE (n:Node {{id: num}})",
                "MATCH (a)-[r1]->(b)-[r2]->(c) WHERE a.{prop1} = b.{prop2} RETURN a, b, c",
            ],
        }

        self.cli_patterns = {
            "server": [
                ["serve", "--data-dir", "{data_dir}", "--listen", "{address}"],
                ["serve", "--help"],
                ["serve", "--stdio", "--log-level", "debug"],
            ],
            "query": [
                ["query", "{gql_query}"],
                ["query", "--format", "{format}", "{gql_query}"],
                ["query", "--server", "{server}", "{gql_query}"],
            ],
            "auth": [
                ["auth", "login", "--user", "{username}"],
                ["auth", "logout"],
                ["user", "create", "{username}", "{email}"],
                ["role", "create", "{role_name}", "{description}"],
            ],
            "shell": [
                ["shell", "--server", "{server}"],
                ["shell", "--format", "{format}"],
                ["shell", "--no-history"],
            ],
        }

    def fuzz(self, prompt: str, max_cases: int, seed: Optional[int]) -> List[List[str]]:
        """Generate Geode-specific fuzz cases."""
        if max_cases <= 0:
            return []

        # Set up deterministic generation if seed provided
        if seed is not None:
            random.seed(seed)

        # Generate a mix of pattern-based and AI-generated cases
        pattern_cases = self._generate_pattern_cases(max_cases // 2, seed)

        # Use AI for the remaining cases
        ai_cases = []
        if max_cases > len(pattern_cases):
            remaining = max_cases - len(pattern_cases)
            try:
                enhanced_prompt = self._build_enhanced_prompt(prompt, remaining)
                response_text = self._call_api(enhanced_prompt, seed)
                ai_cases = self._parse_response(response_text, remaining)
            except Exception:
                # Fall back to pattern generation if AI fails
                ai_cases = self._generate_pattern_cases(remaining, seed)

        # Combine and return
        all_cases = pattern_cases + ai_cases
        return all_cases[:max_cases]

    def supports_geode_patterns(self) -> bool:
        """Geode AI provider fully supports Geode patterns."""
        return True

    def generate_gql_queries(
        self, max_queries: int, complexity: str = "simple", seed: Optional[int] = None
    ) -> List[str]:
        """Generate sophisticated GQL queries."""
        if max_queries <= 0:
            return []

        if seed is not None:
            random.seed(seed)

        # Generate pattern-based queries
        pattern_queries = self._generate_pattern_queries(max_queries // 2, complexity)

        # Use AI for creative queries
        ai_queries = []
        if max_queries > len(pattern_queries):
            remaining = max_queries - len(pattern_queries)
            try:
                prompt = self._build_gql_generation_prompt(complexity, remaining)
                response_text = self._call_api(prompt, seed)
                ai_queries = self._parse_gql_response(response_text, remaining)
            except Exception:
                # Fall back to patterns
                ai_queries = self._generate_pattern_queries(remaining, complexity)

        all_queries = pattern_queries + ai_queries
        return all_queries[:max_queries]

    def _generate_pattern_cases(self, count: int, seed: Optional[int]) -> List[List[str]]:
        """Generate test cases using built-in patterns."""
        cases = []

        # Generate from different pattern categories
        categories = list(self.cli_patterns.keys())
        if seed is not None:
            random.Random(seed).shuffle(categories)

        for i in range(count):
            category = categories[i % len(categories)]
            pattern = random.choice(self.cli_patterns[category])

            # Fill in template variables
            filled_pattern = self._fill_pattern_template(pattern)
            cases.append(filled_pattern)

        return cases

    def _generate_pattern_queries(self, count: int, complexity: str) -> List[str]:
        """Generate GQL queries using built-in patterns."""
        queries = []
        patterns = self.gql_patterns.get(complexity, self.gql_patterns["simple"])

        for i in range(count):
            pattern = patterns[i % len(patterns)]
            query = self._fill_gql_template(pattern)
            queries.append(query)

        return queries

    def _fill_pattern_template(self, pattern: List[str]) -> List[str]:
        """Fill template variables in a CLI pattern."""
        filled = []

        for arg in pattern:
            if "{" in arg and "}" in arg:
                # Replace template variables
                replacements = {
                    "{data_dir}": "/tmp/geode-test",
                    "{address}": "127.0.0.1:8443",
                    "{format}": random.choice(["json", "table", "csv"]),
                    "{server}": "127.0.0.1:8443",
                    "{username}": random.choice(["admin", "user", "alice", "bob"]),
                    "{email}": "test@example.com",
                    "{role_name}": random.choice(["admin", "user", "viewer"]),
                    "{description}": "Test role",
                    "{gql_query}": "RETURN 1 AS result",
                }

                filled_arg = arg
                for var, value in replacements.items():
                    filled_arg = filled_arg.replace(var, value)
                filled.append(filled_arg)
            else:
                filled.append(arg)

        return filled

    def _fill_gql_template(self, pattern: str) -> str:
        """Fill template variables in a GQL pattern."""
        replacements = {
            "{value}": str(random.randint(1, 100)),
            "{alias}": random.choice(["result", "value", "count", "total"]),
            "{label}": random.choice(["Person", "Node", "Entity", "User", "Product"]),
            "{label1}": random.choice(["Person", "User", "Customer"]),
            "{label2}": random.choice(["Product", "Order", "Company"]),
            "{property}": random.choice(["name", "age", "id", "created_at", "status"]),
            "{prop1}": "id",
            "{prop2}": "user_id",
            "{operator}": random.choice([">", "<", "=", ">=", "<=", "<>"]),
            "{rel_type}": random.choice(["KNOWS", "OWNS", "CREATED", "BELONGS_TO"]),
            "{depth}": str(random.randint(2, 5)),
            "{count}": str(random.randint(5, 20)),
        }

        result = pattern
        for var, value in replacements.items():
            result = result.replace(var, value)

        return result

    def _build_enhanced_prompt(self, base_prompt: str, max_cases: int) -> str:
        """Build an enhanced prompt for Geode-specific testing."""
        return f"""
{base_prompt}

You are an expert at testing the Geode graph database system. Generate {max_cases} sophisticated test cases that thoroughly exercise Geode's capabilities.

GEODE SYSTEM OVERVIEW:
- Graph database implementing ISO/IEC 39075:2024 GQL standard
- QUIC+TLS transport with strong authentication
- MVCC with snapshot isolation and ARIES recovery
- Supports complex graph patterns, temporal queries, and distributed operations
- Built-in audit logging and security features

COMMANDS TO TEST:
- serve: Server management with various configurations
- query: GQL query execution with different formats and options
- shell: Interactive GQL shell with various modes
- auth/user/role: Authentication and authorization testing
- backup/restore: Data management operations

TESTING FOCUS AREAS:
1. Complex GQL queries with multiple patterns
2. Authentication edge cases and security scenarios
3. Performance testing with large datasets
4. Error handling and recovery scenarios
5. Configuration variations and edge cases

Generate realistic test cases that could uncover bugs or performance issues.
Return each test case as a JSON array of command line arguments.
Focus on sophisticated scenarios that stress-test the system.

Examples:
["query", "MATCH (a:Person)-[:KNOWS*2..4]->(b:Person) WHERE a.age > b.age RETURN count(*)"]
["serve", "--data-dir", "/dev/shm/test", "--listen", "0.0.0.0:8443", "--log-level", "debug"]
["user", "create", "alice", "alice@graph.example.com", "--role", "power_user"]
"""

    def _build_gql_generation_prompt(self, complexity: str, max_queries: int) -> str:
        """Build a specialized prompt for GQL query generation."""
        complexity_guidance = {
            "simple": "Focus on basic MATCH, CREATE, RETURN patterns with single nodes/edges",
            "medium": "Include WHERE clauses, aggregations, path patterns up to length 3, and simple subqueries",
            "complex": "Generate advanced queries with complex path patterns, multiple WITH clauses, optional matches, and sophisticated graph algorithms",
        }

        return f"""
Generate {max_queries} sophisticated Graph Query Language (GQL) queries for the Geode database.

COMPLEXITY LEVEL: {complexity}
REQUIREMENTS: {complexity_guidance.get(complexity, "Mixed complexity levels")}

GQL CAPABILITIES TO LEVERAGE:
- Graph pattern matching with variable-length paths
- Property graph model with typed nodes and relationships
- Temporal queries and time-based filtering
- Aggregation functions and statistical operations
- Subqueries and complex data transformations
- Path finding and graph algorithms
- Schema introspection and metadata queries

QUERY CATEGORIES TO INCLUDE:
1. Graph traversal and pattern matching
2. Data creation and modification
3. Analytical queries with aggregations
4. Schema and metadata exploration
5. Performance testing patterns

Return one valid GQL query per line without quotes.
Ensure all queries are syntactically correct and meaningful for graph analysis.
Focus on realistic use cases that would be valuable for testing a graph database.

Example advanced patterns:
MATCH path = shortestPath((a:Person)-[*]-(b:Person)) WHERE a.city <> b.city RETURN path
CALL {{ MATCH (n) RETURN labels(n) AS label, count(*) AS cnt }} RETURN label, cnt ORDER BY cnt DESC
WITH ["Alice", "Bob", "Carol"] AS names UNWIND names AS name CREATE (p:Person {{name: name}})
"""

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
                "content": "You are an expert database testing engineer specializing in graph databases and GQL. Generate sophisticated, realistic test cases that thoroughly exercise database functionality.",
            },
            {
                "role": "user",
                "content": prompt,
            },
        ]

        body = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.1 if seed is not None else 0.3,
            "top_p": 0.9,
            "max_tokens": 3000,
        }

        if seed is not None:
            body["seed"] = seed

        with httpx.Client(timeout=45) as client:
            response = client.post(url, headers=headers, json=body)
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

    def _parse_response(self, response_text: str, max_cases: int) -> List[List[str]]:
        """Parse API response into argument arrays."""
        cases: List[List[str]] = []

        for line in response_text.splitlines():
            trimmed = line.strip()
            if not trimmed or trimmed.startswith("#"):
                continue

            # Try to parse as JSON array
            if trimmed.startswith("[") and trimmed.endswith("]"):
                try:
                    arr = json.loads(trimmed)
                    if isinstance(arr, list) and all(isinstance(x, str) for x in arr):
                        cases.append(arr)
                        if len(cases) >= max_cases:
                            break
                except json.JSONDecodeError:
                    continue

        return cases

    def _parse_gql_response(self, response_text: str, max_queries: int) -> List[str]:
        """Parse API response into GQL query strings."""
        queries = []

        for line in response_text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("//"):
                continue

            # Remove quotes if present
            if (line.startswith('"') and line.endswith('"')) or (line.startswith("'") and line.endswith("'")):
                line = line[1:-1]

            # Basic validation - should start with a GQL keyword
            gql_keywords = [
                "MATCH",
                "CREATE",
                "DELETE",
                "SET",
                "REMOVE",
                "RETURN",
                "WITH",
                "UNWIND",
                "MERGE",
                "CALL",
                "EXPLAIN",
                "PROFILE",
            ]
            first_word = line.split()[0].upper() if line.split() else ""

            if first_word in gql_keywords:
                queries.append(line)
                if len(queries) >= max_queries:
                    break

        return queries
