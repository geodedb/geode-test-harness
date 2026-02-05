const std = @import("std");
const builtin = @import("builtin");
const geode_client = @import("geode_client");
const GeodeClient = geode_client.GeodeClient;
const proto = geode_client.proto;
const yaml = @import("yaml");

const Allocator = std.mem.Allocator;

fn getStdErr() std.fs.File {
    return if (builtin.os.tag == .windows)
        std.fs.File{ .handle = std.os.windows.GetStdHandle(std.os.windows.STD_ERROR_HANDLE) catch unreachable }
    else
        std.fs.File{ .handle = std.posix.STDERR_FILENO };
}

fn getStdOut() std.fs.File {
    return if (builtin.os.tag == .windows)
        std.fs.File{ .handle = std.os.windows.GetStdHandle(std.os.windows.STD_OUTPUT_HANDLE) catch unreachable }
    else
        std.fs.File{ .handle = std.posix.STDOUT_FILENO };
}

const JsonArray = std.json.Array;
const JsonObject = std.json.ObjectMap;
const JsonValue = std.json.Value;

const TestSpec = struct {
    version: []const u8 = "",
    name: []const u8 = "",
    description: []const u8 = "",
    setup: []Step = &[_]Step{},
    tests: []Test = &[_]Test{},
    cleanup: []Step = &[_]Step{},
};

const Test = struct {
    name: []const u8,
    description: []const u8 = "",
    query: []const u8 = "",
    params: ?JsonValue = null,
    expect: Expectation = .{},
    steps: []Step = &[_]Step{},
    skip: bool = false,
    skip_reason: ?[]const u8 = null,
    timeout_ms: ?u64 = null,
    expect_error: bool = false,
    benchmark: ?BenchmarkConfig = null,
};

const BenchmarkConfig = struct {
    iterations: ?usize = null,
    max_avg_latency_ms: ?f64 = null,
    max_p95_latency_ms: ?f64 = null,
    max_total_time_ms: ?f64 = null,
    concurrent: ?usize = null,
};

const BenchmarkResult = struct {
    iterations: usize,
    avg_latency_ms: f64,
    p95_latency_ms: f64,
    min_latency_ms: f64,
    max_latency_ms: f64,
    total_time_ms: f64,
    errors: usize,
};

const Step = struct {
    type: []const u8,
    text: []const u8 = "",
    params: ?JsonValue = null,
    expect: Expectation = .{},
    expect_error: bool = false,
    connection_id: ?[]const u8 = null,
    id: ?[]const u8 = null,
};

const Expectation = struct {
    rows: ?usize = null,
    min_rows: ?usize = null,
    max_rows: ?usize = null,
    columns: ?[][]u8 = null,
    values: ?[]JsonValue = null,

    fn deinit(self: Expectation, allocator: Allocator) void {
        if (self.columns) |cols| {
            for (cols) |col| allocator.free(col);
            allocator.free(cols);
        }
        if (self.values) |vals| {
            for (vals) |*v| freeJsonValue(allocator, v);
            allocator.free(vals);
        }
    }
};

const QueryResult = struct {
    columns: [][]u8,
    rows: []JsonValue,

    fn deinit(self: QueryResult, allocator: Allocator) void {
        for (self.columns) |col| allocator.free(col);
        allocator.free(self.columns);

        for (self.rows) |*row| freeJsonValue(allocator, row);
        allocator.free(self.rows);
    }
};

// Default admin credentials for testing
const DEFAULT_USERNAME = "geode";
const DEFAULT_PASSWORD = "GeodeTestPassword123!";

const TransportType = enum {
    quic,
    grpc,
};

const RunnerConfig = struct {
    spec_path: []const u8,
    host: []const u8,
    port: u16,
    transport: TransportType,
    username: []const u8,
    password: []const u8,
    json_output: bool,
    verbose: bool,

    fn deinit(self: RunnerConfig, allocator: Allocator) void {
        allocator.free(self.spec_path);
        allocator.free(self.host);
    }
};

fn freeJsonValue(allocator: Allocator, value: *JsonValue) void {
    switch (value.*) {
        .string => |s| allocator.free(s),
        .number_string => |s| allocator.free(s),
        .array => |*arr| {
            for (arr.items) |*item| freeJsonValue(allocator, item);
            arr.deinit();
        },
        .object => |*obj| {
            var it = obj.iterator();
            while (it.next()) |entry| {
                allocator.free(entry.key_ptr.*);
                freeJsonValue(allocator, entry.value_ptr);
            }
            obj.deinit();
        },
        else => {},
    }
}

fn cloneJsonValue(allocator: Allocator, src: JsonValue) !JsonValue {
    return switch (src) {
        .null => JsonValue{ .null = {} },
        .bool => |b| JsonValue{ .bool = b },
        .integer => |i| JsonValue{ .integer = i },
        .float => |f| JsonValue{ .float = f },
        .number_string => |s| JsonValue{ .number_string = try allocator.dupe(u8, s) },
        .string => |s| JsonValue{ .string = try allocator.dupe(u8, s) },
        .array => |arr| blk: {
            var new_arr = JsonArray.init(allocator);
            errdefer new_arr.deinit();
            for (arr.items) |item| {
                const cloned = try cloneJsonValue(allocator, item);
                try new_arr.append(cloned);
            }
            break :blk JsonValue{ .array = new_arr };
        },
        .object => |obj| blk: {
            var new_obj = JsonObject.init(allocator);
            errdefer new_obj.deinit();
            var it = obj.iterator();
            while (it.next()) |entry| {
                const key_copy = try allocator.dupe(u8, entry.key_ptr.*);
                const cloned = try cloneJsonValue(allocator, entry.value_ptr.*);
                try new_obj.put(key_copy, cloned);
            }
            break :blk JsonValue{ .object = new_obj };
        },
    };
}

fn writeEscapedString(buf: *std.ArrayList(u8), allocator: Allocator, text: []const u8) !void {
    try buf.append(allocator, '"');
    for (text) |c| {
        switch (c) {
            '"' => try buf.appendSlice(allocator, "\\\""),
            '\\' => try buf.appendSlice(allocator, "\\\\"),
            '\n' => try buf.appendSlice(allocator, "\\n"),
            '\r' => try buf.appendSlice(allocator, "\\r"),
            '\t' => try buf.appendSlice(allocator, "\\t"),
            else => try buf.append(allocator, c),
        }
    }
    try buf.append(allocator, '"');
}

