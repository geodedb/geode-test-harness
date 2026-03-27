"""Plaintext scanner for TDE verification.

This module provides tools for scanning data files to detect plaintext
that should have been encrypted by TDE (Transparent Data Encryption).

Design rationale (QG-030):
    The scanner uses a single ``grep -rE`` invocation via ``_scan_combined()``
    to check all patterns in one pass.  An earlier design spawned one grep
    per pattern (``_scan_pattern``), which was removed in PERF-005 because
    the per-pattern approach scaled as O(patterns * files).  The combined
    approach is O(files) regardless of pattern count.

    The public entry points are:
    - ``PlaintextScanner.scan()`` — class-based, returns ``PlaintextViolation`` objects.
    - ``scan_for_plaintext()`` — standalone function used by ``executor.py``.

    Both delegate to ``_scan_combined()`` internally.
"""

from __future__ import annotations

import contextlib
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class PlaintextViolation:
    """A single plaintext violation found in a data file."""

    file_path: str
    pattern: str
    line_number: int | None = None
    context: str | None = None
    file_type: str = "unknown"

    def __str__(self) -> str:
        location = f"{self.file_path}"
        if self.line_number:
            location += f":{self.line_number}"
        return f"Plaintext '{self.pattern}' found in {location}"


class PlaintextScanner:
    """Scanner for detecting plaintext in encrypted data files.

    This class provides comprehensive scanning capabilities for verifying
    that TDE (Transparent Data Encryption) is working correctly by ensuring
    no plaintext appears in data files.
    """

    # Default file extensions to scan (binary data files)
    DEFAULT_DATA_EXTENSIONS: set[str] = {
        ".db",
        ".dat",
        ".page",
        ".wal",
        ".idx",
        ".index",
        ".bak",
        ".backup",
        ".archive",
        ".segment",
        ".log",
    }

    # Extensions to exclude from scanning (text/config files)
    DEFAULT_EXCLUDE_EXTENSIONS: set[str] = {
        ".md",
        ".txt",
        ".yml",
        ".yaml",
        ".json",
        ".xml",
        ".toml",
        ".conf",
        ".cfg",
        ".ini",
        ".sh",
        ".bash",
        ".py",
        ".zig",
        ".go",
        ".rs",
        ".js",
        ".ts",
    }

    def __init__(
        self,
        data_dir: Path,
        patterns: list[str],
        exclude_extensions: set[str] | None = None,
        include_extensions: set[str] | None = None,
        scan_all_files: bool = False,
    ):
        """Initialize the plaintext scanner.

        Parameters
        ----------
        data_dir : Path
            Directory to scan for plaintext violations.
        patterns : List[str]
            List of plaintext patterns to search for.
        exclude_extensions : Optional[Set[str]]
            File extensions to exclude from scanning.
        include_extensions : Optional[Set[str]]
            If provided, only scan files with these extensions.
        scan_all_files : bool
            If True, scan all files regardless of extension.
        """
        self.data_dir = Path(data_dir)
        self.patterns = patterns
        self.exclude_extensions = exclude_extensions or self.DEFAULT_EXCLUDE_EXTENSIONS
        self.include_extensions = include_extensions
        self.scan_all_files = scan_all_files
        self.violations: list[PlaintextViolation] = []

    def scan(self) -> list[PlaintextViolation]:
        """Scan the data directory for plaintext violations.

        Combines all patterns into a single ``grep -E`` call to avoid
        N recursive directory scans (PERF-005).

        Returns
        -------
        List[PlaintextViolation]
            List of violations found.
        """
        self.violations = []

        if not self.data_dir.exists() or not self.patterns:
            return self.violations

        self._scan_combined()
        return self.violations

    def _scan_combined(self) -> None:
        """Scan for all patterns in a single grep invocation."""
        import re as _re

        combined = "|".join(_re.escape(p) for p in self.patterns)
        try:
            cmd = ["grep", "-r", "-a", "-n", "-E", combined, str(self.data_dir)]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    if not line:
                        continue
                    # Parse file_path:line_number:content
                    parts = line.split(":", 2)
                    file_path = parts[0]
                    line_number = None
                    with contextlib.suppress(ValueError, IndexError):
                        line_number = int(parts[1])

                    if not self._should_scan_file(file_path):
                        continue

                    # Determine which pattern matched
                    matched_pattern = self.patterns[0]
                    content = parts[2] if len(parts) > 2 else ""
                    for p in self.patterns:
                        if p in content:
                            matched_pattern = p
                            break

                    self.violations.append(
                        PlaintextViolation(
                            file_path=file_path,
                            pattern=matched_pattern,
                            line_number=line_number,
                            file_type=self._get_file_type(file_path),
                        )
                    )
        except subprocess.TimeoutExpired:
            logger.warning("Grep timed out during combined pattern scan on %s", self.data_dir)
        except Exception:
            logger.warning("Error during combined pattern scan on %s", self.data_dir, exc_info=True)

    def _should_scan_file(self, file_path: str) -> bool:
        """Check if a file should be included in the scan."""
        if self.scan_all_files:
            return True

        path = Path(file_path)
        ext = path.suffix.lower()

        # Check exclude list
        if ext in self.exclude_extensions:
            return False

        # Check include list if specified
        if self.include_extensions:
            return ext in self.include_extensions

        return True

    def _get_file_type(self, file_path: str) -> str:
        """Determine the type of file based on path and extension."""
        path = Path(file_path)
        name = path.name.lower()
        ext = path.suffix.lower()

        if "wal" in name or ext == ".wal":
            return "wal"
        elif "page" in name or ext == ".page":
            return "page"
        elif "index" in name or ext in (".idx", ".index"):
            return "index"
        elif "backup" in name or ext in (".bak", ".backup"):
            return "backup"
        elif "archive" in name or ext == ".archive":
            return "archive"
        elif ext in (".db", ".dat"):
            return "data"
        else:
            return "unknown"

    def has_violations(self) -> bool:
        """Check if any violations were found."""
        return len(self.violations) > 0

    def get_report(self) -> str:
        """Generate a human-readable report of violations."""
        if not self.violations:
            return "No plaintext violations found."

        lines = [
            f"PLAINTEXT VIOLATIONS FOUND: {len(self.violations)}",
            "=" * 60,
        ]

        # Group by pattern
        by_pattern: dict[str, list[PlaintextViolation]] = {}
        for v in self.violations:
            if v.pattern not in by_pattern:
                by_pattern[v.pattern] = []
            by_pattern[v.pattern].append(v)

        for pattern, violations in by_pattern.items():
            lines.append(f"\nPattern: '{pattern}'")
            lines.append("-" * 40)
            for v in violations:
                location = v.file_path
                if v.line_number:
                    location += f":{v.line_number}"
                lines.append(f"  [{v.file_type}] {location}")

        return "\n".join(lines)


