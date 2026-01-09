//! Rust test runner for Geode client library.

use anyhow::{Context, Result};
use clap::Parser;
use geode_client::{Client, Connection};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::time::Instant;

#[derive(Parser, Debug)]
#[command(name = "rust_runner")]
#[command(about = "Rust test runner for Geode client library")]
struct Args {
    /// Path to test specification file
    #[arg(long)]
    spec: PathBuf,

    /// Server address (host:port)
    #[arg(long, default_value = "localhost:8443")]
    server: String,

    /// Output JSON format
    #[arg(long)]
    json: bool,

    /// Verbose output
    #[arg(long)]
    verbose: bool,
}

#[derive(Debug, Deserialize)]
struct TestSpec {
    #[serde(default)]
    version: String,
    #[serde(default)]
    name: String,
    #[serde(default)]
    description: String,
    #[serde(default)]
    setup: Vec<StepDef>,
    tests: Vec<Test>,
    #[serde(default)]
    cleanup: Vec<StepDef>,
}

#[derive(Debug, Deserialize)]
struct Test {
    name: String,
    #[serde(default)]
    description: String,
    #[serde(default)]
    query: String,
    #[serde(default)]
    params: HashMap<String, serde_json::Value>,
    #[serde(default)]
    expect: Expectation,
    #[serde(default)]
    steps: Vec<StepDef>,
    #[serde(default)]
    skip: bool,
    #[serde(default)]
    timeout_ms: Option<u64>,
    #[serde(default)]
    expect_error: bool,
}

#[derive(Debug, Deserialize, Default)]
struct StepDef {
    #[serde(rename = "type")]
    step_type: String,
    #[serde(default)]
    text: String,
    #[serde(default)]
    params: HashMap<String, serde_json::Value>,
    #[serde(default)]
    expect: Expectation,
    #[serde(default)]
    expect_error: bool,
}

#[derive(Debug, Deserialize, Default)]
struct Expectation {
    #[serde(default)]
    rows: Option<usize>,
    #[serde(default)]
    min_rows: Option<usize>,
    #[serde(default)]
    max_rows: Option<usize>,
    #[serde(default)]
    columns: Option<Vec<String>>,
    #[serde(default)]
    values: Option<Vec<HashMap<String, serde_json::Value>>>,
}

#[derive(Debug, Serialize)]
struct TestResult {
    test: String,
    status: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    error: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    result: Option<QueryResult>,
    duration_ms: f64,
}

#[derive(Debug, Serialize)]
struct QueryResult {
    rows: usize,
    columns: Vec<String>,
    data: Vec<HashMap<String, serde_json::Value>>,
}

#[derive(Debug, Serialize)]
struct Summary {
    total: usize,
    passed: usize,
    failed: usize,
    errors: usize,
    skipped: usize,
}

#[derive(Debug, Serialize)]
struct Output {
    summary: Summary,
    results: Vec<TestResult>,
}

struct Runner {
    client: Client,
    connection: Arc<Mutex<Option<Connection>>>,
    verbose: bool,
}

impl Runner {
    fn new(server: &str, verbose: bool) -> Self {
        let parts: Vec<&str> = server.split(':').collect();
        let host = parts[0];
        let port: u16 = parts.get(1).unwrap_or(&"8443").parse().unwrap_or(8443);

        let client = Client::new(host, port).skip_verify(true);

        Self {
            client,
            connection: Arc::new(Mutex::new(None)),
            verbose,
        }
    }

    async fn ensure_connection(&mut self) -> Result<()> {
        let mut conn_guard = self.connection.lock().unwrap();
        if conn_guard.is_none() {
            let client = self.client.clone();
            // Connect is async, so call it directly
            let connection = client.connect().await?;
            *conn_guard = Some(connection);
        }
        Ok(())
    }

    async fn run_setup(&mut self, setup: &[StepDef]) -> Result<()> {
        for step in setup {
            if step.step_type == "query" && !step.text.is_empty() {
                self.ensure_connection().await?;

                // Take connection out, use it, put it back
                let mut conn_opt = {
                    let mut guard = self.connection.lock().unwrap();
                    guard.take()
                };

                if let Some(mut conn) = conn_opt {
                    let query_text = step.text.clone();
                    conn = tokio::task::spawn_blocking(move || {
                        conn.query_sync(&query_text, None)?;
                        Ok::<_, anyhow::Error>(conn)
                    })
                    .await
                    .map_err(|e| anyhow::anyhow!("Spawn error: {}", e))??;

                    // Put connection back
                    let mut guard = self.connection.lock().unwrap();
                    *guard = Some(conn);
                }
            }
        }
        Ok(())
    }