fn serializeJsonValue(buf: *std.ArrayList(u8), allocator: Allocator, value: JsonValue) !void {
    switch (value) {
        .null => try buf.appendSlice(allocator, "null"),
        .bool => |b| {
            if (b) {
                try buf.appendSlice(allocator, "true");
            } else {
                try buf.appendSlice(allocator, "false");
            }
        },
        .integer => |i| try buf.writer(allocator).print("{d}", .{i}),
        .float => |f| try buf.writer(allocator).print("{}", .{f}),
        .number_string => |s| try buf.appendSlice(allocator, s),
        .string => |s| try writeEscapedString(buf, allocator, s),
        .array => |arr| {
            try buf.append(allocator, '[');
            for (arr.items, 0..) |item, idx| {
                if (idx > 0) try buf.append(allocator, ',');
                try serializeJsonValue(buf, allocator, item);
            }
            try buf.append(allocator, ']');
        },
        .object => |obj| {
            try buf.append(allocator, '{');
            var it = obj.iterator();
            var first = true;
            while (it.next()) |entry| {
                if (!first) try buf.append(allocator, ',');
                first = false;
                try writeEscapedString(buf, allocator, entry.key_ptr.*);
                try buf.append(allocator, ':');
                try serializeJsonValue(buf, allocator, entry.value_ptr.*);
            }
            try buf.append(allocator, '}');
        },
    }
}

fn jsonToString(allocator: Allocator, value: JsonValue) ![]u8 {
    var buf = try std.ArrayList(u8).initCapacity(allocator, 0);
    errdefer buf.deinit(allocator);
    try serializeJsonValue(&buf, allocator, value);
    return buf.toOwnedSlice(allocator);
}

fn valuesEqual(a: JsonValue, b: JsonValue) bool {
    switch (a) {
        .null => return b == .null,
        .bool => |ba| return b == .bool and ba == b.bool,
        .integer => |ia| return (b == .integer and ia == b.integer) or (b == .float and @as(f64, @floatFromInt(ia)) == b.float),
        .float => |fa| return (b == .float and fa == b.float) or (b == .integer and fa == @as(f64, @floatFromInt(b.integer))),
        .number_string => |sa| return b == .number_string and std.mem.eql(u8, sa, b.number_string),
        .string => |sa| return b == .string and std.mem.eql(u8, sa, b.string),
        .array => |arr_a| {
            if (b != .array) return false;
            const arr_b = b.array;
            if (arr_a.items.len != arr_b.items.len) return false;
            for (arr_a.items, 0..) |item, idx| {
                if (!valuesEqual(item, arr_b.items[idx])) return false;
            }
            return true;
        },
        .object => |obj_a| {
            if (b != .object) return false;
            const obj_b = b.object;
            if (obj_a.count() != obj_b.count()) return false;
            var it = obj_a.iterator();
            while (it.next()) |entry| {
                const other = obj_b.get(entry.key_ptr.*) orelse return false;
                if (!valuesEqual(entry.value_ptr.*, other)) return false;
            }
            return true;
        },
    }
}

// Helper to lookup a key in yaml map (which is []ValueKVPair)
fn yamlMapGet(map: []const yaml.ValueKVPair, key: []const u8) ?yaml.Value {
    for (map) |kv| {
        if (kv.k == .str and std.mem.eql(u8, kv.k.str, key)) {
            return kv.v;
        }
    }
    return null;
}

fn yamlToJsonValue(allocator: Allocator, node: yaml.Value) !JsonValue {
    return switch (node) {
        .null => JsonValue{ .null = {} },
        .bool => |b| JsonValue{ .bool = b },
        .int => |i| JsonValue{ .integer = i },
        .big_int => |s| JsonValue{ .number_string = try allocator.dupe(u8, s) },
        .float => |f| JsonValue{ .float = f },
        .inf_pos => JsonValue{ .float = std.math.inf(f64) },
        .inf_neg => JsonValue{ .float = -std.math.inf(f64) },
        .nan => JsonValue{ .float = std.math.nan(f64) },
        .str => |s| JsonValue{ .string = try allocator.dupe(u8, s) },
        .seq => |seq| blk: {
            var arr = JsonArray.init(allocator);
            errdefer arr.deinit();
            for (seq) |item| {
                const v = try yamlToJsonValue(allocator, item);
                try arr.append(v);
            }
            break :blk JsonValue{ .array = arr };
        },
        .map => |map| blk: {
            var obj = JsonObject.init(allocator);
            errdefer obj.deinit();
            for (map) |kv| {
                // Keys should be strings
                const key_str = switch (kv.k) {
                    .str => |s| s,
                    else => continue, // Skip non-string keys
                };
                const key_copy = try allocator.dupe(u8, key_str);
                const v = try yamlToJsonValue(allocator, kv.v);
                try obj.put(key_copy, v);
            }
            break :blk JsonValue{ .object = obj };
        },
    };
}

fn parseExpectation(allocator: Allocator, value: ?yaml.Value) !Expectation {
    var expect = Expectation{};
    if (value == null) return expect;
    const v = value.?;
    if (v != .map) return expect;
    const map = v.map;

    if (yamlMapGet(map, "rows")) |rows_val| {
        if (rows_val == .int) expect.rows = @intCast(rows_val.int);
    }
    if (yamlMapGet(map, "min_rows")) |rows_val| {
        if (rows_val == .int) expect.min_rows = @intCast(rows_val.int);
    }
    if (yamlMapGet(map, "max_rows")) |rows_val| {
        if (rows_val == .int) expect.max_rows = @intCast(rows_val.int);
    }
    if (yamlMapGet(map, "columns")) |cols_val| {
        if (cols_val == .seq) {
            var cols = try allocator.alloc([]u8, cols_val.seq.len);
            for (cols_val.seq, 0..) |col_val, idx| {
                if (col_val == .str) {
                    cols[idx] = try allocator.dupe(u8, col_val.str);
                } else {
                    cols[idx] = try allocator.dupe(u8, "");
                }
            }
            expect.columns = cols;
        }
    }
    if (yamlMapGet(map, "values")) |vals_val| {
        if (vals_val == .seq) {
            var rows = try allocator.alloc(JsonValue, vals_val.seq.len);
            var i: usize = 0;
            errdefer {
                while (i > 0) : (i -= 1) freeJsonValue(allocator, &rows[i - 1]);
                allocator.free(rows);
            }
            for (vals_val.seq) |row_val| {
                rows[i] = try yamlToJsonValue(allocator, row_val);
                i += 1;
            }
            expect.values = rows;
        }
    }
    return expect;
}

