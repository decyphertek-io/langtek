#!/usr/bin/env python3

import os
import sqlite3
import time

# Set the region explicitly before importing translators
os.environ["translators_default_region"] = "EN"

import translators.server as tss

class TranslationDB:
    def __init__(self, db_path='translations.db', progress_file='progress.txt'):
        """Initialize the translation database."""
        self.db_path = db_path
        self.progress_file = progress_file
        self.conn = None
        self.cursor = None
        self.translators = [
            'lingvanex', 'argos', 'apertium', 'modernmt', 'deepl', 'google'
        ]
        self.init_db()
        self.last_processed = self.get_last_processed()
        
    def init_db(self):
        """Initialize the SQLite database."""
        # Connect to database
        self.conn = sqlite3.connect(self.db_path)
        self.cursor = self.conn.cursor()
        
        # Create table if it doesn't exist
        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS translations (
            spanish TEXT PRIMARY KEY,
            english TEXT
        )
        ''')
        
        # Create index on spanish for faster lookups
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_spanish ON translations(spanish)')
        
        # Commit changes
        self.conn.commit()
        print(f"Database initialized at {self.db_path}")
    
    def close(self):
        """Close the database connection."""
        if self.conn:
            self.conn.close()
    
    def get_translation(self, word):
        """Get translation from database if it exists."""
        self.cursor.execute("SELECT english FROM translations WHERE spanish = ? COLLATE NOCASE", (word,))
        result = self.cursor.fetchone()
        return result[0] if result else None
    
    def save_translation(self, word, translation):
        """Save translation to database."""
        self.cursor.execute(
            "INSERT OR REPLACE INTO translations (spanish, english) VALUES (?, ?)",
            (word.lower(), translation)
        )
        self.conn.commit()
    
    def translate(self, word, from_lang='es_US', to_lang='en_US', resume=False):
        """Translate a word using multiple translation services with fallback."""
        # Normalize language codes
        from_lang = from_lang.lower()
        to_lang = to_lang.lower()
        
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
                    # Google uses 'es' for Spanish
                    translation = tss.google(word, from_language='es', to_language='en')
                elif translator == 'deepl':
                    # DeepL uses 2-letter codes
                    translation = tss.deepl(word, from_language='es', to_language='en')
                elif translator == 'lingvanex':
                    # Lingvanex uses specific format
                    translation = tss.lingvanex(word, from_language='es_ES', to_language='en_US')
                elif translator == 'argos':
                    # Argos uses 2-letter codes
                    # Using a different endpoint that might be more reliable
                    translation = tss.argos(word, from_language='es', to_language='en', api_url='https://api-free.deepl.com/v2/translate')
                elif translator == 'apertium':
                    # Apertium uses 3-letter codes
                    translation = tss.apertium(word, from_language='spa', to_language='eng')
                else:
                    continue
                
                # Check if translation is different from the original word
                if translation and translation.lower() != word.lower():
                    self.save_translation(word, translation)
                    print(f"Added: {word} → {translation}")
                    return translation
                elif translation:
                    print(f"Warning: {translator} returned same word: {word}")
                    
            except Exception as e:
                print(f"Error with {translator}: {str(e)}")
                continue
        
        print(f"Failed to translate {word} after all attempts")
        return None
    
    def get_last_processed(self):
        """Get the last processed word from progress file."""
        if os.path.exists(self.progress_file):
            with open(self.progress_file, 'r') as f:
                return f.read().strip()
        return None
        
    def update_progress(self, word):
        """Update the progress file with the last processed word."""
        with open(self.progress_file, 'w') as f:
            f.write(word)
            
    def process_spanish_words(self, words_file='spanish_words.txt', limit=None):
        """Process words from the Spanish words file."""
        print(f"Starting translation process from {words_file}")
        
        # Read words from file
        with open(words_file, 'r') as f:
            words = [line.strip() for line in f if line.strip()]
        
        # If we have a last processed word, start from there
        if self.last_processed:
            print(f"Resuming from last processed word: {self.last_processed}")
            start_index = words.index(self.last_processed) + 1
        else:
            start_index = 0
        
        # Process words
        processed = 0
        total_words = len(words)
        for i, word in enumerate(words[start_index:], start=start_index):
            if limit and processed >= limit:
                break
                
            print(f"Processing {i+1}/{total_words} ({(i+1)/total_words*100:.1f}%): {word}")
            translation = self.translate(word, resume=True)
            if translation:
                self.update_progress(word)
                processed += 1
                
            # Sleep a bit between requests to avoid rate limiting
            time.sleep(1)
        
        print("Finished processing spanish_words.txt")

def main():
    # Initialize database
    db = TranslationDB()
    
    try:
        # Process spanish_words.txt
        db.process_spanish_words()
    except KeyboardInterrupt:
        print("\nScript interrupted by user")
    finally:
        db.close()
        print("Database connection closed")

if __name__ == "__main__":
    main()