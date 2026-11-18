from __future__ import annotations
import os
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from debug_gui import Debugger, dependency_summary

@unittest.skipUnless(os.environ.get('LYCEE_TEST_GUI') == '1', 'Run explicitly with make test-gui or make test-gui-headless')
class GUISmokeTest(unittest.TestCase):
    def test_example_loads(self):
        gui = Debugger()
        try:
            gui._example()
            self.assertEqual(len(gui.lectures), 5)
            self.assertTrue(gui.student_rows)
            self.assertEqual(len(dependency_summary(gui.input_rows, gui.student_rows)), 3)
        finally:
            gui.destroy()

if __name__ == '__main__':
    unittest.main()
