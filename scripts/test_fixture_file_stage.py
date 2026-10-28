#!/usr/bin/env python3
"""Exercise the actual shell publisher with a deliberately incomplete stdin."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from fixture_file_stage import FOLDER, atomic_stage_script

SHELL = shutil.which('sh')


class FilePublication(unittest.TestCase):
    def test_only_known_private_files_are_accepted(self):
        for name in ('../peer-result.json', 'peer-result.json;echo bad', 'unknown', ''):
            with self.assertRaises(ValueError):
                atomic_stage_script(name)

    @unittest.skipUnless(SHELL, 'POSIX shell unavailable; Linux CI runs this case')
    def test_reader_never_observes_truncated_completion(self):
        with tempfile.TemporaryDirectory(prefix='cmfa-file-publish-') as folder:
            root = Path(folder)
            destination = root / FOLDER / 'peer-result.json'
            for previous in (None, b'{"passed":false}'):
                if previous is not None:
                    destination.write_bytes(previous)
                writer = subprocess.Popen([SHELL, '-c', atomic_stage_script('peer-result.json')],
                                          cwd=root, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                          stderr=subprocess.PIPE)
                try:
                    writer.stdin.write(b'{"passed":')
                    writer.stdin.flush()
                    until = time.monotonic() + 5
                    while not list(destination.parent.glob('peer-result.json.pending.*')):
                        if writer.poll() is not None or time.monotonic() >= until:
                            self.fail('Private staged write did not start')
                        time.sleep(.01)
                    # This is the precise formerly racy window: the writer has
                    # created a file and is blocked waiting for the rest of JSON.
                    for _ in range(100):
                        if previous is None:
                            self.assertFalse(destination.exists())
                        else:
                            self.assertEqual(destination.read_bytes(), previous)
                    writer.stdin.write(b'true}')
                    writer.stdin.close()
                    self.assertEqual(writer.wait(timeout=5), 0)
                    self.assertEqual(json.loads(destination.read_bytes()), {'passed': True})
                    if os.name == 'posix':
                        self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
                    self.assertFalse(list(destination.parent.glob('peer-result.json.pending.*')))
                finally:
                    if writer.poll() is None:
                        writer.terminate()
                        writer.wait(timeout=5)
                    if not writer.stdin.closed:
                        writer.stdin.close()
                    writer.stderr.close()


if __name__ == '__main__':
    unittest.main()
