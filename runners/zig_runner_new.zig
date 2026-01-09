const std = @import("std");
const builtin = @import("builtin");
const GeodeClient = @import("geode_client").GeodeClient;
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
    timeout_ms: ?u64 = null,
    expect_error: bool = false,
};

const Step = struct {
    type: []const u8,
    text: []const u8 = "",
    params: ?JsonValue = null,
    expect: Expectation = .{},
    expect_error: bool = false,
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

const RunnerConfig = struct {
    spec_path: []const u8,
    host: []const u8,
    port: u16,
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

fn yamlToJsonValue(allocator: Allocator, node: yaml.Value) !JsonValue {
    return switch (node) {
        .null_value => JsonValue{ .null = {} },
        .bool_value => |b| JsonValue{ .bool = b },
        .int_value => |i| JsonValue{ .integer = i },
        .float_value => |f| JsonValue{ .float = f },
        .string_value => |s| JsonValue{ .string = try allocator.dupe(u8, s) },
        .list => |list| blk: {
            var arr = JsonArray.init(allocator);
            errdefer arr.deinit();
            for (list.items) |item| {
                const v = try yamlToJsonValue(allocator, item);
                try arr.append(v);
            }
            break :blk JsonValue{ .array = arr };
        },
        .map => |map| blk: {
            var obj = JsonObject.init(allocator);
            errdefer obj.deinit();
            var it = map.iterator();
            while (it.next()) |entry| {
                const key_copy = try allocator.dupe(u8, entry.key_ptr.*);
                const v = try yamlToJsonValue(allocator, entry.value_ptr.*);
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

    if (v.map.get("rows")) |rows_val| {
        if (rows_val == .int_value) expect.rows = @intCast(rows_val.int_value);
    }
    if (v.map.get("min_rows")) |rows_val| {
        if (rows_val == .int_value) expect.min_rows = @intCast(rows_val.int_value);
    }
    if (v.map.get("max_rows")) |rows_val| {
        if (rows_val == .int_value) expect.max_rows = @intCast(rows_val.int_value);
    }
    if (v.map.get("columns")) |cols_val| {
        if (cols_val == .list) {
            var cols = try allocator.alloc([]u8, cols_val.list.items.len);
            for (cols_val.list.items, 0..) |*col_val, idx| {
                if (col_val.* == .string_value) {
                    cols[idx] = try allocator.dupe(u8, col_val.string_value);
                } else {
                    cols[idx] = try allocator.dupe(u8, "");
                }
            }
            expect.columns = cols;
        }
    }
    if (v.map.get("values")) |vals_val| {
        if (vals_val == .list) {
            var rows = try allocator.alloc(JsonValue, vals_val.list.items.len);
            var i: usize = 0;
            errdefer {
                while (i > 0) : (i -= 1) freeJsonValue(allocator, &rows[i - 1]);
                allocator.free(rows);
            }
            for (vals_val.list.items) |row_val| {
                rows[i] = try yamlToJsonValue(allocator, row_val);
                i += 1;
            }
            expect.values = rows;
        }
    }
    return expect;
}

fn parseSteps(allocator: Allocator, value: ?yaml.Value) ![]Step {
    if (value == null or value.? != .list) return try allocator.alloc(Step, 0);
    const list = value.?.list.items;
    var steps = try allocator.alloc(Step, list.len);
    var idx: usize = 0;
    errdefer {
        while (idx > 0) : (idx -= 1) {
            steps[idx - 1].expect.deinit(allocator);
        }
        allocator.free(steps);
    }

    for (list) |*step_val| {
        var step = Step{
            .type = "",
        };
        if (step_val.* == .map) {
            if (step_val.map.get("type")) |t| {
                if (t == .string_value) step.type = try allocator.dupe(u8, t.string_value);
            }
            if (step_val.map.get("text")) |txt| {
                if (txt == .string_value) step.text = try allocator.dupe(u8, txt.string_value);
            }
            if (step_val.map.get("params")) |p| {
                step.params = try yamlToJsonValue(allocator, p);
            }
            if (step_val.map.get("expect_error")) |ee| {
                if (ee == .bool_value) step.expect_error = ee.bool_value;
            }
            step.expect = try parseExpectation(allocator, step_val.map.get("expect"));
        }
        steps[idx] = step;
        idx += 1;
    }
    return steps;
}

fn parseSpec(allocator: Allocator, yaml_content: []const u8) !TestSpec {
    var parser = yaml.Parser.init(allocator, yaml_content);
    var root_value = try parser.parse();
    defer root_value.deinit(allocator);

    if (root_value != .map) return error.InvalidSpec;

    var spec = TestSpec{};

    if (root_value.map.get("version")) |ver| {
        if (ver == .string_value) spec.version = try allocator.dupe(u8, ver.string_value);
    }
    if (root_value.map.get("name")) |n| {
        if (n == .string_value) spec.name = try allocator.dupe(u8, n.string_value);
    }
    if (root_value.map.get("description")) |d| {
        if (d == .string_value) spec.description = try allocator.dupe(u8, d.string_value);
    }

    spec.setup = try parseSteps(allocator, root_value.map.get("setup"));
    spec.cleanup = try parseSteps(allocator, root_value.map.get("cleanup"));

    if (root_value.map.get("tests")) |tests_val| {
        if (tests_val == .list) {
            spec.tests = try allocator.alloc(Test, tests_val.list.items.len);
            var idx: usize = 0;
            errdefer {
                while (idx > 0) : (idx -= 1) {
                    spec.tests[idx - 1].expect.deinit(allocator);
                }
                allocator.free(spec.tests);
            }
            for (tests_val.list.items) |*test_val| {
                var tcase = Test{
                    .name = "",
                };
                if (test_val.* != .map) {
                    spec.tests[idx] = tcase;
                    idx += 1;
                    continue;
                }
                if (test_val.map.get("name")) |n| {
                    if (n == .string_value) tcase.name = try allocator.dupe(u8, n.string_value);
                }
                if (test_val.map.get("description")) |d| {
                    if (d == .string_value) tcase.description = try allocator.dupe(u8, d.string_value);
                }
                if (test_val.map.get("query")) |q| {
                    if (q == .string_value) tcase.query = try allocator.dupe(u8, q.string_value);
                }
                if (test_val.map.get("params")) |p| {
                    tcase.params = try yamlToJsonValue(allocator, p);
                }
                tcase.expect = try parseExpectation(allocator, test_val.map.get("expect"));
                tcase.steps = try parseSteps(allocator, test_val.map.get("steps"));
                if (test_val.map.get("skip")) |s| {
                    if (s == .bool_value) tcase.skip = s.bool_value;
                }
                if (test_val.map.get("timeout_ms")) |t| {
                    if (t == .int_value) tcase.timeout_ms = @intCast(t.int_value);
                }
                if (test_val.map.get("expect_error")) |ee| {
                    if (ee == .bool_value) tcase.expect_error = ee.bool_value;
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
    var server: []const u8 = "localhost:8443";
    var json_output = false;
    var verbose = false;

    while (args.next()) |arg| {
        if (std.mem.eql(u8, arg, "--spec")) {
            spec_path_opt = args.next() orelse return error.MissingSpecValue;
        } else if (std.mem.eql(u8, arg, "--server")) {
            server = args.next() orelse return error.MissingServerValue;
        } else if (std.mem.eql(u8, arg, "--json")) {
            json_output = true;
        } else if (std.mem.eql(u8, arg, "--verbose")) {
            verbose = true;
        }
    }

    const spec_path = spec_path_opt orelse return error.MissingSpec;
    const server_parts = try parseServer(allocator, server);
    const spec_copy = try allocator.dupe(u8, spec_path);

    return RunnerConfig{
        .spec_path = spec_copy,
        .host = server_parts.host,
        .port = server_parts.port,
        .json_output = json_output,
        .verbose = verbose,
    };
}

const ClientContext = struct {
    allocator: Allocator,
    host: []const u8,
    port: u16,
    client: ?GeodeClient = null,

    fn ensureConnected(self: *ClientContext, verbose: bool) !void {
        if (self.client != null) return;
        var cli = GeodeClient.init(self.allocator, self.host, self.port, true);
        if (verbose) {
            std.debug.print("  Connecting to {s}:{d}\n", .{ self.host, self.port });
        }
        try cli.connect();
        try cli.openStream();
        try cli.sendHello("geode-zig-runner", "1.0.0");
        // Keep the client even if the HELLO ack is missing; subsequent messages should still flow.
        self.client = cli;
        const hello = self.client.?.receiveMessage(2000) catch |err| {
            if (verbose) {
                std.debug.print("  HELLO receive skipped: {any}\n", .{err});
            }
            return;
        };
        self.allocator.free(hello);
    }

    fn close(self: *ClientContext) void {
        if (self.client) |*c| {
            c.deinit();
            self.client = null;
        }
    }

    fn begin(self: *ClientContext) !void {
        try self.ensureConnected(false);
        const msg = try buildSimpleMessage(self.allocator, "BEGIN");
        defer self.allocator.free(msg);
        try self.client.?.sendMessage(msg);
        const ack = try self.client.?.receiveMessage(2000);
        self.allocator.free(ack);
    }

    fn commit(self: *ClientContext) !void {
        try self.ensureConnected(false);
        const msg = try buildSimpleMessage(self.allocator, "COMMIT");
        defer self.allocator.free(msg);
        try self.client.?.sendMessage(msg);
        const ack = try self.client.?.receiveMessage(2000);
        self.allocator.free(ack);
    }

    fn rollback(self: *ClientContext) !void {
        try self.ensureConnected(false);
        const msg = try buildSimpleMessage(self.allocator, "ROLLBACK");
        defer self.allocator.free(msg);
        try self.client.?.sendMessage(msg);
        const ack = try self.client.?.receiveMessage(2000);
        self.allocator.free(ack);
    }

    fn runQuery(self: *ClientContext, query: []const u8, params: ?JsonValue, verbose: bool) !QueryResult {
        try self.ensureConnected(verbose);

        const run_msg = try buildRunMessage(self.allocator, query, params);
        defer self.allocator.free(run_msg);
        try self.client.?.sendMessage(run_msg);

        const schema_raw = try self.client.?.receiveMessage(3000);
        defer self.allocator.free(schema_raw);
        var schema_parsed = try std.json.parseFromSlice(JsonValue, self.allocator, schema_raw, .{});
        defer schema_parsed.deinit();
        const schema_obj = try extractResultObject(schema_parsed.value);
        const res_type = getTypeString(schema_obj);
        if (std.mem.eql(u8, res_type, "ERROR")) {
            const msg = schema_obj.get("message");
            if (msg != null and msg.? == .string) {
                return error.QueryError;
            }
            return error.QueryError;
        }

        const columns = try parseColumns(self.allocator, schema_obj);
        errdefer {
            for (columns) |col| self.allocator.free(col);
            self.allocator.free(columns);
        }

        const pull_msg = try buildPullMessage(self.allocator, 1000);
        defer self.allocator.free(pull_msg);
        try self.client.?.sendMessage(pull_msg);

        var all_rows = try std.ArrayList(JsonValue).initCapacity(self.allocator, 0);
        errdefer {
            for (all_rows.items) |*row| freeJsonValue(self.allocator, row);
            all_rows.deinit(self.allocator);
        }

        while (true) {
            const resp_raw = try self.client.?.receiveMessage(3000);
            defer self.allocator.free(resp_raw);
            var parsed = try std.json.parseFromSlice(JsonValue, self.allocator, resp_raw, .{});
            defer parsed.deinit();
            const res_obj = try extractResultObject(parsed.value);
            const rtype = getTypeString(res_obj);
            if (std.mem.eql(u8, rtype, "PROFILE") or std.mem.eql(u8, rtype, "RESULT") or std.mem.eql(u8, rtype, "STATUS")) {
                break;
            }
            if (!std.mem.eql(u8, rtype, "BINDINGS")) return error.UnexpectedFrame;

            try appendRowsFromResult(self.allocator, res_obj, &all_rows);

            const final_val = res_obj.get("final");
            if (final_val != null and final_val.? == .bool and final_val.?.bool) {
                break;
            }
            try self.client.?.sendMessage(pull_msg);
        }

        const rows = try all_rows.toOwnedSlice(self.allocator);
        return QueryResult{ .columns = columns, .rows = rows };
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
    result: ?QueryResult = null,
    duration_ms: f64,
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
                ctx.ensureConnected(verbose) catch {
                    had_error = true;
                };
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
                ctx.close();
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

    var ctx = ClientContext{ .allocator = allocator, .host = config.host, .port = config.port };
    defer ctx.close();

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
