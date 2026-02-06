#!/usr/bin/env node
/**
 * Node.js client test runner.
 *
 * Executes test specifications using the Geode Node.js client library.
 */

const fs = require('fs');
const path = require('path');
const yaml = require('yaml');

// Load the Geode client dynamically (ESM module)
let createClient;

async function loadGeodeClient() {
    try {
        // First try the installed package
        const mod = await import('@geode/client');
        return mod.createClient || mod.default?.createClient;
    } catch (e) {
        // Try loading from sibling directory
        const clientPath = path.join(__dirname, '..', '..', 'geode-client-nodejs', 'dist', 'index.js');
        try {
            const mod = await import(clientPath);
            return mod.createClient || mod.default?.createClient;
        } catch (e2) {
            console.error('Error: Geode Node.js client not found.');
            console.error('Install it from: npm install @geode/client');
            console.error('Or ensure ../geode-client-nodejs/dist exists');
            console.error('Details:', e2.message);
            process.exit(1);
        }
    }
}

// Default admin credentials for testing
const DEFAULT_USERNAME = 'geode';
const DEFAULT_PASSWORD = 'GeodeTestPassword123!';

/**
 * Parse command-line arguments.
 */
function parseArgs() {
    const args = process.argv.slice(2);
    const options = {
        spec: null,
        server: 'localhost:3141',
        transport: 'quic',
        json: false,
        verbose: false,
    };

    for (let i = 0; i < args.length; i++) {
        switch (args[i]) {
            case '--spec':
                options.spec = args[++i];
                break;
            case '--server':
                options.server = args[++i];
                break;
            case '--transport':
                options.transport = args[++i];
                break;
            case '--json':
                options.json = true;
                break;
            case '--verbose':
            case '-v':
                options.verbose = true;
                break;
        }
    }

    return options;
}

/**
 * Test runner class.
 */
/**
 * Recursively convert BigInt values to Number for JSON serialization.
 */
function convertBigInts(value) {
    if (typeof value === 'bigint') {
        return Number(value);
    }
    if (Array.isArray(value)) {
        return value.map(convertBigInts);
    }
    if (value !== null && typeof value === 'object') {
        const result = {};
        for (const [k, v] of Object.entries(value)) {
            result[k] = convertBigInts(v);
        }
        return result;
    }
    return value;
}

class NodeJSTestRunner {
    constructor(server, verbose = false, transport = 'quic') {
        this.server = server;
        this.verbose = verbose;
        this.transport = transport;
        this.username = process.env.GEODE_USERNAME || DEFAULT_USERNAME;
        this.password = process.env.GEODE_ADMIN_PASSWORD || DEFAULT_PASSWORD;
        this.client = null;
        this.connection = null;
        this.transaction = null;
        this.inTransaction = false;
        this.connections = new Map();  // Connection registry for multi-connection tests
    }

    /**
     * Build DSN based on transport type and credentials.
     */
    buildDsn() {
        const scheme = this.transport === 'grpc' ? 'grpc' : 'quic';
        const tlsParam = this.transport === 'grpc' ? 'tls=0' : 'insecure=true';
        return `${scheme}://${this.server}?${tlsParam}&user=${this.username}&pass=${encodeURIComponent(this.password)}`;
    }

    async setup() {
        // Client is connected on demand
    }

    async teardown() {
        if (this.transaction) {
            try {
                await this.transaction.rollback();
            } catch (e) {
                // Ignore rollback errors
            }
            this.transaction = null;
        }
        if (this.connection) {
            try {
                await this.client.releaseConnection(this.connection);
            } catch (e) {
                // Ignore release errors
            }
            this.connection = null;
        }
        // Close all pooled connections
        for (const [connId, connData] of this.connections) {
            try {
                if (connData.connection) {
                    await connData.client.releaseConnection(connData.connection);
                }
                await connData.client.close();
            } catch (e) {
                // Ignore errors
            }
        }
        this.connections.clear();
        if (this.client) {
            try {
                await this.client.close();
            } catch (e) {
                // Ignore close errors
            }
            this.client = null;
        }
    }

    async poolAcquire(connectionId) {
        const dsn = this.buildDsn();
        const client = await createClient(dsn, { pooling: false });
        this.connections.set(connectionId, { client, connection: null });
    }

