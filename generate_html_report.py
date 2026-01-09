#!/usr/bin/env python3
"""
HTML Report Generator for Client Library Tests

Generates interactive HTML dashboards from JSON test results with:
- Pass/fail summary by client
- Test-by-test breakdown with expand/collapse
- Performance comparison charts
- Error details and stack traces
- Coverage matrix
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List
from datetime import datetime


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Geode Client Test Report</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: #f5f7fa;
            color: #333;
            line-height: 1.6;
        }

        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
        }

        header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 40px 20px;
            border-radius: 12px;
            margin-bottom: 30px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }

        header h1 {
            font-size: 2.5em;
            margin-bottom: 10px;
        }

        header .metadata {
            opacity: 0.9;
            font-size: 0.95em;
        }

        .summary-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }

        .summary-card {
            background: white;
            border-radius: 12px;
            padding: 25px;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
            transition: transform 0.2s, box-shadow 0.2s;
        }

        .summary-card:hover {
            transform: translateY(-4px);
            box-shadow: 0 8px 16px rgba(0, 0, 0, 0.12);
        }

        .summary-card h3 {
            font-size: 0.85em;
            text-transform: uppercase;
            color: #666;
            margin-bottom: 10px;
            letter-spacing: 0.5px;
        }

        .summary-card .value {
            font-size: 2.5em;
            font-weight: 700;
            margin-bottom: 5px;
        }

        .summary-card .label {
            font-size: 0.9em;
            color: #888;
        }

        .status-passed { color: #10b981; }
        .status-failed { color: #ef4444; }
        .status-error { color: #f59e0b; }
        .status-skipped { color: #6b7280; }

        .tabs {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
            border-bottom: 2px solid #e5e7eb;
            flex-wrap: wrap;
        }

        .tab {
            padding: 12px 24px;
            background: white;
            border: none;
            border-bottom: 3px solid transparent;
            cursor: pointer;
            font-size: 1em;
            font-weight: 500;
            color: #666;
            transition: all 0.2s;
            border-radius: 8px 8px 0 0;
        }

        .tab:hover {
            background: #f9fafb;
            color: #333;
        }

        .tab.active {
            color: #667eea;
            border-bottom-color: #667eea;
            background: white;
        }

        .tab-content {
            display: none;
            background: white;
            padding: 30px;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
        }

        .tab-content.active {
            display: block;
        }

        .client-section {
            margin-bottom: 40px;
        }

        .client-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 20px;
            background: #f9fafb;
            border-radius: 8px;
            margin-bottom: 15px;
            cursor: pointer;
            transition: background 0.2s;
        }

        .client-header:hover {
            background: #f3f4f6;
        }

        .client-name {
            font-size: 1.4em;
            font-weight: 600;
        }

        .client-stats {
            display: flex;
            gap: 20px;
            font-size: 0.9em;
        }

        .stat {
            display: flex;
            align-items: center;
            gap: 5px;
        }

        .test-list {
            margin-left: 20px;
        }

        .test-item {
            border-left: 4px solid #e5e7eb;
            padding: 15px 20px;
            margin-bottom: 10px;
            background: #fafbfc;
            border-radius: 0 8px 8px 0;
            transition: all 0.2s;
        }

        .test-item:hover {
            background: #f5f6f7;
            border-left-color: #667eea;
        }

        .test-item.passed { border-left-color: #10b981; }
        .test-item.failed { border-left-color: #ef4444; }
        .test-item.error { border-left-color: #f59e0b; }
        .test-item.skipped { border-left-color: #6b7280; }

        .test-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            cursor: pointer;
        }

        .test-name {
            font-weight: 600;
            font-size: 1.05em;
        }

        .test-status {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 0.85em;
            font-weight: 600;
            text-transform: uppercase;
        }

        .test-status.passed {
            background: #d1fae5;
            color: #065f46;
        }

        .test-status.failed {
            background: #fee2e2;
            color: #991b1b;
        }

        .test-status.error {
            background: #fef3c7;
            color: #92400e;
        }

        .test-status.skipped {
            background: #f3f4f6;
            color: #374151;
        }

        .test-details {
            display: none;
            margin-top: 15px;
            padding-top: 15px;
            border-top: 1px solid #e5e7eb;
        }

        .test-details.expanded {
            display: block;
        }

        .test-meta {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 10px;
            margin-bottom: 15px;
            font-size: 0.9em;
        }

        .meta-item {
            display: flex;
            gap: 8px;
        }

        .meta-label {
            font-weight: 600;
            color: #666;
        }

        .error-message {
            background: #fef2f2;
            border-left: 4px solid #ef4444;
            padding: 15px;
            border-radius: 4px;
            font-family: 'Courier New', monospace;
            font-size: 0.9em;
            white-space: pre-wrap;
            overflow-x: auto;
        }

        .chart-container {
            position: relative;
            height: 400px;
            margin: 30px 0;
        }

        .coverage-matrix {
            overflow-x: auto;
        }

        .coverage-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.9em;
        }

        .coverage-table th,
        .coverage-table td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #e5e7eb;
        }

        .coverage-table th {
            background: #f9fafb;
            font-weight: 600;
            position: sticky;
            top: 0;
        }

        .coverage-table tr:hover {
            background: #f9fafb;
        }

        .coverage-check {
            text-align: center;
            font-size: 1.2em;
        }

        .coverage-check.yes { color: #10b981; }
        .coverage-check.no { color: #ef4444; }
        .coverage-check.partial { color: #f59e0b; }

        .filters {
            display: flex;
            gap: 15px;
            margin-bottom: 20px;
            flex-wrap: wrap;
        }

        .filter-group {
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .filter-group label {
            font-weight: 500;
            font-size: 0.9em;
        }

        select, input[type="text"] {
            padding: 8px 12px;
            border: 1px solid #d1d5db;
            border-radius: 6px;
            font-size: 0.9em;
            background: white;
        }

        select:focus, input[type="text"]:focus {
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
        }

        .footer {
            text-align: center;
            padding: 30px;
            color: #888;
            font-size: 0.9em;
            margin-top: 40px;
        }

        @media (max-width: 768px) {
            .summary-grid {
                grid-template-columns: 1fr;
            }

            .client-stats {
                flex-direction: column;
                gap: 8px;
            }

            .test-meta {
                grid-template-columns: 1fr;
            }

            .filters {
                flex-direction: column;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Geode Client Library Test Report</h1>
            <div class="metadata">
                <div>Generated: {timestamp}</div>
                <div>Server: {server}</div>
                <div>Total Tests: {total_tests}</div>
            </div>
        </header>

        <div class="summary-grid">
            <div class="summary-card">
                <h3>Passed</h3>
                <div class="value status-passed">{passed}</div>
                <div class="label">{pass_rate}% pass rate</div>
            </div>
            <div class="summary-card">
                <h3>Failed</h3>
                <div class="value status-failed">{failed}</div>
                <div class="label">{fail_rate}% fail rate</div>
            </div>
            <div class="summary-card">
                <h3>Errors</h3>
                <div class="value status-error">{errors}</div>
                <div class="label">Runtime errors</div>
            </div>
            <div class="summary-card">
                <h3>Skipped</h3>
                <div class="value status-skipped">{skipped}</div>
                <div class="label">Not executed</div>
            </div>
        </div>

        <div class="tabs">
            <button class="tab active" onclick="showTab('overview')">Overview</button>
            <button class="tab" onclick="showTab('by-client')">By Client</button>
            <button class="tab" onclick="showTab('by-test')">By Test</button>
            <button class="tab" onclick="showTab('coverage')">Coverage Matrix</button>
            <button class="tab" onclick="showTab('performance')">Performance</button>
        </div>

        <div id="overview" class="tab-content active">
            <h2>Test Results Overview</h2>
            <div class="chart-container">
                <canvas id="overviewChart"></canvas>
            </div>

            <div class="chart-container">
                <canvas id="statusChart"></canvas>
            </div>
        </div>

        <div id="by-client" class="tab-content">
            <div class="filters">
                <div class="filter-group">
                    <label>Status:</label>
                    <select id="statusFilter" onchange="filterTests()">
                        <option value="all">All</option>
                        <option value="passed">Passed</option>
                        <option value="failed">Failed</option>
                        <option value="error">Error</option>
                        <option value="skipped">Skipped</option>
                    </select>
                </div>
                <div class="filter-group">
                    <label>Search:</label>
                    <input type="text" id="searchInput" placeholder="Filter by test name..." onkeyup="filterTests()">
                </div>
            </div>

            {client_sections}
        </div>

        <div id="by-test" class="tab-content">
            <div class="filters">
                <div class="filter-group">
                    <label>Client:</label>
                    <select id="clientFilter" onchange="filterByTest()">
                        <option value="all">All Clients</option>
                        {client_options}
                    </select>
                </div>
            </div>
            {test_sections}
        </div>

        <div id="coverage" class="tab-content">
            <h2>Feature Coverage Matrix</h2>
            <div class="coverage-matrix">
                <table class="coverage-table">
                    <thead>
                        <tr>
                            <th>Test Name</th>
                            {client_headers}
                        </tr>
                    </thead>
                    <tbody>
                        {coverage_rows}
                    </tbody>
                </table>
            </div>
        </div>

        <div id="performance" class="tab-content">
            <h2>Performance Metrics</h2>
            <div class="chart-container">
                <canvas id="performanceChart"></canvas>
            </div>
            {performance_details}
        </div>

        <footer class="footer">
            <div>Geode Client Library Test Harness</div>
            <div>Report generated by generate_html_report.py</div>
        </footer>
    </div>

    <script>
        // Test data
        const testData = {test_data_json};

        // Tab switching
        function showTab(tabId) {
            document.querySelectorAll('.tab').forEach(tab => tab.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));

            event.target.classList.add('active');
            document.getElementById(tabId).classList.add('active');
        }

        // Toggle test details
        function toggleDetails(testId) {
            const details = document.getElementById('details-' + testId);
            details.classList.toggle('expanded');
        }

        // Filter tests
        function filterTests() {
            const statusFilter = document.getElementById('statusFilter').value;
            const searchText = document.getElementById('searchInput').value.toLowerCase();

            document.querySelectorAll('.test-item').forEach(item => {
                const status = item.dataset.status;
                const name = item.dataset.name.toLowerCase();

                const statusMatch = statusFilter === 'all' || status === statusFilter;
                const searchMatch = searchText === '' || name.includes(searchText);

                item.style.display = (statusMatch && searchMatch) ? 'block' : 'none';
            });
        }

        // Filter by test view
        function filterByTest() {
            const clientFilter = document.getElementById('clientFilter').value;

            document.querySelectorAll('.test-by-name').forEach(section => {
                if (clientFilter === 'all') {
                    section.style.display = 'block';
                } else {
                    // Show only if this test has results for the selected client
                    const hasClient = section.querySelector(`[data-client="${clientFilter}"]`) !== null;
                    section.style.display = hasClient ? 'block' : 'none';
                }
            });
        }

        // Initialize charts
        window.addEventListener('load', function() {
            // Overview chart - results by client
            const overviewCtx = document.getElementById('overviewChart').getContext('2d');
            new Chart(overviewCtx, {
                type: 'bar',
                data: {
                    labels: {client_labels_json},
                    datasets: [
                        {
                            label: 'Passed',
                            data: {passed_data_json},
                            backgroundColor: 'rgba(16, 185, 129, 0.7)'
                        },
                        {
                            label: 'Failed',
                            data: {failed_data_json},
                            backgroundColor: 'rgba(239, 68, 68, 0.7)'
                        },
                        {
                            label: 'Errors',
                            data: {errors_data_json},
                            backgroundColor: 'rgba(245, 158, 11, 0.7)'
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        title: {
                            display: true,
                            text: 'Test Results by Client'
                        }
                    },
                    scales: {
                        x: { stacked: true },
                        y: { stacked: true, beginAtZero: true }
                    }
                }
            });

            // Status distribution chart
            const statusCtx = document.getElementById('statusChart').getContext('2d');
            new Chart(statusCtx, {
                type: 'doughnut',
                data: {
                    labels: ['Passed', 'Failed', 'Errors', 'Skipped'],
                    datasets: [{
                        data: [{passed}, {failed}, {errors}, {skipped}],
                        backgroundColor: [
                            'rgba(16, 185, 129, 0.7)',
                            'rgba(239, 68, 68, 0.7)',
                            'rgba(245, 158, 11, 0.7)',
                            'rgba(107, 114, 128, 0.7)'
                        ]
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        title: {
                            display: true,
                            text: 'Overall Test Status Distribution'
                        }
                    }
                }
            });

            // Performance chart (if performance data available)
            const perfData = {performance_chart_json};
            if (perfData && perfData.labels && perfData.labels.length > 0) {
                const perfCtx = document.getElementById('performanceChart').getContext('2d');
                new Chart(perfCtx, {
                    type: 'bar',
                    data: {
                        labels: perfData.labels,
                        datasets: perfData.datasets
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            title: {
                                display: true,
                                text: 'Average Test Duration by Client (ms)'
                            }
                        },
                        scales: {
                            y: { beginAtZero: true }
                        }
                    }
                });
            }
        });
    </script>
</body>
</html>
"""


