import sqlite3
import csv

# Connect to SQLite database
conn = sqlite3.connect('translations.db')
cursor = conn.cursor()

# Create the translations table
cursor.execute('''
    CREATE TABLE IF NOT EXISTS translations (
        spanish TEXT PRIMARY KEY,
        english TEXT
    )
''')

# Read CSV and insert into database
with open('translations.csv', 'r') as f:
    reader = csv.reader(f)
    for row in reader:
        if len(row) == 2:
            cursor.execute('INSERT OR IGNORE INTO translations VALUES (?, ?)', row)

# Commit changes and close connection
conn.commit()
conn.close()