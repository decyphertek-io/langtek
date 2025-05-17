#!/bin/bash

# Script to run translate_builder.py in a virtual environment

# Set up paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="/tmp/langtek_venv"
PYTHON_SCRIPT="${SCRIPT_DIR}/translate_builder.py"
REQ_FILE="${SCRIPT_DIR}/requirements.txt"
NODE_VERSION="20.11.1"
NODE_DIR="/tmp/langtek_node"

# Create virtual environment if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    python -m venv "$VENV_DIR"
    
    # Activate virtual environment
    source "${VENV_DIR}/bin/activate"
    
    # Install requirements
    pip install -r "$REQ_FILE"
else
    # Activate virtual environment
    source "${VENV_DIR}/bin/activate"
fi

# Install Node.js if not already installed
if [ ! -d "$NODE_DIR" ]; then
    echo "Installing Node.js for translators library..."
    mkdir -p "$NODE_DIR"
    
    # Download and extract Node.js
    if [ "$(uname -m)" == "x86_64" ]; then
        curl -L "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz" -o "${NODE_DIR}/node.tar.xz"
        tar -xf "${NODE_DIR}/node.tar.xz" -C "${NODE_DIR}" --strip-components=1
    else
        echo "Error: Unsupported architecture. Please install Node.js manually."
        exit 1
    fi
fi

# Add Node.js to PATH
export PATH="${NODE_DIR}/bin:$PATH"

# Ensure the Python script is executable
chmod +x "$PYTHON_SCRIPT"

# Run the Python script with all arguments passed to this script
python "$PYTHON_SCRIPT" "$@"

# Deactivate virtual environment
deactivate

# Clean up virtual environment and Node.js
echo "Cleaning up temporary files..."
rm -rf "$VENV_DIR" "$NODE_DIR"
