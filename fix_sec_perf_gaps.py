import sys

def replace_in_file(path, old, new):
    with open(path, 'r') as f:
        content = f.read()
    if old in content:
        content = content.replace(old, new)
        with open(path, 'w') as f:
            f.write(content)

# Update PERF_GAP_ANALYSIS.md
with open('docs/PERF_GAP_ANALYSIS.md', 'r') as f:
    perf_content = f.read()

perf_content = perf_content.replace('**Accepted**', '**Blocked**')
perf_content = perf_content.replace('**Deferred**', '**Blocked**')
perf_content = perf_content.replace('Status: Accepted', 'Status: Blocked')
perf_content = perf_content.replace('Status: Deferred', 'Status: Blocked')
perf_content = perf_content.replace('Accepted because', 'Blocked because')
perf_content = perf_content.replace('Deferral rationale', 'Blocker rationale')

with open('docs/PERF_GAP_ANALYSIS.md', 'w') as f:
    f.write(perf_content)

# Update SECURITY_GAP_ANALYSIS.md
with open('docs/SECURITY_GAP_ANALYSIS.md', 'r') as f:
    sec_content = f.read()

sec_content = sec_content.replace('**Accepted**', '**Blocked**')
sec_content = sec_content.replace('Accepted Risks', 'Blocked Risks')

with open('docs/SECURITY_GAP_ANALYSIS.md', 'w') as f:
    f.write(sec_content)

# Update QUALITY_GAP_ANALYSIS.md
with open('docs/QUALITY_GAP_ANALYSIS.md', 'r') as f:
    qg_content = f.read()

qg_content = qg_content.replace('| Deferred |', '| Blocked |')
qg_content = qg_content.replace(' Deferred ', ' Blocked ')

with open('docs/QUALITY_GAP_ANALYSIS.md', 'w') as f:
    f.write(qg_content)

print('Updated files to use Blocked instead of Accepted/Deferred.')
