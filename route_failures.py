#!/usr/bin/env python3
"""
Route test failures to appropriate GitLab repositories.

This script analyzes test results from the test harness and creates
GitLab issues in the appropriate repositories for failures.

Usage:
    python route_failures.py reports/results.json [--dry-run] [--verbose]

Repositories:
    - Server issues: devnw/codepros/geode/geode
    - Go client: devnw/codepros/geode/geode-client-go
    - Python client: devnw/codepros/geode/geode-client-python
    - Rust client: devnw/codepros/geode/geode-client-rust
    - Zig client: devnw/codepros/geode/geode-client-zig
    - Node.js client: devnw/codepros/geode/geode-client-nodejs
"""

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


# Repository mapping
REPO_MAP = {
    "server": "devnw/codepros/geode/geode",
    "go": "devnw/codepros/geode/geode-client-go",
    "python": "devnw/codepros/geode/geode-client-python",
    "rust": "devnw/codepros/geode/geode-client-rust",
    "zig": "devnw/codepros/geode/geode-client-zig",
    "nodejs": "devnw/codepros/geode/geode-client-nodejs",
    "harness": "devnw/codepros/geode/geode-test-harness",
}

# Error patterns that indicate server-side issues
SERVER_ERROR_PATTERNS = [
    r"connection refused",
    r"connection reset",
    r"timeout.*server",
    r"server.*crash",
    r"segmentation fault",
    r"internal server error",
    r"QUIC.*error",
    r"transport.*error",
    r"protocol.*error",
    r"database.*error",
    r"query execution failed.*server",
    r"transaction.*aborted.*server",
    r"schema.*error",
    r"GQL-\d+",  # GQL error codes from server
]

# Error patterns that indicate client-side issues
CLIENT_ERROR_PATTERNS = {
    "go": [
        r"go:.*error",
        r"panic:",
        r"nil pointer",
        r"slice bounds",
        r"driver\..*error",
    ],
    "python": [
        r"Traceback",
        r"TypeError:",
        r"ValueError:",
        r"AttributeError:",
        r"ImportError:",
        r"asyncio.*error",
    ],
    "rust": [
        r"thread.*panicked",
        r"unwrap.*failed",
        r"assertion failed",
        r"stack backtrace",
        r"tokio.*error",
    ],
    "zig": [
        r"panic:",
        r"assertion failure",
        r"unreachable",
        r"OutOfMemory",
        r"error\..*=",
    ],
    "nodejs": [
        r"TypeError:",
        r"ReferenceError:",
        r"Error:",
        r"Unhandled promise rejection",
        r"Cannot read propert",
    ],
}


@dataclass
class FailureGroup:
    """Group of related failures for a single issue."""

    client: str
    test_names: List[str] = field(default_factory=list)
    error_messages: List[str] = field(default_factory=list)
    is_server_issue: bool = False
    spec_name: Optional[str] = None

    def add_failure(self, test_name: str, error_message: str):
        self.test_names.append(test_name)
        if error_message and error_message not in self.error_messages:
            self.error_messages.append(error_message)

    @property
    def target_repo(self) -> str:
        if self.is_server_issue:
            return REPO_MAP["server"]
        return REPO_MAP.get(self.client, REPO_MAP["harness"])

    @property
    def issue_title(self) -> str:
        if len(self.test_names) == 1:
            return f"[Test Harness] Test failure: {self.test_names[0]}"
        else:
            return f"[Test Harness] {len(self.test_names)} test failures in {self.spec_name or 'tests'}"

    @property
    def labels(self) -> List[str]:
        labels = ["test-harness", "automated"]
        if self.is_server_issue:
            labels.append("server")
        else:
            labels.append(f"client-{self.client}")
        return labels


def classify_error(error_message: str, client: str) -> Tuple[bool, float]:
    """
    Classify an error as server-side or client-side.

    Returns:
        Tuple of (is_server_issue, confidence)
    """
    if not error_message:
        return False, 0.0

    error_lower = error_message.lower()

    # Check for server error patterns
    server_matches = 0
    for pattern in SERVER_ERROR_PATTERNS:
        if re.search(pattern, error_message, re.IGNORECASE):
            server_matches += 1

    # Check for client error patterns
    client_matches = 0
    client_patterns = CLIENT_ERROR_PATTERNS.get(client, [])
    for pattern in client_patterns:
        if re.search(pattern, error_message, re.IGNORECASE):
            client_matches += 1

    # Decision logic
    if server_matches > 0 and client_matches == 0:
        return True, min(1.0, server_matches * 0.3)
    elif client_matches > 0 and server_matches == 0:
        return False, min(1.0, client_matches * 0.3)
    elif server_matches > client_matches:
        return True, 0.5
    elif client_matches > server_matches:
        return False, 0.5
    else:
        # Default to client issue if unclear
        return False, 0.3


