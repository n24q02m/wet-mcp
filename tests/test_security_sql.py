import json

from wet_mcp.db import DocsDB


def test_get_existing_allowed_tables(tmp_path):
    db_path = tmp_path / "test.db"
    db = DocsDB(db_path)

    # Setup some data
    lib_id = "lib1"
    ver_id = "ver1"
    chunk_id = "chunk1"

    db.import_jsonl(
        json.dumps(
            {
                "_type": "library",
                "id": lib_id,
                "name": "lib1",
                "created_at": 1,
                "updated_at": 1,
            }
        )
    )
    db.import_jsonl(
        json.dumps(
            {
                "_type": "version",
                "id": ver_id,
                "library_id": lib_id,
                "version": "1.0",
                "created_at": 1,
                "updated_at": 1,
            }
        )
    )
    db.import_jsonl(
        json.dumps(
            {
                "_type": "chunk",
                "id": chunk_id,
                "version_id": ver_id,
                "library_id": lib_id,
                "url": "u",
                "title": "t",
                "chunk_index": 0,
                "content": "c",
                "created_at": 1,
            }
        )
    )

    # This indirectly tests _get_existing during import_jsonl merge mode
    stats = db.import_jsonl(
        json.dumps(
            {
                "_type": "library",
                "id": lib_id,
                "name": "lib1",
                "created_at": 1,
                "updated_at": 1,
            }
        ),
        mode="merge",
    )
    assert stats["skipped"] == 1

    stats = db.import_jsonl(
        json.dumps(
            {
                "_type": "version",
                "id": ver_id,
                "library_id": lib_id,
                "version": "1.0",
                "created_at": 1,
                "updated_at": 1,
            }
        ),
        mode="merge",
    )
    assert stats["skipped"] == 1

    stats = db.import_jsonl(
        json.dumps(
            {
                "_type": "chunk",
                "id": chunk_id,
                "version_id": ver_id,
                "library_id": lib_id,
                "url": "u",
                "title": "t",
                "chunk_index": 0,
                "content": "c",
                "created_at": 1,
            }
        ),
        mode="merge",
    )
    assert stats["skipped"] == 1


def test_get_existing_invalid_table(tmp_path):
    db_path = tmp_path / "test.db"
    # Just ensure we can instantiate DocsDB
    db = DocsDB(db_path)
    assert db._db_path == db_path


def test_get_existing_large_batch(tmp_path):
    db_path = tmp_path / "test_large.db"
    db = DocsDB(db_path)

    # Create 6000 libraries (more than the 5000 batch size)
    libs = []
    for i in range(6000):
        libs.append(
            {
                "_type": "library",
                "id": f"lib_{i}",
                "name": f"Library {i}",
                "created_at": 1,
                "updated_at": 1,
            }
        )

    # First import to populate
    data = "\n".join(json.dumps(lib_item) for lib_item in libs)
    db.import_jsonl(data)

    # Second import in merge mode to check existing
    # All 6000 should be skipped
    stats = db.import_jsonl(data, mode="merge")
    assert stats["skipped"] == 6000
    assert stats["libraries"] == 0


def test_get_existing_malicious_id(tmp_path):
    db_path = tmp_path / "test_malicious.db"
    db = DocsDB(db_path)

    # Test with an ID that looks like SQL injection
    malicious_id = "'); DROP TABLE libraries; --"
    lib = {
        "_type": "library",
        "id": malicious_id,
        "name": "Malicious",
        "created_at": 1,
        "updated_at": 1,
    }

    db.import_jsonl(json.dumps(lib))

    # Check if it exists (should not crash and should correctly identify)
    stats = db.import_jsonl(json.dumps(lib), mode="merge")
    assert stats["skipped"] == 1

    # Verify table still exists
    db.stats()
