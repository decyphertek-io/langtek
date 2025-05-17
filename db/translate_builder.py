#!/usr/bin/env python3

import os
import sqlite3
import time

# Set the region explicitly before importing translators
os.environ["translators_default_region"] = "EN"

import translators.server as tss

class TranslationDB:
    def __init__(self, db_path='translations.db'):
        """Initialize the translation database."""
        self.db_path = db_path
        self.conn = None
        self.cursor = None
        self.translators = [
            'lingvanex', 'argos', 'apertium', 'modernmt', 'deepl', 'google'
        ]
        self.init_db()
        
    def init_db(self):
        """Initialize the SQLite database."""
        # Connect to database
        self.conn = sqlite3.connect(self.db_path)
        self.cursor = self.conn.cursor()
        
        # Create table if it doesn't exist
        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS translations (
            id INTEGER PRIMARY KEY,
            word TEXT NOT NULL,
            translation TEXT NOT NULL,
            source TEXT DEFAULT 'google',
            date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        # Create index on word for faster lookups
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_word ON translations(word)')
        
        # Commit changes
        self.conn.commit()
        print(f"Database initialized at {self.db_path}")
    
    def close(self):
        """Close the database connection."""
        if self.conn:
            self.conn.close()
    
    def get_translation(self, word):
        """Get translation from database if it exists."""
        self.cursor.execute("SELECT translation FROM translations WHERE word = ? COLLATE NOCASE", (word,))
        result = self.cursor.fetchone()
        return result[0] if result else None
    
    def save_translation(self, word, translation, source):
        """Save translation to database."""
        self.cursor.execute(
            "INSERT OR REPLACE INTO translations (word, translation, source) VALUES (?, ?, ?)",
            (word.lower(), translation, source)
        )
        self.conn.commit()
    
    def translate(self, word, from_lang='es_US', to_lang='en_US'):
        """Translate a word using multiple translation services with fallback."""
        # Check if translation already exists in database
        existing = self.get_translation(word)
        if existing:
            print(f"Skipping {word} - already in database")
            return existing
        
        # Try each translator in sequence
        for translator in self.translators:
            try:
                print(f"Translating {word} with {translator}...")
                
                # Different handling based on translator
                if translator == 'google':
                    translation = tss.google(word, from_language=from_lang, to_language=to_lang)
                elif translator == 'deepl':
                    translation = tss.deepl(word, from_language=from_lang, to_language=to_lang)
                elif translator == 'modernmt':
                    translation = tss.modernmt(word, from_language=from_lang, to_language=to_lang)
                elif translator == 'apertium':
                    translation = tss.apertium(word, from_language=from_lang, to_language=to_lang)
                elif translator == 'argos':
                    translation = tss.argos(word, from_language=from_lang, to_language=to_lang)
                elif translator == 'lingvanex':
                    translation = tss.lingvanex(word, from_language=from_lang, to_language=to_lang)
                else:
                    continue
                
                if translation:
                    # Save to database
                    self.save_translation(word, translation, translator)
                    print(f"Added: {word} → {translation}")
                    return translation
                    
            except Exception as e:
                print(f"Error with {translator}: {str(e)}")
                # Wait a bit before trying the next translator
                time.sleep(1)
                continue
        
        print(f"Failed to translate: {word}")
        return None
    
    def process_spanish_words(self):
        """Process spanish_words.txt file and add translations to database."""
        script_dir = os.path.dirname(os.path.abspath(__file__))
        spanish_words_file = os.path.join(script_dir, 'spanish_words.txt')
        
        if not os.path.exists(spanish_words_file):
            print(f"Error: Spanish words file not found at {spanish_words_file}")
            return
        
        # Read all words from file
        with open(spanish_words_file, 'r', encoding='utf-8') as f:
            words = [line.strip() for line in f if line.strip()]
        
        print(f"Found {len(words)} words in {spanish_words_file}")
        
        # Process each word
        for i, word in enumerate(words):
            print(f"Processing {i+1}/{len(words)} ({(i+1)/len(words)*100:.1f}%)")
            self.translate(word)
            # Be nice to the translation services
            time.sleep(1)
        
        print("Finished processing spanish_words.txt")

def main():
    # Initialize database
    db = TranslationDB()
    
    try:
        # Process spanish_words.txt
        db.process_spanish_words()
    finally:
        db.close()

if __name__ == "__main__":
    main()
