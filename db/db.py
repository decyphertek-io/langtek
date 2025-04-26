#!/usr/bin/env python3
import os
import sys
import re
import json
import time
import logging
import argparse
import requests
import sqlite3
from pathlib import Path
from pyglossary.glossary import Glossary

# Setup logging
logging.basicConfig(
    filename='db.log',
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filemode='w'
)
logger = logging.getLogger('LangTekDB')

class DictionaryManager:
    def __init__(self, db_dir='.', output_file='dictionary.db'):
        self.db_dir = db_dir
        self.output_file = os.path.join(db_dir, output_file)
        self.word_dict = {}
        self.loaded_sources = []
        
        # Initialize pyglossary
        try:
            Glossary.init()
            logger.info("PyGlossary initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize PyGlossary: {e}")
            print(f"Error: Failed to initialize PyGlossary: {e}")
            
        # Initialize SQLite database
        self.init_database()

    def init_database(self):
        """Initialize the SQLite database"""
        try:
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(self.output_file), exist_ok=True)
            
            # Connect to the database
            conn = sqlite3.connect(self.output_file)
            cursor = conn.cursor()
            
            # Create tables if they don't exist
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS translations (
                id INTEGER PRIMARY KEY,
                word TEXT NOT NULL,
                translation TEXT NOT NULL,
                source TEXT,
                date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            ''')
            
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS sources (
                id INTEGER PRIMARY KEY,
                path TEXT NOT NULL,
                format TEXT NOT NULL,
                words INTEGER,
                date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            ''')
            
            # Create index on word for faster lookups
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_word ON translations(word)')
            
            conn.commit()
            conn.close()
            
            logger.info(f"Database initialized at {self.output_file}")
            print(f"Database initialized at {self.output_file}")
            
        except Exception as e:
            logger.error(f"Error initializing database: {e}")
            print(f"Error initializing database: {e}")

    def load_all_dictionaries(self):
        """Load all dictionaries from the db directory"""
        # Ensure the directory exists
        if not os.path.exists(self.db_dir):
            logger.error(f"DB directory {self.db_dir} does not exist")
            return False

        dictionary_files = []
        
        # Tab-separated data files
        data_files = list(Path(self.db_dir).glob('*.data'))
        dictionary_files.extend(data_files)
        
        # StarDict dictionaries (.ifo files)
        stardict_files = list(Path(self.db_dir).glob('**/*.ifo'))
        dictionary_files.extend(stardict_files)
        
        # SLOB dictionaries
        slob_files = list(Path(self.db_dir).glob('*.slob'))
        dictionary_files.extend(slob_files)
        
        # MOBI dictionaries
        mobi_files = list(Path(self.db_dir).glob('*.mobi'))
        dictionary_files.extend(mobi_files)
        
        if not dictionary_files:
            logger.warning("No dictionary files found")
            print("Warning: No dictionary files found")
            return False
            
        # Get count of existing translations
        existing_count = self.get_translation_count()
        logger.info(f"Starting with {existing_count} translations in database")
        print(f"Starting with {existing_count} translations in database")
        
        # Load each dictionary
        for dict_path in dictionary_files:
            dict_path_str = str(dict_path)
            try:
                print(f"Loading dictionary: {dict_path_str}")
                logger.info(f"Loading dictionary: {dict_path_str}")
                
                if dict_path_str.endswith('.data'):
                    count = self.load_data_dictionary(dict_path_str)
                    if count > 0:
                        self.add_source(dict_path_str, "data", count)
                else:
                    # Try to load with PyGlossary
                    try:
                        glossary = Glossary()
                        success = glossary.read(dict_path_str)
                        if not success:
                            logger.warning(f"Failed to read dictionary: {dict_path_str}")
                            print(f"Warning: Failed to read dictionary: {dict_path_str}")
                            continue
                        
                        count = 0
                        for entry in glossary:
                            try:
                                word = entry[0].lower()
                                translation = entry[1]
                                
                                if word and translation:
                                    translation_clean = translation.split(',')[0] if ',' in translation else translation
                                    self.add_translation(word, translation_clean, os.path.basename(dict_path_str))
                                    count += 1
                                    
                                    # Show progress periodically
                                    if count % 1000 == 0:
                                        print(f"Loaded {count} words from {dict_path_str}...")
                            except Exception as entry_error:
                                logger.error(f"Error processing entry in {dict_path_str}: {entry_error}")
                                continue
                                
                        if count > 0:
                            self.add_source(dict_path_str, os.path.splitext(dict_path_str)[1][1:], count)
                        
                        print(f"Successfully loaded {count} words from {dict_path_str}")
                        logger.info(f"Successfully loaded {count} words from {dict_path_str}")
                    except Exception as glossary_error:
                        logger.error(f"Error with glossary for {dict_path_str}: {glossary_error}")
                        print(f"Error with glossary for {dict_path_str}: {glossary_error}")
            except Exception as e:
                logger.error(f"Error loading dictionary {dict_path_str}: {e}")
                print(f"Error loading dictionary {dict_path_str}: {e}")
                
        # Get new count of translations
        new_count = self.get_translation_count()
        added = new_count - existing_count
        
        logger.info(f"Total loaded: {new_count} translations ({added} added)")
        print(f"\nTotal loaded: {new_count} translations ({added} added)")
        
        return added > 0

    def load_data_dictionary(self, file_path):
        """Load a dictionary from a tab-separated .data file"""
        try:
            count = 0
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    parts = line.split('\t')
                    if len(parts) >= 2:
                        word = parts[0].strip().lower()
                        definition = parts[1].strip()
                        if word and definition:
                            self.add_translation(word, definition, os.path.basename(file_path))
                            count += 1
                            
                            # Show progress periodically
                            if count % 1000 == 0:
                                print(f"Loaded {count} words from {file_path}...")
            
            print(f"Successfully loaded {count} words from {file_path}")
            logger.info(f"Loaded {count} words from {file_path}")
            return count
        except Exception as e:
            logger.error(f"Error loading .data dictionary {file_path}: {e}")
            print(f"Error loading .data dictionary {file_path}: {e}")
            return 0
    
    def add_translation(self, word, translation, source=None):
        """Add a translation to the database"""
        try:
            conn = sqlite3.connect(self.output_file)
            cursor = conn.cursor()
            
            # Check if word already exists
            cursor.execute('SELECT translation FROM translations WHERE word = ?', (word,))
            result = cursor.fetchone()
            
            if result:
                # Word exists, only update if source is not 'online' (to prevent overwriting manual entries)
                if source != 'online':
                    cursor.execute(
                        'UPDATE translations SET translation = ?, source = ? WHERE word = ?',
                        (translation, source, word)
                    )
            else:
                # Insert new word
                cursor.execute(
                    'INSERT INTO translations (word, translation, source) VALUES (?, ?, ?)',
                    (word, translation, source)
                )
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Error adding translation for '{word}': {e}")
            return False
    
    def add_source(self, path, format_type, word_count):
        """Add a source to the database"""
        try:
            conn = sqlite3.connect(self.output_file)
            cursor = conn.cursor()
            
            # Check if source already exists
            cursor.execute('SELECT id FROM sources WHERE path = ?', (path,))
            result = cursor.fetchone()
            
            if result:
                # Update existing source
                cursor.execute(
                    'UPDATE sources SET format = ?, words = ? WHERE path = ?',
                    (format_type, word_count, path)
                )
            else:
                # Insert new source
                cursor.execute(
                    'INSERT INTO sources (path, format, words) VALUES (?, ?, ?)',
                    (path, format_type, word_count)
                )
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Error adding source {path}: {e}")
            return False
    
    def lookup_word(self, word):
        """Look up a word in the database"""
        if not word:
            return None
            
        word = word.lower().strip()
        
        try:
            conn = sqlite3.connect(self.output_file)
            cursor = conn.cursor()
            
            cursor.execute('SELECT translation FROM translations WHERE word = ?', (word,))
            result = cursor.fetchone()
            
            conn.close()
            
            if result:
                return result[0]
            return None
        except Exception as e:
            logger.error(f"Error looking up word '{word}': {e}")
            return None
    
    def lookup_online(self, word, from_lang='es', to_lang='en'):
        """Look up a word online using a free translation API"""
        if not word:
            return None
            
        word = word.lower().strip()
        
        # First check if word is already in database
        existing = self.lookup_word(word)
        if existing:
            print(f"Found in database: '{word}' -> '{existing}'")
            return existing
        
        try:
            logger.info(f"Looking up '{word}' online ({from_lang}->{to_lang})")
            print(f"Looking up '{word}' online ({from_lang}->{to_lang})...")
            
            # Mymemory Translation API (free, no authentication required)
            url = f"https://api.mymemory.translated.net/get?q={word}&langpair={from_lang}|{to_lang}"
            
            response = requests.get(url, timeout=5)
            data = response.json()
            
            if 'responseData' in data and 'translatedText' in data['responseData']:
                translation = data['responseData']['translatedText']
                logger.info(f"Online translation for '{word}': '{translation}'")
                print(f"Found online: '{word}' -> '{translation}'")
                
                # Add to database
                self.add_translation(word, translation, 'online')
                
                return translation
            else:
                logger.warning(f"Failed to get online translation for '{word}': {data.get('responseStatus')}")
                return None
        except Exception as e:
            logger.error(f"Error during online lookup for '{word}': {e}")
            print(f"Error during online lookup: {e}")
            return None
    
    def get_translation_count(self):
        """Get the number of translations in the database"""
        try:
            conn = sqlite3.connect(self.output_file)
            cursor = conn.cursor()
            
            cursor.execute('SELECT COUNT(*) FROM translations')
            result = cursor.fetchone()
            
            conn.close()
            
            if result:
                return result[0]
            return 0
        except Exception as e:
            logger.error(f"Error getting translation count: {e}")
            return 0
    
    def get_sources(self):
        """Get all sources from the database"""
        try:
            conn = sqlite3.connect(self.output_file)
            cursor = conn.cursor()
            
            cursor.execute('SELECT path, format, words, date_added FROM sources ORDER BY date_added')
            results = cursor.fetchall()
            
            conn.close()
            
            sources = []
            for result in results:
                sources.append({
                    'path': result[0],
                    'format': result[1],
                    'words': result[2],
                    'date_added': result[3]
                })
            
            return sources
        except Exception as e:
            logger.error(f"Error getting sources: {e}")
            return []
            
    def add_common_words(self):
        """Add common Spanish words to the database"""
        common_words = {
            "hola": "hello",
            "adios": "goodbye",
            "gracias": "thank you",
            "por favor": "please",
            "si": "yes",
            "no": "no",
            "buenos días": "good morning",
            "buenas tardes": "good afternoon",
            "buenas noches": "good evening",
            "como estás": "how are you",
            "bien": "good",
            "mal": "bad",
            "casa": "house",
            "perro": "dog",
            "gato": "cat",
            "hombre": "man",
            "mujer": "woman",
            "niño": "boy",
            "niña": "girl",
            "amigo": "friend",
            "familia": "family",
            "comida": "food",
            "agua": "water",
            "vino": "wine",
            "cerveza": "beer",
            "pan": "bread",
            "carne": "meat",
            "pescado": "fish",
            "fruta": "fruit",
            "verdura": "vegetable",
            "leche": "milk",
            "café": "coffee",
            "té": "tea",
            "azúcar": "sugar",
            "sal": "salt",
            "pimienta": "pepper",
            "caliente": "hot",
            "frío": "cold",
            "grande": "big",
            "pequeño": "small",
            "bueno": "good",
            "malo": "bad",
            "feliz": "happy",
            "triste": "sad",
            "rápido": "fast",
            "lento": "slow",
            "nuevo": "new",
            "viejo": "old",
            "alto": "tall",
            "bajo": "short",
            "gordo": "fat",
            "delgado": "thin",
            "bonito": "pretty",
            "feo": "ugly",
            "día": "day",
            "noche": "night",
            "mañana": "morning",
            "tarde": "afternoon",
            "semana": "week",
            "mes": "month",
            "año": "year",
            "hora": "hour",
            "minuto": "minute",
            "segundo": "second",
            "hoy": "today",
            "ayer": "yesterday",
            "mañana": "tomorrow",
            "tiempo": "time",
            "padre": "father",
            "madre": "mother",
            "hermano": "brother",
            "hermana": "sister",
            "hijo": "son",
            "hija": "daughter",
            "abuelo": "grandfather",
            "abuela": "grandmother",
            "tío": "uncle",
            "tía": "aunt",
            "primo": "cousin",
            "esposo": "husband",
            "esposa": "wife",
            "amor": "love",
            "odio": "hate",
            "vida": "life",
            "muerte": "death",
            "trabajo": "work",
            "escuela": "school",
            "universidad": "university",
            "hospital": "hospital",
            "tienda": "store",
            "restaurante": "restaurant",
            "banco": "bank",
            "iglesia": "church",
            "calle": "street",
            "ciudad": "city",
            "país": "country",
            "mundo": "world",
            "papa": "potato",
            "Francia": "France",
            "Ucrania": "Ukraine",
            "libro": "book",
            "de": "of",
            "la": "the",
            "el": "the",
            "y": "and",
            "a": "to",
            "en": "in",
            "con": "with",
            "por": "for",
            "para": "for",
            "su": "his/her",
            "mi": "my",
            "tu": "your",
            "líder": "leader",
            "uno": "one",
            "dos": "two",
            "tres": "three",
            "cuatro": "four",
            "cinco": "five",
            "seis": "six",
            "siete": "seven",
            "ocho": "eight",
            "nueve": "nine",
            "diez": "ten"
        }
        
        # Get initial count
        initial_count = self.get_translation_count()
        
        # Add words
        for spanish, english in common_words.items():
            self.add_translation(spanish.lower(), english, 'common')
        
        # Get new count
        new_count = self.get_translation_count()
        added = new_count - initial_count
        
        if added > 0:
            self.add_source('built-in', 'common', added)
        
        logger.info(f"Added {added} common words to database")
        print(f"Added {added} common words to database")
        
        return added > 0

    def export_data_file(self, output_path):
        """Export the database to a tab-separated file"""
        try:
            conn = sqlite3.connect(self.output_file)
            cursor = conn.cursor()
            
            cursor.execute('SELECT word, translation FROM translations ORDER BY word')
            results = cursor.fetchall()
            
            conn.close()
            
            with open(output_path, 'w', encoding='utf-8') as f:
                # Write header
                f.write("# LangTek Combined Spanish-English Dictionary\n")
                f.write("# Format: spanish_word<tab>english_translation\n")
                f.write(f"# Created: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"# Words: {len(results)}\n\n")
                
                # Write translations
                for word, translation in results:
                    f.write(f"{word}\t{translation}\n")
                    
            print(f"Exported {len(results)} translations to {output_path}")
            logger.info(f"Exported {len(results)} translations to {output_path}")
            return True
        except Exception as e:
            logger.error(f"Error exporting to {output_path}: {e}")
            print(f"Error exporting to {output_path}: {e}")
            return False

def interactive_mode(manager):
    """Run an interactive session for dictionary management"""
    print("\nLangTek Dictionary Manager - Interactive Mode")
    print("--------------------------------------------")
    print("Available commands:")
    print("  lookup <word> - Look up a Spanish word locally")
    print("  online <word> - Look up a Spanish word online")
    print("  add <word> <translation> - Add a word to the dictionary")
    print("  export <filename> - Export the database to a tab-separated file")
    print("  stats - Show database statistics")
    print("  exit - Exit the program")
    print("--------------------------------------------\n")
    
    while True:
        try:
            command = input("\nEnter command: ").strip()
            
            if not command:
                continue
                
            parts = command.split(maxsplit=2)
            cmd = parts[0].lower()
            
            if cmd == "exit":
                break
                
            elif cmd == "lookup":
                if len(parts) < 2:
                    print("Usage: lookup <word>")
                    continue
                    
                word = parts[1].lower()
                result = manager.lookup_word(word)
                if result:
                    print(f"'{word}' -> '{result}'")
                else:
                    print(f"'{word}' not found in dictionary")
                    
            elif cmd == "online":
                if len(parts) < 2:
                    print("Usage: online <word>")
                    continue
                    
                word = parts[1].lower()
                result = manager.lookup_online(word)
                if result:
                    print(f"Added to database: '{word}' -> '{result}'")
                else:
                    print(f"Could not find translation for '{word}' online")
                    
            elif cmd == "add":
                if len(parts) < 3:
                    print("Usage: add <word> <translation>")
                    continue
                    
                word = parts[1].lower()
                translation = parts[2]
                
                if manager.add_translation(word, translation, 'manual'):
                    print(f"Added '{word}' -> '{translation}' to dictionary")
                else:
                    print(f"Failed to add '{word}' to dictionary")
                    
            elif cmd == "export":
                if len(parts) < 2:
                    print("Usage: export <filename>")
                    continue
                    
                filename = parts[1]
                manager.export_data_file(filename)
                
            elif cmd == "stats":
                count = manager.get_translation_count()
                sources = manager.get_sources()
                
                print(f"Database: {manager.output_file}")
                print(f"Total translations: {count}")
                print(f"Sources: {len(sources)}")
                
                for source in sources:
                    print(f"  - {source['path']} ({source['format']}): {source['words']} words")
                
            else:
                print(f"Unknown command: {cmd}")
                
        except KeyboardInterrupt:
            print("\nExiting...")
            break
        except Exception as e:
            print(f"Error: {e}")

def main():
    parser = argparse.ArgumentParser(description="LangTek Dictionary Manager")
    parser.add_argument('--output', '-o', default='dictionary.db', help='Output file path')
    parser.add_argument('--combine', '-c', action='store_true', help='Combine all dictionaries')
    parser.add_argument('--lookup', '-l', metavar='WORD', help='Look up a word')
    parser.add_argument('--online', '-n', metavar='WORD', help='Look up a word online')
    parser.add_argument('--add', '-a', metavar='WORD:TRANSLATION', help='Add a word to the dictionary (format: word:translation)')
    parser.add_argument('--export', '-e', metavar='FILE', help='Export the database to a tab-separated file')
    parser.add_argument('--interactive', '-i', action='store_true', help='Run in interactive mode')
    
    args = parser.parse_args()
    
    # Create dictionary manager
    manager = DictionaryManager(output_file=args.output)
    
    if args.combine:
        print("Loading and combining dictionaries...")
        manager.load_all_dictionaries()
        manager.add_common_words()
        print("Dictionary combination complete.")
        
    if args.lookup:
        word = args.lookup.lower()
        result = manager.lookup_word(word)
        if result:
            print(f"'{word}' -> '{result}'")
        else:
            print(f"'{word}' not found in dictionary")
            
    if args.online:
        word = args.online.lower()
        result = manager.lookup_online(word)
        if not result:
            print(f"Could not find translation for '{word}' online")
                
    if args.add:
        if ':' not in args.add:
            print("Error: Word and translation must be separated by a colon (word:translation)")
        else:
            word, translation = args.add.split(':', 1)
            if manager.add_translation(word.lower(), translation, 'manual'):
                print(f"Added '{word}' -> '{translation}' to dictionary")
            else:
                print(f"Failed to add '{word}' to dictionary")
                
    if args.export:
        manager.export_data_file(args.export)
            
    if args.interactive:
        interactive_mode(manager)
        
    if not any([args.combine, args.lookup, args.online, args.add, args.export, args.interactive]):
        parser.print_help()

if __name__ == "__main__":
    main() 