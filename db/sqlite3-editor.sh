#!/bin/bash

# Create virtual environment in /tmp if it doesn't exist
if [ ! -d "/tmp/sqlite3-editor-env" ]; then
    echo "Creating virtual environment in /tmp..."
    python3 -m venv /tmp/sqlite3-editor-env
fi

# Activate virtual environment
source /tmp/sqlite3-editor-env/bin/activate

# Install requirements
pip install -r requirements_sqlite3.txt

# Run the Kivy app
python sqlite3-editor.py
