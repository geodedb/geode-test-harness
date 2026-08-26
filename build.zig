const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});

    // Get the geode_client dependency from build.zig.zon
    const geode_client_dep = b.dependency("geode_client", .{
        .target = target,
        .optimize = optimize,
    });

    // Get the geode_client module exported by the dependency
    const geode_client_mod = geode_client_dep.module("geode_client");

    // Get the yaml module for parsing test specs
    const yaml_dep = b.dependency("yaml", .{
        .target = target,
        .optimize = optimize,
    });
    const yaml_mod = yaml_dep.module("yaml");

    // Build the test runner executable
    const runner = b.addExecutable(.{
        .name = "zig_runner",
        .root_module = b.createModule(.{
            .root_source_file = b.path("runners/zig_runner_new.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });

    // Link system libraries
    runner.root_module.link_libc = true;
    runner.root_module.linkSystemLibrary("ssl", .{});
    runner.root_module.linkSystemLibrary("crypto", .{});
    if (target.result.os.tag == .linux) {
        runner.root_module.linkSystemLibrary("dl", .{});
    }

    // Add modules to the runner
    runner.root_module.addImport("geode_client", geode_client_mod);
    runner.root_module.addImport("yaml", yaml_mod);

    b.installArtifact(runner);

    // Run command
    const run_runner = b.addRunArtifact(runner);
    run_runner.step.dependOn(b.getInstallStep());

    if (b.args) |args| {
        run_runner.addArgs(args);
    }

    const run_step = b.step("run", "Run the test runner");
    run_step.dependOn(&run_runner.step);

    // Test step
    const test_step = b.step("test", "Run unit tests");

    const runner_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("runners/zig_runner_new.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    runner_tests.root_module.addImport("geode_client", geode_client_mod);
    runner_tests.root_module.addImport("yaml", yaml_mod);

    const run_tests = b.addRunArtifact(runner_tests);
    test_step.dependOn(&run_tests.step);
}