def aggregate_results(results: Dict[str, Any]) -> Dict[str, Any]:
    """Aggregate test results across all clients."""
    summary = {
        "total": 0,
        "passed": 0,
        "failed": 0,
        "errors": 0,
        "skipped": 0,
    }

    by_client = {}
    by_test = {}

    for result in results.get("results", []):
        client = result["client"]
        test = result["test"]
        status = result["status"]

        summary["total"] += 1
        summary[status] += 1

        # By client
        if client not in by_client:
            by_client[client] = {
                "passed": 0,
                "failed": 0,
                "error": 0,
                "skipped": 0,
                "tests": [],
            }
        by_client[client][status] += 1
        by_client[client]["tests"].append(result)

        # By test
        if test not in by_test:
            by_test[test] = {}
        by_test[test][client] = result

    return {
        "summary": summary,
        "by_client": by_client,
        "by_test": by_test,
    }


def generate_client_sections(by_client: Dict[str, Any]) -> str:
    """Generate HTML for client-grouped test results."""
    sections = []

    for client, data in sorted(by_client.items()):
        total = len(data["tests"])
        passed = data["passed"]
        failed = data["failed"]
        errors = data["error"]
        skipped = data["skipped"]

        section = f"""
        <div class="client-section">
            <div class="client-header" onclick="this.nextElementSibling.style.display = this.nextElementSibling.style.display === 'none' ? 'block' : 'none'">
                <div class="client-name">{client}</div>
                <div class="client-stats">
                    <div class="stat status-passed">✓ {passed}</div>
                    <div class="stat status-failed">✗ {failed}</div>
                    <div class="stat status-error">⚠ {errors}</div>
                    <div class="stat status-skipped">⊘ {skipped}</div>
                </div>
            </div>
            <div class="test-list">
        """

        for idx, test in enumerate(data["tests"]):
            test_id = f"{client}-{idx}"
            status = test["status"]
            test_name = test["test"]
            duration = test.get("duration_ms", 0)

            error_html = ""
            if status in ("failed", "error") and test.get("error"):
                error_html = f'<div class="error-message">{test["error"]}</div>'

            section += f"""
                <div class="test-item {status}" data-status="{status}" data-name="{test_name}">
                    <div class="test-header" onclick="toggleDetails('{test_id}')">
                        <div class="test-name">{test_name}</div>
                        <div class="test-status {status}">{status}</div>
                    </div>
                    <div class="test-details" id="details-{test_id}">
                        <div class="test-meta">
                            <div class="meta-item">
                                <span class="meta-label">Duration:</span>
                                <span>{duration:.2f}ms</span>
                            </div>
                        </div>
                        {error_html}
                    </div>
                </div>
            """

        section += """
            </div>
        </div>
        """
        sections.append(section)

    return "\n".join(sections)