fn parseSteps(allocator: Allocator, value: ?yaml.Value) ![]Step {
    if (value == null or value.? != .seq) return try allocator.alloc(Step, 0);
    const list = value.?.seq;
    var steps = try allocator.alloc(Step, list.len);
    var idx: usize = 0;
    errdefer {
        while (idx > 0) : (idx -= 1) {
            steps[idx - 1].expect.deinit(allocator);
        }
        allocator.free(steps);
    }

    for (list) |step_val| {
        var step = Step{
            .type = "",
        };
        if (step_val == .map) {
            const step_map = step_val.map;
            if (yamlMapGet(step_map, "type")) |t| {
                if (t == .str) step.type = try allocator.dupe(u8, t.str);
            }
            if (yamlMapGet(step_map, "text")) |txt| {
                if (txt == .str) step.text = try allocator.dupe(u8, txt.str);
            }
            if (yamlMapGet(step_map, "params")) |p| {
                step.params = try yamlToJsonValue(allocator, p);
            }
            if (yamlMapGet(step_map, "expect_error")) |ee| {
                if (ee == .bool) step.expect_error = ee.bool;
            }
            if (yamlMapGet(step_map, "connection_id")) |cid| {
                if (cid == .str) step.connection_id = try allocator.dupe(u8, cid.str);
            }
            if (yamlMapGet(step_map, "id")) |sid| {
                if (sid == .str) step.id = try allocator.dupe(u8, sid.str);
            }
            step.expect = try parseExpectation(allocator, yamlMapGet(step_map, "expect"));
        }
        steps[idx] = step;
        idx += 1;
    }
    return steps;
}

fn parseSpec(allocator: Allocator, yaml_content: []const u8) !TestSpec {
    // Load and resolve YAML to values
    var docs = try yaml.loadAll(allocator, yaml_content, .{});
    defer {
        for (docs) |*d| d.deinit();
        allocator.free(docs);
    }

    if (docs.len == 0) return error.InvalidSpec;

    const root_value = try yaml.resolveToValue(allocator, &docs[0], .{});
    defer yaml.freeValue(allocator, &root_value);

    if (root_value != .map) return error.InvalidSpec;
    const root_map = root_value.map;

    var spec = TestSpec{};

    if (yamlMapGet(root_map, "version")) |ver| {
        if (ver == .str) spec.version = try allocator.dupe(u8, ver.str);
    }
    if (yamlMapGet(root_map, "name")) |n| {
        if (n == .str) spec.name = try allocator.dupe(u8, n.str);
    }
    if (yamlMapGet(root_map, "description")) |d| {
        if (d == .str) spec.description = try allocator.dupe(u8, d.str);
    }

    spec.setup = try parseSteps(allocator, yamlMapGet(root_map, "setup"));
    spec.cleanup = try parseSteps(allocator, yamlMapGet(root_map, "cleanup"));

    if (yamlMapGet(root_map, "tests")) |tests_val| {
        if (tests_val == .seq) {
            spec.tests = try allocator.alloc(Test, tests_val.seq.len);
            var idx: usize = 0;
            errdefer {
                while (idx > 0) : (idx -= 1) {
                    spec.tests[idx - 1].expect.deinit(allocator);
                }
                allocator.free(spec.tests);
            }
            for (tests_val.seq) |test_val| {
                var tcase = Test{
                    .name = "",
                };
                if (test_val != .map) {
                    spec.tests[idx] = tcase;
                    idx += 1;
                    continue;
                }
                const test_map = test_val.map;
                if (yamlMapGet(test_map, "name")) |n| {
                    if (n == .str) tcase.name = try allocator.dupe(u8, n.str);
                }
                if (yamlMapGet(test_map, "description")) |d| {
                    if (d == .str) tcase.description = try allocator.dupe(u8, d.str);
                }
                if (yamlMapGet(test_map, "query")) |q| {
                    if (q == .str) tcase.query = try allocator.dupe(u8, q.str);
                }
                if (yamlMapGet(test_map, "params")) |p| {
                    tcase.params = try yamlToJsonValue(allocator, p);
                }
                tcase.expect = try parseExpectation(allocator, yamlMapGet(test_map, "expect"));
                tcase.steps = try parseSteps(allocator, yamlMapGet(test_map, "steps"));
                if (yamlMapGet(test_map, "skip")) |s| {
                    if (s == .bool) tcase.skip = s.bool;
                }
                if (yamlMapGet(test_map, "skip_reason")) |sr| {
                    if (sr == .str) tcase.skip_reason = try allocator.dupe(u8, sr.str);
                }
                if (yamlMapGet(test_map, "timeout_ms")) |t| {
                    if (t == .int) tcase.timeout_ms = @intCast(t.int);
                }
                if (yamlMapGet(test_map, "expect_error")) |ee| {
                    if (ee == .bool) tcase.expect_error = ee.bool;
                }
                if (yamlMapGet(test_map, "benchmark")) |bench_val| {
                    if (bench_val == .map) {
                        var bench_cfg = BenchmarkConfig{};
                        if (yamlMapGet(bench_val.map, "iterations")) |iter| {
                            if (iter == .int) bench_cfg.iterations = @intCast(iter.int);
                        }
                        if (yamlMapGet(bench_val.map, "max_avg_latency_ms")) |val| {
                            if (val == .float) bench_cfg.max_avg_latency_ms = val.float;
                            if (val == .int) bench_cfg.max_avg_latency_ms = @floatFromInt(val.int);
                        }
                        if (yamlMapGet(bench_val.map, "max_p95_latency_ms")) |val| {
                            if (val == .float) bench_cfg.max_p95_latency_ms = val.float;
                            if (val == .int) bench_cfg.max_p95_latency_ms = @floatFromInt(val.int);
                        }
                        if (yamlMapGet(bench_val.map, "max_total_time_ms")) |val| {
                            if (val == .float) bench_cfg.max_total_time_ms = val.float;
                            if (val == .int) bench_cfg.max_total_time_ms = @floatFromInt(val.int);
                        }
                        tcase.benchmark = bench_cfg;
                    }
                }
                spec.tests[idx] = tcase;
                idx += 1;
            }
        }
    }

    return spec;
}