    async fn run_cleanup(&mut self, cleanup: &[StepDef]) -> Result<()> {
        for step in cleanup {
            if step.step_type == "query" && !step.text.is_empty() {
                if let Err(e) = self.ensure_connection().await {
                    if self.verbose {
                        eprintln!("Cleanup connection error: {}", e);
                    }
                    continue;
                }

                // Take connection out, use it, put it back
                let conn_opt = {
                    let mut guard = self.connection.lock().unwrap();
                    guard.take()
                };

                if let Some(mut conn) = conn_opt {
                    let query_text = step.text.clone();
                    let result = tokio::task::spawn_blocking(move || {
                        conn.query_sync(&query_text, None)?;
                        Ok::<_, anyhow::Error>(conn)
                    })
                    .await;

                    match result {
                        Ok(Ok(c)) => {
                            // Put connection back
                            let mut guard = self.connection.lock().unwrap();
                            *guard = Some(c);
                        }
                        Ok(Err(e)) => {
                            if self.verbose {
                                eprintln!("Cleanup warning: {}", e);
                            }
                            // Connection is lost, don't put it back
                        }
                        Err(e) => {
                            if self.verbose {
                                eprintln!("Cleanup spawn error: {}", e);
                            }
                            // Connection is lost, don't put it back
                        }
                    }
                }
            }
        }
        Ok(())
    }

    async fn run_test(&mut self, test: &Test) -> TestResult {
        let start = Instant::now();

        // Simple query test
        if !test.query.is_empty() {
            match self.execute_query(&test.query, &test.params, &test.expect).await {
                Ok(result) => {
                    let duration = start.elapsed().as_secs_f64() * 1000.0;

                    // Validate expectations
                    if let Err(e) = self.validate_expectations(&result, &test.expect) {
                        return TestResult {
                            test: test.name.clone(),
                            status: "failed".to_string(),
                            error: Some(e.to_string()),
                            result: Some(result),
                            duration_ms: duration,
                        };
                    }

                    TestResult {
                        test: test.name.clone(),
                        status: "passed".to_string(),
                        error: None,
                        result: Some(result),
                        duration_ms: duration,
                    }
                }
                Err(e) => {
                    let duration = start.elapsed().as_secs_f64() * 1000.0;
                    if test.expect_error {
                        TestResult {
                            test: test.name.clone(),
                            status: "passed".to_string(),
                            error: None,
                            result: None,
                            duration_ms: duration,
                        }
                    } else {
                        TestResult {
                            test: test.name.clone(),
                            status: "error".to_string(),
                            error: Some(e.to_string()),
                            result: None,
                            duration_ms: duration,
                        }
                    }
                }
            }
        }
        // Step-based test
        else if !test.steps.is_empty() {
            match self.execute_steps(&test.steps).await {
                Ok(_) => {
                    let duration = start.elapsed().as_secs_f64() * 1000.0;
                    TestResult {
                        test: test.name.clone(),
                        status: "passed".to_string(),
                        error: None,
                        result: None,
                        duration_ms: duration,
                    }
                }
                Err(e) => {
                    let duration = start.elapsed().as_secs_f64() * 1000.0;
                    if test.expect_error {
                        TestResult {
                            test: test.name.clone(),
                            status: "passed".to_string(),
                            error: None,
                            result: None,
                            duration_ms: duration,
                        }
                    } else {
                        TestResult {
                            test: test.name.clone(),
                            status: "error".to_string(),
                            error: Some(e.to_string()),
                            result: None,
                            duration_ms: duration,
                        }
                    }
                }
            }
        } else {
            TestResult {
                test: test.name.clone(),
                status: "error".to_string(),
                error: Some("Test must have 'query' or 'steps'".to_string()),
                result: None,
                duration_ms: 0.0,
            }
        }
    }

