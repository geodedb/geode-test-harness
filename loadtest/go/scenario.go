package main

import (
	"context"
	"database/sql"
	"fmt"
	"math/rand/v2"
	"os"
	"time"
)

// QueryFunc is the function each worker calls in its benchmark loop.
// rng is a per-worker random source for generating query parameters.
type QueryFunc func(db *sql.DB, rng *rand.Rand) error

// DataSize describes the dataset a scenario creates.
type DataSize struct {
	Nodes int `json:"nodes"`
	Edges int `json:"edges"`
}

// Scenario defines a benchmark profile with its own data and query.
type Scenario struct {
	Name        string
	Description string
	Data        DataSize
	Setup       func(db *sql.DB) error
	Teardown    func(db *sql.DB) error
	QueryFn     func(maxNodeID int) QueryFunc
}

// scenarios is the ordered registry of all available scenarios.
var scenarios = []Scenario{
	scenarioPing(),
	scenarioPointRead(),
	scenarioOneHop(),
	scenarioTwoHop(),
	scenarioFanOut(),
	scenarioEdgeCreate(),
	scenarioEdgeCreateWithProps(),
}

// scenarioNames returns a comma-separated list for help text.
func scenarioNames() string {
	names := ""
	for i, s := range scenarios {
		if i > 0 {
			names += ", "
		}
		names += s.Name
	}
	return names + ", all"
}

// findScenario returns the scenario with the given name, or nil.
func findScenario(name string) *Scenario {
	for i := range scenarios {
		if scenarios[i].Name == name {
			return &scenarios[i]
		}
	}
	return nil
}

func scenarioPing() Scenario {
	return Scenario{
		Name:        "ping",
		Description: "Baseline transport: RETURN 1 AS x (no data)",
		Data:        DataSize{Nodes: 0, Edges: 0},
		Setup:       func(db *sql.DB) error { return nil },
		Teardown:    func(db *sql.DB) error { return nil },
		QueryFn: func(maxNodeID int) QueryFunc {
			return func(db *sql.DB, rng *rand.Rand) error {
				ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
				defer cancel()
				rows, err := db.QueryContext(ctx, "RETURN 1 AS x")
				if err != nil {
					return err
				}
				defer rows.Close()
				for rows.Next() {
					var x int
					if err := rows.Scan(&x); err != nil {
						return err
					}
				}
				return rows.Err()
			}
		},
	}
}

func scenarioPointRead() Scenario {
	const numNodes = 500

	return Scenario{
		Name:        "point_read",
		Description: "Property lookup: MATCH by lt_id (500 nodes)",
		Data:        DataSize{Nodes: numNodes, Edges: 0},
		Setup: func(db *sql.DB) error {
			return batchCreateNodes(db, "LT_Person", numNodes)
		},
		Teardown: func(db *sql.DB) error {
			return deleteByLabel(db, "LT_Person")
		},
		QueryFn: func(maxNodeID int) QueryFunc {
			return func(db *sql.DB, rng *rand.Rand) error {
				id := rng.IntN(numNodes)
				ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
				defer cancel()
				rows, err := db.QueryContext(ctx, fmt.Sprintf(
					"MATCH (p:LT_Person {lt_id: %d}) RETURN p.name, p.age", id))
				if err != nil {
					return err
				}
				defer rows.Close()
				return drainRows(rows)
			}
		},
	}
}

func scenarioOneHop() Scenario {
	const numNodes = 1000
	const edgesPerNode = 3
	const totalEdges = numNodes * edgesPerNode

	return Scenario{
		Name:        "one_hop",
		Description: "Single-hop traversal: person -[:LT_KNOWS]-> person (1K nodes, 3K edges)",
		Data:        DataSize{Nodes: numNodes, Edges: totalEdges},
		Setup: func(db *sql.DB) error {
			if err := batchCreateNodes(db, "LT_Person", numNodes); err != nil {
				return err
			}
			return batchCreateEdges(db, "LT_Person", "LT_KNOWS", "LT_Person",
				numNodes, numNodes, edgesPerNode)
		},
		Teardown: func(db *sql.DB) error {
			_ = deleteEdgesByType(db, "LT_KNOWS")
			return deleteByLabel(db, "LT_Person")
		},
		QueryFn: func(maxNodeID int) QueryFunc {
			return func(db *sql.DB, rng *rand.Rand) error {
				id := rng.IntN(numNodes)
				ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
				defer cancel()
				rows, err := db.QueryContext(ctx, fmt.Sprintf(
					"MATCH (a:LT_Person {lt_id: %d})-[:LT_KNOWS]->(b) RETURN b.name, b.age", id))
				if err != nil {
					return err
				}
				defer rows.Close()
				return drainRows(rows)
			}
		},
	}
}

