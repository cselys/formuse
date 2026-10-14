import sqlite3
db = sqlite3.connect(r'C:\Git\AI\Claude\SectorRadar\data\sector_radar.db')
cur = db.cursor()

cur.execute('SELECT sql FROM sqlite_master WHERE name="quote_snapshots"')
print('Schema:', cur.fetchone()[0])

cur.execute('SELECT symbol, data_age_seconds FROM quote_snapshots WHERE session_date="2026-10-07" AND symbol="NVDA" ORDER BY fetched_at DESC LIMIT 1')
row = cur.fetchone()
print(f'NVDA data_age_seconds: {row[1]}')

cur.execute('SELECT symbol, data_age_seconds FROM quote_snapshots WHERE session_date="2026-10-07" ORDER BY symbol LIMIT 5')
rows = cur.fetchall()
for r in rows:
    print(f'  {r[0]}: data_age_seconds={r[1]}')

db.close()