    async fn execute_query(
        &mut self,
        query: &str,
        params: &HashMap<String, serde_json::Value>,
        _expect: &Expectation,
    ) -> Result<QueryResult> {
        self.ensure_connection().await?;

        // Take connection out, use it, put it back
        let mut conn_opt = {
            let mut guard = self.connection.lock().unwrap();
            guard.take()
        };

        let mut conn = conn_opt.context("No active connection")?;

        // Convert params to Option<HashMap<String, serde_json::Value>>
        let params_opt = if params.is_empty() {
            None
        } else {
            Some(params.clone())
        };

        let query_str = query.to_string();
        let (page, updated_conn) = tokio::task::spawn_blocking(move || {
            let page = conn.query_sync(&query_str, params_opt)?;
            Ok::<_, anyhow::Error>((page, conn))
        })
        .await
        .map_err(|e| anyhow::anyhow!("Spawn error: {}", e))??;

        conn = updated_conn;

        // Extract column names
        let columns: Vec<String> = page.columns.iter().map(|c| c.name.clone()).collect();

        // Extract row data
        let mut data = Vec::new();
        for row in &page.rows {
            let mut row_map = HashMap::new();
            for col in &page.columns {
                if let Some(value) = row.get(&col.name) {
                    // Convert to serde_json::Value
                    row_map.insert(col.name.clone(), value.to_json());
                }
            }
            data.push(row_map);
        }

        // Put connection back
        let mut guard = self.connection.lock().unwrap();
        *guard = Some(conn);

        Ok(QueryResult {
            rows: page.rows.len(),
            columns,
            data,
        })
    }

    async fn execute_steps(&mut self, steps: &[StepDef]) -> Result<()> {
        for step in steps {
            let expect_error = step.expect_error;

            let result = match step.step_type.as_str() {
                "connect" => {
                    let client = self.client.clone();
                    let connection = client.connect().await?;

                    let mut guard = self.connection.lock().unwrap();
                    *guard = Some(connection);
                    Ok(())
                }
                "disconnect" => {
                    let conn_opt = {
                        let mut guard = self.connection.lock().unwrap();
                        guard.take()
                    };

                    if let Some(mut conn) = conn_opt {
                        tokio::task::spawn_blocking(move || conn.close())
                            .await
                            .map_err(|e| anyhow::anyhow!("Spawn error: {}", e))??;
                    }
                    Ok(())
                }
                "begin" => {
                    self.ensure_connection().await?;

                    let mut conn_opt = {
                        let mut guard = self.connection.lock().unwrap();
                        guard.take()
                    };

                    if let Some(mut conn) = conn_opt {
                        conn = tokio::task::spawn_blocking(move || {
                            conn.begin()?;
                            Ok::<_, anyhow::Error>(conn)
                        })
                        .await
                        .map_err(|e| anyhow::anyhow!("Spawn error: {}", e))??;

                        let mut guard = self.connection.lock().unwrap();
                        *guard = Some(conn);
                    }
                    Ok(())
                }
                "commit" => {
                    let mut conn_opt = {
                        let mut guard = self.connection.lock().unwrap();
                        guard.take()
                    };

                    if let Some(mut conn) = conn_opt {
                        conn = tokio::task::spawn_blocking(move || {
                            conn.commit()?;
                            Ok::<_, anyhow::Error>(conn)
                        })
                        .await
                        .map_err(|e| anyhow::anyhow!("Spawn error: {}", e))??;

                        let mut guard = self.connection.lock().unwrap();
                        *guard = Some(conn);
                    }
                    Ok(())
                }
                "rollback" => {
                    let mut conn_opt = {
                        let mut guard = self.connection.lock().unwrap();
                        guard.take()
                    };

                    if let Some(mut conn) = conn_opt {
                        conn = tokio::task::spawn_blocking(move || {
                            conn.rollback()?;
                            Ok::<_, anyhow::Error>(conn)
                        })
                        .await
                        .map_err(|e| anyhow::anyhow!("Spawn error: {}", e))??;

                        let mut guard = self.connection.lock().unwrap();
                        *guard = Some(conn);
                    }
                    Ok(())
                }
                "query" => {
                    let result = self
                        .execute_query(&step.text, &step.params, &step.expect)
                        .await?;
                    self.validate_expectations(&result, &step.expect)?;
                    Ok(())
                }
                _ => {
                    if self.verbose {
                        eprintln!("Unknown step type: {}", step.step_type);
                    }
                    Ok(())
                }
            };

            if let Err(e) = result {
                if !expect_error {
                    return Err(e);
                }
            }
        }

        Ok(())
    }

