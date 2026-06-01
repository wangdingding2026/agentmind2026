from pathlib import Path
from fnmatch import fnmatch


def test_package_data_includes_nested_panel_static_assets():
    import tomllib

    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["tool"]["setuptools"]["package-data"]["agentmind"] == [
        "panel/static/**",
    ]


def test_package_data_patterns_cover_all_panel_static_files():
    import tomllib

    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    patterns = pyproject["tool"]["setuptools"]["package-data"]["agentmind"]
    static_files = [
        path.relative_to("src/agentmind").as_posix()
        for path in Path("src/agentmind/panel/static").rglob("*")
        if path.is_file()
    ]

    assert static_files
    assert [
        path for path in static_files
        if not any(fnmatch(path, pattern) for pattern in patterns)
    ] == []


def test_sqlite_vec_is_optional_not_required_for_default_install():
    import tomllib

    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert "sqlite-vec>=0.1.0" not in pyproject["project"]["dependencies"]
    assert pyproject["project"]["optional-dependencies"]["vector"] == [
        "sqlite-vec>=0.1.0",
    ]
