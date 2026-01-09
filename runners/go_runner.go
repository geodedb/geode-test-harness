package main

import (
	"database/sql"
	"encoding/json"
	"flag"
	"fmt"
	"io/ioutil"
	"os"
	"sort"
	"time"

	"gopkg.in/yaml.v3"

	_ "gitlab.com/devnw/geode/geode/clients/go/geode"
)

type TestSpec struct {
	Version     string                   `yaml:"version"`
	Name        string                   `yaml:"name"`
	Description string                   `yaml:"description"`
	Setup       []map[string]interface{} `yaml:"setup"`
	Tests       []Test                   `yaml:"tests"`
	Cleanup     []map[string]interface{} `yaml:"cleanup"`
}

type Test struct {
	Name        string                   `yaml:"name"`
	Description string                   `yaml:"description"`
	Query       string                   `yaml:"query"`
	Params      map[string]interface{}   `yaml:"params"`
	Expect      map[string]interface{}   `yaml:"expect"`
	Steps       []map[string]interface{} `yaml:"steps"`
	Skip        bool                     `yaml:"skip"`
	TimeoutMS   int                      `yaml:"timeout_ms"`
	ExpectError bool                     `yaml:"expect_error"`
}

type TestResult struct {
	Test       string                 `json:"test"`
	Status     string                 `json:"status"`
	Error      string                 `json:"error,omitempty"`
	Result     map[string]interface{} `json:"result,omitempty"`
	DurationMS float64                `json:"duration_ms"`
}

type Summary struct {
	Total   int `json:"total"`
	Passed  int `json:"passed"`
	Failed  int `json:"failed"`
	Errors  int `json:"errors"`
	Skipped int `json:"skipped"`
}

type Output struct {
	Summary Summary      `json:"summary"`
	Results []TestResult `json:"results"`
}

type Runner struct {
	db      *sql.DB
	tx      *sql.Tx
	verbose bool
}

func main() {
	specPath := flag.String("spec", "", "Test specification file")
	server := flag.String("server", "localhost:8443", "Server address")
	jsonOutput := flag.Bool("json", false, "Output JSON")
	verbose := flag.Bool("verbose", false, "Verbose output")
	flag.Parse()

	if *specPath == "" {
		fmt.Fprintln(os.Stderr, "ERROR: --spec is required")
		os.Exit(2)
	}

	// quic-go will return an error if the UDP receive buffer cannot be increased.
	// In constrained CI environments this is expected, so disable the fatal check.
	_ = os.Setenv("QUIC_GO_DISABLE_RECEIVE_BUFFER_WARNING", "true")

	// Load spec
	data, err := ioutil.ReadFile(*specPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "ERROR: Failed to read spec: %v\n", err)
		os.Exit(2)
	}

	var spec TestSpec
	if err := yaml.Unmarshal(data, &spec); err != nil {
		fmt.Fprintf(os.Stderr, "ERROR: Failed to parse spec: %v\n", err)
		os.Exit(2)
	}

	// Create DSN for QUIC connection
	dsn := fmt.Sprintf("quic:%s?skip_verify=true", *server)

	// Open database connection
	db, err := sql.Open("geode", dsn)
	if err != nil {
		fmt.Fprintf(os.Stderr, "ERROR: Failed to open connection: %v\n", err)
		os.Exit(3)
	}
	defer db.Close()

	runner := &Runner{
		db:      db,
		verbose: *verbose,
	}

	// Run setup
	if err := runner.runSetup(spec.Setup); err != nil {
		fmt.Fprintf(os.Stderr, "ERROR: Setup failed: %v\n", err)
		os.Exit(3)
	}

	// Run tests
	results := []TestResult{}
	for _, test := range spec.Tests {
		if test.Skip {
			results = append(results, TestResult{
				Test:   test.Name,
				Status: "skipped",
			})
			continue
		}

		if *verbose {
			fmt.Fprintf(os.Stderr, "Running test: %s\n", test.Name)
		}

		result := runner.runTest(test)
		result.Test = test.Name
		results = append(results, result)
	}

	// Run cleanup
	if err := runner.runCleanup(spec.Cleanup); err != nil {
		fmt.Fprintf(os.Stderr, "WARNING: Cleanup failed: %v\n", err)
	}

	// Calculate summary
	summary := Summary{Total: len(results)}
	for _, r := range results {
		switch r.Status {
		case "passed":
			summary.Passed++
		case "failed":
			summary.Failed++
		case "error":
			summary.Errors++
		case "skipped":
			summary.Skipped++
		}
	}

	output := Output{
		Summary: summary,
		Results: results,
	}

	if *jsonOutput {
		data, _ := json.MarshalIndent(output, "", "  ")
		fmt.Println(string(data))
	} else {
		fmt.Printf("Tests: %d\n", summary.Total)
		fmt.Printf("Passed: %d\n", summary.Passed)
		fmt.Printf("Failed: %d\n", summary.Failed)
		fmt.Printf("Errors: %d\n", summary.Errors)
	}

	os.Exit(0)
}