    fn validate_expectations(&self, result: &QueryResult, expect: &Expectation) -> Result<()> {
        // Check row count
        if let Some(expected_rows) = expect.rows {
            if result.rows != expected_rows {
                anyhow::bail!(
                    "Expected {} rows, got {}",
                    expected_rows,
                    result.rows
                );
            }
        }

        // Check min rows
        if let Some(min_rows) = expect.min_rows {
            if result.rows < min_rows {
                anyhow::bail!("Expected at least {} rows, got {}", min_rows, result.rows);
            }
        }

        // Check max rows
        if let Some(max_rows) = expect.max_rows {
            if result.rows > max_rows {
                anyhow::bail!("Expected at most {} rows, got {}", max_rows, result.rows);
            }
        }

        // Check columns
        if let Some(ref expected_cols) = expect.columns {
            if result.columns.len() != expected_cols.len() {
                anyhow::bail!(
                    "Expected {} columns, got {}",
                    expected_cols.len(),
                    result.columns.len()
                );
            }
            for (i, exp_col) in expected_cols.iter().enumerate() {
                if &result.columns[i] != exp_col {
                    anyhow::bail!(
                        "Expected column {} to be {}, got {}",
                        i,
                        exp_col,
                        result.columns[i]
                    );
                }
            }
        }

        // Check values
        if let Some(ref expected_values) = expect.values {
            for (i, expected_row) in expected_values.iter().enumerate() {
                if i >= result.data.len() {
                    anyhow::bail!("Expected row {} missing", i);
                }

                let actual_row = &result.data[i];
                for (key, expected_val) in expected_row {
                    let actual_val = actual_row
                        .get(key)
                        .ok_or_else(|| anyhow::anyhow!("Expected column '{}' missing in row {}", key, i))?;

                    if !values_equal(actual_val, expected_val) {
                        anyhow::bail!(
                            "Row {}: expected {}={:?}, got {:?}",
                            i,
                            key,
                            expected_val,
                            actual_val
                        );
                    }
                }
            }
        }

        Ok(())
    }
}

fn values_equal(actual: &serde_json::Value, expected: &serde_json::Value) -> bool {
    use serde_json::Value;

    match (actual, expected) {
        (Value::Null, Value::Null) => true,
        (Value::Bool(a), Value::Bool(e)) => a == e,
        (Value::Number(a), Value::Number(e)) => {
            // Try to compare as i64 first, then f64
            if let (Some(a_int), Some(e_int)) = (a.as_i64(), e.as_i64()) {
                a_int == e_int
            } else if let (Some(a_f), Some(e_f)) = (a.as_f64(), e.as_f64()) {
                (a_f - e_f).abs() < f64::EPSILON
            } else {
                false
            }
        }
        (Value::String(a), Value::String(e)) => a == e,
        (Value::Array(a), Value::Array(e)) => {
            a.len() == e.len() && a.iter().zip(e.iter()).all(|(a, e)| values_equal(a, e))
        }
        (Value::Object(a), Value::Object(e)) => {
            a.len() == e.len()
                && a.iter()
                    .all(|(k, v)| e.get(k).map_or(false, |ev| values_equal(v, ev)))
        }
        // Try string comparison as fallback
        _ => format!("{:?}", actual) == format!("{:?}", expected),
    }
}

#[tokio::main]
async fn main() -> Result<()> {
    let args = Args::parse();

    // Load spec
    let spec_content = std::fs::read_to_string(&args.spec)
        .with_context(|| format!("Failed to read spec file: {:?}", args.spec))?;

    let spec: TestSpec = serde_yaml::from_str(&spec_content)
        .with_context(|| "Failed to parse YAML specification")?;

    // Create runner
    let mut runner = Runner::new(&args.server, args.verbose);

    // Run setup
    if let Err(e) = runner.run_setup(&spec.setup).await {
        eprintln!("ERROR: Setup failed: {}", e);
        std::process::exit(3);
    }

    // Run tests
    let mut results = Vec::new();

    for test in &spec.tests {
        if test.skip {
            results.push(TestResult {
                test: test.name.clone(),
                status: "skipped".to_string(),
                error: None,
                result: None,
                duration_ms: 0.0,
            });
            continue;
        }

        if args.verbose {
            eprintln!("Running test: {}", test.name);
        }

        let result = runner.run_test(test).await;
        results.push(result);
    }

    // Run cleanup
    if let Err(e) = runner.run_cleanup(&spec.cleanup).await {
        if args.verbose {
            eprintln!("WARNING: Cleanup failed: {}", e);
        }
    }

    // Calculate summary
    let mut summary = Summary {
        total: results.len(),
        passed: 0,
        failed: 0,
        errors: 0,
        skipped: 0,
    };

    for result in &results {
        match result.status.as_str() {
            "passed" => summary.passed += 1,
            "failed" => summary.failed += 1,
            "error" => summary.errors += 1,
            "skipped" => summary.skipped += 1,
            _ => {}
        }
    }

    let output = Output { summary, results };

    if args.json {
        println!("{}", serde_json::to_string_pretty(&output)?);
    } else {
        println!("Tests: {}", output.summary.total);
        println!("Passed: {}", output.summary.passed);
        println!("Failed: {}", output.summary.failed);
        println!("Errors: {}", output.summary.errors);
    }

    Ok(())
}