def generate_test_sections(by_test: Dict[str, Dict[str, Any]]) -> str:
    """Generate HTML for test-grouped results."""
    sections = []

    for test_name, clients in sorted(by_test.items()):
        section = f"""
        <div class="client-section test-by-name">
            <div class="client-header" onclick="this.nextElementSibling.style.display = this.nextElementSibling.style.display === 'none' ? 'block' : 'none'">
                <div class="client-name">{test_name}</div>
                <div class="client-stats">
                    <span>{len(clients)} client(s)</span>
                </div>
            </div>
            <div class="test-list">
        """

        for client, result in sorted(clients.items()):
            status = result["status"]
            duration = result.get("duration_ms", 0)
            test_id = f"{test_name}-{client}"

            error_html = ""
            if status in ("failed", "error") and result.get("error"):
                error_html = f'<div class="error-message">{result["error"]}</div>'

            section += f"""
                <div class="test-item {status}" data-client="{client}">
                    <div class="test-header" onclick="toggleDetails('{test_id}')">
                        <div class="test-name">{client}</div>
                        <div class="test-status {status}">{status}</div>
                    </div>
                    <div class="test-details" id="details-{test_id}">
                        <div class="test-meta">
                            <div class="meta-item">
                                <span class="meta-label">Duration:</span>
                                <span>{duration:.2f}ms</span>
                            </div>
                        </div>
                        {error_html}
                    </div>
                </div>
            """

        section += """
            </div>
        </div>
        """
        sections.append(section)

    return "\n".join(sections)