    async poolRelease(connectionId) {
        const connData = this.connections.get(connectionId);
        if (connData) {
            try {
                if (connData.connection) {
                    await connData.client.releaseConnection(connData.connection);
                }
                await connData.client.close();
            } catch (e) {
                // Ignore errors
            }
            this.connections.delete(connectionId);
        }
    }

    getConnection(connectionId) {
        if (connectionId && this.connections.has(connectionId)) {
            return this.connections.get(connectionId);
        }
        return { client: this.client, connection: this.connection };
    }

    async connect() {
        if (!this.client) {
            const dsn = this.buildDsn();
            this.client = await createClient(dsn, { pooling: false });
        }
    }

    async disconnect() {
        if (this.transaction) {
            try {
                await this.transaction.rollback();
            } catch (e) {
                // Ignore
            }
            this.transaction = null;
        }
        if (this.connection) {
            try {
                await this.client.releaseConnection(this.connection);
            } catch (e) {
                // Ignore
            }
            this.connection = null;
        }
        if (this.client) {
            await this.client.close();
            this.client = null;
        }
        this.inTransaction = false;
    }

    async runQuery(query, params = {}) {
        await this.connect();

        // Pass params as an options object
        const options = Object.keys(params).length > 0 ? { params } : undefined;

        // Use transaction connection if in a transaction, otherwise use client
        let queryResult;
        if (this.inTransaction && this.connection) {
            queryResult = await this.connection.query(query, options);
        } else {
            queryResult = await this.client.query(query, options);
        }

        const columns = queryResult.columnNames || [];

        const data = [];
        for await (const row of queryResult) {
            // Row is a Map, convert to object
            const rowObj = {};
            if (row instanceof Map) {
                for (const [key, value] of row) {
                    // Value might be a GQLValue with toJS(), or already a primitive
                    const jsVal = value && typeof value.toJS === 'function' ? value.toJS() : value;
                    rowObj[key] = convertBigInts(jsVal);
                }
            } else if (typeof row === 'object' && row !== null) {
                // Already an object
                for (const key of columns) {
                    rowObj[key] = row[key];
                }
            }
            data.push(rowObj);
        }

        return {
            rows: data.length,
            columns: columns,
            data: data,
        };
    }

    async beginTransaction() {
        await this.connect();
        // Get a dedicated connection for the transaction
        this.connection = await this.client.getConnection();
        this.transaction = await this.connection.begin();
        this.inTransaction = true;
    }

    async commitTransaction() {
        if (this.inTransaction && this.transaction) {
            await this.transaction.commit();
            this.transaction = null;
            this.inTransaction = false;
        }
        if (this.connection) {
            await this.client.releaseConnection(this.connection);
            this.connection = null;
        }
    }

    async rollbackTransaction() {
        if (this.inTransaction && this.transaction) {
            await this.transaction.rollback();
            this.transaction = null;
            this.inTransaction = false;
        }
        if (this.connection) {
            await this.client.releaseConnection(this.connection);
            this.connection = null;
        }
    }

    async runTest(test) {
        // Check if this is a benchmark test
        if (test.benchmark) {
            return await this.runBenchmarkTest(test);
        }
        return await this.runSingleTest(test);
    }

    async runBenchmarkTest(test) {
        const benchmark = test.benchmark;
        const iterations = benchmark.iterations || 10;
        const latencies = [];
        let errorCount = 0;
        const startTotal = Date.now();

        for (let i = 0; i < iterations; i++) {
            const start = Date.now();
            try {
                const result = await this.runSingleTest(test);
                latencies.push(Date.now() - start);

                if (result.status !== 'passed') {
                    errorCount++;
                }
            } catch (e) {
                latencies.push(Date.now() - start);
                errorCount++;
            }
        }

        const totalTimeMs = Date.now() - startTotal;

        if (latencies.length === 0) {
            return {
                status: 'error',
                error: 'No benchmark iterations completed',
            };
        }

        // Calculate statistics
        latencies.sort((a, b) => a - b);
        const avgLatency = latencies.reduce((a, b) => a + b, 0) / latencies.length;
        const p95Index = Math.min(Math.floor(latencies.length * 0.95), latencies.length - 1);
        const p95Latency = latencies[p95Index];

        const benchmarkResult = {
            iterations,
            avg_latency_ms: Math.round(avgLatency * 100) / 100,
            p95_latency_ms: latencies[p95Index],
            min_latency_ms: latencies[0],
            max_latency_ms: latencies[latencies.length - 1],
            total_time_ms: totalTimeMs,
            errors: errorCount,
        };

        // Check thresholds
        const failures = [];
        if (benchmark.max_avg_latency_ms && avgLatency > benchmark.max_avg_latency_ms) {
            failures.push(`Average latency ${avgLatency.toFixed(2)}ms exceeds max ${benchmark.max_avg_latency_ms}ms`);
        }
        if (benchmark.max_p95_latency_ms && p95Latency > benchmark.max_p95_latency_ms) {
            failures.push(`P95 latency ${p95Latency}ms exceeds max ${benchmark.max_p95_latency_ms}ms`);
        }
        if (benchmark.max_total_time_ms && totalTimeMs > benchmark.max_total_time_ms) {
            failures.push(`Total time ${totalTimeMs}ms exceeds max ${benchmark.max_total_time_ms}ms`);
        }

        if (failures.length > 0) {
            return {
                status: 'failed',
                error: failures.join('; '),
                benchmark: benchmarkResult,
            };
        }

        return { status: 'passed', benchmark: benchmarkResult };
    }

