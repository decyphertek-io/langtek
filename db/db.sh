#!/bin/bash

# LangTek Dictionary Manager Script
# This script helps with setting up and managing dictionaries for LangTek

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DB_DIR="${SCRIPT_DIR}/db"
MASTER_DICT_FILE="${DB_DIR}/master-es-en.data"
VENV_DIR="${SCRIPT_DIR}/.langtek_venv"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check if virtual environment exists
if [ ! -d "$VENV_DIR" ]; then
    echo -e "${YELLOW}Creating virtual environment for dictionary management...${NC}"
    python3 -m venv "$VENV_DIR"
    echo -e "${GREEN}Virtual environment created at $VENV_DIR${NC}"
fi

# Activate virtual environment
source "${VENV_DIR}/bin/activate"

# Ensure required packages are installed
echo -e "${YELLOW}Installing required packages...${NC}"
pip install -q -r requirements.txt
pip install -q requests

# Check if db directory exists
if [ ! -d "$DB_DIR" ]; then
    echo -e "${YELLOW}Creating db directory...${NC}"
    mkdir -p "$DB_DIR"
    echo -e "${GREEN}Created db directory at $DB_DIR${NC}"
fi

# Function to show help
show_help() {
    echo -e "${GREEN}LangTek Dictionary Manager${NC}"
    echo
    echo "Usage: $0 [command] [options]"
    echo
    echo "Commands:"
    echo "  combine       Combine all dictionaries into one master dictionary"
    echo "  lookup WORD   Look up a Spanish word in the dictionary"
    echo "  online WORD   Look up a Spanish word online and add to dictionary"
    echo "  add WORD TRANSLATION   Add a word and its translation to the dictionary"
    echo "  interactive   Run in interactive mode"
    echo "  info          Show information about dictionaries"
    echo "  help          Show this help message"
    echo
    echo "Examples:"
    echo "  $0 combine                       # Combine all dictionaries"
    echo "  $0 lookup hola                   # Look up 'hola' in the dictionary"
    echo "  $0 online computadora            # Look up 'computadora' online"
    echo "  $0 add gato \"cat\"                # Add 'gato' -> 'cat' to the dictionary"
    echo "  $0 interactive                   # Run in interactive mode"
    echo
}

# Function to check if the db.py file exists
check_dbpy() {
    if [ ! -f "${SCRIPT_DIR}/db.py" ]; then
        echo -e "${RED}Error: db.py not found in $SCRIPT_DIR${NC}"
        exit 1
    fi
}

# Process arguments
if [ $# -eq 0 ]; then
    show_help
    exit 0
fi

# Main command processing
command="$1"
shift

case "$command" in
    combine)
        check_dbpy
        echo -e "${YELLOW}Combining all dictionaries into $MASTER_DICT_FILE...${NC}"
        python "${SCRIPT_DIR}/db.py" --combine
        ;;
    lookup)
        check_dbpy
        if [ $# -eq 0 ]; then
            echo -e "${RED}Error: No word specified for lookup${NC}"
            echo "Usage: $0 lookup WORD"
            exit 1
        fi
        echo -e "${YELLOW}Looking up '$1' in dictionary...${NC}"
        python "${SCRIPT_DIR}/db.py" --lookup "$1"
        ;;
    online)
        check_dbpy
        if [ $# -eq 0 ]; then
            echo -e "${RED}Error: No word specified for online lookup${NC}"
            echo "Usage: $0 online WORD"
            exit 1
        fi
        echo -e "${YELLOW}Looking up '$1' online...${NC}"
        python "${SCRIPT_DIR}/db.py" --online "$1"
        ;;
    add)
        check_dbpy
        if [ $# -lt 2 ]; then
            echo -e "${RED}Error: Both word and translation must be specified${NC}"
            echo "Usage: $0 add WORD TRANSLATION"
            exit 1
        fi
        word="$1"
        translation="$2"
        echo -e "${YELLOW}Adding '$word' -> '$translation' to dictionary...${NC}"
        python "${SCRIPT_DIR}/db.py" --add "${word}:${translation}"
        ;;
    interactive)
        check_dbpy
        echo -e "${YELLOW}Starting interactive mode...${NC}"
        python "${SCRIPT_DIR}/db.py" --interactive
        ;;
    info)
        echo -e "${YELLOW}Dictionary information:${NC}"
        echo "DB Directory: $DB_DIR"
        echo "Master Dictionary: $MASTER_DICT_FILE"
        
        if [ -f "$MASTER_DICT_FILE" ]; then
            word_count=$(grep -v "^#" "$MASTER_DICT_FILE" | wc -l)
            echo "Master Dictionary Word Count: $word_count"
        else
            echo "Master Dictionary does not exist yet. Use '$0 combine' to create it."
        fi
        
        echo
        echo "Available Dictionary Files:"
        find "$DB_DIR" -type f \( -name "*.data" -o -name "*.ifo" -o -name "*.slob" -o -name "*.mobi" \) | while read -r file; do
            echo "  - $(basename "$file")"
        done
        ;;
    help)
        show_help
        ;;
    *)
        echo -e "${RED}Error: Unknown command '$command'${NC}"
        show_help
        exit 1
        ;;
esac

# Deactivate virtual environment
deactivate
exit 0 