def analyze_failures(results: List[Dict]) -> Dict[str, List[FailureGroup]]:
    """
    Analyze test failures and group them by target repository.

    Returns:
        Dict mapping repo path to list of FailureGroups
    """
    # Group failures by client and error pattern
    client_failures: Dict[str, Dict[str, FailureGroup]] = {}

    for result in results:
        status = result.get("status", "")
        if status not in ("failed", "error"):
            continue

        client = result.get("client", "unknown")
        test_name = result.get("test", result.get("test_name", "unknown"))
        error_message = result.get("error", result.get("error_message", ""))

        # Skip if client is unknown or harness
        if client in ("unknown", "harness"):
            continue

        # Classify the error
        is_server_issue, confidence = classify_error(error_message, client)

        # Create a grouping key based on error type
        if is_server_issue:
            group_key = "server"
        else:
            # Group by first significant error pattern match
            group_key = client

        if client not in client_failures:
            client_failures[client] = {}

        if group_key not in client_failures[client]:
            client_failures[client][group_key] = FailureGroup(
                client=client,
                is_server_issue=is_server_issue,
            )

        client_failures[client][group_key].add_failure(test_name, error_message)

    # Reorganize by target repository
    repo_groups: Dict[str, List[FailureGroup]] = {}

    for client, groups in client_failures.items():
        for group in groups.values():
            repo = group.target_repo
            if repo not in repo_groups:
                repo_groups[repo] = []
            repo_groups[repo].append(group)

    return repo_groups


