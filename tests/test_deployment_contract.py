from pathlib import Path


def test_update_script_initializes_additive_database_schema_before_restart():
    script = (Path(__file__).resolve().parents[1] / "update.sh").read_text(
        encoding="utf-8"
    )

    maintenance_index = script.index("database_maintenance.py")
    restart_index = script.index("systemctl restart codesense")

    assert "set -e" in script
    assert maintenance_index < restart_index
