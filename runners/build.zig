const std = @import("std");
const quic_vendor_setup = @import("vendor_quic_setup.zig");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});

    // Build the test runner executable
    const runner = b.addExecutable(.{
        .name = "zig_runner",
        .root_module = b.createModule(.{
            .root_source_file = b.path("zig_runner_new.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });

    runner.linkLibC();
    runner.linkSystemLibrary("ssl");
    runner.linkSystemLibrary("crypto");
    if (target.result.os.tag == .linux) {
        runner.linkSystemLibrary("dl");
    }

    const quic_modules = quic_vendor_setup.setupModules(b, "../../../vendor/quic", target, optimize);

    // Geode client built on shared vendor/quic implementation
    const client_mod = b.createModule(.{
        .root_source_file = b.path("../../zig/geode_client_v2.zig"),
        .target = target,
        .optimize = optimize,
    });
    client_mod.addImport("vendor_quic", quic_modules.quic_api);

    // Create YAML parser module
    const yaml_mod = b.createModule(.{
        .root_source_file = b.path("../../../src/util/yaml.zig"),
        .target = target,
        .optimize = optimize,
    });

    // Add modules to the runner
    runner.root_module.addImport("geode_client", client_mod);
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
}
