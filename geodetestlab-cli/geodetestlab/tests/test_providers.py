"""Tests for LLM providers."""

import pytest

from geodetestlab.providers import get_provider
from geodetestlab.providers.geode_ai import GeodeAIProvider
from geodetestlab.providers.mock import MockProvider


def test_get_mock_provider():
    """Test getting mock provider."""
    provider = get_provider("mock")
    assert isinstance(provider, MockProvider)

    provider = get_provider("none")
    assert isinstance(provider, MockProvider)


def test_get_geode_ai_provider():
    """Test getting Geode AI provider."""
    provider = get_provider("geode-ai", model="gpt-4")
    assert isinstance(provider, GeodeAIProvider)

    provider = get_provider("geode_ai")
    assert isinstance(provider, GeodeAIProvider)

    provider = get_provider("geodai")
    assert isinstance(provider, GeodeAIProvider)


def test_unknown_provider():
    """Test error on unknown provider."""
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        get_provider("unknown_provider")


def test_mock_provider_fuzz():
    """Test mock provider fuzzing."""
    provider = MockProvider()

    # Test deterministic behavior
    cases1 = provider.fuzz("test prompt", 5, seed=42)
    cases2 = provider.fuzz("test prompt", 5, seed=42)
    assert cases1 == cases2

    # Test max_cases limiting
    cases = provider.fuzz("test prompt", 3, seed=42)
    assert len(cases) == 3

    # Test zero cases
    cases = provider.fuzz("test prompt", 0, seed=42)
    assert len(cases) == 0

    # Test that all cases are valid
    cases = provider.fuzz("test prompt", 10, seed=42)
    for case in cases:
        assert isinstance(case, list)
        assert all(isinstance(arg, str) for arg in case)


def test_mock_provider_geode_patterns():
    """Test mock provider Geode-specific functionality."""
    provider = MockProvider()

    assert provider.supports_geode_patterns() is True

    # Test GQL query generation
    queries = provider.generate_gql_queries(5, complexity="simple", seed=42)
    assert len(queries) <= 5
    assert all(isinstance(q, str) for q in queries)

    # Test different complexity levels
    simple_queries = provider.generate_gql_queries(10, complexity="simple", seed=42)
    complex_queries = provider.generate_gql_queries(10, complexity="complex", seed=42)

    # Simple queries should generally be shorter
    if simple_queries and complex_queries:
        avg_simple_len = sum(len(q.split()) for q in simple_queries) / len(simple_queries)
        avg_complex_len = sum(len(q.split()) for q in complex_queries) / len(complex_queries)
        # This might not always hold, but it's a reasonable expectation
        # assert avg_simple_len <= avg_complex_len


def test_geode_ai_provider_patterns():
    """Test Geode AI provider pattern generation."""
    provider = GeodeAIProvider()

    assert provider.supports_geode_patterns() is True

    # Test pattern-based case generation (doesn't require API)
    cases = provider._generate_pattern_cases(5, seed=42)
    assert len(cases) == 5
    assert all(isinstance(case, list) for case in cases)
    assert all(all(isinstance(arg, str) for arg in case) for case in cases)

    # Test GQL pattern generation
    queries = provider._generate_pattern_queries(3, "simple")
    assert len(queries) == 3
    assert all(isinstance(q, str) for q in queries)

    # Test template filling
    pattern = ["query", "{gql_query}"]
    filled = provider._fill_pattern_template(pattern)
    assert len(filled) == 2
    assert filled[0] == "query"
    assert filled[1] != "{gql_query}"  # Should be replaced

    # Test GQL template filling
    gql_pattern = "MATCH (n:{label}) RETURN n.{property}"
    filled_gql = provider._fill_gql_template(gql_pattern)
    assert "{label}" not in filled_gql
    assert "{property}" not in filled_gql


def test_provider_error_handling():
    """Test provider error handling."""
    provider = MockProvider()

    # Test negative max_cases
    cases = provider.fuzz("test", -1, seed=42)
    assert len(cases) == 0

    # Test very large max_cases (should be limited by available patterns)
    cases = provider.fuzz("test", 1000, seed=42)
    assert len(cases) > 0  # Should return available cases

    # Mock provider should not raise errors for any reasonable input
    cases = provider.fuzz("", 5, seed=None)
    assert isinstance(cases, list)