    async runSingleTest(test) {
        try {
            // Simple query test
            if (test.query) {
                const result = await this.runQuery(test.query, test.params || {});

                // Validate expectations
                const expect = test.expect || {};

                if (expect.rows !== undefined && result.rows !== expect.rows) {
                    return {
                        status: 'failed',
                        error: `Expected ${expect.rows} rows, got ${result.rows}`,
                        result,
                    };
                }

                if (expect.columns) {
                    const actualCols = new Set(result.columns);
                    const expectedCols = new Set(expect.columns);
                    const match = expect.columns.length === result.columns.length &&
                        expect.columns.every(c => actualCols.has(c));
                    if (!match) {
                        return {
                            status: 'failed',
                            error: `Expected columns ${JSON.stringify(expect.columns)}, got ${JSON.stringify(result.columns)}`,
                            result,
                        };
                    }
                }

                if (expect.values && expect.values.length > 0) {
                    for (let i = 0; i < expect.values.length; i++) {
                        if (i >= result.data.length) {
                            return {
                                status: 'failed',
                                error: `Expected row ${i} missing`,
                                result,
                            };
                        }

                        const expectedRow = expect.values[i];
                        const actualRow = result.data[i];

                        for (const [key, expectedValue] of Object.entries(expectedRow)) {
                            if (!(key in actualRow)) {
                                return {
                                    status: 'failed',
                                    error: `Expected column '${key}' missing in row ${i}`,
                                    result,
                                };
                            }

                            if (!this.compareValues(actualRow[key], expectedValue)) {
                                return {
                                    status: 'failed',
                                    error: `Expected ${key}=${expectedValue}, got ${actualRow[key]}`,
                                    result,
                                };
                            }
                        }
                    }
                }

                return { status: 'passed', result };
            }

            // Step-based test
            if (test.steps) {
                const results = [];

                for (const step of test.steps) {
                    const stepType = step.type;
                    const connectionId = step.connection_id || step.id;

                    try {
                        switch (stepType) {
                            case 'connect':
                                if (connectionId) {
                                    // Multi-connection: create named connection
                                    await this.poolAcquire(connectionId);
                                } else {
                                    await this.connect();
                                }
                                break;

                            case 'disconnect':
                                if (connectionId) {
                                    await this.poolRelease(connectionId);
                                } else {
                                    await this.disconnect();
                                }
                                break;

                            case 'pool_acquire': {
                                const connId = connectionId || 'default';
                                await this.poolAcquire(connId);
                                break;
                            }

                            case 'pool_release': {
                                const connId = connectionId || 'default';
                                await this.poolRelease(connId);
                                break;
                            }

                            case 'query':
                                const result = await this.runQuery(step.text, step.params || {});
                                results.push(result);

                                // Check expectations
                                const expect = step.expect || {};
                                if (expect.rows !== undefined && result.rows !== expect.rows) {
                                    if (!step.expect_error) {
                                        return {
                                            status: 'failed',
                                            error: `Step query: Expected ${expect.rows} rows, got ${result.rows}`,
                                            results,
                                        };
                                    }
                                }
                                break;

                            case 'begin':
                                await this.beginTransaction();
                                break;

                            case 'commit':
                                await this.commitTransaction();
                                break;

                            case 'rollback':
                                await this.rollbackTransaction();
                                break;

                            default:
                                if (this.verbose) {
                                    console.error(`Unknown step type: ${stepType}`);
                                }
                        }
                    } catch (stepError) {
                        if (!step.expect_error) {
                            throw stepError;
                        }
                        // Expected error, continue
                    }
                }

                return { status: 'passed', results };
            }

            return {
                status: 'error',
                error: "Test must have 'query' or 'steps'",
            };

        } catch (e) {
            // Check if error was expected
            if (test.expect_error || (test.steps && test.steps.some(s => s.expect_error))) {
                return { status: 'passed', error_expected: e.message };
            }

            return { status: 'error', error: e.message };
        }
    }

