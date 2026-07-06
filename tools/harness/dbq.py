#!/usr/bin/env python3
import sqlite3, sys, os
db = os.path.join(os.path.dirname(__file__), 'helpdesk.db')
rows = sqlite3.connect(db).execute(sys.argv[1]).fetchall()
for r in rows: print('|'.join(str(c) for c in r))
