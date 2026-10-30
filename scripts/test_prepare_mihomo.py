import runpy
import unittest
from pathlib import Path


class PreparationTest(unittest.TestCase):
    def setUp(self):
        self.module = runpy.run_path(str(Path(__file__).with_name('prepare-mihomo.py')))
        self.source = self.module['TARGET'].read_bytes()
        for before, after in self.module['REPLACEMENTS']:
            self.source = self.source.replace(after.encode(), before.encode())

    def test_original_and_prepared_are_idempotent(self):
        prepare = self.module['prepared']
        result = prepare(self.source)
        self.assertEqual(prepare(result), result)
        self.assertEqual(prepare(self.source.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')), result)
        self.assertNotEqual(result, self.source.replace(b'\r\n', b'\n'))

    def test_unknown_source_is_rejected(self):
        changed = self.source + b'\n// Unreviewed upstream change\n'
        with self.assertRaises(ValueError):
            self.module['prepared'](changed)


if __name__ == '__main__':
    unittest.main()
