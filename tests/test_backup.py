"""Nightly backup (backup.py): a zip a day, photos mirrored, old days thinned to one a month, restore."""
import datetime as dt
import sqlite3
import zipfile

from sanae.backup import Backup, restore


def make_root(tmp_path):
    root = tmp_path / "root"
    (root / "data" / "scrapbook").mkdir(parents=True)
    db = sqlite3.connect(root / "data" / "sanae.db")
    db.execute("CREATE TABLE t (x TEXT)")
    db.execute("INSERT INTO t VALUES ('hello')")
    db.commit()
    db.close()
    (root / "persona.yaml").write_text("name: Sanae\n")
    (root / "data" / "scrapbook" / "1.jpg").write_bytes(b"jpeg")
    return root


def test_backup_zip_mirror_and_prune(tmp_path):
    root = make_root(tmp_path)
    now = {"t": dt.datetime(2026, 10, 27, 5, 0).timestamp()}
    b = Backup(tmp_path / "out", keep_days=3, root=root, clock=lambda: now["t"],
               databases=["data/sanae.db"], small_files=["persona.yaml", "data/missing.txt"], folders=["data/scrapbook"])
    assert b.due()
    info = b.run()
    assert info["day"] == "2026-10-27" and info["copied"] == 1 and not b.due()
    with zipfile.ZipFile(tmp_path / "out" / "sanae-2026-10-27.zip") as z:
        assert sorted(z.namelist()) == ["data/sanae.db", "persona.yaml"]
    assert (tmp_path / "out" / "files" / "data" / "scrapbook" / "1.jpg").read_bytes() == b"jpeg"
    assert b.run()["copied"] == 0                         # unchanged files aren't copied again
    (root / "data" / "scrapbook" / "1.jpg").unlink()      # deleted here -> deleted in the backup too
    assert b.run()["removed"] == 1
    # 3 AM still counts as the day before
    now["t"] = dt.datetime(2026, 10, 28, 3, 0).timestamp()
    assert not b.due()
    # thinning: every day for keep_days, then the first of each month
    for day in ["2026-08-15", "2026-08-20", "2026-09-01", "2026-09-30", "2026-10-25"]:
        (tmp_path / "out" / f"sanae-{day}.zip").write_bytes(b"")
    b.prune()
    left = sorted(p.stem[6:] for p in b.zips())
    assert left == ["2026-08-15", "2026-09-01", "2026-10-25", "2026-10-27"]
    assert b.spoken().startswith("Last backup was today. I'm keeping 4")


def test_restore_keeps_the_current_copy(tmp_path):
    root = make_root(tmp_path)
    b = Backup(tmp_path / "out", root=root, clock=lambda: dt.datetime(2026, 10, 27, 12).timestamp(),
               databases=["data/sanae.db"], small_files=[], folders=["data/scrapbook"])
    b.run()
    db = sqlite3.connect(root / "data" / "sanae.db")
    db.execute("DELETE FROM t")
    db.commit()
    db.close()
    (root / "data" / "scrapbook" / "1.jpg").unlink()
    assert restore("2026-10-27", b) == ["data/sanae.db"]
    db = sqlite3.connect(root / "data" / "sanae.db")
    assert db.execute("SELECT x FROM t").fetchall() == [("hello",)]
    db.close()
    assert (root / "data" / "sanae.db.before-restore").is_file()
    assert (root / "data" / "scrapbook" / "1.jpg").read_bytes() == b"jpeg"
