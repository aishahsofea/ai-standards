import os
import sys

from pipeline.checks import CheckRun, baseline_report, run_checks


def test_run_checks_reports_pass_fail_and_the_output_tail(tmp_path):
    fail = f'{sys.executable} -c "import sys; print(\'boom\'); sys.exit(3)"'
    ok, failed, missing = run_checks((f"{sys.executable} -c pass", fail, "no-such-command-xyz"), tmp_path, dict(os.environ))
    assert ok == CheckRun(f"{sys.executable} -c pass", True)
    assert not failed.ok and failed.tail == "boom"
    assert not missing.ok and "no-such-command-xyz" in missing.tail


def test_baseline_report_lists_only_failing_checks():
    assert baseline_report([CheckRun("a", True)]) == "Every check passed before this branch changed anything: `a`."
    report = baseline_report([CheckRun("a", True), CheckRun("b", False, "1 failed")])
    assert "### `b`" in report and "1 failed" in report and "`a`" not in report