func (r *Runner) runSetup(setup []map[string]interface{}) error {
	for _, step := range setup {
		if stepType, ok := step["type"].(string); ok && stepType == "query" {
			if text, ok := step["text"].(string); ok {
				if _, err := r.db.Exec(text); err != nil {
					return err
				}
			}
		}
	}
	return nil
}

func (r *Runner) runCleanup(cleanup []map[string]interface{}) error {
	for _, step := range cleanup {
		if stepType, ok := step["type"].(string); ok && stepType == "query" {
			if text, ok := step["text"].(string); ok {
				if _, err := r.db.Exec(text); err != nil {
					// Log but don't fail on cleanup errors
					if r.verbose {
						fmt.Fprintf(os.Stderr, "Cleanup warning: %v\n", err)
					}
				}
			}
		}
	}
	return nil
}

func (r *Runner) runTest(test Test) TestResult {
	start := time.Now()

	// Simple query test
	if test.Query != "" {
		result, err := r.executeQuery(test.Query, test.Params, test.Expect)
		duration := time.Since(start).Milliseconds()

		if err != nil {
			if test.ExpectError {
				return TestResult{
					Status:     "passed",
					DurationMS: float64(duration),
					Result:     map[string]interface{}{"error_expected": err.Error()},
				}
			}
			return TestResult{
				Status:     "error",
				Error:      err.Error(),
				DurationMS: float64(duration),
			}
		}

		// Validate expectations
		if err := r.validateExpectations(result, test.Expect); err != nil {
			return TestResult{
				Status:     "failed",
				Error:      err.Error(),
				Result:     result,
				DurationMS: float64(duration),
			}
		}

		return TestResult{
			Status:     "passed",
			Result:     result,
			DurationMS: float64(duration),
		}
	}

	// Step-based test
	if len(test.Steps) > 0 {
		err := r.executeSteps(test.Steps)
		duration := time.Since(start).Milliseconds()

		if err != nil {
			if test.ExpectError {
				return TestResult{
					Status:     "passed",
					DurationMS: float64(duration),
					Result:     map[string]interface{}{"error_expected": err.Error()},
				}
			}
			return TestResult{
				Status:     "error",
				Error:      err.Error(),
				DurationMS: float64(duration),
			}
		}

		return TestResult{
			Status:     "passed",
			DurationMS: float64(duration),
		}
	}

	return TestResult{
		Status: "error",
		Error:  "Test must have 'query' or 'steps'",
	}
}

