#!/usr/bin/env python3
"""Apply the reviewed REJECT ownership fix to the pinned Mihomo checkout.

No network, fuzzy patching, dependency upgrades or module-cache modifications.
Unknown input stops the build instead of silently discarding upstream edits.
"""
import hashlib
import os
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / 'core/src/foss/golang/clash/adapter/outbound/reject.go'
UPSTREAM_SHA256 = 'a770352925769f858b7849d1082e8b7004d492dd47f7d5925798323a7e14b62d'
REPLACEMENTS = [
    (f'func (rw {kind}) WriteBuffer(buffer *buf.Buffer) error {{ return io.EOF }}',
     f'func (rw {kind}) WriteBuffer(buffer *buf.Buffer) error {{\n'
     '\tbuffer.Release()\n\treturn io.EOF\n}')
    for kind in ('nopConn', 'dropConn')
]


def prepared(content):
    source = content.replace(b'\r\n', b'\n').decode('utf-8')
    original = source
    for before, after in REPLACEMENTS:
        if original.count(after) == 1:
            original = original.replace(after, before)
    if hashlib.sha256(original.encode()).hexdigest() != UPSTREAM_SHA256:
        raise ValueError('Pinned Mihomo REJECT source differs; review before building')
    for before, after in REPLACEMENTS:
        original = original.replace(before, after)
    return original.encode()


def main():
    before = TARGET.read_bytes()
    after = prepared(before)
    if before.replace(b'\r\n', b'\n') != after:
        with tempfile.NamedTemporaryFile(dir=TARGET.parent, prefix='.reject-', delete=False) as pending:
            pending.write(after)
            name = Path(pending.name)
        try:
            os.chmod(name, TARGET.stat().st_mode)
            os.replace(name, TARGET)
        finally:
            name.unlink(missing_ok=True)
    print('Pinned Mihomo REJECT buffer ownership fix verified')


if __name__ == '__main__':
    main()
