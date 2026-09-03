from __future__ import annotations

import ast
import inspect
import textwrap
import unittest

from loomarr_models import training


class TrainingImportOrderTests(unittest.TestCase):
    def test_unsloth_is_imported_before_training_stack(self):
        tree = ast.parse(textwrap.dedent(inspect.getsource(training.run_training)))
        modules = [
            node.module if isinstance(node, ast.ImportFrom) else node.names[0].name
            for node in tree.body[0].body
            if isinstance(node, (ast.Import, ast.ImportFrom))
        ]
        self.assertEqual(modules[:2], ["unsloth", "unsloth.chat_templates"])
        self.assertLess(modules.index("unsloth"), modules.index("torch"))
        self.assertLess(modules.index("unsloth"), modules.index("trl"))


if __name__ == "__main__":
    unittest.main()
