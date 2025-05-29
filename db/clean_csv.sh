#!/bin/bash

# Activate the virtual environment
source "$HOME/.clean_csv_venv/bin/activate"

# Run the clean-csv.py script
python clean-csv.py

# Deactivate the virtual environment
deactivate