fn freeSpec(allocator: Allocator, spec: TestSpec) void {
    for (spec.tests) |tc| {
        if (tc.params) |p_const| {
            var p = p_const;
            freeJsonValue(allocator, &p);
        }
        tc.expect.deinit(allocator);
        for (tc.steps) |step| {
            if (step.params) |p_const| {
                var p = p_const;
                freeJsonValue(allocator, &p);
            }
            step.expect.deinit(allocator);
            allocator.free(step.type);
            if (step.text.len > 0) allocator.free(step.text);
        }
        allocator.free(tc.steps);
        allocator.free(tc.name);
        if (tc.description.len > 0) allocator.free(tc.description);
        if (tc.query.len > 0) allocator.free(tc.query);
    }
    allocator.free(spec.tests);
    allocator.free(spec.setup);
    allocator.free(spec.cleanup);
    if (spec.version.len > 0) allocator.free(spec.version);
    if (spec.name.len > 0) allocator.free(spec.name);
    if (spec.description.len > 0) allocator.free(spec.description);
}

fn buildRunMessage(allocator: Allocator, query: []const u8, params: ?JsonValue) ![]u8 {
    var obj = JsonObject.init(allocator);

    try obj.put("type", JsonValue{ .string = try allocator.dupe(u8, "RUN_GQL") });
    try obj.put("text", JsonValue{ .string = try allocator.dupe(u8, query) });
    try obj.put("request_id", JsonValue{ .integer = 1 });

    if (params) |p| {
        const cloned = try cloneJsonValue(allocator, p);
        try obj.put("params", cloned);
    }

    const msg_val = JsonValue{ .object = obj };

    const msg = try jsonToString(allocator, msg_val);
    return msg;
}

fn buildSimpleMessage(allocator: Allocator, msg_type: []const u8) ![]u8 {
    var obj = JsonObject.init(allocator);
    try obj.put("type", JsonValue{ .string = try allocator.dupe(u8, msg_type) });
    const msg_val = JsonValue{ .object = obj };
    const msg = try jsonToString(allocator, msg_val);
    return msg;
}

fn buildPullMessage(allocator: Allocator, page_size: usize) ![]u8 {
    var obj = JsonObject.init(allocator);
    try obj.put("type", JsonValue{ .string = try allocator.dupe(u8, "PULL") });
    try obj.put("request_id", JsonValue{ .integer = 1 });
    try obj.put("page_size", JsonValue{ .integer = @intCast(page_size) });
    const msg_val = JsonValue{ .object = obj };
    const msg = try jsonToString(allocator, msg_val);
    return msg;
}

fn extractResultObject(value: JsonValue) !JsonObject {
    if (value != .object) return error.InvalidResponse;
    const root = value.object;
    const result_val = root.get("result") orelse return error.InvalidResponse;
    if (result_val != .object) return error.InvalidResponse;
    return result_val.object;
}

fn parseColumns(allocator: Allocator, schema: JsonObject) ![][]u8 {
    const cols_val = schema.get("columns") orelse return try allocator.alloc([]u8, 0);
    if (cols_val != .array) return try allocator.alloc([]u8, 0);
    const items = cols_val.array.items;
    var cols = try allocator.alloc([]u8, items.len);
    var idx: usize = 0;
    errdefer {
        while (idx > 0) : (idx -= 1) allocator.free(cols[idx - 1]);
        allocator.free(cols);
    }
    for (items) |col_val| {
        if (col_val != .object) {
            cols[idx] = try allocator.dupe(u8, "");
        } else {
            const name_val = col_val.object.get("name") orelse {
                cols[idx] = try allocator.dupe(u8, "");
                idx += 1;
                continue;
            };
            if (name_val == .string) {
                cols[idx] = try allocator.dupe(u8, name_val.string);
            } else {
                cols[idx] = try allocator.dupe(u8, "");
            }
        }
        idx += 1;
    }
    return cols;
}

fn appendRowsFromResult(allocator: Allocator, res: JsonObject, rows: *std.ArrayList(JsonValue)) !void {
    const rows_val = res.get("rows") orelse return;
    if (rows_val != .array) return;
    for (rows_val.array.items) |row_val| {
        const cloned = try cloneJsonValue(allocator, row_val);
        try rows.append(allocator, cloned);
    }
}

fn getTypeString(obj: JsonObject) []const u8 {
    const t = obj.get("type") orelse return "";
    if (t == .string) return t.string;
    return "";
}

fn protoValueToJson(allocator: Allocator, val: proto.Value) !JsonValue {
    if (val.null_val) {
        return JsonValue{ .null = {} };
    } else if (val.string_val) |s| {
        return JsonValue{ .string = try allocator.dupe(u8, s) };
    } else if (val.int_val) |i| {
        return JsonValue{ .integer = i };
    } else if (val.double_val) |d| {
        return JsonValue{ .float = d };
    } else if (val.bool_val) |b| {
        return JsonValue{ .bool = b };
    }
    return JsonValue{ .null = {} };
}

fn jsonValueToParamString(allocator: Allocator, val: JsonValue) ![]u8 {
    return switch (val) {
        .null => try allocator.dupe(u8, "null"),
        .bool => |b| try allocator.dupe(u8, if (b) "true" else "false"),
        .integer => |i| try std.fmt.allocPrint(allocator, "{d}", .{i}),
        .float => |f| try std.fmt.allocPrint(allocator, "{d}", .{f}),
        .string => |s| try allocator.dupe(u8, s),
        .number_string => |s| try allocator.dupe(u8, s),
        .array, .object => try jsonToString(allocator, val),
    };
}

