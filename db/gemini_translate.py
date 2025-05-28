#!/usr/bin/env python3

import os
import sqlite3
import time
import json
import argparse
from dotenv import load_dotenv
import google.generativeai as genai

class GeminiTranslator:
    def __init__(self, db_path='es-en.sqlite3', progress_file='progress.txt', batch_size=1000):
        """Initialize the Gemini translation database."""
        self.db_path = db_path
        self.progress_file = progress_file
        self.batch_size = batch_size
        self.conn = None
        self.cursor = None
        
        # Load API key from environment
        load_dotenv()
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in environment variables")
        
        # Configure Gemini
        genai.configure(api_key=api_key)
        
        # Try different model names in order of preference
        model_names = ['gemini-2.5-pro', 'gemini-pro', 'gemini-1.5-pro', 'gemini-1.0-pro']
        self.model = None
        
        for model_name in model_names:
            try:
                self.model = genai.GenerativeModel(model_name)
                # Test with a simple prompt
                self.model.generate_content("Hello")
                print(f"Successfully connected to model: {model_name}")
                break
            except Exception as e:
                print(f"Model {model_name} not available: {str(e)}")
                continue
                
        if self.model is None:
            raise ValueError("No available Gemini models found. Please check your API key and available models.")
        
        # Initialize database
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
        self.cursor.execute("SELECT english FROM translations WHERE spanish = ? COLLATE NOCASE", (word.lower(),))
        result = self.cursor.fetchone()
        return result[0] if result else None
    
    def save_translation(self, word, translation):
        """Save translation to database."""
        if not word or not translation:
            return
            
        self.cursor.execute(
            "INSERT OR REPLACE INTO translations (spanish, english) VALUES (?, ?)",
            (word.lower(), translation)
        )
        self.conn.commit()
    
    def save_batch_translations(self, translations_dict):
        """Save a batch of translations to database."""
        if not translations_dict:
            return
            
        data = []
        for word, translation in translations_dict.items():
            if word and translation:
                # Strip quotes from both word and translation
                clean_word = word.lower().strip('"\'')
                clean_translation = translation.strip('"\'')
                data.append((clean_word, clean_translation))
        
        if data:
            self.cursor.executemany(
                "INSERT OR REPLACE INTO translations (spanish, english) VALUES (?, ?)",
                data
            )
            self.conn.commit()
            print(f"Saved {len(data)} translations to database")
    
    def batch_translate(self, words):
        """Translate a batch of words using Gemini API."""
        if not words:
            return {}
            
        # Filter out words that already exist in the database
        words_to_translate = []
        for word in words:
            if not self.get_translation(word):
                words_to_translate.append(word)
            else:
                print(f"Skipping {word} - already in database")
        
        if not words_to_translate:
            return {}
        
        # If batch is very large, split it into smaller batches to avoid JSON errors
        MAX_SAFE_BATCH = 500  # Maximum words to send in a single API call
        
        if len(words_to_translate) > MAX_SAFE_BATCH:
            print(f"Large batch detected ({len(words_to_translate)} words). Splitting into smaller batches...")
            all_translations = {}
            
            # Process in smaller batches
            for i in range(0, len(words_to_translate), MAX_SAFE_BATCH):
                sub_batch = words_to_translate[i:i + MAX_SAFE_BATCH]
                print(f"Processing sub-batch {i//MAX_SAFE_BATCH + 1} with {len(sub_batch)} words...")
                
                # Translate sub-batch
                sub_translations = self._translate_batch(sub_batch)
                
                # Merge results
                all_translations.update(sub_translations)
                
            return all_translations
        else:
            print(f"Translating batch of {len(words_to_translate)} words...")
            return self._translate_batch(words_to_translate)
            
    def _translate_batch(self, words_to_translate):
        """Internal method to translate a batch of words."""
        if not words_to_translate:
            return {}
        
        # Prepare prompt for Gemini - improved to avoid JSON errors
        prompt = f"""
        Translate these Spanish words to English. Return a valid JSON dictionary with no extra text.
        Format: {{"spanish_word": "english_translation"}}
        
        IMPORTANT: 
        1. Use double quotes for all keys and values
        2. Escape any quotes within translations
        3. Do not use special characters that would break JSON
        4. Keep translations simple and direct
        5. Make sure all strings are properly terminated with quotes
        
        Words: {json.dumps(words_to_translate)}
        
        Return ONLY the JSON object with no other text or explanation.
        """
        
        try:
            response = self.model.generate_content(prompt)
            
            # Extract JSON from response
            response_text = response.text
            
            # Find JSON in the response (it might be wrapped in markdown code blocks)
            if "```json" in response_text:
                json_str = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                json_str = response_text.split("```")[1].strip()
            else:
                json_str = response_text.strip()
            
            try:
                # Try to parse the JSON
                translations = json.loads(json_str)
            except json.JSONDecodeError as e:
                print(f"Error parsing JSON: {e}")
                print(f"First 100 chars of response: {json_str[:100]}...")
                
                # Try to fix common JSON issues
                try:
                    # Replace single quotes with double quotes
                    fixed_json = json_str.replace("'", '"')
                    # Try to parse again
                    translations = json.loads(fixed_json)
                    print("Fixed JSON parsing issue by replacing quotes")
                except json.JSONDecodeError:
                    # If still failing, try a more aggressive approach - extract only valid parts
                    print("Attempting to extract valid JSON parts...")
                    try:
                        # Find the start of JSON object
                        start_idx = json_str.find('{')
                        end_idx = json_str.rfind('}')
                        if start_idx >= 0 and end_idx > start_idx:
                            # Extract just the JSON object part
                            clean_json = json_str[start_idx:end_idx+1]
                            # Try to fix common JSON issues
                            clean_json = clean_json.replace('\n', '')
                            clean_json = clean_json.replace('\r', '')
                            
                            # Try to extract valid key-value pairs manually
                            print("Attempting manual JSON extraction...")
                            manual_dict = {}
                            try:
                                # Simple regex to extract key-value pairs - more robust pattern
                                import re
                                # This pattern matches "key": "value" pairs even if there are errors elsewhere in the JSON
                                pairs = re.findall(r'"([^"]+)"\s*:\s*"([^"]*)"', clean_json)
                                for key, value in pairs:
                                    # Strip any remaining quotes
                                    clean_key = key.strip('"\'')
                                    clean_value = value.strip('"\'')
                                    if clean_key and clean_value:  # Only add if both are non-empty
                                        manual_dict[clean_key] = clean_value
                                
                                # Try another pattern for cases where the JSON might use single quotes
                                if not manual_dict:
                                    pairs = re.findall(r'\'([^\']+)\'\s*:\s*\'([^\']*)\'', clean_json)
                                    for key, value in pairs:
                                        clean_key = key.strip('"\'')
                                        clean_value = value.strip('"\'')
                                        if clean_key and clean_value:
                                            manual_dict[clean_key] = clean_value
                                    
                                if manual_dict:
                                    print(f"Manually extracted {len(manual_dict)} translations")
                                    return manual_dict
                                else:
                                    # Last resort - try to extract any word-like pattern with a colon
                                    print("Trying last resort extraction...")
                                    # This pattern is more permissive and will catch more potential pairs
                                    pairs = re.findall(r'"([\w\s]+)"\s*:\s*"([\w\s]+)"', clean_json)
                                    for key, value in pairs:
                                        clean_key = key.strip('"\'')
                                        clean_value = value.strip('"\'')
                                        if clean_key and clean_value:
                                            manual_dict[clean_key] = clean_value
                                            
                                    if manual_dict:
                                        print(f"Last resort extraction found {len(manual_dict)} translations")
                                        return manual_dict
                                    else:
                                        print("No key-value pairs found in any extraction method")
                            except Exception as e:
                                print(f"Manual extraction failed: {e}")
                            
                            # If manual extraction failed, try the original approach
                            try:
                                translations = json.loads(clean_json)
                                print("Successfully extracted valid JSON part")
                                return translations
                            except json.JSONDecodeError:
                                print("Could not parse extracted JSON")
                                return {}
                        else:
                            # Try one more approach - look for any key-value patterns in the entire string
                            print("Trying direct extraction from full response...")
                            manual_dict = {}
                            try:
                                import re
                                pairs = re.findall(r'"([^"]+)"\s*:\s*"([^"]*)"', json_str)
                                for key, value in pairs:
                                    clean_key = key.strip('"\'')
                                    clean_value = value.strip('"\'')
                                    if clean_key and clean_value:
                                        manual_dict[clean_key] = clean_value
                                        
                                if manual_dict:
                                    print(f"Direct extraction found {len(manual_dict)} translations")
                                    return manual_dict
                                else:
                                    print("Could not find valid JSON object markers or patterns")
                                    return {}
                            except Exception as e:
                                print(f"Direct extraction failed: {e}")
                                return {}
                            
                            return {}
                        return {}
                    except Exception as e2:
                        print(f"All JSON parsing attempts failed: {e2}")
                        return {}
            
            # Validate translations
            valid_translations = {}
            for word, translation in translations.items():
                word = word.strip().lower()
                translation = translation.strip()
                
                # Skip if translation is empty or same as original
                if not translation or translation.lower() == word:
                    print(f"Warning: Invalid translation for {word}, skipping")
                    continue
                    
                # Check for emojis (Unicode ranges for emojis)
                if any(ord(char) >= 0x1F000 for char in translation):
                    print(f"Warning: Translation contains emoji for {word}, skipping")
                    continue
                    
                valid_translations[word] = translation
                
            return valid_translations
            
        except Exception as e:
            print(f"Error with Gemini translation: {str(e)}")
            return {}
    
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
        """Process words from the Spanish words file in batches."""
        print(f"Starting batch translation process from {words_file}")
        
        # Read words from file
        with open(words_file, 'r') as f:
            words = [line.strip() for line in f if line.strip()]
        
        # If we have a last processed word, start from there
        if self.last_processed and self.last_processed in words:
            print(f"Resuming from last processed word: {self.last_processed}")
            try:
                start_index = words.index(self.last_processed) + 1
                print(f"Starting from index {start_index} (word: {words[start_index] if start_index < len(words) else 'END'})")
            except ValueError:
                print(f"Last processed word '{self.last_processed}' not found in word list. Starting from beginning.")
                start_index = 0
        else:
            start_index = 0
            print("No progress file found or empty. Starting from the beginning.")
        
        # Process words in batches
        total_words = len(words)
        processed_batches = 0
        last_saved_word = None
        
        for batch_start in range(start_index, total_words, self.batch_size):
            if limit and batch_start >= start_index + limit:
                break
                
            batch_end = min(batch_start + self.batch_size, total_words)
            if limit:
                batch_end = min(batch_end, start_index + limit)
                
            word_batch = words[batch_start:batch_end]
            
            if not word_batch:
                print("No more words to process.")
                break
                
            print(f"Processing batch {processed_batches+1}: words {batch_start+1}-{batch_end} of {total_words}")
            print(f"First word in batch: {word_batch[0]}, Last word in batch: {word_batch[-1]}")
            
            # Translate batch
            translations = self.batch_translate(word_batch)
            
            # Save translations
            if translations:
                self.save_batch_translations(translations)
                # Get the last word that was actually translated (may not be the last in batch)
                if translations:
                    # Find the last word in the batch that was actually translated
                    for word in reversed(word_batch):
                        if word.lower() in translations:
                            last_saved_word = word
                            break
                    
                    # If we found a word that was translated, update progress
                    if last_saved_word:
                        print(f"Updating progress with last translated word: {last_saved_word}")
                        self.update_progress(last_saved_word)
                    else:
                        # If no words were translated in this batch but we processed it,
                        # update with the last word in batch to move forward
                        print(f"No new translations in this batch. Updating progress with: {word_batch[-1]}")
                        self.update_progress(word_batch[-1])
            else:
                # Even if no translations were made, update progress to move forward
                print(f"No translations in this batch. Updating progress with: {word_batch[-1]}")
                self.update_progress(word_batch[-1])
                    
            processed_batches += 1
            
            # Sleep a bit between batches to avoid rate limiting
            time.sleep(2)
        
        print("Finished processing spanish_words.txt")
        if last_saved_word:
            print(f"Last word saved to progress file: {last_saved_word}")
        else:
            print("No words were translated in this session.")

def main():
    parser = argparse.ArgumentParser(description='Batch translate Spanish words to English using Gemini API')
    parser.add_argument('--batch-size', type=int, default=1000, help='Number of words to translate in each batch')
    parser.add_argument('--limit', type=int, default=None, help='Limit the number of words to process')
    parser.add_argument('--words-file', type=str, default='spanish_words.txt', help='Path to the word list file')
    args = parser.parse_args()
    
    # Initialize translator
    translator = GeminiTranslator(batch_size=args.batch_size)
    
    try:
        # Process spanish_words.txt
        translator.process_spanish_words(words_file=args.words_file, limit=args.limit)
    except KeyboardInterrupt:
        print("\nScript interrupted by user")
    finally:
        translator.close()
        print("Database connection closed")

if __name__ == "__main__":
    main()
