#!/usr/bin/env python3
"""
Generate test files for geodetestlab shell persistence tests.

This script generates GQL files of various sizes to test:
1. Small files (under 32KB) - processed in single request
2. Large files (over 32KB) - processed with chunked execution
"""

import argparse
import os
from pathlib import Path


def generate_create_statements(count: int, label: str = "TestNode", include_properties: bool = True) -> str:
    """Generate CREATE statements for nodes."""
    statements = []
    for i in range(1, count + 1):
        if include_properties:
            stmt = f'CREATE (n{i}:{label} {{id: {i}, name: "node_{i}", description: "A test node for persistence testing with some extra data to make it larger"}});'
        else:
            stmt = f'CREATE (n{i}:{label} {{id: {i}}});'
        statements.append(stmt)
    return "\n".join(statements)


def generate_small_test_file(output_path: str, node_count: int = 10):
    """Generate a small test file (under 32KB)."""
    content = f"""-- Small test file for shell persistence testing
-- This file should be processed in a single request (under 32KB)
-- Generated with {node_count} CREATE statements

{generate_create_statements(node_count, "SmallTestNode")}

-- Verify the data
MATCH (n:SmallTestNode) RETURN count(n) AS node_count;
"""
    with open(output_path, "w") as f:
        f.write(content)

    size = os.path.getsize(output_path)
    print(f"Generated small test file: {output_path} ({size} bytes, {node_count} nodes)")
    return size


def generate_large_test_file(output_path: str, node_count: int = 500):
    """Generate a large test file (over 32KB) to trigger chunked execution."""
    content = f"""-- Large test file for shell persistence testing
-- This file should trigger chunked execution (over 32KB)
-- Generated with {node_count} CREATE statements

{generate_create_statements(node_count, "LargeTestNode")}

-- Verify the data
MATCH (n:LargeTestNode) RETURN count(n) AS node_count;
"""
    with open(output_path, "w") as f:
        f.write(content)

    size = os.path.getsize(output_path)
    print(f"Generated large test file: {output_path} ({size} bytes, {node_count} nodes)")
    return size


def generate_mixed_test_file(output_path: str):
    """Generate a file with nodes, edges, and various operations."""
    content = """-- Mixed test file for comprehensive persistence testing
-- Contains nodes, edges, properties of various types

-- Create nodes with different labels
CREATE (alice:Person {name: "Alice", age: 30, active: true});
CREATE (bob:Person {name: "Bob", age: 25, active: true});
CREATE (charlie:Person {name: "Charlie", age: 35, active: false});

CREATE (acme:Company {name: "Acme Corp", founded: 2010});
CREATE (tech:Company {name: "Tech Inc", founded: 2015});

-- Create relationships
MATCH (a:Person {name: "Alice"}), (acme:Company {name: "Acme Corp"})
CREATE (a)-[:WORKS_AT {since: 2020, role: "Engineer"}]->(acme);

MATCH (b:Person {name: "Bob"}), (tech:Company {name: "Tech Inc"})
CREATE (b)-[:WORKS_AT {since: 2022, role: "Manager"}]->(tech);

MATCH (a:Person {name: "Alice"}), (b:Person {name: "Bob"})
CREATE (a)-[:KNOWS {since: 2019}]->(b);

MATCH (b:Person {name: "Bob"}), (c:Person {name: "Charlie"})
CREATE (b)-[:KNOWS {since: 2021}]->(c);

-- Create nodes with various property types
CREATE (test:PropertyTest {
    string_val: "hello world",
    int_val: 42,
    float_val: 3.14159,
    bool_val: true,
    list_val: [1, 2, 3, 4, 5],
    nested_val: {a: 1, b: 2}
});

-- Verify data
MATCH (p:Person) RETURN count(p) AS person_count;
MATCH (c:Company) RETURN count(c) AS company_count;
MATCH ()-[r]->() RETURN count(r) AS relationship_count;
"""
    with open(output_path, "w") as f:
        f.write(content)

    size = os.path.getsize(output_path)
    print(f"Generated mixed test file: {output_path} ({size} bytes)")
    return size


def generate_named_graph_test_file(output_path: str):
    """Generate a file that creates and uses named graphs."""
    content = """-- Named graph test file
-- Tests persistence of named graphs

-- Create first named graph
CREATE GRAPH social;
USE GRAPH social;
CREATE (a:User {name: "Alice", email: "alice@example.com"});
CREATE (b:User {name: "Bob", email: "bob@example.com"});
MATCH (a:User {name: "Alice"}), (b:User {name: "Bob"})
CREATE (a)-[:FOLLOWS]->(b);

-- Create second named graph
CREATE GRAPH products;
USE GRAPH products;
CREATE (p1:Product {name: "Widget", price: 9.99});
CREATE (p2:Product {name: "Gadget", price: 19.99});

-- Switch back to default graph
USE GRAPH DEFAULT;
CREATE (marker:Marker {purpose: "mark default graph usage"});

-- Verify
USE GRAPH social;
MATCH (u:User) RETURN count(u) AS social_users;

USE GRAPH products;
MATCH (p:Product) RETURN count(p) AS products_count;
"""
    with open(output_path, "w") as f:
        f.write(content)

    size = os.path.getsize(output_path)
    print(f"Generated named graph test file: {output_path} ({size} bytes)")
    return size


def main():
    parser = argparse.ArgumentParser(description="Generate test files for shell persistence testing")
    parser.add_argument("--output-dir", default="./test_files", help="Output directory for test files")
    parser.add_argument("--small-nodes", type=int, default=10, help="Number of nodes in small file")
    parser.add_argument("--large-nodes", type=int, default=500, help="Number of nodes in large file")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Generating test files in {output_dir}")
    print()

    # Generate various test files
    generate_small_test_file(output_dir / "small_test.gql", args.small_nodes)
    generate_large_test_file(output_dir / "large_test.gql", args.large_nodes)
    generate_mixed_test_file(output_dir / "mixed_test.gql")
    generate_named_graph_test_file(output_dir / "named_graph_test.gql")

    # Generate extra large file for stress testing
    generate_large_test_file(output_dir / "stress_test.gql", 2000)

    print()
    print("Test files generated successfully!")
    print()
    print("Usage examples:")
    print(f"  ./zig-out/bin/geode shell --insecure")
    print(f"  /source {output_dir}/small_test.gql")
    print(f"  /source {output_dir}/large_test.gql")


if __name__ == "__main__":
    main()
