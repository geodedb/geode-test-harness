"""Tests for _escape_gql_string / the auth-to-CALL conversion.

A value containing a single quote must stay inside its GQL string literal.
"""

from __future__ import annotations

from geodetestlab.lib.executor import _convert_auth_to_call, _escape_gql_string


def _unescape(literal_body: str) -> str:
    """Decode a backslash-escaped GQL single-quoted string body."""
    out = []
    i = 0
    while i < len(literal_body):
        c = literal_body[i]
        if c == "\\":
            i += 1
            out.append(literal_body[i])
        else:
            assert c != "'", f"bare quote ends the literal early: {literal_body!r}"
            out.append(c)
        i += 1
    return "".join(out)


def test_escape_round_trips_quotes_and_backslashes() -> None:
    for value in ["plain", "it's", "a\\b", "x\\'y", "'; DROP GRAPH g; '", "\\"]:
        assert _unescape(_escape_gql_string(value)) == value


def test_policy_condition_with_quotes_stays_one_argument() -> None:
    call = _convert_auth_to_call(["policy", "create", "p", "--table", "Doc", "--condition", "current_user() = 'bob'"])
    assert call == ("CALL geode.auth.policy_create('p', 'Doc', 'current_user() = \\'bob\\'')")
