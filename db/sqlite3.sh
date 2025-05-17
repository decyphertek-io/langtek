#!/bin/bash

# Create virtual environment in home directory if it doesn't exist
if [ ! -d "$HOME/.venv_sqlite3" ]; then
    python3 -m venv $HOME/.venv_sqlite3
fi

# Activate virtual environment and install requirements
source $HOME/.venv_sqlite3/bin/activate
pip install -r requirements_sqlite3.txt

# Run the Kivy app
python sqlite3.py