def generate_coverage_matrix(by_test: Dict[str, Dict[str, Any]]) -> tuple:
    """Generate coverage matrix HTML."""
    all_clients = set()
    for clients in by_test.values():
        all_clients.update(clients.keys())
    all_clients = sorted(all_clients)

    headers = "".join(f"<th>{client}</th>" for client in all_clients)

    rows = []
    for test_name, clients in sorted(by_test.items()):
        cells = []
        for client in all_clients:
            if client in clients:
                status = clients[client]["status"]
                if status == "passed":
                    cell = '<td class="coverage-check yes">✓</td>'
                elif status == "skipped":
                    cell = '<td class="coverage-check partial">⊘</td>'
                else:
                    cell = '<td class="coverage-check no">✗</td>'
            else:
                cell = '<td class="coverage-check no">-</td>'
            cells.append(cell)

        row = f"<tr><td><strong>{test_name}</strong></td>{''.join(cells)}</tr>"
        rows.append(row)

    return headers, "\n".join(rows), list(all_clients)


def extract_performance_data(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Extract performance metrics from results."""
    by_client = {}

    for result in results:
        client = result["client"]
        duration = result.get("duration_ms", 0)

        if client not in by_client:
            by_client[client] = []
        by_client[client].append(duration)

    # Calculate averages
    perf_data = {}
    for client, durations in by_client.items():
        if durations:
            perf_data[client] = sum(durations) / len(durations)

    if not perf_data:
        return {"labels": [], "datasets": []}

    return {
        "labels": list(perf_data.keys()),
        "datasets": [
            {
                "label": "Avg Duration (ms)",
                "data": list(perf_data.values()),
                "backgroundColor": "rgba(102, 126, 234, 0.7)",
            }
        ],
    }


def generate_html_report(results: Dict[str, Any], output_file: Path) -> None:
    """Generate complete HTML report."""
    aggregated = aggregate_results(results)
    summary = aggregated["summary"]

    # Calculate rates
    total = summary["total"]
    pass_rate = (summary["passed"] / total * 100) if total > 0 else 0
    fail_rate = (summary["failed"] / total * 100) if total > 0 else 0

    # Generate sections
    client_sections = generate_client_sections(aggregated["by_client"])
    test_sections = generate_test_sections(aggregated["by_test"])
    coverage_headers, coverage_rows, all_clients = generate_coverage_matrix(
        aggregated["by_test"]
    )

    client_options = "".join(
        f'<option value="{client}">{client}</option>' for client in all_clients
    )

    # Performance data
    perf_chart = extract_performance_data(results.get("results", []))
    perf_details = ""
    if perf_chart["labels"]:
        perf_details = "<h3>Client Performance Summary</h3><p>See chart above for average test duration by client.</p>"

    # Chart data
    client_labels = []
    passed_data = []
    failed_data = []
    errors_data = []

    for client, data in sorted(aggregated["by_client"].items()):
        client_labels.append(client)
        passed_data.append(data["passed"])
        failed_data.append(data["failed"])
        errors_data.append(data["error"])

    # Render template
    html = HTML_TEMPLATE.format(
        timestamp=results.get("timestamp", datetime.now().isoformat()),
        server=results.get("server", "N/A"),
        total_tests=total,
        passed=summary["passed"],
        failed=summary["failed"],
        errors=summary["errors"],
        skipped=summary["skipped"],
        pass_rate=f"{pass_rate:.1f}",
        fail_rate=f"{fail_rate:.1f}",
        client_sections=client_sections,
        test_sections=test_sections,
        client_headers=coverage_headers,
        coverage_rows=coverage_rows,
        client_options=client_options,
        performance_details=perf_details,
        test_data_json=json.dumps(results),
        client_labels_json=json.dumps(client_labels),
        passed_data_json=json.dumps(passed_data),
        failed_data_json=json.dumps(failed_data),
        errors_data_json=json.dumps(errors_data),
        performance_chart_json=json.dumps(perf_chart),
    )

    with open(output_file, "w") as f:
        f.write(html)

    print(f"HTML report generated: {output_file}")


def main():
    parser = argparse.ArgumentParser(
        description="Generate HTML report from test results"
    )
    parser.add_argument("results_json", type=Path, help="Test results JSON file")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("test_report.html"),
        help="Output HTML file (default: test_report.html)",
    )

    args = parser.parse_args()

    if not args.results_json.exists():
        print(f"ERROR: Results file not found: {args.results_json}", file=sys.stderr)
        sys.exit(1)

    with open(args.results_json) as f:
        results = json.load(f)

    generate_html_report(results, args.output)


if __name__ == "__main__":
    main()