func scenarioTwoHop() Scenario {
	const numNodes = 2000
	const edgesPerNode = 4
	const totalEdges = numNodes * edgesPerNode

	return Scenario{
		Name:        "two_hop",
		Description: "Two-hop traversal with DISTINCT: person->person->person (2K nodes, 8K edges)",
		Data:        DataSize{Nodes: numNodes, Edges: totalEdges},
		Setup: func(db *sql.DB) error {
			if err := batchCreateNodes(db, "LT_Person", numNodes); err != nil {
				return err
			}
			return batchCreateEdges(db, "LT_Person", "LT_KNOWS", "LT_Person",
				numNodes, numNodes, edgesPerNode)
		},
		Teardown: func(db *sql.DB) error {
			_ = deleteEdgesByType(db, "LT_KNOWS")
			return deleteByLabel(db, "LT_Person")
		},
		QueryFn: func(maxNodeID int) QueryFunc {
			return func(db *sql.DB, rng *rand.Rand) error {
				id := rng.IntN(numNodes)
				ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
				defer cancel()
				rows, err := db.QueryContext(ctx, fmt.Sprintf(
					"MATCH (a:LT_Person {lt_id: %d})-[:LT_KNOWS]->(b)-[:LT_KNOWS]->(c) RETURN DISTINCT c.name, c.lt_id LIMIT 20", id))
				if err != nil {
					return err
				}
				defer rows.Close()
				return drainRows(rows)
			}
		},
	}
}

// edgeCreateNumNodes is the source/target pool for edge_create* scenarios.
// Sized to match point_read's pool — known to seed cleanly through the
// single-connection batchCreateNodes path — while still giving random pair
// selection plenty of variety.  2000+ has been observed to hit a periodic
// single-connection write stall on this build that is unrelated to the
// edge-merge bug under investigation; the smaller pool keeps the scenario
// usable until that separate issue is triaged.
const edgeCreateNumNodes = 500

// edgeCreateRelType is the relationship type used by edge_create* scenarios.
// Distinct from LT_KNOWS so teardown does not interfere with one_hop/two_hop
// runs that may share the LT_Person pool in mixed sequences.
const edgeCreateRelType = "LT_KNOWS_BENCH"

// scenarioEdgeCreate exercises the MATCH+CREATE-edge path that the msft seed
// pipeline uses (`MATCH (a:L {k:?}), (b:L {k:?}) CREATE (a)-[:R]->(b)`). This
// shape currently runs under the per-graph EXCLUSIVE write lock at
// `quic_connection_handler.zig:3387` for the full duration of MATCH endpoint
// resolve + CREATE + WAL fsync, so concurrent workers serialize. The scenario
// is the first-class regression vehicle for that fix.
func scenarioEdgeCreate() Scenario {
	return Scenario{
		Name:        "edge_create",
		Description: "Concurrent MATCH+CREATE edges by node_id (2K nodes, write-heavy, no edge props)",
		Data:        DataSize{Nodes: edgeCreateNumNodes, Edges: 0},
		Setup: func(db *sql.DB) error {
			return batchCreateNodes(db, "LT_Person", edgeCreateNumNodes)
		},
		Teardown: func(db *sql.DB) error {
			_ = deleteEdgesByType(db, edgeCreateRelType)
			return deleteByLabel(db, "LT_Person")
		},
		QueryFn: func(maxNodeID int) QueryFunc {
			return func(db *sql.DB, rng *rand.Rand) error {
				src := rng.IntN(edgeCreateNumNodes)
				dst := rng.IntN(edgeCreateNumNodes)
				if dst == src {
					dst = (dst + 1) % edgeCreateNumNodes
				}
				ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
				defer cancel()
				_, err := db.ExecContext(ctx, fmt.Sprintf(
					"MATCH (a:LT_Person {lt_id: %d}), (b:LT_Person {lt_id: %d}) CREATE (a)-[:%s]->(b)",
					src, dst, edgeCreateRelType))
				return err
			}
		},
	}
}

