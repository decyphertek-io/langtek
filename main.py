import kivy
import os
import json
import feedparser
import re
import threading
import time
import urllib.request
import subprocess
import logging
import sqlite3
import requests
import html
import sys
import random
import queue
from io import BytesIO
from PIL import Image as PILImage
from kivy.app import App
from kivy.lang import Builder
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.scrollview import ScrollView
from kivy.uix.modalview import ModalView
from kivy.uix.image import AsyncImage
from kivy.properties import StringProperty, ListProperty, ObjectProperty, BooleanProperty
from kivy.core.window import Window
from kivy.clock import Clock
from kivy.utils import platform
from functools import partial
from kivy.metrics import dp
from kivy.uix.tabbedpanel import TabbedPanel, TabbedPanelItem
from pyglossary.glossary_v2 import Glossary

# Setup logging to file
logging.basicConfig(
    filename='rss.log',
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filemode='w'  # Overwrite the log file each time
)
logger = logging.getLogger('LangTek')

class TranslationService:
    def __init__(self):
        self.from_lang = 'es'
        self.to_lang = 'en'
        self.word_dict = {}  # In-memory cache
        self.translator_available = True  # Always available with Google Translate
        self.debug_mode = True  # Enable debugging
        self.used_dictionary = "Translation APIs + SQLite"
        
        # Translation request queue and thread
        self.translation_queue = queue.Queue()
        self.queue_lock = threading.Lock()
        self.translation_thread = threading.Thread(target=self._process_translation_queue, daemon=True)
        self.max_requests_per_minute = 10  # Adjust as needed to prevent API limits
        self.request_timestamps = []
        
        # Translation APIs with rate limits
        self.translation_apis = [
            {
                'name': 'MyMemory',
                'max_per_minute': 10,
                'timestamps': [],
                'lock': threading.Lock()
            },
            {
                'name': 'LibreTranslate',
                'max_per_minute': 5,
                'timestamps': [],
                'lock': threading.Lock()
            },
            {
                'name': 'Lingva',
                'max_per_minute': 8,
                'timestamps': [],
                'lock': threading.Lock()
            }
        ]
        
        # For UI refreshing
        self.pending_translations = {}
        self.refresh_callback = None
        
        logger.info("Initializing TranslationService with multiple APIs")
        
        # Initialize SQLite database
        self.db_dir = os.path.join(os.path.dirname(__file__), 'db')
        self.db_file = os.path.join(self.db_dir, 'translations.db')
        
        # Create thread-local storage for database connections
        self.thread_local = threading.local()
        
        # Initialize database schema
        self._get_db_connection()
        self.init_database()
        
        # Add some basic common words to avoid hitting translation APIs too much
        self.add_common_words()
        
        # Start the translation queue processing thread
        self.translation_thread.start()
        
        # Run a test with common Spanish words to verify everything is working
        self.test_dictionary()
    
    def set_refresh_callback(self, callback):
        """Set a function to call when pending translations are completed"""
        self.refresh_callback = callback
        
    def _get_db_connection(self):
        """Get a thread-local database connection"""
        if not hasattr(self.thread_local, 'db_conn'):
            # Create a new connection for this thread
            self.thread_local.db_conn = sqlite3.connect(self.db_file)
            logger.debug(f"Created new SQLite connection for thread {threading.get_ident()}")
        return self.thread_local.db_conn
        
    def init_database(self):
        """Initialize the SQLite database for translations"""
        try:
            # Create directory if it doesn't exist
            os.makedirs(self.db_dir, exist_ok=True)
            
            # Connect to the database (using thread-local connection)
            conn = self._get_db_connection()
            cursor = conn.cursor()
            
            # Create table if it doesn't exist
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS translations (
                id INTEGER PRIMARY KEY,
                word TEXT NOT NULL,
                translation TEXT NOT NULL,
                source TEXT DEFAULT 'google',
                date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            ''')
            
            # Create index on word for faster lookups
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_word ON translations(word)')
            
            # Commit changes
            conn.commit()
            
            logger.info(f"Database initialized at {self.db_file}")
            print(f"Database initialized at {self.db_file}")
            
        except Exception as e:
            logger.error(f"Error initializing database: {e}")
            print(f"Error initializing database: {e}")
            self.translator_available = False
    
    def add_common_words(self):
        """Add common Spanish words to avoid hitting translation APIs too much"""
        common_words = {
            "hola": "hello",
            "adiós": "goodbye",
            "gracias": "thank you",
            "por favor": "please",
            "sí": "yes",
            "no": "no",
            "buenos días": "good morning",
            "buenas tardes": "good afternoon",
            "buenas noches": "good evening",
            "cómo estás": "how are you",
            "bien": "good",
            "mal": "bad",
            "casa": "house",
            "perro": "dog",
            "gato": "cat",
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
            "papa": "potato",
            "funeral": "funeral",
            "puentes": "bridges",
            "construir": "build",
            "Francia": "France",
            "Ucrania": "Ukraine"
        }
        
        count = 0
        conn = self._get_db_connection()
        cursor = conn.cursor()
        
        for spanish, english in common_words.items():
            try:
                cursor.execute(
                    'INSERT OR IGNORE INTO translations (word, translation, source) VALUES (?, ?, ?)',
                    (spanish.lower(), english, 'common')
                )
                count += 1
            except:
                pass
        
        conn.commit()
        logger.info(f"Added {count} common words to database")
        print(f"Added {count} common words to database")
            
    def test_dictionary(self):
        """Test the translation service with some common Spanish words"""
        print("\n=== TRANSLATION SERVICE TEST ===")
        print(f"Using: {self.used_dictionary}")
        print("Testing translation of common Spanish words:")
        
        test_words = ["hola", "casa", "perro", "gato", "libro", "papa", "Francia", "Ucrania", "líder", "de", "la"]
        max_word_len = max(len(word) for word in test_words)
        
        for word in test_words:
            translation = self.lookup_word(word)
            found = translation != "[no translation found]" and translation != "[lookup error]"
            status = "✓" if found else "✗"
            padding = " " * (max_word_len - len(word))
            result = f"  {word}{padding} → {translation} {status}"
            logger.info(result)
            print(result)
            
        logger.info("======================")
        print("======================\n")
            
    def _process_translation_queue(self):
        """Background thread that processes translation requests in the queue"""
        logger.info("Translation queue processor thread started")
        
        while True:
            try:
                # Get a translation request from the queue
                request = self.translation_queue.get(timeout=1)
                if not request:
                    self.translation_queue.task_done()
                    continue
                    
                word, from_lang, to_lang, callback = request
                
                # Rate limiting - ensure we don't exceed max_requests_per_minute
                with self.queue_lock:
                    current_time = time.time()
                    # Remove timestamps older than 1 minute
                    self.request_timestamps = [ts for ts in self.request_timestamps 
                                              if current_time - ts < 60]
                    
                    if len(self.request_timestamps) >= self.max_requests_per_minute:
                        # We've hit our rate limit, wait until we can make another request
                        sleep_time = 60 - (current_time - self.request_timestamps[0])
                        if sleep_time > 0:
                            logger.debug(f"Rate limiting: waiting {sleep_time:.2f}s before next translation")
                            time.sleep(sleep_time)
                    
                    # Add the current timestamp
                    self.request_timestamps.append(time.time())
                
                # Check database first
                translation = None
                try:
                    # Get thread-local connection
                    db_conn = self._get_db_connection()
                    db_cursor = db_conn.cursor()
                    db_cursor.execute("SELECT translation FROM translations WHERE word = ?", (word.lower(),))
                    result = db_cursor.fetchone()
                    if result:
                        translation = result[0]
                        logger.debug(f"Queue: Found '{word}' in database")
                except Exception as db_error:
                    logger.error(f"Queue: Database error: {db_error}")
                
                # If not in database, perform online translation
                if not translation:
                    try:
                        translation = self._perform_online_translation(word, from_lang, to_lang)
                        if translation:
                            # Save to database
                            try:
                                # Get thread-local connection
                                db_conn = self._get_db_connection()
                                db_cursor = db_conn.cursor()
                                db_cursor.execute(
                                    'INSERT OR IGNORE INTO translations (word, translation, source) VALUES (?, ?, ?)',
                                    (word.lower(), translation, 'api')
                                )
                                db_conn.commit()
                                logger.debug(f"Queue: Saved '{word}' to database")
                            except Exception as save_error:
                                logger.error(f"Queue: Error saving to database: {save_error}")
                    except Exception as translate_error:
                        logger.error(f"Queue: Translation error: {translate_error}")
                
                # Call the callback with the result
                if callback:
                    try:
                        callback(word, translation or "[no translation found]")
                    except Exception as callback_error:
                        logger.error(f"Queue: Callback error: {callback_error}")
                
                # Mark task as done
                self.translation_queue.task_done()
                
            except queue.Empty:
                # No requests in queue, just continue
                pass
            except Exception as e:
                logger.error(f"Queue processor error: {e}")
                # Sleep a bit to prevent tight looping if there's an error
                time.sleep(0.5)
    
    def _perform_online_translation(self, word, from_lang='es', to_lang='en'):
        """Perform actual online translation using multiple APIs with fallback"""
        
        # Try each API until one succeeds
        for api_config in self.translation_apis:
            api_name = api_config['name']
            try:
                # Check rate limits for this specific API
                with api_config['lock']:
                    current_time = time.time()
                    # Remove timestamps older than 1 minute
                    api_config['timestamps'] = [ts for ts in api_config['timestamps'] 
                                               if current_time - ts < 60]
                    
                    if len(api_config['timestamps']) >= api_config['max_per_minute']:
                        # Skip this API, it's at rate limit
                        logger.debug(f"API {api_name} rate limited, trying next")
                        continue
                    
                    # If we get here, we're under the rate limit for this API
                    api_config['timestamps'].append(current_time)
                
                # Translate using the appropriate API
                if api_name == 'MyMemory':
                    translation = self._translate_mymemory(word, from_lang, to_lang)
                elif api_name == 'LibreTranslate':
                    translation = self._translate_libretranslate(word, from_lang, to_lang)
                elif api_name == 'Lingva':
                    translation = self._translate_lingva(word, from_lang, to_lang)
                
                if translation:
                    logger.debug(f"Successfully translated '{word}' using {api_name}")
                    return translation
                    
            except Exception as e:
                logger.error(f"Error with {api_name} API: {e}")
        
        # If all APIs fail, return None
        logger.error(f"All translation APIs failed for '{word}'")
        return None
    
    def _translate_mymemory(self, word, from_lang='es', to_lang='en'):
        """Translate using MyMemory API"""
        url = f"https://api.mymemory.translated.net/get?q={word}&langpair={from_lang}|{to_lang}"
        
        response = requests.get(url, timeout=5)
        data = response.json()
        
        if 'responseData' in data and 'translatedText' in data['responseData']:
            translation = data['responseData']['translatedText']
            # Unescape HTML entities and clean up the translation
            translation = html.unescape(translation).strip()
            
            # Check if matches original word
            if translation.lower() == word.lower():
                # Try an alternative translation if available
                if 'matches' in data and len(data['matches']) > 0:
                    for match in data['matches']:
                        if 'translation' in match and match['translation'].lower() != word.lower():
                            translation = match['translation']
                            break
            
            return translation
        return None
    
    def _translate_libretranslate(self, word, from_lang='es', to_lang='en'):
        """Translate using LibreTranslate API"""
        # Using public LibreTranslate instance - can be changed if needed
        url = "https://libretranslate.org/translate"
        
        payload = {
            "q": word,
            "source": from_lang,
            "target": to_lang,
            "format": "text"
        }
        
        headers = {"Content-Type": "application/json"}
        
        response = requests.post(url, json=payload, headers=headers, timeout=5)
        data = response.json()
        
        if 'translatedText' in data:
            return data['translatedText'].strip()
        return None
    
    def _translate_lingva(self, word, from_lang='es', to_lang='en'):
        """Translate using Lingva Translate API (unofficial Google Translate API)"""
        url = f"https://lingva.ml/api/v1/{from_lang}/{to_lang}/{word}"
        
        response = requests.get(url, timeout=5)
        data = response.json()
        
        if 'translation' in data:
            return data['translation'].strip()
        return None
    
    def _check_pending_translations(self):
        """Check if there are pending translations that have completed and trigger UI refresh"""
        has_updates = False
        completed_words = []
        
        # Check if any pending translations are now in the cache
        for word in self.pending_translations:
            if word.lower() in self.word_dict:
                has_updates = True
                completed_words.append(word)
        
        # Remove completed translations from pending list
        for word in completed_words:
            del self.pending_translations[word]
        
        # If something was updated and we have a callback, trigger it
        if has_updates and self.refresh_callback:
            logger.debug("Triggering UI refresh because translations completed")
            self.refresh_callback()
    
    def queue_translation(self, word, callback=None, from_lang=None, to_lang=None):
        """Add a word to the translation queue"""
        if not word:
            return
            
        # Use default languages if not specified
        from_lang = from_lang or self.from_lang
        to_lang = to_lang or self.to_lang
        
        # Add request to queue
        self.translation_queue.put((word, from_lang, to_lang, callback))
        logger.debug(f"Added '{word}' to translation queue")
                
    def lookup_word(self, word):
        """Look up a word in the database or online if not found"""
        if not word:
            logger.debug("Empty word passed to lookup_word")
            return "[no translation found]"
        
        try:
            word_lower = word.lower().strip()
            
            # First check in memory cache (fastest)
            if word_lower in self.word_dict:
                if self.debug_mode:
                    logger.debug(f"Found '{word}' in memory cache")
                    print(f"DEBUG: Found '{word}' in memory cache")
                return self.word_dict[word_lower]
            
            # Next check in SQLite database using thread-local connection
            conn = self._get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT translation FROM translations WHERE word = ?", (word_lower,))
            result = cursor.fetchone()
            
            if result:
                if self.debug_mode:
                    logger.debug(f"Found '{word}' in database")
                    print(f"DEBUG: Found '{word}' in database")
                
                # Add to memory cache for faster future lookups
                self.word_dict[word_lower] = result[0]
                return result[0]
            
            # If not found locally, first check if we're under any API rate limit
            current_time = time.time()
            can_translate_now = False
            
            # Check if any API is available
            for api_config in self.translation_apis:
                with api_config['lock']:
                    # Remove timestamps older than 1 minute
                    api_config['timestamps'] = [ts for ts in api_config['timestamps'] 
                                              if current_time - ts < 60]
                    if len(api_config['timestamps']) < api_config['max_per_minute']:
                        can_translate_now = True
                        break
            
            if not can_translate_now:
                # We're at the rate limit for all APIs, return placeholder and queue for later
                if self.debug_mode:
                    logger.debug(f"All APIs rate limited, queueing '{word}' for later translation")
                    print(f"DEBUG: All APIs rate limited, queueing '{word}' for later translation")
                
                # Queue it for later update with a callback that adds to memory cache
                def update_cache(word_to_update, translation):
                    self.word_dict[word_to_update.lower()] = translation
                    logger.debug(f"Updated cache with delayed translation for '{word_to_update}'")
                    # Check if pending translations need UI refresh
                    self._check_pending_translations()
                
                self.queue_translation(word, update_cache)
                
                # Add to pending translations
                self.pending_translations[word] = True
                
                return "[translating...]"
            
            # We have at least one API under rate limit, do direct online lookup
            if self.debug_mode:
                logger.debug(f"Looking up '{word}' online")
                print(f"DEBUG: Looking up '{word}' online")
                
            translation = self._perform_online_translation(word_lower)
            
            if translation:
                if self.debug_mode:
                    logger.debug(f"Found '{word}' online: {translation}")
                    print(f"DEBUG: Found '{word}' online: {translation}")
                
                # Save to database using thread-local connection
                try:
                    conn = self._get_db_connection()
                    cursor = conn.cursor()
                    cursor.execute(
                        'INSERT OR IGNORE INTO translations (word, translation, source) VALUES (?, ?, ?)',
                        (word_lower, translation, 'api')
                    )
                    conn.commit()
                except Exception as db_error:
                    logger.error(f"Error saving translation to database: {db_error}")
                
                # Add to memory cache
                self.word_dict[word_lower] = translation
                
                return translation
            
            if self.debug_mode:
                logger.debug(f"No translation found for '{word}'")
                print(f"DEBUG: No translation found for '{word}'")
            return "[no translation found]"
        except Exception as e:
            if self.debug_mode:
                logger.error(f"Lookup error for '{word}': {e}")
                print(f"DEBUG: Lookup error for '{word}': {e}")
            
            # On error, add to memory cache with an error message to prevent repeated lookups
            self.word_dict[word_lower] = "[error]"
            return "[error]"  # Shorter message that won't cause concatenation errors
    
    def google_translate(self, word, from_lang='es', to_lang='en'):
        """Look up a word using Google Translate API (or free alternative)"""
        return self._perform_online_translation(word, from_lang, to_lang)

    def translate_text(self, text):
        if not text:
            return text
            
        logger.debug(f"Translating text: {text[:50]}{'...' if len(text) > 50 else ''}")
        lines = text.split('\n')
        translated_lines = []
        for line in lines:
            if not line.strip():
                translated_lines.append('')
                continue
            original_line = line.strip()
            translated_line = self.word_for_word_line(original_line)
            translated_lines.append(original_line)
            translated_lines.append(translated_line)
            translated_lines.append('')
        result = '\n'.join(translated_lines)
        logger.debug(f"Translation result: {result[:100]}{'...' if len(result) > 100 else ''}")
        return result
    
    def translate_title(self, title):
        if not title:
            return title
        logger.debug(f"Translating title: {title}")
        result = self.word_for_word_line(title)
        logger.debug(f"Title translation result: {result}")
        return result

    def word_for_word_line(self, line):
        logger.debug(f"Word-for-word translating: {line}")
        words = line.split()
        translated_words = []
        for word in words:
            # Log the word being processed
            logger.debug(f"Processing word: '{word}'")
            
            # Clean the word of punctuation
            clean_word = word.strip('.,!?:;()"\'')
            
            # Get prefix and suffix (punctuation)
            prefix = word[:len(word)-len(clean_word)] if len(clean_word) < len(word) else ''
            suffix = word[len(clean_word):] if len(clean_word) < len(word) else ''
            
            logger.debug(f"Word: '{word}', Clean: '{clean_word}', Prefix: '{prefix}', Suffix: '{suffix}'")
            
            if clean_word:
                translation = self.lookup_word(clean_word.lower())
                logger.debug(f"Translation for '{clean_word}': '{translation}'")
                
                if translation in ("[no translation found]", "[lookup error]"):
                    # If no translation, just use original word
                    translated_words.append(prefix + clean_word + suffix)
                    logger.debug(f"Using original: '{prefix + clean_word + suffix}'")
                else:
                    # Only use the original punctuation from the word, not duplicated with translation
                    translated_words.append(prefix + translation + suffix)
                    logger.debug(f"Using translation: '{prefix + translation + suffix}'")
            else:
                translated_words.append(word)
                logger.debug(f"Empty word, using as is: '{word}'")
        
        result = ' '.join(translated_words)
        logger.debug(f"Translation complete: '{result}'")
        return result

    def set_languages(self, from_lang, to_lang):
        self.from_lang = from_lang
        self.to_lang = to_lang
        logger.info(f"Using {from_lang}-{to_lang} dictionary for translations")
        print(f"Using {from_lang}-{to_lang} dictionary for translations")
    
    def __del__(self):
        """Close database connection"""
        # Try to shut down the queue gracefully
        try:
            if hasattr(self, 'translation_queue'):
                # Add None to signal thread to stop
                self.translation_queue.put(None)
        except:
            pass
        
        # No need to close connections - they're thread-local and will be cleaned up automatically

# Core RSS functionality
class RSSParser:
    def __init__(self):
        pass

    @staticmethod
    def parse_feed(url):
        try:
            return feedparser.parse(url)
        except Exception as e:
            print(f"Error parsing feed: {e}")
            return None

    @staticmethod
    def get_feed_title(feed):
        return feed.feed.title if hasattr(feed.feed, 'title') else "No Title"

    @staticmethod
    def get_entries(feed):
        return feed.entries if hasattr(feed, 'entries') else []
        
    @staticmethod
    def get_image_url(entry):
        if 'media_content' in entry and entry.media_content:
            for media in entry.media_content:
                if 'url' in media:
                    return media['url']
        
        if 'links' in entry:
            for link in entry.links:
                if 'type' in link and link['type'] and link['type'].startswith('image/'):
                    return link['href']
        
        if 'content' in entry and entry.content:
            content = entry.content[0].value if isinstance(entry.content, list) else entry.content
            match = re.search(r'<img[^>]+src="([^">]+)"', content)
            if match:
                return match.group(1)
                
        if 'summary' in entry:
            match = re.search(r'<img[^>]+src="([^">]+)"', entry.summary)
            if match:
                return match.group(1)
                
        return None
        
    @staticmethod
    def clean_html(html_content):
        # Remove all HTML tags except for basic formatting
        if not html_content:
            return ""
            
        # First unescape any HTML entities
        html_content = html.unescape(html_content)
        
        # Remove script, style tags and their content
        html_content = re.sub(r'<script.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
        html_content = re.sub(r'<style.*?</style>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
        
        # Remove all HTML tags
        html_content = re.sub(r'<[^>]+>', ' ', html_content)
        
        # Fix multiple spaces
        html_content = re.sub(r'\s+', ' ', html_content).strip()
        
        # Split into sentences (simple implementation)
        html_content = re.sub(r'([.!?])\s+', r'\1\n', html_content)
        
        return html_content

# KV Language string
KV = '''
<RSSLayout>:
        orientation: 'vertical'
        canvas.before:
                Color:
                        rgba: 0.05, 0.05, 0.05, 1
                Rectangle:
                        pos: self.pos
                        size: self.size
        BoxLayout:
                id: toolbar
                orientation: 'horizontal'
                size_hint_y: None
                height: dp(56)
                canvas.before:
                        Color:
                                rgba: 0.1, 0.1, 0.1, 1
                        Rectangle:
                                pos: self.pos
                                size: self.size
                Button:
                        id: menu_button
                        text: '⚙'
                        font_size: '24sp'
                        size_hint_x: None
                        width: dp(56)
                        background_color: 0.1, 0.1, 0.1, 1
                        background_normal: ''
                        on_release: app.show_menu()
        ScrollView:
                id: main_scroll
                do_scroll_x: False
                GridLayout:
                        id: feed_grid
                        cols: 1
                        spacing: dp(8)
                        padding: dp(8)
                        size_hint_y: None
                        height: self.minimum_height
<ArticleCard>:
        size_hint_y: None
        height: dp(150)
        orientation: 'horizontal'
        spacing: dp(10)
        padding: dp(10)
        canvas.before:
                Color:
                        rgba: 0.12, 0.12, 0.12, 1
                RoundedRectangle:
                        pos: self.pos
                        size: self.size
                        radius: [dp(10)]
        AsyncImage:
                id: thumbnail
                source: root.thumbnail_url if root.thumbnail_url else 'data/default_thumbnail.png'
                allow_stretch: True
                keep_ratio: True
                size_hint_x: 0.3
        BoxLayout:
                orientation: 'vertical'
                size_hint_x: 0.7
                padding: dp(5)
                spacing: dp(5)
                Label:
                        id: article_title
                        text: root.article_title
                        color: 0.9, 0.9, 0.9, 1
                        font_size: '16sp'
                        text_size: self.width, None
                        size_hint_y: None
                        height: self.texture_size[1]
                        halign: 'left'
                        valign: 'top'
                        bold: True
                        shorten: False
                        markup: True
                Label:
                        id: article_title_translation
                        text: root.article_title_translation
                        color: 0.7, 0.7, 0.7, 1
                        font_size: '14sp'
                        text_size: self.width, None
                        size_hint_y: None
                        height: self.texture_size[1]
                        halign: 'left'
                        valign: 'top'
                        italic: True
                        shorten: False
                Label:
                        id: feed_title
                        text: root.feed_title
                        color: 0.5, 0.5, 0.5, 1
                        font_size: '12sp'
                        text_size: self.width, None
                        size_hint_y: None
                        height: self.texture_size[1]
                        halign: 'left'
                        valign: 'bottom'
<ArticleScreen>:
        orientation: 'vertical'
        canvas.before:
                Color:
                        rgba: 0.95, 0.95, 0.95, 1
                Rectangle:
                        pos: self.pos
                        size: self.size
        BoxLayout:
                id: article_toolbar
                orientation: 'horizontal'
                size_hint_y: None
                height: dp(56)
                canvas.before:
                        Color:
                                rgba: 0.1, 0.1, 0.1, 1
                        Rectangle:
                                pos: self.pos
                                size: self.size
                Button:
                        id: back_button
                        text: '←'
                        font_size: '20sp'
                        size_hint_x: None
                        width: dp(56)
                        background_color: 0.1, 0.1, 0.1, 1
                        background_normal: ''
                        on_release: app.close_article()
                Label:
                        id: article_header
                        text: root.article_title
                        font_size: '16sp'
                        bold: True
                        color: 0.9, 0.9, 0.9, 1
                        size_hint_x: 1
                        halign: 'left'
                        text_size: self.size
                        padding_x: dp(10)
                        shorten: True
                        shorten_from: 'right'
                        valign: 'center'
                        markup: True
                Button:
                        id: article_translate_btn
                        text: 'T'
                        font_size: '18sp'
                        size_hint_x: None
                        width: dp(56)
                        background_color: 0.1, 0.1, 0.1, 1
                        background_normal: ''
                        on_release: app.toggle_article_translation()
        ScrollView:
                id: article_scroll
                do_scroll_x: False
                BoxLayout:
                        orientation: 'vertical'
                        size_hint_y: None
                        height: self.minimum_height
                        padding: dp(16)
                        spacing: dp(16)
                        AsyncImage:
                                id: article_image
                                source: root.image_url if root.image_url else ''
                                size_hint_y: None
                                height: dp(200) if root.image_url else 0
                                allow_stretch: True
                                keep_ratio: True
                                opacity: 1
                        Label:
                                id: article_date
                                text: root.article_date
                                color: 0.3, 0.3, 0.3, 1
                                size_hint_y: None
                                height: self.texture_size[1]
                                font_size: '14sp'
                                text_size: self.width, None
                                halign: 'left'
                                markup: True
                        Label:
                                id: article_content
                                text: root.article_content
                                color: 0, 0, 0, 1
                                size_hint_y: None
                                height: self.texture_size[1] + dp(100)
                                text_size: self.width, None
                                font_size: '16sp'
                                line_height: 1.5
                                markup: True
                        Button:
                                text: 'Read Full Article'
                                size_hint_y: None
                                height: dp(50)
                                background_color: 0.2, 0.5, 0, 1
                                color: 1, 1, 1, 1
                                on_release: app.open_link(root.article_link)
<MenuPopup>:
        size_hint: 0.8, None
        height: content.height
        auto_dismiss: True
        overlay_color: 0, 0, 0, 0.7
        background_color: 0, 0, 0, 0
        BoxLayout:
                id: content
                orientation: 'vertical'
                size_hint_y: None
                height: self.minimum_height
                padding: dp(16)
                spacing: dp(8)
                canvas.before:
                        Color:
                                rgba: 0.15, 0.15, 0.15, 1
                        RoundedRectangle:
                                pos: self.pos
                                size: self.size
                                radius: [dp(10)]
<AddFeedDialog>:
        title: 'Add RSS Feed'
        size_hint: 0.9, 0.3
        background_color: 0.15, 0.15, 0.15, 1
        title_color: 0.9, 0.9, 0.9, 1
        BoxLayout:
                orientation: 'vertical'
                padding: dp(20)
                spacing: dp(16)
                TextInput:
                        id: feed_url
                        hint_text: 'https://example.com/rss.xml'
                        multiline: False
                        size_hint_y: None
                        height: dp(50)
                        padding: dp(12)
                        font_size: '16sp'
                BoxLayout:
                        orientation: 'horizontal'
                        size_hint_y: None
                        height: dp(50)
                        spacing: dp(16)
                        Button:
                                text: 'Cancel'
                                background_color: 0.5, 0.5, 0.5, 1
                                on_release: root.dismiss()
                        Button:
                                text: 'Add'
                                background_color: 0.2, 0.5, 0.8, 1
                                on_release: root.add_feed()

<DatabaseEditorScreen>:
        orientation: 'vertical'
        canvas.before:
                Color:
                        rgba: 0.95, 0.95, 0.95, 1
                Rectangle:
                        pos: self.pos
                        size: self.size
        BoxLayout:
                id: editor_toolbar
                orientation: 'horizontal'
                size_hint_y: None
                height: dp(56)
                canvas.before:
                        Color:
                                rgba: 0.1, 0.1, 0.1, 1
                        Rectangle:
                                pos: self.pos
                                size: self.size
                Button:
                        id: back_button
                        text: 'Back'
                        font_size: '16sp'
                        size_hint_x: None
                        width: dp(80)
                        background_color: 0.1, 0.1, 0.1, 1
                        background_normal: ''
                        on_release: app.close_db_editor()
                Label:
                        text: 'Translation Database Editor'
                        font_size: '18sp'
                        bold: True
                        color: 0.9, 0.9, 0.9, 1
        BoxLayout:
                orientation: 'horizontal'
                padding: dp(10)
                spacing: dp(10)
                BoxLayout:
                        orientation: 'vertical'
                        size_hint_x: 0.4
                        spacing: dp(10)
                        BoxLayout:
                                orientation: 'horizontal'
                                size_hint_y: None
                                height: dp(50)
                                TextInput:
                                        id: search_input
                                        hint_text: 'Search translations...'
                                        multiline: False
                                        size_hint_x: 0.7
                                Button:
                                        text: 'Search'
                                        size_hint_x: 0.3
                                        on_release: app.search_translations(search_input.text)
                        ScrollView:
                                do_scroll_x: False
                                GridLayout:
                                        id: translation_list
                                        cols: 1
                                        spacing: dp(2)
                                        size_hint_y: None
                                        height: self.minimum_height
                BoxLayout:
                        orientation: 'vertical'
                        size_hint_x: 0.6
                        spacing: dp(10)
                        BoxLayout:
                                orientation: 'vertical'
                                size_hint_y: None
                                height: dp(120)
                                padding: dp(10)
                                canvas.before:
                                        Color:
                                                rgba: 0.9, 0.9, 0.9, 1
                                        RoundedRectangle:
                                                pos: self.pos
                                                size: self.size
                                                radius: [dp(5)]
                                Label:
                                        text: 'Word:'
                                        color: 0, 0, 0, 1
                                        size_hint_y: None
                                        height: dp(20)
                                        text_size: self.size
                                        halign: 'left'
                                TextInput:
                                        id: word_input
                                        hint_text: 'Spanish word'
                                        multiline: False
                                        size_hint_y: None
                                        height: dp(40)
                                Label:
                                        text: 'Translation:'
                                        color: 0, 0, 0, 1
                                        size_hint_y: None
                                        height: dp(20)
                                        text_size: self.size
                                        halign: 'left'
                                TextInput:
                                        id: translation_input
                                        hint_text: 'English translation'
                                        multiline: False
                                        size_hint_y: None
                                        height: dp(40)
                        BoxLayout:
                                orientation: 'horizontal'
                                size_hint_y: None
                                height: dp(50)
                                spacing: dp(10)
                                Button:
                                        text: 'Add/Update'
                                        background_color: 0.2, 0.7, 0.3, 1
                                        on_release: app.add_update_translation(word_input.text, translation_input.text)
                                Button:
                                        text: 'Delete'
                                        background_color: 0.8, 0.2, 0.2, 1
                                        on_release: app.delete_translation(word_input.text)
                        Label:
                                id: status_label
                                text: ''
                                color: 0.2, 0.6, 0.2, 1
                                size_hint_y: None
                                height: dp(30)
                        GridLayout:
                                cols: 3
                                size_hint_y: None
                                height: dp(40)
                                Label:
                                        text: 'Word'
                                        bold: True
                                Label:
                                        text: 'Translation'
                                        bold: True
                                Label:
                                        text: 'Source'
                                        bold: True
                        ScrollView:
                                do_scroll_x: False
                                GridLayout:
                                        id: translation_details
                                        cols: 3
                                        spacing: dp(2)
                                        size_hint_y: None
                                        height: self.minimum_height

<TranslationButton>:
        size_hint_y: None
        height: dp(40)
        text_size: self.width, None
        halign: 'left'
        valign: 'middle'
        padding: dp(10), dp(5)
        background_color: 0.85, 0.85, 0.85, 1
        color: 0, 0, 0, 1
'''

class ArticleCard(BoxLayout):
    article_title = StringProperty('')
    article_title_translation = StringProperty('')
    feed_title = StringProperty('')
    feed_url = StringProperty('')
    thumbnail_url = StringProperty('')
    article_link = StringProperty('')
    article_content = StringProperty('')
    article = ObjectProperty(None)

class ArticleScreen(BoxLayout):
    article_title = StringProperty('')
    article_content = StringProperty('')
    article_link = StringProperty('')
    image_url = StringProperty('')
    article_date = StringProperty('')
    original_content = StringProperty('')

class MenuPopup(ModalView):
    def __init__(self, **kwargs):
        super(MenuPopup, self).__init__(**kwargs)

class AddFeedDialog(Popup):
    def __init__(self, add_callback, **kwargs):
        super(AddFeedDialog, self).__init__(**kwargs)
        self.add_callback = add_callback
    
    def add_feed(self):
        url = self.ids.feed_url.text.strip()
        
        if url:
            feed = RSSParser.parse_feed(url)
            if feed:
                title = RSSParser.get_feed_title(feed)
                self.add_callback(url, title)
                self.dismiss()
            else:
                error_popup = Popup(
                    title='Error',
                    content=Label(text='Invalid feed URL'),
                    size_hint=(0.6, 0.3)
                )
                error_popup.open()
        else:
            self.ids.feed_url.hint_text = "URL cannot be empty"

class RSSLayout(BoxLayout):
    pass

class DatabaseEditorScreen(BoxLayout):
    pass

class TranslationButton(Button):
    word = StringProperty('')
    
    def on_release(self):
        app = App.get_running_app()
        if hasattr(app, 'select_translation'):
            app.select_translation(self.word)

class RSSApp(App):
    def __init__(self, **kwargs):
        super(RSSApp, self).__init__(**kwargs)
        self.article_screen = None
        self.db_editor_screen = None
        self.translator = TranslationService()
        self.article_translation_enabled = False
        self.current_article = None
        self.selected_translation = None
        
        # Set up translation update callback
        self.translator.set_refresh_callback(self.refresh_translations)

    def build(self):
        Builder.load_string(KV)
        self.root = RSSLayout()
        self.feeds = []
        self.current_articles = []
        
        if not os.path.exists('feeds.json'):
            self.save_feeds()
        
        self.load_feeds()
        Clock.schedule_once(self.load_all_feeds, 0.5)
        return self.root
    
    def load_feeds(self):
        feed_file = 'feeds.json'
        try:
            with open(feed_file, 'r') as f:
                feed_data = json.load(f)
                if feed_data:
                    self.feeds = []
                    for feed in feed_data:
                        if 'url' in feed and 'title' in feed:
                            self.feeds.append({'url': feed['url'], 'title': feed['title']})
                    print(f"Loaded {len(self.feeds)} feeds from {feed_file}")
        except Exception as e:
            print(f"Error loading feeds: {e}")
    
    def save_feeds(self):
        feed_file = 'feeds.json'
        try:
            with open(feed_file, 'w') as f:
                json.dump(self.feeds, f, indent=2)
            print(f"Saved {len(self.feeds)} feeds to {feed_file}")
        except Exception as e:
            print(f"Error saving feeds: {e}")
    
    def load_all_feeds(self, dt):
        self.root.ids.feed_grid.clear_widgets()
        
        if not self.feeds:
            placeholder = Label(
                text='No feeds added yet. Use the menu to add RSS feeds.',
                color=(0.8, 0.8, 0.8, 1),
                size_hint_y=None,
                height=dp(100)
            )
            self.root.ids.feed_grid.add_widget(placeholder)
            return
        
        for feed_data in self.feeds:
            threading.Thread(target=self.fetch_feed, args=(feed_data,), daemon=True).start()
    
    def fetch_feed(self, feed_data):
        feed = RSSParser.parse_feed(feed_data['url'])
        if feed:
            entries = RSSParser.get_entries(feed)
            if entries:
                for entry in entries[:10]:
                    title = entry.get('title', 'No Title')
                    clean_title = RSSParser.clean_html(title)
                    # Translate the title (word-for-word)
                    title_translation = self.translator.word_for_word_line(clean_title)
                    image_url = RSSParser.get_image_url(entry)
                    if not image_url:
                        image_url = 'https://via.placeholder.com/300x200'
                    Clock.schedule_once(lambda dt, e=entry, t=clean_title, tt=title_translation, i=image_url, f=feed_data['title']: 
                                         self.add_article_card(e, t, tt, i, f, feed_data['url']), 0)
    
    def add_article_card(self, article, title, title_translation, image_url, feed_title, feed_url):
        # Check if card already exists
        for child in self.root.ids.feed_grid.children[:]:
            if (isinstance(child, ArticleCard) and 
                child.article_link == article.get('link', '#')):
                # Update existing card instead of creating a duplicate
                english_line = self.translator.word_for_word_line(title)
                stacked_title = f"{title}\n[i][color=#777777]{english_line}[/color][/i]"
                child.article_title = stacked_title
                child.thumbnail_url = image_url
                return
                
        # Stack Spanish and English translation in the title label, English in gray italics
        english_line = self.translator.word_for_word_line(title)
        stacked_title = f"{title}\n[i][color=#777777]{english_line}[/color][/i]"
        card = ArticleCard(
            article_title=stacked_title,
            article_title_translation='',
            feed_title=feed_title,
            feed_url=feed_url,
            thumbnail_url=image_url,
            article_link=article.get('link', '#'),
            article=article
        )
        card.bind(on_touch_down=self.on_card_touched)
        self.root.ids.feed_grid.add_widget(card)
    
    def on_card_touched(self, card, touch):
        if card.collide_point(*touch.pos):
            if hasattr(card, 'article') and card.article:
                self.show_article(card.article)
            return True
    
    def show_article(self, article):
        title = article.get('title', 'No title available')
        content = article.get('summary', 'No content available')
        link = article.get('link', '#')
        published = article.get('published', '')
        clean_title = RSSParser.clean_html(title)
        clean_content = RSSParser.clean_html(content)
        
        # Store the original content for reference
        self.current_article = {
            'title': clean_title,
            'content': clean_content
        }
        
        # Stack Spanish and English translation in the title label, English in gray italics
        english_title = self.translator.word_for_word_line(clean_title)
        stacked_title = f"{clean_title}\n[i][color=#777777]{english_title}[/color][/i]"
        
        # For content, interleave Spanish and English lines, English in gray italics
        lines = clean_content.split('\n')
        translated_lines = []
        for line in lines:
            if not line.strip():
                translated_lines.append('')
                continue
            translated_lines.append(line)
            translated_lines.append(f"[i][color=#777777]{self.translator.word_for_word_line(line)}[/color][/i]")
        stacked_content = '\n'.join(translated_lines)
        
        image_url = RSSParser.get_image_url(article)
        
        if not self.article_screen:
            self.article_screen = ArticleScreen()
            self.root.add_widget(self.article_screen)
            
        self.article_screen.article_title = stacked_title
        self.article_screen.article_content = stacked_content
        self.article_screen.article_link = link
        self.article_screen.image_url = image_url
        self.article_screen.article_date = published
        self.article_screen.original_content = clean_content
        
        self.article_translation_enabled = True
        if hasattr(self.article_screen.ids, 'article_translate_btn'):
            self.article_screen.ids.article_translate_btn.text = 'O'  # 'O' for Original
            
        # Schedule periodic checks for translation updates (every 2 seconds)
        Clock.schedule_interval(self._check_translations_update, 2)
    
    def _check_translations_update(self, dt):
        """Check if there are any completed translations that should update the UI"""
        if hasattr(self.translator, '_check_pending_translations'):
            self.translator._check_pending_translations()
    
    def close_article(self):
        if self.article_screen:
            # Stop the translation update checker
            Clock.unschedule(self._check_translations_update)
            
            self.root.remove_widget(self.article_screen)
            self.article_screen = None
            self.current_article = None
    
    def toggle_article_translation(self):
        if not self.article_screen or not self.current_article:
            return
        
        self.article_translation_enabled = not self.article_translation_enabled
        
        if self.article_translation_enabled:
            # Apply word-for-word translation
            translated_content = self.translator.translate_text(self.current_article['content'])
            self.article_screen.article_content = translated_content
            self.article_screen.ids.article_translate_btn.text = 'O'  # 'O' for Original
        else:
            # Restore original content
            self.article_screen.article_content = self.current_article['content']
            self.article_screen.ids.article_translate_btn.text = 'T'  # 'T' for Translate
    
    def show_menu(self):
        menu = MenuPopup()
        content = menu.ids.content
        
        # Add feed option
        add_feed_btn = Button(
            text='Add Feed',
            size_hint_y=None,
            height=dp(60),
            background_color=(0.2, 0.5, 0.8, 1),
            font_size='16sp'
        )
        add_feed_btn.bind(on_release=lambda x: self.show_add_feed_dialog(menu))
        content.add_widget(add_feed_btn)
        
        # Refresh button
        refresh_btn = Button(
            text='Refresh Feeds',
            size_hint_y=None,
            height=dp(60),
            background_color=(0.2, 0.6, 0.2, 1),
            font_size='16sp'
        )
        refresh_btn.bind(on_release=lambda x: self.refresh_feeds(menu))
        content.add_widget(refresh_btn)
        
        # Translation DB editor button
        db_editor_btn = Button(
            text='Edit Translations',
            size_hint_y=None,
            height=dp(60),
            background_color=(0.8, 0.4, 0.2, 1),
            font_size='16sp'
        )
        db_editor_btn.bind(on_release=lambda x: self.show_db_editor(menu))
        content.add_widget(db_editor_btn)
        
        # Show feeds if any
        if self.feeds:
            feeds_label = Label(
                text='Your Feeds',
                size_hint_y=None,
                height=dp(40),
                color=(0.8, 0.8, 0.8, 1),
                font_size='14sp',
                bold=True
            )
            content.add_widget(feeds_label)
            
            # List each feed with delete option
            for i, feed in enumerate(self.feeds):
                feed_box = BoxLayout(
                    orientation='horizontal',
                    size_hint_y=None,
                    height=dp(50),
                    spacing=dp(8)
                )
                
                feed_label = Label(
                    text=feed['title'],
                    size_hint_x=0.8,
                    text_size=(None, None),
                    halign='left',
                    color=(0.9, 0.9, 0.9, 1)
                )
                
                delete_btn = Button(
                    text='×',
                    size_hint_x=0.2,
                    background_color=(0.8, 0.2, 0.2, 1)
                )
                delete_btn.bind(on_release=lambda btn, idx=i: self.delete_feed(idx, menu))
                
                feed_box.add_widget(feed_label)
                feed_box.add_widget(delete_btn)
                content.add_widget(feed_box)
        
        menu.open()
    
    def delete_feed(self, index, menu):
        if 0 <= index < len(self.feeds):
            del self.feeds[index]
            self.save_feeds()
            menu.dismiss()
            self.load_all_feeds(0)
    
    def refresh_feeds(self, menu=None):
        if menu:
            menu.dismiss()
        self.load_all_feeds(0)
    
    def show_add_feed_dialog(self, menu=None):
        if menu:
            menu.dismiss()
        dialog = AddFeedDialog(add_callback=self.add_feed)
        dialog.open()
    
    def add_feed(self, url, title):
        feed_data = {'url': url, 'title': title}
        self.feeds.append(feed_data)
        self.save_feeds()
        self.load_all_feeds(0)
    
    def open_link(self, link):
        print(f"Opening link: {link}")
        if platform == 'android':
            try:
                from android.intent import Intent
                from jnius import autoclass
                PythonActivity = autoclass('org.kivy.android.PythonActivity')
                Intent = autoclass('android.content.Intent')
                Uri = autoclass('android.net.Uri')
                browserIntent = Intent()
                browserIntent.setAction(Intent.ACTION_VIEW)
                browserIntent.setData(Uri.parse(link))
                currentActivity = PythonActivity.mActivity
                currentActivity.startActivity(browserIntent)
            except Exception as e:
                print(f"Error opening link on Android: {e}")
        else:
            import webbrowser
            webbrowser.open(link)

    def refresh_translations(self):
        """Refresh UI when pending translations complete"""
        if not self.article_screen:
            return
            
        # If we're in an article view, refresh the article content
        if self.current_article:
            title = self.current_article.get('title', '')
            content = self.current_article.get('content', '')
            
            # Regenerate the translations
            if title:
                english_title = self.translator.word_for_word_line(title)
                stacked_title = f"{title}\n[i][color=#777777]{english_title}[/color][/i]"
                self.article_screen.article_title = stacked_title
            
            if content:
                # For content, interleave Spanish and English lines
                lines = content.split('\n')
                translated_lines = []
                for line in lines:
                    if not line.strip():
                        translated_lines.append('')
                        continue
                    translated_lines.append(line)
                    translated_lines.append(f"[i][color=#777777]{self.translator.word_for_word_line(line)}[/color][/i]")
                stacked_content = '\n'.join(translated_lines)
                self.article_screen.article_content = stacked_content
        
        # DON'T reload all feeds - this causes duplicate windows
        # Instead, just update the existing widgets
        self._update_feed_widgets()
    
    def _update_feed_widgets(self):
        """Update existing feed widgets with new translations without creating duplicates"""
        if not hasattr(self.root.ids, 'feed_grid'):
            return
            
        # Loop through existing article cards and update translations
        for child in self.root.ids.feed_grid.children[:]:
            if isinstance(child, ArticleCard):
                title = child.article_title.split('\n')[0] if '\n' in child.article_title else child.article_title
                # Strip any Kivy markup
                title = re.sub(r'\[.*?\]', '', title).strip()
                
                # Get updated translation
                english_line = self.translator.word_for_word_line(title)
                stacked_title = f"{title}\n[i][color=#777777]{english_line}[/color][/i]"
                child.article_title = stacked_title

    def show_db_editor(self, menu=None):
        """Show the database editor screen"""
        if menu:
            menu.dismiss()
            
        if not self.db_editor_screen:
            self.db_editor_screen = DatabaseEditorScreen()
            
        # Add to root
        self.root.add_widget(self.db_editor_screen)
        
        # Load translations
        self.load_translations()
    
    def close_db_editor(self):
        """Close the database editor screen"""
        if self.db_editor_screen:
            self.root.remove_widget(self.db_editor_screen)
    
    def load_translations(self, search_term=None):
        """Load translations from the database into the editor"""
        if not self.db_editor_screen:
            return
            
        # Clear existing items
        if hasattr(self.db_editor_screen.ids, 'translation_list'):
            self.db_editor_screen.ids.translation_list.clear_widgets()
        
        if hasattr(self.db_editor_screen.ids, 'translation_details'):
            self.db_editor_screen.ids.translation_details.clear_widgets()
        
        try:
            # Get all translations
            conn = self.translator._get_db_connection()
            cursor = conn.cursor()
            
            if search_term:
                # Search for specific terms
                cursor.execute(
                    "SELECT word, translation, source FROM translations WHERE word LIKE ? OR translation LIKE ? ORDER BY word LIMIT 200",
                    (f"%{search_term}%", f"%{search_term}%")
                )
            else:
                # Get recent translations
                cursor.execute(
                    "SELECT word, translation, source FROM translations ORDER BY date_added DESC LIMIT 100"
                )
                
            translations = cursor.fetchall()
            
            for word, translation, source in translations:
                # Create a button for the list
                item = TranslationButton(text=word, word=word)
                self.db_editor_screen.ids.translation_list.add_widget(item)
                
                # Add to details grid
                word_label = Label(
                    text=word, 
                    color=(0, 0, 0, 1),
                    size_hint_y=None,
                    height=dp(30),
                    text_size=(None, None),
                    halign='left'
                )
                translation_label = Label(
                    text=translation, 
                    color=(0, 0, 0, 1),
                    size_hint_y=None,
                    height=dp(30),
                    text_size=(None, None),
                    halign='left'
                )
                source_label = Label(
                    text=source, 
                    color=(0, 0, 0, 1),
                    size_hint_y=None,
                    height=dp(30),
                    text_size=(None, None),
                    halign='left'
                )
                
                self.db_editor_screen.ids.translation_details.add_widget(word_label)
                self.db_editor_screen.ids.translation_details.add_widget(translation_label)
                self.db_editor_screen.ids.translation_details.add_widget(source_label)
                
            # Update status
            if hasattr(self.db_editor_screen.ids, 'status_label'):
                self.db_editor_screen.ids.status_label.text = f"Loaded {len(translations)} translations"
            
        except Exception as e:
            logger.error(f"Error loading translations: {e}")
            if hasattr(self.db_editor_screen.ids, 'status_label'):
                self.db_editor_screen.ids.status_label.text = f"Error: {e}"
    
    def search_translations(self, search_term):
        """Search for translations in the database"""
        self.load_translations(search_term)
    
    def select_translation(self, word):
        """Select a translation for editing"""
        if not self.db_editor_screen:
            return
            
        try:
            # Get current translation data from DB
            conn = self.translator._get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT translation, source FROM translations WHERE word = ?", (word.lower(),))
            result = cursor.fetchone()
            
            if not result:
                return
                
            translation, source = result
            
            # Update input fields
            self.db_editor_screen.ids.word_input.text = word
            self.db_editor_screen.ids.translation_input.text = translation
            
            # Store selection
            self.selected_translation = (word, translation, source)
            
            # Update status
            self.db_editor_screen.ids.status_label.text = f"Selected: {word}"
        except Exception as e:
            logger.error(f"Error selecting translation: {e}")
            if hasattr(self.db_editor_screen.ids, 'status_label'):
                self.db_editor_screen.ids.status_label.text = f"Error: {e}"
    
    def add_update_translation(self, word, translation):
        """Add or update a translation in the database"""
        if not word or not translation:
            if self.db_editor_screen:
                self.db_editor_screen.ids.status_label.text = "Error: Word and translation required"
            return
            
        try:
            # Save to database
            conn = self.translator._get_db_connection()
            cursor = conn.cursor()
            
            # Check if word exists
            cursor.execute("SELECT id FROM translations WHERE word = ?", (word.lower(),))
            result = cursor.fetchone()
            
            if result:
                # Update existing translation
                cursor.execute(
                    "UPDATE translations SET translation = ?, source = 'manual', date_added = CURRENT_TIMESTAMP WHERE word = ?",
                    (translation, word.lower())
                )
                action = "Updated"
            else:
                # Add new translation
                cursor.execute(
                    "INSERT INTO translations (word, translation, source) VALUES (?, ?, 'manual')",
                    (word.lower(), translation)
                )
                action = "Added"
                
            conn.commit()
            
            # Update memory cache
            self.translator.word_dict[word.lower()] = translation
            
            # Update status
            if self.db_editor_screen:
                self.db_editor_screen.ids.status_label.text = f"{action} translation for '{word}'"
                
            # Reload translations
            self.load_translations()
            
        except Exception as e:
            logger.error(f"Error adding/updating translation: {e}")
            if self.db_editor_screen:
                self.db_editor_screen.ids.status_label.text = f"Error: {e}"
    
    def delete_translation(self, word):
        """Delete a translation from the database"""
        if not word:
            if self.db_editor_screen:
                self.db_editor_screen.ids.status_label.text = "Error: No word specified"
            return
            
        try:
            # Delete from database
            conn = self.translator._get_db_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM translations WHERE word = ?", (word.lower(),))
            conn.commit()
            
            # Remove from memory cache
            if word.lower() in self.translator.word_dict:
                del self.translator.word_dict[word.lower()]
            
            # Update status
            if self.db_editor_screen:
                self.db_editor_screen.ids.status_label.text = f"Deleted translation for '{word}'"
                
            # Reload translations
            self.load_translations()
            
        except Exception as e:
            logger.error(f"Error deleting translation: {e}")
            if self.db_editor_screen:
                self.db_editor_screen.ids.status_label.text = f"Error: {e}"

if __name__ == '__main__':
    RSSApp().run()