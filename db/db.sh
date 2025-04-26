#!/bin/bash

# LangTek Dictionary Manager Script
# This script helps with setting up and managing SQLite dictionaries for LangTek

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PARENT_DIR="$(dirname "$SCRIPT_DIR")"
DB_FILE="${SCRIPT_DIR}/dictionary.db"
LOG_FILE="${SCRIPT_DIR}/db.log"
EXPORT_FILE="${SCRIPT_DIR}/master-es-en.data"

# Function to show help
show_help() {
    echo "LangTek Dictionary Manager"
    echo
    echo "Usage: $0 [command] [options]"
    echo
    echo "Commands:"
    echo "  combine       Combine all dictionaries into SQLite database"
    echo "  lookup WORD   Look up a Spanish word in the database"
    echo "  online WORD   Look up a Spanish word online and add to database"
    echo "  add WORD TRANSLATION   Add a word and its translation to the database"
    echo "  export        Export the database to a tab-separated file"
    echo "  interactive   Run in interactive mode"
    echo "  stats         Show database statistics"
    echo "  help          Show this help message"
    echo
    echo "Examples:"
    echo "  $0 combine                       # Combine all dictionaries"
    echo "  $0 lookup hola                   # Look up 'hola' in the database"
    echo "  $0 online computadora            # Look up 'computadora' online"
    echo "  $0 add gato \"cat\"                # Add 'gato' -> 'cat' to the database"
    echo "  $0 export                        # Export to tab-separated file"
    echo "  $0 interactive                   # Run in interactive mode"
    echo "  $0 stats                         # Show database statistics"
    echo
}

# Function to check if the db.py file exists
check_dbpy() {
    if [ ! -f "${SCRIPT_DIR}/db.py" ]; then
        echo "Error: db.py not found in $SCRIPT_DIR"
        exit 1
    fi
}

# Make db.py executable
chmod +x "${SCRIPT_DIR}/db.py" 2>/dev/null

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
        echo "Combining all dictionaries into $DB_FILE..."
        python3 "${SCRIPT_DIR}/db.py" --combine
        ;;
    lookup)
        check_dbpy
        if [ $# -eq 0 ]; then
            echo "Error: No word specified for lookup"
            echo "Usage: $0 lookup WORD"
            exit 1
        fi
        echo "Looking up '$1' in dictionary..."
        python3 "${SCRIPT_DIR}/db.py" --lookup "$1"
        ;;
    online)
        check_dbpy
        if [ $# -eq 0 ]; then
            echo "Error: No word specified for online lookup"
            echo "Usage: $0 online WORD"
            exit 1
        fi
        echo "Looking up '$1' online..."
        python3 "${SCRIPT_DIR}/db.py" --online "$1"
        ;;
    add)
        check_dbpy
        if [ $# -lt 2 ]; then
            echo "Error: Both word and translation must be specified"
            echo "Usage: $0 add WORD TRANSLATION"
            exit 1
        fi
        word="$1"
        translation="$2"
        echo "Adding '$word' -> '$translation' to dictionary..."
        python3 "${SCRIPT_DIR}/db.py" --add "${word}:${translation}"
        ;;
    export)
        check_dbpy
        echo "Exporting database to $EXPORT_FILE..."
        python3 "${SCRIPT_DIR}/db.py" --export "$EXPORT_FILE"
        ;;
    interactive)
        check_dbpy
        echo "Starting interactive mode..."
        python3 "${SCRIPT_DIR}/db.py" --interactive
        ;;
    stats)
        check_dbpy
        echo "Database statistics:"
        python3 "${SCRIPT_DIR}/db.py" --interactive <<EOF
stats
exit
EOF
        ;;
    help)
        show_help
        ;;
    *)
        echo "Error: Unknown command '$command'"
        show_help
        exit 1
        ;;
esac

exit 0 