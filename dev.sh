#!/bin/bash

# Script to set up the Python environment and run the LangTek Kivy app.
# Note: This runs a desktop application window, not a web server.
# WARNING: This script creates the venv in the home directory and deletes it on exit.

set -e # Exit immediately if a command exits with a non-zero status.

# --- CHANGED venv location to home directory --- 
VENV_DIR="$HOME/.langtek_venv" # Use a specific name in the home directory
# ---------------------------------------------
PYTHON_EXEC="python3" # Adjust if your python3 executable has a different name

# --- Function for cleanup --- 
cleanup() {
    echo "Cleaning up virtual environment in $VENV_DIR..."
    # Check if deactivate function exists (we might be in a subshell where it doesn't)
    if command -v deactivate &> /dev/null; then
        deactivate || echo "Deactivate failed (already inactive?)"
    fi
    rm -rf "$VENV_DIR"
    echo "Cleanup finished."
}
# -------------------------

# --- Trap EXIT signal to run cleanup --- 
trap cleanup EXIT
# ---------------------------------------


# Check if python3 and venv are available
if ! command -v $PYTHON_EXEC &> /dev/null; then
    echo "$PYTHON_EXEC could not be found. Please install Python 3."
    exit 1
fi

if ! $PYTHON_EXEC -m venv -h &> /dev/null; then
    echo "The 'venv' module is not available with $PYTHON_EXEC. Please install the python3-venv package (or equivalent)."
    exit 1
fi

# Create virtual environment if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment in $VENV_DIR..."
    $PYTHON_EXEC -m venv "$VENV_DIR"
else
    echo "Virtual environment $VENV_DIR already exists."
fi

# First check if dev.py exists, if not, create it from main.py
if [ ! -f "dev.py" ]; then
    echo "Creating dev.py from main.py..."
    cp main.py dev.py
fi

# Activate virtual environment (for installing packages) and run the app
echo "Activating virtual environment and installing dependencies..."
source "$VENV_DIR/bin/activate"
pip install -r requirements.txt

echo "Running the LangTek Kivy development application (dev.py)..."
# --- Run Python app within the same script execution --- 
python dev.py
# -----------------------------------------------------

# --- Cleanup will be handled by the trap --- 
echo "Application process finished. Trap will handle cleanup."
# Exit normally, allowing the trap to run
exit 0 
# ------------------------------------------ 