    compareValues(actual, expected) {
        // Handle NULL
        if (expected === null) {
            return actual === null || actual === undefined;
        }
        if (actual === null || actual === undefined) {
            return false;
        }

        // Type conversions
        if (typeof expected === 'number') {
            const actualNum = Number(actual);
            return !isNaN(actualNum) && actualNum === expected;
        }

        if (typeof expected === 'string') {
            return String(actual) === expected;
        }

        if (typeof expected === 'boolean') {
            // Handle boolean-string comparisons
            if (typeof actual === 'boolean') {
                return actual === expected;
            }
            if (typeof actual === 'string') {
                return (actual === 'true') === expected || (actual === 'false') === !expected;
            }
            return Boolean(actual) === expected;
        }

        // Fallback: string comparison
        return String(actual) === String(expected);
    }

    async runSpec(spec) {
        const results = [];

        // Run setup
        for (const setupStep of (spec.setup || [])) {
            try {
                if (setupStep.type === 'query') {
                    await this.runQuery(setupStep.text);
                }
            } catch (e) {
                console.error(`Setup failed: ${e.message}`);
                return {
                    status: 'error',
                    error: `Setup failed: ${e.message}`,
                };
            }
        }

        // Run tests
        for (const test of (spec.tests || [])) {
            if (test.skip) {
                const skippedResult = { test: test.name, status: 'skipped' };
                if (test.skip_reason) {
                    skippedResult.skip_reason = test.skip_reason;
                }
                results.push(skippedResult);
                continue;
            }

            const result = await this.runTest(test);
            result.test = test.name;
            results.push(result);
        }

        // Run cleanup
        for (const cleanupStep of (spec.cleanup || [])) {
            try {
                if (cleanupStep.type === 'query') {
                    await this.runQuery(cleanupStep.text);
                }
            } catch (e) {
                console.error(`Cleanup warning: ${e.message}`);
            }
        }

        // Calculate summary
        const summary = {
            total: results.length,
            passed: results.filter(r => r.status === 'passed').length,
            failed: results.filter(r => r.status === 'failed').length,
            errors: results.filter(r => r.status === 'error').length,
            skipped: results.filter(r => r.status === 'skipped').length,
        };

        return { summary, results };
    }
}

async function main() {
    const options = parseArgs();

    if (!options.spec) {
        console.error('ERROR: --spec is required');
        process.exit(2);
    }

    // Load ESM client module
    createClient = await loadGeodeClient();

    // Load spec
    let spec;
    try {
        const content = fs.readFileSync(options.spec, 'utf8');
        spec = yaml.parse(content);
    } catch (e) {
        console.error(`ERROR: Failed to read spec: ${e.message}`);
        process.exit(2);
    }

    // Run tests
    const runner = new NodeJSTestRunner(options.server, options.verbose, options.transport);

    try {
        await runner.setup();
        const result = await runner.runSpec(spec);

        if (options.json) {
            console.log(JSON.stringify(result, null, 2));
        } else {
            console.log(`Tests: ${result.summary.total}`);
            console.log(`Passed: ${result.summary.passed}`);
            console.log(`Failed: ${result.summary.failed}`);
            console.log(`Errors: ${result.summary.errors}`);
        }

        process.exit(0);
    } catch (e) {
        const errorResult = {
            summary: { total: 0, passed: 0, failed: 0, errors: 1, skipped: 0 },
            results: [],
        };

        if (options.json) {
            console.log(JSON.stringify(errorResult, null, 2));
        } else {
            console.error(`Runner error: ${e.message}`);
        }

        process.exit(1);
    } finally {
        await runner.teardown();
    }
}

main();
