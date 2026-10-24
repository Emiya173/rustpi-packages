#!/usr/bin/env python3
"""Allow publication retries only from validated builds of this repository's main."""
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
REPO = json.loads((ROOT / 'ci/pins.json').read_text())['repository']


def validate(run, jobs):
    assert run['head_repository']['full_name'] == REPO, 'Foreign repository'
    assert run['head_branch'] == 'main', 'Only main builds may be published'
    assert run['path'] == '.github/workflows/repository.yml', 'Unexpected source workflow'
    assert run['event'] in ('push', 'schedule', 'workflow_dispatch'), 'Untrusted trigger'
    assert run['status'] == 'completed', 'Wait until the source run finishes'
    assert any(j['name'] == 'plan' and j['conclusion'] == 'success' for j in jobs)
    builds = [j for j in jobs if j['name'].startswith('build (')]
    assert builds and all(j['conclusion'] == 'success' for j in builds), 'A build or validation failed'
    assert {j['name'] for j in builds} <= {'build (kernel)', 'build (ffmpeg)', 'build (integration)'}
    assert re.fullmatch(r'[0-9a-f]{40}', run['head_sha'])
    return run['head_sha']


def main():
    run_id = os.environ['SOURCE_RUN_ID']
    assert re.fullmatch(r'[1-9][0-9]*', run_id)
    def api(path):
        return json.loads(subprocess.check_output(['gh', 'api', f'repos/{REPO}/' + path], text=True))
    run = api('actions/runs/' + run_id)
    jobs = api('actions/runs/' + run_id + '/jobs?per_page=100')['jobs']
    sha = validate(run, jobs)
    with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
        output.write(f'sha={sha}\nrun={run_id}\n')
    print(f'Validated source run {run_id}, commit {sha}')


if __name__ == '__main__':
    main()
