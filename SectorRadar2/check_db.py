#!/usr/bin/env python
"""Check database structure"""

import sqlite3
import pandas as pd

db = sqlite3.connect('data/sector_radar.db')
cur = db.cursor()

# Check tables
cur.execute('SELECT name FROM sqlite_master WHERE type="table"')
tables = cur.fetchall()
print('Tables:', tables)

# Check quote_snapshots
cur.execute('SELECT COUNT(*) FROM quote_snapshots')
print('quote_snapshots count:', cur.fetchone()[0])

cur.execute('PRAGMA table_info(quote_snapshots)')
for row in cur.fetchall():
    print(row)

# Check stock_snapshots
cur.execute('SELECT name FROM sqlite_master WHERE type="table" AND name LIKE "%snapshot%"')
print('Snapshot tables:', cur.fetchall())

db.close()