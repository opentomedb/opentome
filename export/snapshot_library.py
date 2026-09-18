"""Snapshot the parts of a Mangarr library the measure gate needs, as a committed fixture.

    python3 export/snapshot_library.py /path/readarr.db export/fixtures/library.json

Series names, the library folder name, status and the volume numbers on disk -- nothing
else. Reads exactly what measure_library.library() reads from readarr.db (same joins,
same NOT NULL filter, same order), so measuring from the fixture and from the DB copy
gives the same rows. Run once on a host that has a readarr.db copy; the pipeline
itself never needs one.
"""
import json, os, sqlite3, sys


def snapshot(db_path):
    db = sqlite3.connect(db_path)
    rows = db.execute("""SELECT a.Id, am.Name, a.Path, am.Status FROM Authors a
                         JOIN AuthorMetadata am ON am.Id=a.AuthorMetadataId ORDER BY am.Name""").fetchall()
    out = []
    for aid, name, path, status in rows:
        vols = sorted({r[0] for r in db.execute("""
            SELECT b.VolumeNumber FROM BookFiles bf JOIN Editions e ON e.Id=bf.EditionId
            JOIN Books b ON b.Id=e.BookId JOIN Authors a ON a.AuthorMetadataId=b.AuthorMetadataId
            WHERE a.Id=? AND b.VolumeNumber IS NOT NULL""", (aid,))})
        out.append({"name": name, "folder": os.path.basename(path.rstrip("/")), "status": status, "volumes": vols})
    return out


if __name__ == "__main__":
    data = snapshot(sys.argv[1])
    with open(sys.argv[2], "w", encoding="utf8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
        f.write("\n")
    print("%d series -> %s" % (len(data), sys.argv[2]))
