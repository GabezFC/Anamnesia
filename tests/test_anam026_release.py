"""ANAM-026: release hygiene, backup/restore round-trip and license allow-list."""
from __future__ import annotations

import json
import re
import sqlite3
import zipfile
from pathlib import Path

import pytest

from app.cli.main import build_parser, main
from app.services import license_policy as lp
from app.services.backup import BackupError, create_backup, restore_backup, verify_backup

ROOT = Path(__file__).resolve().parent.parent


def _make_store(tmp_path):
    db = tmp_path / "src" / "benchmark.db"
    db.parent.mkdir()
    con = sqlite3.connect(db)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("create table t(x text)")
    con.executemany("insert into t values (?)", [("a",), ("b",)])
    con.commit()                                  # row data may still live only in the -wal file
    mem = tmp_path / "src" / "saved_context"
    (mem / "sub").mkdir(parents=True)
    (mem / "n1.md").write_text("# um\n", encoding="utf-8")
    (mem / "sub" / "n2.md").write_text("dois\n", encoding="utf-8")
    return con, db, mem


# ---------------------------------------------------------------- backup / restore
def test_round_trip_in_temp_dir(tmp_path):
    con, db, mem = _make_store(tmp_path)
    before = {p: p.read_bytes() for p in mem.rglob("*.md")}
    arc = tmp_path / "b.zip"
    info = create_backup(arc, db, mem)
    con.close()
    assert info["files"] == 3 and len(info["archive_sha256"]) == 64
    assert verify_backup(arc)["format"] == 1

    dst = tmp_path / "dst"
    out = restore_backup(arc, dst / "benchmark.db", dst / "mem")
    assert out["restored"] == 3 and not out["overwrote"]
    got = sqlite3.connect(dst / "benchmark.db")
    assert [r[0] for r in got.execute("select x from t order by x")] == ["a", "b"]
    got.close()
    for p, data in before.items():
        assert (dst / "mem" / p.relative_to(mem)).read_bytes() == data


def test_restore_refuses_overwrite_without_force(tmp_path):
    con, db, mem = _make_store(tmp_path)
    arc = tmp_path / "b.zip"
    create_backup(arc, db, mem)
    con.close()
    target = tmp_path / "t.db"
    target.write_bytes(b"precious")
    with pytest.raises(BackupError, match="--force"):
        restore_backup(arc, target, tmp_path / "m")
    assert target.read_bytes() == b"precious"
    assert not (tmp_path / "m").exists()                       # nothing written on refusal
    assert restore_backup(arc, target, tmp_path / "m", force=True)["overwrote"]
    assert target.read_bytes() != b"precious"


def test_create_refuses_existing_archive(tmp_path):
    con, db, mem = _make_store(tmp_path)
    con.close()
    arc = tmp_path / "b.zip"
    create_backup(arc, db, mem)
    with pytest.raises(BackupError):
        create_backup(arc, db, mem)
    create_backup(arc, db, mem, force=True)


def test_source_untouched_and_corruption_detected(tmp_path):
    con, db, mem = _make_store(tmp_path)
    con.close()
    snap = {p: p.read_bytes() for p in mem.rglob("*.md")}
    arc = tmp_path / "b.zip"
    create_backup(arc, db, mem)
    assert snap == {p: p.read_bytes() for p in mem.rglob("*.md")}

    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(arc) as zi, zipfile.ZipFile(bad, "w") as zo:
        for n in zi.namelist():
            data = zi.read(n)
            zo.writestr(n, b"tampered" if n == "memory/n1.md" else data)
    with pytest.raises(BackupError, match="sha256"):
        verify_backup(bad)
    dst = tmp_path / "d"
    with pytest.raises(BackupError):
        restore_backup(bad, dst / "x.db", dst / "m")
    assert not dst.exists()


def test_path_traversal_rejected(tmp_path):
    arc = tmp_path / "evil.zip"
    import hashlib
    data = b"x"
    manifest = {"format": 1, "files": [{"name": "memory/../../evil.md", "size": 1,
                                        "sha256": hashlib.sha256(data).hexdigest()}]}
    with zipfile.ZipFile(arc, "w") as z:
        z.writestr("manifest.json", json.dumps(manifest))
        z.writestr("memory/../../evil.md", data)
    with pytest.raises(BackupError):
        restore_backup(arc, None, tmp_path / "m")


