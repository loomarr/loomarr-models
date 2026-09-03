from __future__ import annotations

import ast
import inspect
import textwrap
import unittest

from loomarr_models import training
from loomarr_models.experiment import PreflightError


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

    def test_a40_marketed_memory_is_checked_in_decimal_gb(self):
        execution = {"gpuSku": "NVIDIA A40", "minimumVramGb": 48}
        training._validate_gpu("NVIDIA A40", 47_708_110_848, execution)
        with self.assertRaisesRegex(PreflightError, "outside the experiment envelope"):
            training._validate_gpu("NVIDIA A40", 46_999_999_999, execution)


if __name__ == "__main__":
    unittest.main()