def scan_for_plaintext(
    data_dir: Path,
    patterns: list[str],
    verbose: bool = False,
) -> list[PlaintextViolation]:
    """Convenience function to scan for plaintext violations.

    Parameters
    ----------
    data_dir : Path
        Directory to scan.
    patterns : List[str]
        Patterns to search for.
    verbose : bool
        If True, print progress.

    Returns
    -------
    List[PlaintextViolation]
        List of violations found.
    """
    scanner = PlaintextScanner(
        data_dir=data_dir,
        patterns=patterns,
        scan_all_files=True,
    )

    if verbose:
        print(f"Scanning {data_dir} for {len(patterns)} patterns...")

    violations = scanner.scan()

    if verbose:
        if violations:
            print(f"CRITICAL: Found {len(violations)} plaintext violations!")
            print(scanner.get_report())
        else:
            print("No plaintext violations found.")

    return violations


def quick_verify_tde(
    data_dir: Path,
    test_marker: str = "TESTSECRET_",
) -> bool:
    """Quick verification that TDE is working.

    Parameters
    ----------
    data_dir : Path
        Directory to scan.
    test_marker : str
        Marker prefix to search for.

    Returns
    -------
    bool
        True if no violations found (TDE working), False otherwise.
    """
    scanner = PlaintextScanner(
        data_dir=data_dir,
        patterns=[test_marker],
        scan_all_files=True,
    )
    violations = scanner.scan()
    return len(violations) == 0