def test_cli_registered_and_round_trip(tmp_path, capsys):
    names = build_parser()._subparsers._group_actions[0].choices  # noqa: SLF001
    assert {"backup-create", "backup-restore"} <= set(names)
    con, db, mem = _make_store(tmp_path)
    con.close()
    arc = tmp_path / "cli.zip"
    main(["backup-create", "--out", str(arc), "--db", str(db), "--memory-dir", str(mem)])
    assert json.loads(capsys.readouterr().out)["files"] == 3
    main(["backup-restore", str(arc), "--verify-only"])
    assert json.loads(capsys.readouterr().out)["ok"] is True
    dst = tmp_path / "r"
    main(["backup-restore", str(arc), "--db", str(dst / "b.db"), "--memory-dir", str(dst / "m")])
    assert (dst / "b.db").is_file()
    with pytest.raises(SystemExit):                         # second restore without --force fails
        main(["backup-restore", str(arc), "--db", str(dst / "b.db"), "--memory-dir", str(dst / "m")])


# ---------------------------------------------------------------- licenses
def test_policy_classification():
    assert lp.classify("Apache-2.0") == "allowed" and lp.classify("MIT") == "allowed"
    assert lp.classify("qwen") == "restricted" and lp.classify("Qwen Community") == "restricted"
    assert lp.classify("CC BY-NC-ND 4.0".replace(" ", "-")) == "non_commercial"
    assert lp.classify(None) == "unknown"


def test_model_catalog_respects_allow_list():
    cat = json.loads((ROOT / "config" / "model_catalog.json").read_text(encoding="utf-8"))
    for m in cat["models"]:
        if m["license_status"] == "VERIFIED":
            assert lp.classify(m["license"]) == "allowed", (m["id"], m["license"])
            assert m["commercial_use"] is True, m["id"]
        else:                                               # unknown never silently allowed
            assert lp.classify(m["license"]) in {"unknown"} or m["license"] is None, m["id"]
            assert m["commercial_use"] is not True, m["id"]


def test_dependency_licenses_on_allow_list():
    text = (ROOT / "THIRD_PARTY_LICENSES.md").read_text(encoding="utf-8")
    head = text.split("## Optional components")[0]
    rows = re.findall(r"^\| ([A-Za-z0-9_.\-]+) \| [^|]+ \| ([^|]+) \|", head, flags=re.M)
    rows = [(n, lic.strip()) for n, lic in rows if n != "Package"]
    assert len(rows) >= 9
    bad = [(n, lic) for n, lic in rows if lp.classify_metadata_string(lic) not in {"allowed", "weak_copyleft"}]
    assert not bad, bad


def test_provence_is_optional_and_off_by_default(monkeypatch):
    from config.optimization import OptionalStagesConfig  # noqa: PLC0415

    monkeypatch.delenv("OPT_STAGE_PROVENCE", raising=False)
    monkeypatch.delenv("MG_OPT_STAGE_PROVENCE", raising=False)

    assert "provence" in lp.NON_COMMERCIAL_STAGES
    assert OptionalStagesConfig().provence is False
    example = json.loads((ROOT / "config" / "local_settings.example.json").read_text(encoding="utf-8"))
    assert example["optional_stages"]["provence"] is False
    req = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    assert "provence" not in req
    notices = (ROOT / "THIRD_PARTY_LICENSES.md").read_text(encoding="utf-8")
    assert "CC BY-NC-ND" in notices


# ---------------------------------------------------------------- release files
def test_notices_cover_required_components():
    n = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert re.search(r"Colibr.*Apache-2\.0", n) and re.search(r"Laya.*Apache-2\.0", n)
    assert re.search(r"ds4.*MIT", n) and "CC BY-NC-ND" in n
    assert (ROOT / "NOTICE").is_file()


def test_changelog_dependabot_and_lock_hashes():
    assert "ANAM-026" in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "package-ecosystem" in (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    lock = (ROOT / "requirements.lock").read_text(encoding="utf-8")
    pins = re.findall(r"^([A-Za-z0-9_.\-]+)==([^\s\\]+)", lock, flags=re.M)
    assert len(pins) >= 10
    assert lock.count("--hash=sha256:") >= len(pins)
    # lock must not drift from the pinned runtime versions
    locked = {n.lower().replace("_", "-"): v for n, v in pins}
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Za-z0-9_.\-]+)(?:\[[^\]]*\])?==([^\s;#]+)", line)
        if m:
            assert locked[m.group(1).lower().replace("_", "-")] == m.group(2), m.group(1)