// scenarioEdgeCreateWithProps mirrors the exact statement shape the msft seed
// pipeline emits — endpoint MATCH by `node_id` plus a CREATE that sets a
// fixed `link_id` + `snapshot_id` and three string properties on the edge.
// This is the closest in-tree benchmark to the msft chunk_size=8/workers=8
// workload the user reported (~18s first-chunk stall).
func scenarioEdgeCreateWithProps() Scenario {
	return Scenario{
		Name:        "edge_create_with_props",
		Description: "Concurrent MATCH+CREATE edges with msft-style props (link_id, snapshot_id, 3 strings)",
		Data:        DataSize{Nodes: edgeCreateNumNodes, Edges: 0},
		Setup: func(db *sql.DB) error {
			return batchCreateNodes(db, "LT_Person", edgeCreateNumNodes)
		},
		Teardown: func(db *sql.DB) error {
			_ = deleteEdgesByType(db, edgeCreateRelType)
			return deleteByLabel(db, "LT_Person")
		},
		QueryFn: func(maxNodeID int) QueryFunc {
			return func(db *sql.DB, rng *rand.Rand) error {
				src := rng.IntN(edgeCreateNumNodes)
				dst := rng.IntN(edgeCreateNumNodes)
				if dst == src {
					dst = (dst + 1) % edgeCreateNumNodes
				}
				// Per-call link_id keeps each edge unique without coordination.
				linkID := fmt.Sprintf("lk-%d-%d-%d", src, dst, rng.Int64())
				ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
				defer cancel()
				_, err := db.ExecContext(ctx, fmt.Sprintf(
					"MATCH (a:LT_Person {lt_id: %d}), (b:LT_Person {lt_id: %d}) "+
						"CREATE (a)-[:%s {link_id: '%s', snapshot_id: 'snap-bench', "+
						"prop_role: 'reader', prop_status: 'active', prop_kind: 'bench'}]->(b)",
					src, dst, edgeCreateRelType, linkID))
				return err
			}
		},
	}
}

func scenarioFanOut() Scenario {
	const numPersons = 2000
	const numCompanies = 200
	const knowsPerPerson = 3
	const totalKnows = numPersons * knowsPerPerson
	const totalWorksAt = numPersons

	return Scenario{
		Name:        "fan_out",
		Description: "Cross-type 2-hop: person->person->company (2.2K nodes, 8K edges)",
		Data:        DataSize{Nodes: numPersons + numCompanies, Edges: totalKnows + totalWorksAt},
		Setup: func(db *sql.DB) error {
			fmt.Fprintf(os.Stderr, "  Setting up fan_out scenario...\n")
			if err := batchCreateNodes(db, "LT_Person", numPersons); err != nil {
				return err
			}
			if err := batchCreateCompanies(db, numCompanies); err != nil {
				return err
			}
			if err := batchCreateEdges(db, "LT_Person", "LT_KNOWS", "LT_Person",
				numPersons, numPersons, knowsPerPerson); err != nil {
				return err
			}
			return batchCreateWorksAt(db, numPersons, numCompanies)
		},
		Teardown: func(db *sql.DB) error {
			_ = deleteEdgesByType(db, "LT_WORKS_AT")
			_ = deleteEdgesByType(db, "LT_KNOWS")
			_ = deleteByLabel(db, "LT_Company")
			return deleteByLabel(db, "LT_Person")
		},
		QueryFn: func(maxNodeID int) QueryFunc {
			return func(db *sql.DB, rng *rand.Rand) error {
				id := rng.IntN(numPersons)
				ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
				defer cancel()
				rows, err := db.QueryContext(ctx, fmt.Sprintf(
					"MATCH (a:LT_Person {lt_id: %d})-[:LT_KNOWS]->(b)-[:LT_WORKS_AT]->(c:LT_Company) RETURN b.name, c.name LIMIT 20", id))
				if err != nil {
					return err
				}
				defer rows.Close()
				return drainRows(rows)
			}
		},
	}
}