fn jsonValueToProtoValue(val: JsonValue) proto.Value {
    return switch (val) {
        .null => proto.Value.initNull(),
        .bool => |b| proto.Value.initBool(b),
        .integer => |i| proto.Value.initInt(i),
        .float => |f| proto.Value.initDouble(f),
        .string => |s| proto.Value.initString(s),
        .number_string => |s| proto.Value.initString(s),
        .array, .object => proto.Value.initNull(), // Complex types not supported
    };
}

fn parseServer(allocator: Allocator, server: []const u8) !struct { host: []const u8, port: u16 } {
    var host_port = std.mem.splitScalar(u8, server, ':');
    const host_part = host_port.next() orelse "localhost";
    const port_part = host_port.next() orelse "8443";
    const port = std.fmt.parseInt(u16, port_part, 10) catch 8443;
    const host = try allocator.dupe(u8, host_part);
    return .{ .host = host, .port = port };
}

fn parseArgs(allocator: Allocator) !RunnerConfig {
    var args = std.process.args();
    _ = args.next(); // program name

    var spec_path_opt: ?[]const u8 = null;
    var server: []const u8 = "localhost:3141";
    var transport: TransportType = .quic;
    var json_output = false;
    var verbose = false;

    while (args.next()) |arg| {
        if (std.mem.eql(u8, arg, "--spec")) {
            spec_path_opt = args.next() orelse return error.MissingSpecValue;
        } else if (std.mem.eql(u8, arg, "--server")) {
            server = args.next() orelse return error.MissingServerValue;
        } else if (std.mem.eql(u8, arg, "--transport")) {
            const transport_str = args.next() orelse return error.MissingTransportValue;
            if (std.mem.eql(u8, transport_str, "grpc")) {
                transport = .grpc;
            } else {
                transport = .quic;
            }
        } else if (std.mem.eql(u8, arg, "--json")) {
            json_output = true;
        } else if (std.mem.eql(u8, arg, "--verbose")) {
            verbose = true;
        }
    }

    // Get credentials from environment or use defaults
    const username = std.posix.getenv("GEODE_USERNAME") orelse DEFAULT_USERNAME;
    const password = std.posix.getenv("GEODE_ADMIN_PASSWORD") orelse DEFAULT_PASSWORD;

    const spec_path = spec_path_opt orelse return error.MissingSpec;
    const server_parts = try parseServer(allocator, server);
    const spec_copy = try allocator.dupe(u8, spec_path);

    return RunnerConfig{
        .spec_path = spec_copy,
        .host = server_parts.host,
        .port = server_parts.port,
        .transport = transport,
        .username = username,
        .password = password,
        .json_output = json_output,
        .verbose = verbose,
    };
}

const ClientContext = struct {
    allocator: Allocator,
    host: []const u8,
    port: u16,
    transport: TransportType,
    username: []const u8,
    password: []const u8,
    client: ?GeodeClient = null,
    connections: std.StringHashMap(GeodeClient) = undefined,  // Connection registry for multi-connection tests

    fn initConnections(self: *ClientContext) void {
        self.connections = std.StringHashMap(GeodeClient).init(self.allocator);
    }

    fn deinitConnections(self: *ClientContext) void {
        var it = self.connections.iterator();
        while (it.next()) |entry| {
            entry.value_ptr.deinit();
        }
        self.connections.deinit();
    }

    fn poolAcquire(self: *ClientContext, conn_id: []const u8, verbose: bool) !void {
        var cli = GeodeClient.init(self.allocator, self.host, self.port, true, "", "");
        if (verbose) {
            std.debug.print("  Acquiring pool connection: {s}\n", .{conn_id});
        }
        try cli.connect();
        try cli.openStream();
        try cli.sendHello();
        _ = cli.receiveProto(2000) catch {};
        try self.connections.put(try self.allocator.dupe(u8, conn_id), cli);
    }

    fn poolRelease(self: *ClientContext, conn_id: []const u8) void {
        if (self.connections.fetchRemove(conn_id)) |kv| {
            var client = kv.value;
            client.deinit();
            self.allocator.free(kv.key);
        }
    }

    fn ensureConnected(self: *ClientContext, verbose: bool) !void {
        if (self.client != null) return;
        // Pass username and password for authentication
        var cli = GeodeClient.init(self.allocator, self.host, self.port, true, self.username, self.password);
        if (verbose) {
            const transport_str = if (self.transport == .grpc) "gRPC" else "QUIC";
            std.debug.print("  Connecting to {s}:{d} via {s}\n", .{ self.host, self.port, transport_str });
        }
        try cli.connect();
        try cli.openStream();
        try cli.sendHello();
        // Keep the client even if the HELLO ack is missing; subsequent messages should still flow.
        self.client = cli;
        _ = self.client.?.receiveProto(2000) catch |err| {
            if (verbose) {
                std.debug.print("  HELLO receive skipped: {any}\n", .{err});
            }
            return;
        };
    }

    fn close(self: *ClientContext) void {
        if (self.client) |*c| {
            c.deinit();
            self.client = null;
        }
    }

    fn begin(self: *ClientContext) !void {
        try self.ensureConnected(false);
        const msg = proto.QuicClientMessage{
            .begin = proto.BeginRequest{ .read_only = false },
        };
        try self.client.?.sendProto(msg);
        _ = try self.client.?.receiveProto(2000);
    }

    fn commit(self: *ClientContext) !void {
        try self.ensureConnected(false);
        const msg = proto.QuicClientMessage{
            .commit = proto.CommitRequest{},
        };
        try self.client.?.sendProto(msg);
        _ = try self.client.?.receiveProto(2000);
    }

    fn rollback(self: *ClientContext) !void {
        try self.ensureConnected(false);
        const msg = proto.QuicClientMessage{
            .rollback = proto.RollbackRequest{},
        };
        try self.client.?.sendProto(msg);
        _ = try self.client.?.receiveProto(2000);
    }

    fn runQuery(self: *ClientContext, query_text: []const u8, params: ?JsonValue, verbose: bool) !QueryResult {
        try self.ensureConnected(verbose);

        // Build the ExecuteRequest protobuf message
        var execute = proto.ExecuteRequest{
            .session_id = "",
            .query = query_text,
        };
        defer execute.deinit(self.allocator);

        // Convert JSON params to proto.Value and add to execute request
        if (params) |p| {
            if (p == .object) {
                var it = p.object.iterator();
                while (it.next()) |entry| {
                    const proto_val = jsonValueToProtoValue(entry.value_ptr.*);
                    try execute.addParam(self.allocator, entry.key_ptr.*, proto_val);
                }
            }
        }

        const msg = proto.QuicClientMessage{
            .execute = execute,
        };
        try self.client.?.sendProto(msg);

        // Receive the response
        const response = try self.client.?.receiveProto(30000);

        // Check for errors
        if (response.execute) |exec| {
            if (exec.err) |_| {
                return error.QueryError;
            }

            // Parse columns from schema
            var columns = try std.ArrayList([]u8).initCapacity(self.allocator, 0);
            errdefer {
                for (columns.items) |col| self.allocator.free(col);
                columns.deinit(self.allocator);
            }

            if (exec.schema) |schema| {
                for (schema.columns.items) |col| {
                    const col_name = try self.allocator.dupe(u8, col.name);
                    try columns.append(self.allocator, col_name);
                }
            }

            // Parse rows from data page
            var all_rows = try std.ArrayList(JsonValue).initCapacity(self.allocator, 0);
            errdefer {
                for (all_rows.items) |*row| freeJsonValue(self.allocator, row);
                all_rows.deinit(self.allocator);
            }

            if (exec.page) |page| {
                for (page.rows.items) |row| {
                    // Convert each row to a JSON object with column names as keys
                    var row_obj = JsonObject.init(self.allocator);
                    errdefer row_obj.deinit();

                    for (row.values.items, 0..) |val, idx| {
                        const col_name = if (idx < columns.items.len) columns.items[idx] else "";
                        const json_val = try protoValueToJson(self.allocator, val);
                        const key_copy = try self.allocator.dupe(u8, col_name);
                        try row_obj.put(key_copy, json_val);
                    }
                    try all_rows.append(self.allocator, JsonValue{ .object = row_obj });
                }
            }

            const cols_slice = try columns.toOwnedSlice(self.allocator);
            const rows_slice = try all_rows.toOwnedSlice(self.allocator);
            return QueryResult{ .columns = cols_slice, .rows = rows_slice };
        }

        return error.InvalidResponse;
    }
};

