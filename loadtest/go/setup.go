package main

import (
	"context"
	"database/sql"
	"fmt"
	"os"
	"time"
)

// batchCreateNodes creates count nodes with label and sequential lt_id.
// Each node gets {lt_id: i, name: "<Label>_i", age: 20+(i%50)}.
func batchCreateNodes(db *sql.DB, label string, count int) error {
	for i := 0; i < count; i++ {
		ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		_, err := db.ExecContext(ctx, fmt.Sprintf(
			"CREATE (:%s {lt_id: %d, name: '%s_%d', age: %d})",
			label, i, label, i, 20+(i%50)))
		cancel()
		if err != nil {
			return fmt.Errorf("create node %s %d: %w", label, i, err)
		}
		if (i+1)%200 == 0 {
			fmt.Fprintf(os.Stderr, "    setup: created %d/%d %s nodes\n", i+1, count, label)
		}
	}
	if count > 0 && count%200 != 0 {
		fmt.Fprintf(os.Stderr, "    setup: created %d/%d %s nodes\n", count, count, label)
	}
	return nil
}

// batchCreateEdges creates edges between nodes of the given labels.
// For each source node i (0..sourceCount-1), creates edgesPerNode edges
// to deterministic targets: (i + 1 + j*prime) % targetCount.
func batchCreateEdges(db *sql.DB, srcLabel, relType, dstLabel string,
	sourceCount, targetCount, edgesPerNode int) error {

	prime := 7
	total := sourceCount * edgesPerNode
	created := 0

	for i := 0; i < sourceCount; i++ {
		for j := 0; j < edgesPerNode; j++ {
			target := (i + 1 + j*prime) % targetCount
			if target == i && srcLabel == dstLabel {
				target = (target + 1) % targetCount
			}

			ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
			_, err := db.ExecContext(ctx, fmt.Sprintf(
				"MATCH (a:%s {lt_id: %d}), (b:%s {lt_id: %d}) CREATE (a)-[:%s]->(b)",
				srcLabel, i, dstLabel, target, relType))
			cancel()
			if err != nil {
				return fmt.Errorf("create edge %s -[%s]-> %s (%d->%d): %w",
					srcLabel, relType, dstLabel, i, target, err)
			}
			created++
			if created%500 == 0 {
				fmt.Fprintf(os.Stderr, "    setup: created %d/%d %s edges\n", created, total, relType)
			}
		}
	}
	if total > 0 && total%500 != 0 {
		fmt.Fprintf(os.Stderr, "    setup: created %d/%d %s edges\n", total, total, relType)
	}
	return nil
}

// batchCreateCompanies creates LT_Company nodes with lt_id, name, and founded.
func batchCreateCompanies(db *sql.DB, count int) error {
	for i := 0; i < count; i++ {
		ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		_, err := db.ExecContext(ctx, fmt.Sprintf(
			"CREATE (:LT_Company {lt_id: %d, name: 'Company_%d', founded: %d})",
			i, i, 1990+(i%35)))
		cancel()
		if err != nil {
			return fmt.Errorf("create company %d: %w", i, err)
		}
		if (i+1)%100 == 0 {
			fmt.Fprintf(os.Stderr, "    setup: created %d/%d LT_Company nodes\n", i+1, count)
		}
	}
	if count > 0 && count%100 != 0 {
		fmt.Fprintf(os.Stderr, "    setup: created %d/%d LT_Company nodes\n", count, count)
	}
	return nil
}

// batchCreateWorksAt creates LT_WORKS_AT edges from each LT_Person to a LT_Company.
// Person i works at company (i % numCompanies).
func batchCreateWorksAt(db *sql.DB, numPersons, numCompanies int) error {
	for i := 0; i < numPersons; i++ {
		companyID := i % numCompanies
		ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		_, err := db.ExecContext(ctx, fmt.Sprintf(
			"MATCH (p:LT_Person {lt_id: %d}), (c:LT_Company {lt_id: %d}) CREATE (p)-[:LT_WORKS_AT]->(c)",
			i, companyID))
		cancel()
		if err != nil {
			return fmt.Errorf("create works_at %d->%d: %w", i, companyID, err)
		}
		if (i+1)%500 == 0 {
			fmt.Fprintf(os.Stderr, "    setup: created %d/%d LT_WORKS_AT edges\n", i+1, numPersons)
		}
	}
	if numPersons > 0 && numPersons%500 != 0 {
		fmt.Fprintf(os.Stderr, "    setup: created %d/%d LT_WORKS_AT edges\n", numPersons, numPersons)
	}
	return nil
}

// deleteByLabel deletes all nodes with the given label.
func deleteByLabel(db *sql.DB, label string) error {
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()
	_, err := db.ExecContext(ctx, fmt.Sprintf("MATCH (n:%s) DELETE n", label))
	return err
}

// deleteEdgesByType deletes all relationships of the given type.
func deleteEdgesByType(db *sql.DB, relType string) error {
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()
	_, err := db.ExecContext(ctx, fmt.Sprintf("MATCH ()-[r:%s]->() DELETE r", relType))
	return err
}

// drainRows consumes all rows from a result set, discarding values.
func drainRows(rows *sql.Rows) error {
	cols, err := rows.Columns()
	if err != nil {
		return err
	}
	vals := make([]interface{}, len(cols))
	ptrs := make([]interface{}, len(cols))
	for i := range vals {
		ptrs[i] = &vals[i]
	}
	for rows.Next() {
		if err := rows.Scan(ptrs...); err != nil {
			return err
		}
	}
	return rows.Err()
}
