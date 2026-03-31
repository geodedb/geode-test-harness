import pexpect, os
env = os.environ.copy()
env["TERM"] = "dumb"
child = pexpect.spawn("../geode/zig-out/bin/geode shell --format json --no-history", encoding="utf-8", env=env)
child.setecho(False)
child.expect(r"geode(?:\([^)]+\))?>\s*")
child.sendline("RETURN 1 AS x")
child.expect(r"geode(?:\([^)]+\))?>\s*")
print("BEFORE:")
print(repr(child.before))