fn validateExpectations(result: QueryResult, expect: Expectation) !void {
    if (expect.rows) |r| {
        if (result.rows.len != r) return error.RowMismatch;
    }
    if (expect.min_rows) |r| {
        if (result.rows.len < r) return error.RowMismatch;
    }
    if (expect.max_rows) |r| {
        if (result.rows.len > r) return error.RowMismatch;
    }
    if (expect.columns) |cols| {
        if (result.columns.len != cols.len) return error.ColumnMismatch;
        // Compare as sets
        for (cols) |col| {
            var found = false;
            for (result.columns) |actual| {
                if (std.mem.eql(u8, col, actual)) {
                    found = true;
                    break;
                }
            }
            if (!found) return error.ColumnMismatch;
        }
    }
    if (expect.values) |vals| {
        var idx: usize = 0;
        while (idx < vals.len) : (idx += 1) {
            if (idx >= result.rows.len) return error.RowMismatch;
            const expected = vals[idx];
            const actual = result.rows[idx];
            if (expected != .object or actual != .object) return error.RowMismatch;
            var it = expected.object.iterator();
            while (it.next()) |entry| {
                const other = actual.object.get(entry.key_ptr.*) orelse return error.ValueMismatch;
                if (!valuesEqual(entry.value_ptr.*, other)) return error.ValueMismatch;
            }
        }
    }
}

const TestResult = struct {
    test_name: []const u8,
    status: []const u8,
    error_msg: ?[]const u8 = null,
    skip_reason: ?[]const u8 = null,
    result: ?QueryResult = null,
    duration_ms: f64,
    benchmark: ?BenchmarkResult = null,
};

fn runSetup(allocator: Allocator, ctx: *ClientContext, steps: []Step, verbose: bool) void {
    for (steps) |step| {
        if (std.mem.eql(u8, step.type, "query")) {
            if (ctx.runQuery(step.text, step.params, verbose)) |res| {
                res.deinit(allocator);
            } else |_| {}
        }
    }
}

fn runCleanup(allocator: Allocator, ctx: *ClientContext, steps: []Step, verbose: bool) void {
    for (steps) |step| {
        if (std.mem.eql(u8, step.type, "query")) {
            if (ctx.runQuery(step.text, step.params, verbose)) |res| {
                res.deinit(allocator);
            } else |_| {}
        }
    }
}

fn runTest(allocator: Allocator, ctx: *ClientContext, test_case: Test, verbose: bool) TestResult {
    // Check if this is a benchmark test
    if (test_case.benchmark) |benchmark| {
        return runBenchmarkTest(allocator, ctx, test_case, benchmark, verbose);
    }
    return runSingleTest(allocator, ctx, test_case, verbose);
}

