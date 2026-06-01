import subprocess


def test_panel_dashboard_runtime_exercises_all_workbenches_and_actions():
    result = subprocess.run(
        ["node", "tests/panel_dashboard_runtime_check.js"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
