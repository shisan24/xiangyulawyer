# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""Recover corrupted state.db using immutable read mode."""
import sqlite3
import shutil
import os
import sys

OLD_DB = r"[本地路径]"
NEW_DB = r"[本地路径]"
TEMPLATE_DB = r"[本地路径]"

print("Starting recovery...")

# 1. Start with fresh template
shutil.copy2(TEMPLATE_DB, NEW_DB)
print(f"Template copied from {os.path.getsize(TEMPLATE_DB):,} bytes")

# 2. Open old DB in immutable readonly mode
old_uri = f"file:{OLD_DB}?mode=ro&immutable=1"
old = sqlite3.connect(old_uri, uri=True)
new = sqlite3.connect(NEW_DB)

# 3. Copy sessions
print("\n--- Sessions ---")
try:
    cols = [d[0] for d in old.execute("SELECT * FROM sessions LIMIT 0").description]
    print(f"Columns ({len(cols)}): {cols[:5]}...")
    placeholders = ','.join(['?'] * len(cols))
    
    cur = old.execute("SELECT * FROM sessions ORDER BY rowid")
    copied = 0
    errors = 0
    for row in cur:
        try:
            # Convert row to tuple (handle any weird types)
            values = []
            for v in row:
                values.append(v)
            new.execute(f"INSERT OR REPLACE INTO sessions VALUES ({placeholders})", values)
            copied += 1
            if copied <= 5:
                print(f"  OK: rowid={copied} id={str(values[0])[:30]}")
        except Exception as e:
            errors += 1
            if errors <= 3:
                print(f"  ERR ({errors}): {str(e)[:80]}")
    new.commit()
    print(f"  Total: {copied} copied, {errors} errors")
except Exception as e:
    print(f"  SESSION FAIL: {e}")

# 4. Copy messages
print("\n--- Messages ---")
try:
    msg_cols = [d[0] for d in old.execute("SELECT * FROM messages LIMIT 0").description]
    msg_placeholders = ','.join(['?'] * len(msg_cols))
    
    cur = old.execute("SELECT * FROM messages ORDER BY rowid")
    copied = 0
    errors = 0
    for row in cur:
        try:
            values = []
            for v in row:
                values.append(v)
            new.execute(f"INSERT OR REPLACE INTO messages VALUES ({msg_placeholders})", values)
            copied += 1
        except Exception as e:
            errors += 1
            if errors <= 3:
                print(f"  ERR ({errors}): {str(e)[:80]}")
    new.commit()
    print(f"  Total: {copied} copied, {errors} errors")
except Exception as e:
    print(f"  MESSAGE FAIL: {e}")

# 5. Copy state_meta
print("\n--- State Meta ---")
try:
    n = 0
    for row in old.execute("SELECT * FROM state_meta"):
        try:
            new.execute("INSERT OR REPLACE INTO state_meta VALUES (?,?)", (row[0], row[1]))
            n += 1
        except:
            pass
    new.commit()
    print(f"  Copied: {n}")
except Exception as e:
    print(f"  META FAIL: {e}")

# 6. Copy compression_locks if any
print("\n--- Compression Locks ---")
try:
    n = 0
    for row in old.execute("SELECT * FROM compression_locks"):
        try:
            new.execute("INSERT OR REPLACE INTO compression_locks VALUES (?,?,?,?)", 
                       (row[0], row[1], row[2], row[3]))
            n += 1
        except:
            pass
    new.commit()
    print(f"  Copied: {n}")
except Exception as e:
    print(f"  LOCK FAIL: {e}")

old.close()
new.close()

print(f"\n=== Recovery Complete ===")
print(f"Old DB: {os.path.getsize(OLD_DB):,} bytes")
print(f"New DB: {os.path.getsize(NEW_DB):,} bytes")

# Verify
print("\n--- Verification ---")
vfy = sqlite3.connect(NEW_DB)
for table in ['sessions', 'messages', 'state_meta']:
    try:
        cnt = vfy.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table}: {cnt} rows")
    except Exception as e:
        print(f"  {table}: ERROR - {e}")
try:
    result = vfy.execute("PRAGMA integrity_check").fetchone()
    print(f"  Integrity: {result[0]}")
except Exception as e:
    print(f"  Integrity check failed: {e}")
vfy.close()