fn runBenchmarkTest(allocator: Allocator, ctx: *ClientContext, test_case: Test, benchmark: BenchmarkConfig, verbose: bool) TestResult {
    const iterations = benchmark.iterations orelse 10;
    var latencies = std.ArrayList(f64).initCapacity(allocator, iterations) catch {
        return TestResult{
            .test_name = test_case.name,
            .status = "error",
            .error_msg = "Failed to allocate latencies buffer",
            .duration_ms = 0.0,
        };
    };
    defer latencies.deinit(allocator);
    var error_count: usize = 0;
    const start_total = std.time.milliTimestamp();

    var i: usize = 0;
    while (i < iterations) : (i += 1) {
        const start = std.time.milliTimestamp();
        const result = runSingleTest(allocator, ctx, test_case, verbose);
        const latency_ms: f64 = @floatFromInt(std.time.milliTimestamp() - start);
        latencies.append(allocator, latency_ms) catch {};

        if (!std.mem.eql(u8, result.status, "passed")) {
            error_count += 1;
        }
    }

    const total_time_ms: f64 = @floatFromInt(std.time.milliTimestamp() - start_total);

    if (latencies.items.len == 0) {
        return TestResult{
            .test_name = test_case.name,
            .status = "error",
            .error_msg = "No benchmark iterations completed",
            .duration_ms = 0.0,
        };
    }

    // Sort latencies for percentile calculation
    std.mem.sort(f64, latencies.items, {}, std.sort.asc(f64));

    // Calculate statistics
    var sum: f64 = 0.0;
    for (latencies.items) |lat| {
        sum += lat;
    }
    const avg_latency = sum / @as(f64, @floatFromInt(latencies.items.len));
    const p95_index = @min(@as(usize, @intFromFloat(@as(f64, @floatFromInt(latencies.items.len)) * 0.95)), latencies.items.len - 1);
    const p95_latency = latencies.items[p95_index];
    const min_latency = latencies.items[0];
    const max_latency = latencies.items[latencies.items.len - 1];

    const bench_result = BenchmarkResult{
        .iterations = iterations,
        .avg_latency_ms = avg_latency,
        .p95_latency_ms = p95_latency,
        .min_latency_ms = min_latency,
        .max_latency_ms = max_latency,
        .total_time_ms = total_time_ms,
        .errors = error_count,
    };

    // Check thresholds
    var failure_msg: ?[]const u8 = null;
    if (benchmark.max_avg_latency_ms) |max_avg| {
        if (avg_latency > max_avg) {
            failure_msg = "Average latency exceeds threshold";
        }
    }
    if (benchmark.max_p95_latency_ms) |max_p95| {
        if (p95_latency > max_p95) {
            failure_msg = "P95 latency exceeds threshold";
        }
    }
    if (benchmark.max_total_time_ms) |max_total| {
        if (total_time_ms > max_total) {
            failure_msg = "Total time exceeds threshold";
        }
    }

    if (failure_msg != null) {
        return TestResult{
            .test_name = test_case.name,
            .status = "failed",
            .error_msg = failure_msg,
            .duration_ms = total_time_ms,
            .benchmark = bench_result,
        };
    }

    return TestResult{
        .test_name = test_case.name,
        .status = "passed",
        .duration_ms = total_time_ms,
        .benchmark = bench_result,
    };
}

fn runSingleTest(allocator: Allocator, ctx: *ClientContext, test_case: Test, verbose: bool) TestResult {
    const start = std.time.milliTimestamp();

    var status: []const u8 = "passed";
    var error_msg: ?[]const u8 = null;
    var result: ?QueryResult = null;

    const handle_error = struct {
        fn set(err: []const u8, expect_error: bool, status_ptr: *[]const u8, msg_ptr: *?[]const u8) void {
            if (expect_error) {
                status_ptr.* = "passed";
                msg_ptr.* = null;
            } else {
                status_ptr.* = "error";
                msg_ptr.* = err;
            }
        }
    }.set;

    if (test_case.query.len > 0) {
        const res = ctx.runQuery(test_case.query, test_case.params, verbose) catch {
            handle_error("Query failed", test_case.expect_error, &status, &error_msg);
            return TestResult{ .test_name = test_case.name, .status = status, .error_msg = error_msg, .result = null, .duration_ms = @floatFromInt(std.time.milliTimestamp() - start) };
        };
        result = res;
        validateExpectations(res, test_case.expect) catch {
            status = "failed";
            error_msg = "Expectation mismatch";
        };
    } else if (test_case.steps.len > 0) {
        for (test_case.steps) |step| {
            var had_error = false;

            if (std.mem.eql(u8, step.type, "connect")) {
                if (step.connection_id) |conn_id| {
                    // Multi-connection: create named connection
                    ctx.poolAcquire(conn_id, verbose) catch {
                        had_error = true;
                    };
                } else {
                    ctx.ensureConnected(verbose) catch {
                        had_error = true;
                    };
                }
            } else if (std.mem.eql(u8, step.type, "commit")) {
                ctx.commit() catch {
                    had_error = true;
                };
            } else if (std.mem.eql(u8, step.type, "begin")) {
                ctx.begin() catch {
                    had_error = true;
                };
            } else if (std.mem.eql(u8, step.type, "rollback")) {
                ctx.rollback() catch {
                    had_error = true;
                };
            } else if (std.mem.eql(u8, step.type, "disconnect")) {
                if (step.connection_id) |conn_id| {
                    ctx.poolRelease(conn_id);
                } else {
                    ctx.close();
                }
            } else if (std.mem.eql(u8, step.type, "pool_acquire")) {
                const conn_id = step.connection_id orelse step.id orelse "default";
                ctx.poolAcquire(conn_id, verbose) catch {
                    had_error = true;
                };
            } else if (std.mem.eql(u8, step.type, "pool_release")) {
                const conn_id = step.connection_id orelse step.id orelse "default";
                ctx.poolRelease(conn_id);
            } else if (std.mem.eql(u8, step.type, "query")) {
                const res_opt = ctx.runQuery(step.text, step.params, verbose) catch null;
                if (res_opt) |res| {
                    validateExpectations(res, step.expect) catch {
                        res.deinit(allocator);
                        status = "failed";
                        error_msg = "Expectation mismatch";
                        break;
                    };
                    res.deinit(allocator);
                } else {
                    had_error = true;
                }
            }

            if (had_error) {
                if (step.expect_error) {
                    continue;
                } else {
                    status = "error";
                    error_msg = "Step failed";
                    break;
                }
            }
            if (std.mem.eql(u8, status, "failed") or std.mem.eql(u8, status, "error")) break;
        }
    } else {
        status = "error";
        error_msg = "Test must have 'query' or 'steps'";
    }

    const duration = @as(f64, @floatFromInt(std.time.milliTimestamp() - start));
    return TestResult{
        .test_name = test_case.name,
        .status = status,
        .error_msg = error_msg,
        .result = result,
        .duration_ms = duration,
    };
}

