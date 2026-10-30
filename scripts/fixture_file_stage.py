"""Atomic private-file publication shared by the Android test runners."""

FILES = frozenset({
    'physical-consent', 'mesh.toml', 'ci-peer-guard', 'ci-reject-port',
    'peer-result.json', 'mode-request.json', 'rebuild-request',
    'ci-proxy.json', 'network-options-request.json',
})
FOLDER = 'no_backup/native-mesh-acceptance/'


def atomic_stage_script(name):
    if name not in FILES:
        raise ValueError('Unsupported private fixture file')
    target = FOLDER + name
    # The reader uses existence of peer-result.json as a completion signal.
    # Opening that path for cat exposes a zero-length file before stdin arrives.
    # A same-directory rename publishes only the completed write. No input data
    # or configurable path is interpolated into shell code.
    return ('set -e\numask 077\nmkdir -p ' + FOLDER + '\n'
            'tmp=' + target + '.pending.$$\n'
            'trap \'rm -f "$tmp"\' EXIT\n'
            'cat > "$tmp"\n'
            'mv -f "$tmp" ' + target)
