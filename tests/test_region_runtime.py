import importlib.util
from pathlib import Path
import unittest


class RegionRuntimeTests(unittest.TestCase):
    def test_independent_ledger_failure_points_and_production_dependencies(self):
        path = Path('scripts/check-region-runtime.py').resolve()
        spec = importlib.util.spec_from_file_location('region_runtime_gate', path)
        gate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gate)
        report = gate.verify()
        self.assertTrue(report['ok'])
        self.assertEqual(12, report['positive_executions'])
        self.assertEqual(72, report['negative_trap_executions'])
        for capacity in (1, 32, 4096):
            layouts = [row['layout'] for row in report['executions'] if row['layout']['capacity'] == capacity]
            self.assertEqual(4, len(layouts))
            self.assertTrue(all(layout == layouts[0] for layout in layouts))
        self.assertEqual('C-runtime-only; no Talven lifetime checking', report['validation'])


if __name__ == '__main__':
    unittest.main()