fn outputJson(allocator: Allocator, summary: Summary, results: []TestResult) !void {
    var output = try std.ArrayList(u8).initCapacity(allocator, 0);
    defer output.deinit(allocator);

    const writer = output.writer(allocator);

    try writer.print("{{\"summary\":{{\"total\":{d},\"passed\":{d},\"failed\":{d},\"errors\":{d},\"skipped\":{d}}},\"results\":[", .{
        summary.total,
        summary.passed,
        summary.failed,
        summary.errors,
        summary.skipped,
    });

    for (results, 0..) |result, i| {
        if (i > 0) try writer.writeAll(",");
        try writer.print("{{\"test\":\"{s}\",\"status\":\"{s}\"", .{ result.test_name, result.status });
        if (result.error_msg) |err| {
            try writer.print(",\"error\":\"{s}\"", .{err});
        }
        if (result.skip_reason) |reason| {
            try writer.print(",\"skip_reason\":\"{s}\"", .{reason});
        }
        if (result.benchmark) |bench| {
            try writer.print(",\"benchmark\":{{\"iterations\":{d},\"avg_latency_ms\":{d:.2},\"p95_latency_ms\":{d:.2},\"min_latency_ms\":{d:.2},\"max_latency_ms\":{d:.2},\"total_time_ms\":{d:.2},\"errors\":{d}}}", .{
                bench.iterations,
                bench.avg_latency_ms,
                bench.p95_latency_ms,
                bench.min_latency_ms,
                bench.max_latency_ms,
                bench.total_time_ms,
                bench.errors,
            });
        }
        try writer.print(",\"duration_ms\":{d}}}", .{result.duration_ms});
    }

    try writer.writeAll("]}\n");
    try getStdOut().writeAll(output.items);
}

fn outputText(summary: Summary, results: []TestResult) !void {
    var buf = try std.ArrayList(u8).initCapacity(std.heap.page_allocator, 0);
    defer buf.deinit(std.heap.page_allocator);
    const stdout_writer = buf.writer(std.heap.page_allocator);
    try stdout_writer.print("Tests: {d}\n", .{summary.total});
    try stdout_writer.print("Passed: {d}\n", .{summary.passed});
    try stdout_writer.print("Failed: {d}\n", .{summary.failed});
    try stdout_writer.print("Errors: {d}\n", .{summary.errors});

    if (summary.errors > 0 or summary.failed > 0) {
        try stdout_writer.writeAll("\nErrors/Failures:\n");
        for (results) |result| {
            if (result.error_msg) |err| {
                try stdout_writer.print("  {s}: {s}\n", .{ result.test_name, err });
            }
        }
    }
    try getStdOut().writeAll(buf.items);
}

const Summary = struct {
    total: usize,
    passed: usize,
    failed: usize,
    errors: usize,
    skipped: usize,
};

pub fn main() !void {
    var gpa = std.heap.GeneralPurposeAllocator(.{}){};
    defer _ = gpa.deinit();
    const allocator = gpa.allocator();

    // Parse command-line arguments
    var config = parseArgs(allocator) catch |err| {
        switch (err) {
            error.MissingSpec => try getStdErr().writeAll("ERROR: --spec is required\n"),
            error.MissingSpecValue => try getStdErr().writeAll("ERROR: --spec requires a value\n"),
            error.MissingServerValue => try getStdErr().writeAll("ERROR: --server requires a value\n"),
            else => try getStdErr().writeAll("ERROR: failed to parse arguments\n"),
        }
        std.process.exit(2);
    };
    defer config.deinit(allocator);

    if (config.verbose) {
        std.debug.print("Zig runner: Loading spec from {s}\n", .{config.spec_path});
        std.debug.print("Server: {s}:{d}\n", .{ config.host, config.port });
    }

    // Load spec file
    const spec_file = try std.fs.cwd().openFile(config.spec_path, .{});
    defer spec_file.close();

    const spec_content = try spec_file.readToEndAlloc(allocator, 10 * 1024 * 1024);
    defer allocator.free(spec_content);

    const spec = try parseSpec(allocator, spec_content);
    defer freeSpec(allocator, spec);

    var ctx = ClientContext{
        .allocator = allocator,
        .host = config.host,
        .port = config.port,
        .transport = config.transport,
        .username = config.username,
        .password = config.password,
    };
    ctx.initConnections();
    defer {
        ctx.deinitConnections();
        ctx.close();
    }

    // Run setup
    runSetup(allocator, &ctx, spec.setup, config.verbose);

    var results = try std.ArrayList(TestResult).initCapacity(allocator, spec.tests.len);
    defer {
        for (results.items) |res| {
            if (res.result) |r| r.deinit(allocator);
        }
        results.deinit(allocator);
    }

    for (spec.tests) |test_case| {
        if (test_case.skip) {
            try results.append(allocator, TestResult{
                .test_name = test_case.name,
                .status = "skipped",
                .skip_reason = test_case.skip_reason,
                .duration_ms = 0.0,
            });
            continue;
        }

        if (config.verbose) {
            std.debug.print("Running test: {s}\n", .{test_case.name});
        }

        const res = runTest(allocator, &ctx, test_case, config.verbose);
        try results.append(allocator, res);
    }

    // Run cleanup
    runCleanup(allocator, &ctx, spec.cleanup, config.verbose);

    // Summary
    var summary = Summary{
        .total = results.items.len,
        .passed = 0,
        .failed = 0,
        .errors = 0,
        .skipped = 0,
    };

    for (results.items) |r| {
        if (std.mem.eql(u8, r.status, "passed")) {
            summary.passed += 1;
        } else if (std.mem.eql(u8, r.status, "failed")) {
            summary.failed += 1;
        } else if (std.mem.eql(u8, r.status, "error")) {
            summary.errors += 1;
        } else if (std.mem.eql(u8, r.status, "skipped")) {
            summary.skipped += 1;
        }
    }

    if (config.json_output) {
        try outputJson(allocator, summary, results.items);
    } else {
        try outputText(summary, results.items);
    }

    if (summary.errors > 0 or summary.failed > 0) {
        std.process.exit(1);
    }
}