func (r *Runner) executeQuery(query string, params map[string]interface{}, expect map[string]interface{}) (map[string]interface{}, error) {
	// Execute query
	rows, err := r.db.Query(query, convertParams(params)...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	// Get column names
	columns, err := rows.Columns()
	if err != nil {
		return nil, err
	}

	// Read all rows
	data := []map[string]interface{}{}
	for rows.Next() {
		// Create slice for scanning
		values := make([]interface{}, len(columns))
		valuePtrs := make([]interface{}, len(columns))
		for i := range values {
			valuePtrs[i] = &values[i]
		}

		if err := rows.Scan(valuePtrs...); err != nil {
			return nil, err
		}

		// Build row map
		row := make(map[string]interface{})
		for i, col := range columns {
			row[col] = values[i]
		}
		data = append(data, row)
	}

	if err := rows.Err(); err != nil {
		return nil, err
	}

	return map[string]interface{}{
		"rows":    len(data),
		"columns": columns,
		"data":    data,
	}, nil
}

func (r *Runner) executeSteps(steps []map[string]interface{}) error {
	for _, step := range steps {
		stepType, ok := step["type"].(string)
		if !ok {
			continue
		}

		expectError := false
		if ee, ok := step["expect_error"].(bool); ok {
			expectError = ee
		}

		var err error
		switch stepType {
		case "begin":
			r.tx, err = r.db.Begin()

		case "commit":
			if r.tx != nil {
				err = r.tx.Commit()
				r.tx = nil
			}

		case "rollback":
			if r.tx != nil {
				err = r.tx.Rollback()
				r.tx = nil
			}

		case "query":
			text, _ := step["text"].(string)
			params, _ := step["params"].(map[string]interface{})
			expect, _ := step["expect"].(map[string]interface{})

			result, qerr := r.executeQuery(text, params, expect)
			if qerr != nil {
				err = qerr
			} else if expect != nil {
				err = r.validateExpectations(result, expect)
			}

		case "connect", "disconnect":
			// No-op for Go SQL driver (managed automatically)

		default:
			if r.verbose {
				fmt.Fprintf(os.Stderr, "Unknown step type: %s\n", stepType)
			}
		}

		if err != nil && !expectError {
			return err
		}
	}

	return nil
}

func (r *Runner) validateExpectations(result map[string]interface{}, expect map[string]interface{}) error {
	if expect == nil {
		return nil
	}

	// Check row count
	if expectedRows, ok := expect["rows"].(int); ok {
		actualRows := result["rows"].(int)
		if actualRows != expectedRows {
			return fmt.Errorf("expected %d rows, got %d", expectedRows, actualRows)
		}
	}

	// Check min rows
	if minRows, ok := expect["min_rows"].(int); ok {
		actualRows := result["rows"].(int)
		if actualRows < minRows {
			return fmt.Errorf("expected at least %d rows, got %d", minRows, actualRows)
		}
	}

	// Check max rows
	if maxRows, ok := expect["max_rows"].(int); ok {
		actualRows := result["rows"].(int)
		if actualRows > maxRows {
			return fmt.Errorf("expected at most %d rows, got %d", maxRows, actualRows)
		}
	}

	// Check columns
	if expectedCols, ok := expect["columns"].([]interface{}); ok {
		actualCols := result["columns"].([]string)
		if len(expectedCols) != len(actualCols) {
			return fmt.Errorf("expected %d columns, got %d", len(expectedCols), len(actualCols))
		}
		for i, expCol := range expectedCols {
			if expCol.(string) != actualCols[i] {
				return fmt.Errorf("expected column %d to be %s, got %s", i, expCol, actualCols[i])
			}
		}
	}

	// Check values
	if expectedValues, ok := expect["values"].([]interface{}); ok {
		data := result["data"].([]map[string]interface{})
		for i, expRowInterface := range expectedValues {
			if i >= len(data) {
				return fmt.Errorf("expected row %d missing", i)
			}

			expRow, ok := expRowInterface.(map[string]interface{})
			if !ok {
				continue
			}

			actualRow := data[i]
			for key, expVal := range expRow {
				actualVal, ok := actualRow[key]
				if !ok {
					return fmt.Errorf("expected column '%s' missing in row %d", key, i)
				}

				if !compareValues(actualVal, expVal) {
					return fmt.Errorf("row %d: expected %s=%v, got %v", i, key, expVal, actualVal)
				}
			}
		}
	}

	return nil
}

func compareValues(actual, expected interface{}) bool {
	// Handle NULL
	if expected == nil {
		return actual == nil
	}
	if actual == nil {
		return false
	}

	// Type conversions
	switch exp := expected.(type) {
	case int:
		switch act := actual.(type) {
		case int:
			return act == exp
		case int64:
			return act == int64(exp)
		case float64:
			return act == float64(exp)
		}
	case int64:
		switch act := actual.(type) {
		case int:
			return int64(act) == exp
		case int64:
			return act == exp
		case float64:
			return act == float64(exp)
		}
	case float64:
		switch act := actual.(type) {
		case int:
			return float64(act) == exp
		case int64:
			return float64(act) == exp
		case float64:
			return act == exp
		}
	case string:
		if actStr, ok := actual.(string); ok {
			return actStr == exp
		}
		// Try converting actual to string
		return fmt.Sprintf("%v", actual) == exp
	case bool:
		if actBool, ok := actual.(bool); ok {
			return actBool == exp
		}
	}

	// Fallback: string comparison
	return fmt.Sprintf("%v", actual) == fmt.Sprintf("%v", expected)
}

func convertParams(params map[string]interface{}) []interface{} {
	if len(params) == 0 {
		return nil
	}

	keys := make([]string, 0, len(params))
	for k := range params {
		keys = append(keys, k)
	}
	sort.Strings(keys)

	args := make([]interface{}, 0, len(keys))
	for _, k := range keys {
		args = append(args, sql.Named(k, params[k]))
	}
	return args
}
