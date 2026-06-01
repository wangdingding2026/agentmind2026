from pathlib import Path


def test_package_data_includes_nested_panel_static_assets():
    import tomllib

    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["tool"]["setuptools"]["package-data"]["agentmind"] == [
        "panel/static/**",
    ]
