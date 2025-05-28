#!/bin/bash

# Set up paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="/tmp/langtek_gemini_venv"
PYTHON_SCRIPT="${SCRIPT_DIR}/gemini_translate.py"
REQ_FILE="${SCRIPT_DIR}/ai-translate.txt"

# Remove old venv if it exists but is incomplete
if [ -d "$VENV_DIR" ] && [ ! -f "${VENV_DIR}/bin/activate" ]; then
    echo "Removing incomplete virtual environment..."
    rm -rf "$VENV_DIR"
fi

# Create virtual environment if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    python -m venv "$VENV_DIR"
    
    # Activate virtual environment
    source "${VENV_DIR}/bin/activate"
    
    # Install requirements
    echo "Installing requirements..."
    pip install -r "$REQ_FILE"
else
    # Activate virtual environment
    source "${VENV_DIR}/bin/activate"
fi

# Ensure the Python script is executable
chmod +x "$PYTHON_SCRIPT"

# Run the translation script
echo "Starting batch translation..."
python "$PYTHON_SCRIPT" "$@"

# Deactivate virtual environment
deactivate

# Clean up virtual environment
echo "Cleaning up temporary files..."
rm -rf "$VENV_DIR"

echo "Translation process completed."
