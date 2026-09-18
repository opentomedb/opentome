"""The measure gate reads a committed library snapshot the same way it reads readarr.db.
Run: python3 export/test_measure_fixture.py

Offline and self-contained: a two-series library is built twice in a temp dir -- as a
readarr.db-shaped SQLite (the tables measure_library.library() joins) and as the JSON
snapshot export/snapshot_library.py writes from it -- and measured against a tiny
artifact carrying only the columns measure_library.py reads. The assertion that matters:
measure() returns the same rows and the same failures from either input. A second set
of assertions pins what those rows must say, so the test cannot pass because both paths
are equally broken.
"""
import json, os, shutil, sqlite3, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import measure_library as M  # noqa: E402
import snapshot_library as S  # noqa: E402

FAILS = []


def eq(label, got, want):
    ok = got == want
    print(("  ok   " if ok else "  FAIL ") + label + ("" if ok else f"  got={got!r} want={want!r}"))
    if not ok:
        FAILS.append(label)


def make_artifact(path):
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE series (gcd_series_id INTEGER PRIMARY KEY, name TEXT NOT NULL, language TEXT,
            is_omnibus INTEGER NOT NULL DEFAULT 0, volume_count INTEGER NOT NULL DEFAULT 0,
            anilist_id INTEGER, medium TEXT, dated_count INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE volumes (id INTEGER PRIMARY KEY, gcd_series_id INTEGER NOT NULL,
            volume_number INTEGER NOT NULL, release_date TEXT);
        CREATE TABLE series_alias (gcd_series_id INTEGER NOT NULL, alias TEXT NOT NULL,
            UNIQUE (gcd_series_id, alias));
    """)
    # 1: matched by name; volumes 1-4, 3 owned, 4 released long ago -> "+1 (1 past)"
    db.execute("INSERT INTO series VALUES (1, 'Vinland Saga', 'en', 0, 4, 101, 'manga', 4)")
    for n in range(1, 5):
        db.execute("INSERT INTO volumes VALUES (NULL, 1, ?, '2000-01-0' || ?)", (n, n))
    # 2: matched only through the folder name (an alias); volumes 1-3, the library owns 5
    db.execute("INSERT INTO series VALUES (2, 'Witch Hat Atelier', 'en', 0, 3, NULL, 'manga', 3)")
    db.execute("INSERT INTO series_alias VALUES (2, 'Tongari Boushi no Atelier')")
    for n in range(1, 4):
        db.execute("INSERT INTO volumes VALUES (NULL, 2, ?, NULL)", (n,))
    db.commit()
    db.close()


def make_readarr(path):
    """The five tables library() joins, with the columns it touches and nothing else."""
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE AuthorMetadata (Id INTEGER PRIMARY KEY, Name TEXT NOT NULL, Status INTEGER NOT NULL);
        CREATE TABLE Authors (Id INTEGER PRIMARY KEY, AuthorMetadataId INTEGER NOT NULL, Path TEXT NOT NULL);
        CREATE TABLE Books (Id INTEGER PRIMARY KEY, AuthorMetadataId INTEGER NOT NULL, VolumeNumber INTEGER);
        CREATE TABLE Editions (Id INTEGER PRIMARY KEY, BookId INTEGER NOT NULL);
        CREATE TABLE BookFiles (Id INTEGER PRIMARY KEY, EditionId INTEGER NOT NULL);
    """)
    db.execute("INSERT INTO AuthorMetadata VALUES (10, 'Vinland Saga', 0)")
    db.execute("INSERT INTO Authors VALUES (1, 10, '/manga/Vinland Saga/')")
    db.execute("INSERT INTO AuthorMetadata VALUES (20, 'Atelier of Witch Hat', 1)")
    db.execute("INSERT INTO Authors VALUES (2, 20, '/manga/Tongari Boushi no Atelier')")
    # (book id, metadata id, volume number, number of files on disk)
    books = [(1, 10, 1, 1), (2, 10, 2, 2), (3, 10, 3, 1), (4, 10, 4, 0),   # v4 is a book without a file
             (5, 20, 1, 1), (6, 20, 2, 1), (7, 20, 5, 1), (8, 20, None, 1)]  # a NULL volume number is skipped
    fid = 0
    for bid, mid, num, files in books:
        db.execute("INSERT INTO Books VALUES (?, ?, ?)", (bid, mid, num))
        db.execute("INSERT INTO Editions VALUES (?, ?)", (bid, bid))
        for _ in range(files):
            fid += 1
            db.execute("INSERT INTO BookFiles VALUES (?, ?)", (fid, bid))
    db.commit()
    db.close()


def main():
    tmp = tempfile.mkdtemp(prefix="opentome-measure-")
    try:
        art = os.path.join(tmp, "manga-metadata.sqlite")
        lib = os.path.join(tmp, "readarr.db")
        fix = os.path.join(tmp, "library.json")
        make_artifact(art)
        make_readarr(lib)
        snap = S.snapshot(lib)
        with open(fix, "w", encoding="utf8") as f:
            json.dump(snap, f, indent=1, ensure_ascii=False)

        # -- the snapshot carries exactly the four public fields, as library() sees them
        eq("snapshot: one entry per series, in library() order", [s["name"] for s in snap],
           ["Atelier of Witch Hat", "Vinland Saga"])
        eq("snapshot: keys", sorted(snap[0]), ["folder", "name", "status", "volumes"])
        eq("snapshot: folder is the basename (trailing slash dropped), status as stored, volumes distinct+sorted",
           [(s["folder"], s["status"], s["volumes"]) for s in snap],
           [("Tongari Boushi no Atelier", 1, [1, 2, 5]), ("Vinland Saga", 0, [1, 2, 3])])
        from_db = [{k: v for k, v in s.items() if k != "id"} for s in M.library(lib)]
        from_fix = [{k: v for k, v in s.items() if k != "id"} for s in M.library(fix)]
        eq("library(): the fixture path yields the DB path's dicts (minus Mangarr ids)", from_fix, from_db)

        # -- the real assertion: measure() cannot tell the two inputs apart
        rows_db, fails_db = M.measure(art, lib, verbose=False)
        rows_fix, fails_fix = M.measure(art, fix, verbose=False)
        eq("measure(): same rows from readarr.db and from the fixture", rows_fix, rows_db)
        eq("measure(): same failures from readarr.db and from the fixture", fails_fix, fails_db)

        # -- and the rows say what a real measurement would say
        eq("row 1: folder alias matched, owned v5 missing from the picked line",
           rows_fix[0], ("Atelier of Witch Hat", 3, "Witch Hat Atelier [manga] v3 d3", "MISSING [5]", "+0 (0 past)", "--"))
        eq("row 2: name matched, all owned present, one past-dated volume beyond",
           rows_fix[1], ("Vinland Saga", 3, "Vinland Saga [manga] v4 d4", "OK", "+1 (1 past)", "--"))
        eq("failures name the series, the pick and the missing volumes",
           fails_fix, [("Atelier of Witch Hat", "Witch Hat Atelier", [5])])

        # -- the CLI accepts the fixture and exits non-zero on a coverage failure
        r = subprocess.run([sys.executable, os.path.join(HERE, "measure_library.py"), art, fix],
                           capture_output=True, text=True)
        eq("CLI: exit 1 on the coverage failure", r.returncode, 1)
        eq("CLI: prints the summary line", "matched 2/2   coverage failures 1" in r.stdout, True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILS:
        print(f"{len(FAILS)} FAILED: {FAILS}")
        sys.exit(1)
    print("all measure_fixture tests passed")


if __name__ == "__main__":
    main()
