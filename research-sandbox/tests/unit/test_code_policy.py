import pytest

from sandbox_service.code_policy import CodePolicyChecker, CodePolicyViolation


VALID_ANALYSIS = """
import pandas as pd
import numpy as np
import json
import pathlib
from sandbox_sdk import load_dataset, emit_result, emit_table

df = load_dataset()
summary = df.describe()
emit_table("summary", summary.reset_index())
emit_result({"schema_version": "analysis_result.v1", "method": "describe"})
"""


def test_allowlisted_analysis_using_sdk_passes_policy() -> None:
    result = CodePolicyChecker().check(VALID_ANALYSIS)

    assert result.allowed
    assert result.violations == []
    assert result.node_count > 0


@pytest.mark.parametrize(
    "source",
    [
        "from sandbox_sdk import emit_result\nexec('emit_result({})')",
        "from sandbox_sdk import emit_result\neval('1 + 1')\nemit_result({})",
        "import os\nfrom sandbox_sdk import emit_result\nemit_result({})",
        "import sys\nfrom sandbox_sdk import emit_result\nemit_result({})",
        "import subprocess\nfrom sandbox_sdk import emit_result\nemit_result({})",
        "import socket\nfrom sandbox_sdk import emit_result\nemit_result({})",
        "from sandbox_sdk import emit_result\nopen('/etc/passwd').read()\nemit_result({})",
        "from sandbox_sdk import emit_result\n__import__('os')\nemit_result({})",
        "from sandbox_sdk import emit_result\nitems = [0] * (10 ** 9)\nemit_result({})",
        "from sandbox_sdk import emit_result\nwhile True:\n    pass\nemit_result({})",
        "import pandas as pd\nfrom sandbox_sdk import emit_result\npd.read_csv('/etc/passwd')\nemit_result({})",
        "import pandas as pd\nfrom sandbox_sdk import emit_result\nsecrets = pd.io.common.os.environ\nemit_result({'secrets': str(secrets)})",
        "import pyarrow.fs as fs\nfrom sandbox_sdk import emit_result\nclient = fs.S3FileSystem()\nemit_result({})",
    ],
)
def test_adversarial_code_is_rejected_before_execution(source: str) -> None:
    checker = CodePolicyChecker()
    result = checker.check(source)

    assert not result.allowed
    with pytest.raises(CodePolicyViolation):
        checker.ensure_allowed(source)
