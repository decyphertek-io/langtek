KIVY RSS Reader in DEV
---------------------
This app is built using Kivy , so it can be cross platform. Build once , deploy everywhere. The purpose of this RSS Feed is to learn spanish by reading. The idea is to have a line by line translation. When I use a free API , it is too slow and crashes the app, it does translate. I am working on getting an offline spanish Dictionary working with Pyglossary. It supports many formats, none seem to be working correctly? It is spanish/spanish , instead of Spanish / English . Also , working on functionality first before features or beauty. Troublebshooting , Work in progress. Expect glitches. 

Issues:
------
* New DB scheme broke the python script. Working on updating the logic. 
* Working on cleaning up the Database.
* Some translators are adding * and Caps to the saved translations.
* When fixing it and rebuilding the DB, some words not being translated.
* I am actively fixing these issues and rebuilding the DB, when the DB is built runs smoothly. 
* Please note this is in DEV. 

Getting Started:
----------------
* Make sure python is installed
* This was only tested on Linux.
* from terminal run:
```
bash langtek.sh
```
* This will create a virtual python environment and run the application. 

Malo Words:
------------------------------------------------------
* Can update from the GUI > Top Left > Search > Update
* Can also update from terminal
```
EX: Papa Francis was being translated as Potato Fran
* Removing bad translation sources in the custom db

# 1. Connect to database
cd /langtek/db
sqlite3 translations.db

# 2. View data
SELECT * FROM translations WHERE word = 'papa';
# 30|papa|potato|common|2025-04-26 22:56:57

# 3. Update translation
UPDATE translations 
SET translation = 'father' 
WHERE word = 'papa';

# 4. Verify change
SELECT * FROM translations WHERE word = 'papa';
# 30|papa|father|common|2025-04-26 22:56:57

# 5. Exit SQLite
.quit
```
