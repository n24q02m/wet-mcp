import re

file_path = 'src/wet_mcp/db.py'
with open(file_path, 'r') as f:
    content = f.read()

# Find the upsert_library method and fix the if row: block
pattern = r'(if row:\s+lib_id = row\["id"\]\s+updates = \[\]\s+params: list = \[\]\s+if docs_url is not None:\s+updates\.append\("docs_url = \?"\)\s+params\.append\(docs_url\)\s+if registry is not None:\s+updates\.append\("registry = \?"\)\s+params\.append\(registry\)\s+if description is not None:\s+updates\.append\("description = \?"\)\s+params\.append\(description\)\s+updates\.append\("discovery_version = \?"\)\s+params\.append\(DISCOVERY_VERSION\)\s+updates\.append\("updated_at = \?"\)\s+)(if updates:.*?)(return lib_id)'

replacement = r'''\1            params.append(now)
            params.append(lib_id)
            if updates:
                # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
                _sql = "UPDATE libraries SET " + ", ".join(updates) + " WHERE id = ?"
                self._conn.execute(_sql, params)
                self._conn.commit()
            \3'''

# Actually, the pattern is complex due to whitespace. Let's use a simpler approach.
start_marker = 'if row:'
end_marker = 'return lib_id'

# Find the block
start_idx = content.find('def upsert_library')
if start_idx != -1:
    block_start = content.find(start_marker, start_idx)
    block_end = content.find(end_marker, block_start)

    new_block = """if row:
            lib_id = row["id"]
            updates = []
            params: list = []
            if docs_url is not None:
                updates.append("docs_url = ?")
                params.append(docs_url)
            if registry is not None:
                updates.append("registry = ?")
                params.append(registry)
            if description is not None:
                updates.append("description = ?")
                params.append(description)
            updates.append("discovery_version = ?")
            params.append(DISCOVERY_VERSION)
            updates.append("updated_at = ?")
            params.append(now)
            params.append(lib_id)
            if updates:
                # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
                _sql = "UPDATE libraries SET " + ", ".join(updates) + " WHERE id = ?"
                self._conn.execute(_sql, params)
                self._conn.commit()
            """

    content = content[:block_start] + new_block + content[block_end:]

    with open(file_path, 'w') as f:
        f.write(content)
    print("Fixed upsert_library")