def check_existing_issues(repo: str, title_pattern: str, verbose: bool = False) -> List[str]:
    """Check for existing open issues matching the pattern."""
    try:
        cmd = [
            "glab", "issue", "list",
            "--repo", repo,
            "--state", "opened",
            "--search", title_pattern[:50],  # Limit search string
            "--json", "iid,title,webUrl"
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode == 0 and result.stdout.strip():
            issues = json.loads(result.stdout)
            return [f"#{i['iid']}: {i['title']}" for i in issues]
    except Exception as e:
        if verbose:
            print(f"  Warning: Could not check existing issues: {e}")

    return []


def create_issue(
    repo: str,
    title: str,
    description: str,
    labels: List[str],
    dry_run: bool = False,
    verbose: bool = False
) -> Optional[str]:
    """
    Create a GitLab issue using glab CLI.

    Returns:
        Issue URL if created, None otherwise
    """
    if dry_run:
        print(f"  [DRY-RUN] Would create issue in {repo}:")
        print(f"    Title: {title}")
        print(f"    Labels: {', '.join(labels)}")
        if verbose:
            print(f"    Description:\n{description[:500]}...")
        return None

    try:
        cmd = [
            "glab", "issue", "create",
            "--repo", repo,
            "--title", title,
            "--description", description,
        ]

        for label in labels:
            cmd.extend(["--label", label])

        if verbose:
            print(f"  Running: {' '.join(cmd[:6])}...")

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        if result.returncode == 0:
            # Extract URL from output
            url_match = re.search(r'https://[^\s]+', result.stdout)
            if url_match:
                return url_match.group(0)
            return result.stdout.strip()
        else:
            print(f"  Error creating issue: {result.stderr}", file=sys.stderr)
            return None

    except subprocess.TimeoutExpired:
        print(f"  Timeout creating issue in {repo}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  Error creating issue: {e}", file=sys.stderr)
        return None


def generate_issue_description(group: FailureGroup, ci_info: Dict) -> str:
    """Generate a detailed issue description."""

    description = f"""## Test Harness Failure Report

**Generated**: {datetime.now(timezone.utc).isoformat()}Z
**Pipeline**: {ci_info.get('pipeline_url', 'N/A')}
**Commit**: {ci_info.get('commit_sha', 'N/A')}
**Branch**: {ci_info.get('branch', 'N/A')}

### Failed Tests

| Test Name | Client |
|-----------|--------|
"""

    for test_name in group.test_names[:20]:  # Limit to 20 tests
        description += f"| `{test_name}` | {group.client} |\n"

    if len(group.test_names) > 20:
        description += f"\n*... and {len(group.test_names) - 20} more tests*\n"

    description += "\n### Error Messages\n\n"

    for i, error in enumerate(group.error_messages[:5], 1):
        # Truncate long error messages
        error_truncated = error[:1000] if len(error) > 1000 else error
        description += f"**Error {i}:**\n```\n{error_truncated}\n```\n\n"

    if len(group.error_messages) > 5:
        description += f"*... and {len(group.error_messages) - 5} more unique errors*\n\n"

    description += """### Classification

"""

    if group.is_server_issue:
        description += """This failure appears to be a **server-side issue** based on error pattern analysis.

The error patterns suggest the issue originates from the Geode database server rather than the client library.
"""
    else:
        description += f"""This failure appears to be a **client-side issue** in the **{group.client}** client.

The error patterns suggest the issue originates from the client library implementation.
"""

    description += """
### Reproduction

To reproduce these failures:

1. Clone the test harness: `git clone https://gitlab.com/devnw/codepros/geode/geode-test-harness`
2. Run: `make docker-start && make test-all`
3. Check `reports/results.json` for detailed results

### Labels

"""

    for label in group.labels:
        description += f"- `{label}`\n"

    description += """
---
*This issue was automatically created by the Geode Test Harness CI/CD pipeline.*
"""

    return description


def get_ci_info() -> Dict[str, str]:
    """Get CI/CD environment information."""
    return {
        "pipeline_url": os.environ.get("CI_PIPELINE_URL", "N/A"),
        "commit_sha": os.environ.get("CI_COMMIT_SHA", os.environ.get("GITHUB_SHA", "N/A")),
        "branch": os.environ.get("CI_COMMIT_BRANCH", os.environ.get("GITHUB_REF_NAME", "N/A")),
        "job_url": os.environ.get("CI_JOB_URL", "N/A"),
        "project": os.environ.get("CI_PROJECT_PATH", "N/A"),
    }


def route_failures(
    results_file: Path,
    dry_run: bool = False,
    verbose: bool = False,
    skip_duplicates: bool = True,
) -> Dict[str, List[str]]:
    """
    Main function to route failures to appropriate repositories.

    Returns:
        Dict mapping repo to list of created issue URLs
    """
    # Load results
    with open(results_file) as f:
        data = json.load(f)

    results = data.get("results", [])

    if not results:
        print("No test results found")
        return {}

    # Count failures
    failures = [r for r in results if r.get("status") in ("failed", "error")]

    if not failures:
        print("No failures to route")
        return {}

    print(f"Found {len(failures)} failures to analyze")

    # Analyze and group failures
    repo_groups = analyze_failures(results)

    if not repo_groups:
        print("No failures could be classified for routing")
        return {}

    print(f"Grouped failures into {sum(len(g) for g in repo_groups.values())} issue groups across {len(repo_groups)} repositories")

    # Get CI info
    ci_info = get_ci_info()

    # Create issues
    created_issues: Dict[str, List[str]] = {}

    for repo, groups in repo_groups.items():
        print(f"\nProcessing repository: {repo}")
        created_issues[repo] = []

        for group in groups:
            title = group.issue_title

            # Check for existing issues if skip_duplicates is enabled
            if skip_duplicates and not dry_run:
                existing = check_existing_issues(repo, "[Test Harness]", verbose)
                if existing:
                    # Check if any existing issue is for the same tests
                    for test_name in group.test_names[:3]:
                        for existing_issue in existing:
                            if test_name in existing_issue:
                                print(f"  Skipping: Similar issue already exists: {existing_issue[:80]}")
                                continue

            # Generate description
            description = generate_issue_description(group, ci_info)

            # Create issue
            print(f"  Creating issue: {title[:60]}...")
            url = create_issue(
                repo=repo,
                title=title,
                description=description,
                labels=group.labels,
                dry_run=dry_run,
                verbose=verbose,
            )

            if url:
                created_issues[repo].append(url)
                print(f"  Created: {url}")

    return created_issues


def main():
    parser = argparse.ArgumentParser(
        description="Route test failures to appropriate GitLab repositories"
    )
    parser.add_argument(
        "results_file",
        type=Path,
        help="Path to test results JSON file",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be created without actually creating issues",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print verbose output",
    )
    parser.add_argument(
        "--no-skip-duplicates",
        action="store_true",
        help="Create issues even if similar ones exist",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        help="Write created issue URLs to this file",
    )

    args = parser.parse_args()

    if not args.results_file.exists():
        print(f"Error: Results file not found: {args.results_file}", file=sys.stderr)
        sys.exit(1)

    # Check for glab CLI
    try:
        subprocess.run(["glab", "--version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("Error: glab CLI not found. Install from https://gitlab.com/gitlab-org/cli", file=sys.stderr)
        if not args.dry_run:
            sys.exit(1)
        print("Continuing in dry-run mode...")

    # Route failures
    created_issues = route_failures(
        args.results_file,
        dry_run=args.dry_run,
        verbose=args.verbose,
        skip_duplicates=not args.no_skip_duplicates,
    )

    # Summary
    total_created = sum(len(urls) for urls in created_issues.values())
    print(f"\n{'='*60}")
    print(f"Summary: Created {total_created} issues across {len(created_issues)} repositories")

    if args.output and created_issues:
        with open(args.output, "w") as f:
            json.dump(created_issues, f, indent=2)
        print(f"Issue URLs written to: {args.output}")

    # Return non-zero if there were failures (even if issues were created)
    if total_created > 0 or args.dry_run:
        sys.exit(0)
    else:
        # No issues created means no failures or all were duplicates
        sys.exit(0)


if __name__ == "__main__":
    main()
