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
from datetime import datetime

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
        self.word_dict = {}
        self.translator_available = True
        self.debug_mode = True
        self.used_dictionary = "Translation APIs + SQLite"
        
        self.translation_queue = queue.Queue()
        self.queue_lock = threading.Lock()
        self.translation_thread = threading.Thread(target=self._process_translation_queue, daemon=True)
        self.max_requests_per_minute = 10
        self.request_timestamps = []
        
        self.translation_apis = [
            {
                'name': 'LibreTranslate',
                'max_per_minute': 15,
                'timestamps': [],
                'lock': threading.Lock()
            },
            {
                'name': 'Lingva',
                'max_per_minute': 20,
                'timestamps': [],
                'lock': threading.Lock()
            },
            {
                'name': 'SimplyTranslate',
                'max_per_minute': 15,
                'timestamps': [],
                'lock': threading.Lock()
            },
            {
                'name': 'DeepL',
                'max_per_minute': 10,
                'timestamps': [],
                'lock': threading.Lock()
            }
        ]
        
        self.pending_translations = {}
        self.refresh_callback = None
        
        logger.info("Initializing TranslationService with multiple APIs")
        
        self.db_dir = os.path.join(os.path.dirname(__file__), 'db')
        self.db_file = os.path.join(self.db_dir, 'es-en.sqlite3')
        
        self.thread_local = threading.local()
        
        self._get_db_connection()
        self.init_database()
        
        self.translation_thread.start()
    
    def set_refresh_callback(self, callback):
        """Set a function to call when pending translations are completed"""
        self.refresh_callback = callback
        
    def _get_db_connection(self):
        """Get a thread-local database connection with better locking"""
        if not hasattr(self.thread_local, 'db_conn'):
            # Create db directory if it doesn't exist
            os.makedirs(self.db_dir, exist_ok=True)
            
            # Create a new connection for this thread with timeout
            self.thread_local.db_conn = sqlite3.connect(
                self.db_file, 
                timeout=30.0,  # Wait up to 30 seconds for lock to clear
                isolation_level=None  # Enable autocommit mode
            )
            
            # Use direct writes instead of WAL mode
            cursor = self.thread_local.db_conn.cursor()
            cursor.execute("PRAGMA journal_mode=DELETE")  # Use standard rollback journal
            cursor.execute("PRAGMA synchronous=FULL")  # Full synchronization
            cursor.execute("PRAGMA busy_timeout=30000")  # 30 seconds
            
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
            
            # Create table if it doesn't exist - match es-en.sqlite3 schema
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS translations (
                spanish TEXT PRIMARY KEY,
                english TEXT
            )
            ''')
            
            # Create index on word for faster lookups
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_spanish ON translations(spanish)')
            
            # Commit changes
            conn.commit()
            
            logger.info(f"Database initialized at {self.db_file}")
            print(f"Database initialized at {self.db_file}")
            
        except Exception as e:
            logger.error(f"Error initializing database: {e}")
            print(f"Error initializing database: {e}")
            self.translator_available = False
            
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
                    db_cursor.execute("SELECT english FROM translations WHERE spanish = ? COLLATE NOCASE", (word.lower(),))
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
                                self._save_translation_to_db(word, translation)
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
                translation = None
                if api_name == 'LibreTranslate':
                    translation = self._translate_libretranslate(word, from_lang, to_lang)
                elif api_name == 'Lingva':
                    translation = self._translate_lingva(word, from_lang, to_lang)
                elif api_name == 'SimplyTranslate':
                    translation = self._translate_simplytranslate(word, from_lang, to_lang)
                elif api_name == 'DeepL':
                    translation = self._translate_deepl(word, from_lang, to_lang)
                
                if translation:
                    logger.debug(f"Successfully translated '{word}' using {api_name}")
                    if self.debug_mode:
                        print(f"DEBUG: Translated '{word}' using API: {api_name}")
                    # Return both the translation and the API used
                    return {"text": translation, "api": api_name}
                    
            except Exception as e:
                logger.error(f"Error with {api_name} API: {e}")
                if self.debug_mode:
                    print(f"DEBUG: Error with {api_name} API: {str(e)[:100]}")
        
        # If all APIs fail, return None
        logger.error(f"All translation APIs failed for '{word}'")
        return None
    
    def _translate_libretranslate(self, word, from_lang='es', to_lang='en'):
        """Translate using LibreTranslate API with better endpoint management"""
        
        # List of LibreTranslate endpoints in order of preference
        endpoints = [
            "https://translate.terraprint.co/translate",
            "https://lt.vern.cc/translate",
            "https://translate.fedilab.app/translate",
            "https://translate.astian.org/translate"
        ]
        
        # Remove translate.argosopentech.com since it consistently fails with name resolution errors
        
        for endpoint in endpoints:
            try:
                # Standard LibreTranslate API format
                headers = {'Content-Type': 'application/json'}
                data = {
                    'q': word,
                    'source': from_lang,
                    'target': to_lang,
                    'format': 'text'
                }
                
                response = requests.post(endpoint, headers=headers, json=data, timeout=5)
                
                if response.status_code == 200:
                    result = response.json()
                    if 'translatedText' in result:
                        return result['translatedText']
                else:
                    logger.debug(f"[LibreTranslate API error] {response.status_code} from {endpoint}")
                    
            except Exception as e:
                logger.error(f"Error with LibreTranslate API ({endpoint}): {e}")
                # Continue to the next endpoint
        
        return None
    
    def _translate_lingva(self, word, from_lang='es', to_lang='en'):
        """Translate using Lingva Translate API (unofficial Google Translate API)"""
        # Try multiple Lingva instances in order of reliability
        endpoints = [
            "https://lingva.garudalinux.org/api/v1",
            "https://lingva.pussthecat.org/api/v1",
            "https://translate.plausibility.cloud/api/v1"
        ]
        
        for endpoint in endpoints:
            try:
                url = f"{endpoint}/{from_lang}/{to_lang}/{urllib.parse.quote(word)}"
                response = requests.get(url, timeout=5)
                
                if response.status_code == 200:
                    data = response.json()
                    if 'translation' in data:
                        return data['translation'].strip()
            except Exception as e:
                logger.debug(f"Error with Lingva endpoint {endpoint}: {e}")
                continue
        
        return None
    
    def _translate_simplytranslate(self, word, from_lang='es', to_lang='en'):
        """Translate using SimplyTranslate API (no API key required)"""
        # Try multiple SimplyTranslate instances
        endpoints = [
            "https://simplytranslate.org",
            "https://st.tokhmi.xyz",
            "https://translate.josias.dev"
        ]
        
        for endpoint in endpoints:
            try:
                url = f"{endpoint}/api/translate"
                
                params = {
                    'engine': 'google',  # Use Google as the backend engine
                    'from': from_lang,
                    'to': to_lang,
                    'text': word
                }
                
                response = requests.get(url, params=params, timeout=5)
                
                if response.status_code == 200:
                    try:
                        data = response.json()
                        if 'translation' in data:
                            return data['translation'].strip()
                    except Exception as e:
                        logger.debug(f"Error parsing SimplyTranslate response: {e}")
                        continue
            except Exception as e:
                logger.debug(f"Error with SimplyTranslate endpoint {endpoint}: {e}")
                continue
        
        return None
        
    def _translate_deepl(self, word, from_lang='es', to_lang='en'):
        """Translate using DeepL API (free tier)"""
        url = "https://api-free.deepl.com/v2/translate"
        
        # DeepL requires an API key - this is a placeholder for the API key
        # In a real app, this would be securely stored and retrieved
        headers = {
            'Authorization': 'DeepL-Auth-Key YOUR_API_KEY',
            'Content-Type': 'application/json',
        }
        
        data = {
            'text': [word],
            'source_lang': from_lang.upper(),
            'target_lang': to_lang.upper(),
        }
        
        response = requests.post(url, headers=headers, json=data, timeout=5)
        
        if response.status_code == 200:
            result = response.json()
            if 'translations' in result and len(result['translations']) > 0:
                return result['translations'][0]['text']
        
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
            source_info = ""
            
            # First check in memory cache (fastest)
            if word_lower in self.word_dict:
                if isinstance(self.word_dict[word_lower], dict):
                    translation = self.word_dict[word_lower]["text"]
                    source_info = f" [source: {self.word_dict[word_lower]['source']}]"
                else:
                    translation = self.word_dict[word_lower]
                    source_info = " [source: cache]"
                    
                if self.debug_mode:
                    logger.debug(f"Found '{word}' in memory cache{source_info}")
                    print(f"DEBUG: Found '{word}' in memory cache{source_info}")
                return translation
            
            # Check directly in SQLite translations.db database
            conn = self._get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT english FROM translations WHERE spanish = ? COLLATE NOCASE", (word_lower,))
            result = cursor.fetchone()
            
            if result:
                translation = result[0]
                source_info = " [source: database]"
                
                if self.debug_mode:
                    logger.debug(f"Found '{word}' in translations.db database")
                    print(f"DEBUG: Found '{word}' in translations.db database")
                
                # Add to memory cache for faster future lookups
                self.word_dict[word_lower] = {"text": translation, "source": "database"}
                return translation
            
            # If not found locally, check if we're under any API rate limit
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
                    if isinstance(translation, dict):
                        self.word_dict[word_to_update.lower()] = translation
                    else:
                        self.word_dict[word_to_update.lower()] = {"text": translation, "source": "delayed_api"}
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
                
            result = self._perform_online_translation(word_lower)
            
            if result and isinstance(result, dict):
                translation = result["text"]
                api_used = result["api"]
                source_info = f" [source: {api_used}]"
                
                if self.debug_mode:
                    logger.debug(f"Found '{word}' online using {api_used}: {translation}")
                    print(f"DEBUG: Found '{word}' online using {api_used}: {translation}")
                
                # Save to database using thread-local connection
                try:
                    conn = self._get_db_connection()
                    cursor = conn.cursor()
                    cursor.execute(
                        'INSERT OR REPLACE INTO translations (spanish, english) VALUES (?, ?)',
                        (word_lower, translation)
                    )
                    conn.commit()
                except Exception as db_error:
                    logger.error(f"Error saving translation to database: {db_error}")
                    if self.debug_mode:
                        print(f"DEBUG: Error saving to database: {str(db_error)[:100]}")
                
                # Add to memory cache
                self.word_dict[word_lower] = {"text": translation, "source": api_used}
                
                return translation
            
            if self.debug_mode:
                logger.debug(f"No translation found for '{word}'")
                print(f"DEBUG: No translation found for '{word}'")
            return "[no translation found]"
        except Exception as e:
            if self.debug_mode:
                logger.error(f"Lookup error for '{word}': {e}")
                print(f"DEBUG: Lookup error for '{word}': {str(e)[:100]}")
            
            # On error, add to memory cache with an error message to prevent repeated lookups
            self.word_dict[word_lower] = {"text": "[error]", "source": "error"}
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
            logger.debug(f"Processing word: '{word}'")
            
            # Extract punctuation
            clean_word = re.sub(r'[^\w\s]', '', word)
            prefix = ''
            suffix = ''
            
            # Get prefix (punctuation at beginning)
            match = re.match(r'^([^\w\s]*)(.*)', word)
            if match:
                prefix, remaining = match.groups()
            
            # Get suffix (punctuation at end)
            match = re.match(r'(.*?)([^\w\s]*)$', word if not prefix else remaining)
            if match:
                word_part, suffix = match.groups()
            
            # Get the clean word
            clean_word = word[len(prefix):len(word)-len(suffix)] if prefix or suffix else word
            
            logger.debug(f"Word: '{word}', Clean: '{clean_word}', Prefix: '{prefix}', Suffix: '{suffix}'")
            
            # Handle empty word
            if not clean_word:
                translated_words.append(word)
                logger.debug(f"Empty word, using as is: '{word}'")
                continue
            
            # Check for capitalization
            is_capitalized = clean_word[0].isupper() if clean_word else False
            
            # Lookup the word in lowercase
            translation = self.lookup_word(clean_word.lower())
            logger.debug(f"Translation for '{clean_word.lower()}': '{translation}'")
            
            if translation in ("[no translation found]", "[lookup error]"):
                # If no translation, use original word
                translated_words.append(prefix + clean_word + suffix)
                logger.debug(f"Using original: '{prefix + clean_word + suffix}'")
            else:
                # Apply original capitalization to the translation
                if is_capitalized and translation:
                    translation = translation[0].upper() + translation[1:]
                
                # Add prefix and suffix
                translated_words.append(prefix + translation + suffix)
                logger.debug(f"Using translation: '{prefix + translation + suffix}'")
        
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

    def _save_translation_to_db(self, word, translation):
        """Save a word and its translation to the database"""
        try:
            if not word or not translation:
                return
            
            # Extract the text from the translation if it's a dictionary
            translation_text = translation["text"] if isinstance(translation, dict) else translation
            # Get the API name if available
            api_name = translation.get("api", "API") if isinstance(translation, dict) else "API"
            
            conn = self._get_db_connection()
            cursor = conn.cursor()
            
            # Check if word already exists
            cursor.execute("SELECT spanish FROM translations WHERE spanish=? COLLATE NOCASE", (word.lower(),))
            exists = cursor.fetchone()
            
            if not exists:
                cursor.execute(
                    "INSERT OR REPLACE INTO translations (spanish, english) VALUES (?, ?)",
                    (word.lower(), translation_text)
                )
                conn.commit()
                logger.debug(f"[Database   ] Saved translation for '{word}': '{translation_text}' from {api_name}")
            
        except Exception as e:
            logger.error(f"[Queue       ] Error saving to database: {e}")

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
                        background_color: 0.2, 0.5, 0.8, 1
                        color: 1, 1, 1, 1
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
                        text: 'Translate'
                        font_size: '16sp'
                        bold: True
                        size_hint_x: None
                        width: dp(120)
                        height: dp(40)
                        background_color: 0.2, 0.5, 0.8, 1  # Blue color
                        background_normal: ''
                        border: (2, 2, 2, 2)
                        color: 1, 1, 1, 1  # White text
                        canvas.before:
                                Color:
                                        rgba: 0.2, 0.5, 0.8, 1  # Match background_color
                                RoundedRectangle:
                                        pos: self.pos
                                        size: self.size
                                        radius: [dp(8)]
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
                                height: self.texture_size[1]
                                text_size: self.width, None
                                font_size: '16sp'
                                line_height: 1.5
                                markup: True
                                valign: 'top'
                                halign: 'left'

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
                                rgba: 0.25, 0.25, 0.25, 1
                        RoundedRectangle:
                                pos: self.pos
                                size: self.size
                                radius: [dp(10)]
<AddFeedDialog>:
        title: 'Add RSS Feed'
        size_hint: 0.9, 0.3
        background_color: 0.3, 0.3, 0.3, 1
        title_color: 1, 1, 1, 1
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
                        foreground_color: 1, 1, 1, 1
                        background_color: 0.2, 0.2, 0.2, 1
                        cursor_color: 1, 1, 1, 1
                        hint_text_color: 0.7, 0.7, 0.7, 1
                BoxLayout:
                        orientation: 'horizontal'
                        size_hint_y: None
                        height: dp(50)
                        spacing: dp(16)
                        Button:
                                text: 'Cancel'
                                background_color: 0.5, 0.5, 0.5, 1
                                color: 1, 1, 1, 1
                                on_release: root.dismiss()
                        Button:
                                text: 'Add'
                                background_color: 0.2, 0.5, 0.8, 1
                                color: 1, 1, 1, 1
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

class TranslatorPanel(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'vertical'
        self.size_hint_x = 0.3
        
        title_label = Label(text='Translator', size_hint_y=0.1, 
                          bold=True, font_size='18sp')
        self.add_widget(title_label)
        
        self.source_text = TextInput(hint_text='Paste Spanish text here',
                                   size_hint_y=0.4, multiline=True)
        self.add_widget(self.source_text)
        
        self.translate_btn = Button(text='Translate', size_hint_y=0.1)
        self.translate_btn.bind(on_release=self.on_translate)
        self.add_widget(self.translate_btn)
        
        self.result_text = TextInput(hint_text='Translation will appear here',
                                   readonly=True, size_hint_y=0.5)
        self.add_widget(self.result_text)

    def on_translate(self, instance):
        text = self.source_text.text
        if not text:
            return
        
        try:
            app = App.get_running_app()
            translation = app.translator._perform_online_translation(text, 'es', 'en')
            if isinstance(translation, dict) and 'text' in translation:
                self.result_text.text = translation['text']
            else:
                self.result_text.text = translation or "Translation failed"
        except Exception as e:
            self.result_text.text = f"Error: {str(e)}"

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
        
        # Create main layout with horizontal orientation
        main_layout = BoxLayout(orientation='horizontal')
        
        # Create the RSS layout and keep reference to it
        self.rss_layout = RSSLayout()
        main_layout.add_widget(self.rss_layout)
        
        # Add translator panel to the right
        translator_panel = TranslatorPanel()
        main_layout.add_widget(translator_panel)
        
        # Set up other app initialization
        self.feeds = []
        self.current_articles = []
        
        if not os.path.exists('feeds.json'):
            self.save_feeds()
        
        self.load_feeds()
        Clock.schedule_once(self.load_all_feeds, 0.5)
        
        return main_layout
    
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
        self.rss_layout.ids.feed_grid.clear_widgets()
        
        if not self.feeds:
            placeholder = Label(
                text='No feeds added yet. Use the menu to add RSS feeds.',
                color=(0.8, 0.8, 0.8, 1),
                size_hint_y=None,
                height=dp(100)
            )
            self.rss_layout.ids.feed_grid.add_widget(placeholder)
            return
        
        # First collect all entries from all feeds
        all_entries = []
        for feed_data in self.feeds:
            feed = RSSParser.parse_feed(feed_data['url'])
            if feed:
                entries = RSSParser.get_entries(feed)
                if entries:
                    for entry in entries[:10]:
                        all_entries.append((entry, feed_data))
        
        # Sort by date (newest first)
        all_entries.sort(key=lambda x: x[0].get('published_parsed', (0,)), reverse=True)
        
        # Load all entries with placeholder translations
        for entry, feed_data in all_entries:
            title = entry.get('title', 'No Title')
            clean_title = RSSParser.clean_html(title)
            
            # Create stacked title with [translating...] placeholder
            stacked_title = f"{clean_title}\n[i][color=#777777][translating...][/color][/i]"
            
            # Get image URL
            image_url = RSSParser.get_image_url(entry)
            if not image_url:
                image_url = 'https://via.placeholder.com/300x200'
            
            # Add card with placeholder translation
            self.add_article_card(entry, stacked_title, image_url, feed_data['title'], feed_data['url'])
        
        # Then start translations in a separate thread
        threading.Thread(target=self._translate_all_titles, args=(all_entries,), daemon=True).start()
    
    def _translate_all_titles(self, entries):
        """Translate all titles after cards are loaded"""
        for entry, feed_data in entries:
            title = entry.get('title', 'No Title')
            clean_title = RSSParser.clean_html(title)
            
            # Find the card for this entry
            card = None
            for child in self.rss_layout.ids.feed_grid.children[:]:
                if isinstance(child, ArticleCard) and child.article_link == entry.get('link', '#'):
                    card = child
                    break
            
            if card:
                # Translate the title
                english_line = self.translator.word_for_word_line(clean_title)
                stacked_title = f"{clean_title}\n[i][color=#777777]{english_line}[/color][/i]"
                
                # Update on the main thread
                Clock.schedule_once(lambda dt, c=card, st=stacked_title: setattr(c, 'article_title', st), 0)
    
    def _translate_article_title(self, article, title):
        """Translate article title and update the card"""
        # This method is no longer used - translations are now done in _translate_all_titles
        pass
    
    def add_article_card(self, article, title, image_url, feed_title, feed_url):
        # Check if card already exists
        for child in self.rss_layout.ids.feed_grid.children[:]:
            if isinstance(child, ArticleCard) and child.article_link == article.get('link', '#'):
                # Update existing card instead of creating a duplicate
                child.article_title = title
                child.thumbnail_url = image_url
                return
                
        # Create card with title and image
        card = ArticleCard(
            article_title=title,
            feed_title=feed_title,
            feed_url=feed_url,
            thumbnail_url=image_url,
            article_link=article.get('link', '#'),
            article_content=article.get('summary', ''),
            article=article
        )
        card.bind(on_touch_down=self.on_card_touched)
        self.rss_layout.ids.feed_grid.add_widget(card)
    
    def on_card_touched(self, card, touch):
        if card.collide_point(*touch.pos):
            if hasattr(card, 'article') and card.article:
                self.show_article(card.article)
            return True
    
    def show_article(self, article):
        title = article.get('title', 'No title available')
        link = article.get('link', '#')
        published = article.get('published', '')
        
        # Always try to fetch full article content first
        try:
            logger.debug(f"Fetching full content for article: {link}")
            content = self._fetch_full_article_content(link)
            if not content:
                # Fallback to summary if content fetch fails
                content = article.get('summary', 'No content available')
                logger.warning(f"Failed to fetch full content, using summary for: {link}")
        except Exception as e:
            logger.error(f"Error fetching full article: {e}")
            content = article.get('summary', 'No content available')
        
        clean_title = RSSParser.clean_html(title)
        clean_content = RSSParser.clean_html(content)
        
        # Store the original content for reference
        self.current_article = {
            'title': clean_title,
            'content': clean_content
        }
        
        # Check if article_screen already exists and has a parent
        if self.article_screen and self.article_screen.parent:
            self.article_screen.parent.remove_widget(self.article_screen)
        
        # Create new ArticleScreen if needed
        self.article_screen = ArticleScreen() if not self.article_screen else self.article_screen
        self.rss_layout.add_widget(self.article_screen)
        
        self.article_screen.article_title = clean_title
        self.article_screen.article_content = clean_content
        self.article_screen.article_link = link
        self.article_screen.article_date = published
        self.article_screen.image_url = RSSParser.get_image_url(article)
        self.article_screen.original_content = clean_content
        
        self.article_translation_enabled = False
        if hasattr(self.article_screen.ids, 'article_translate_btn'):
            self.article_screen.ids.article_translate_btn.text = 'Translate'
        
        # Start pre-translating in the background
        threading.Thread(target=self._background_translate, args=(clean_content,), daemon=True).start()

    def _fetch_full_article_content(self, url):
        """Fetch full article content from a URL"""
        try:
            # Use requests to fetch the article
            response = requests.get(url, timeout=10)
            if response.status_code != 200:
                logger.error(f"Failed to fetch article: {response.status_code}")
                return None
            
            # Parse HTML content with regex
            html_content = response.text
            
            # For Clarin articles, extract the main content
            # This regex pattern looks for content between article body tags
            if 'clarin.com' in url.lower():
                # Look for the article body
                body_match = re.search(r'<div\s+class="[^"]*article-body[^"]*">(.*?)</div>\s*<div\s+class="[^"]*related-content', 
                                      html_content, re.DOTALL)
                
                if body_match:
                    content = body_match.group(1)
                    # Clean up the content
                    content = re.sub(r'<script.*?</script>', '', content, flags=re.DOTALL | re.IGNORECASE)
                    content = re.sub(r'<style.*?</style>', '', content, flags=re.DOTALL | re.IGNORECASE)
                    content = re.sub(r'<[^>]+>', ' ', content)
                    content = re.sub(r'\s+', ' ', content).strip()
                    return content
            
            return None
        except Exception as e:
            logger.error(f"Error fetching article content: {e}")
            return None
    
    def _background_translate(self, content):
        """Pre-translate content in the background to make it ready when needed"""
        if not content:
            return
            
        # Split content into lines
        lines = content.split('\n')
        
        for line in lines:
            if not line.strip():
                continue
                
            # Pre-translate each line and cache the results
            # This doesn't affect the UI yet, but prepares translations
            self.translator.word_for_word_line(line)
            
        logger.debug("Background translation completed")
    
    def toggle_article_translation(self):
        if not self.article_screen or not self.current_article:
            return
        
        self.article_translation_enabled = not self.article_translation_enabled
        
        if self.article_translation_enabled:
            # Start progressive translation 
            self.article_screen.ids.article_translate_btn.text = 'Original'
            
            # Translate the title
            title = self.current_article.get('title', '')
            if title:
                english_title = self.translator.word_for_word_line(title)
                stacked_title = f"{title}\n[i][color=#777777]{english_title}[/color][/i]"
                self.article_screen.article_title = stacked_title
                # Also update the header if it exists
                if hasattr(self.article_screen.ids, 'article_header'):
                    self.article_screen.ids.article_header.text = stacked_title
            
            # Translate the content
            content = self.current_article['content']
            lines = content.split('\n')
            
            # First, display original content with placeholders
            displayed_lines = []
            for i, line in enumerate(lines):
                if not line.strip():
                    displayed_lines.append('')
                    continue
                displayed_lines.append(line)
                displayed_lines.append('[i][color=#777777]Translating...[/color][/i]')
            
            self.article_screen.article_content = '\n'.join(displayed_lines)
            
            # Then translate line by line with animation effect
            Clock.schedule_once(lambda dt: self._animate_translation(lines, 0), 0.1)
        else:
            # Restore original content
            self.article_screen.article_content = self.current_article['content']
            self.article_screen.article_title = self.current_article['title']
            # Also restore the header if it exists
            if hasattr(self.article_screen.ids, 'article_header'):
                self.article_screen.ids.article_header.text = self.current_article['title']
            self.article_screen.ids.article_translate_btn.text = 'Translate'
    
    def _animate_translation(self, lines, current_line):
        """Progressively translate and update the content line by line"""
        if not self.article_translation_enabled or current_line >= len(lines):
            return
            
        if not lines[current_line].strip():
            # Skip empty lines
            Clock.schedule_once(lambda dt: self._animate_translation(lines, current_line + 1), 0.05)
            return
            
        # Get current displayed content
        if not hasattr(self.article_screen, 'ids') or not hasattr(self.article_screen.ids, 'article_content'):
            return
            
        displayed_text = self.article_screen.article_content
        displayed_lines = displayed_text.split('\n')
        
        # Translate current line
        line = lines[current_line]
        translation = self.translator.word_for_word_line(line)
        
        # Update the translation line
        translation_line_index = current_line * 2 + 1
        if translation_line_index < len(displayed_lines):
            displayed_lines[translation_line_index] = f'[i][color=#777777]{translation}[/color][/i]'
            
        # Update display
        self.article_screen.article_content = '\n'.join(displayed_lines)
        
        # Schedule next line
        Clock.schedule_once(lambda dt: self._animate_translation(lines, current_line + 1), 0.1)
    
    def close_article(self):
        if self.article_screen:
            self.rss_layout.remove_widget(self.article_screen)
            self.article_screen = None
            self.current_article = None
    
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
        if not hasattr(self.rss_layout.ids, 'feed_grid'):
            return
            
        # Loop through existing article cards and update translations
        for child in self.rss_layout.ids.feed_grid.children[:]:
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
            
        # Check if db_editor_screen already exists and has a parent
        if self.db_editor_screen and self.db_editor_screen.parent:
            self.db_editor_screen.parent.remove_widget(self.db_editor_screen)
        
        if not self.db_editor_screen:
            self.db_editor_screen = DatabaseEditorScreen()
            
        # Add to root
        self.rss_layout.add_widget(self.db_editor_screen)
        
        # Load translations
        self.load_translations()
    
    def close_db_editor(self):
        """Close the database editor screen"""
        if self.db_editor_screen:
            self.rss_layout.remove_widget(self.db_editor_screen)
    
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
                    "SELECT spanish, english FROM translations WHERE spanish LIKE ? OR english LIKE ? ORDER BY spanish LIMIT 200",
                    (f"%{search_term}%", f"%{search_term}%")
                )
            else:
                # Get recent translations (no date_added column, using english for sorting)
                cursor.execute(
                    "SELECT spanish, english FROM translations ORDER BY english DESC LIMIT 100"
                )
                
            translations = cursor.fetchall()
            
            for spanish, english in translations:
                # Create a button for the list
                item = TranslationButton(text=spanish, word=spanish)
                self.db_editor_screen.ids.translation_list.add_widget(item)
                
                # Add to details grid
                spanish_label = Label(
                    text=spanish, 
                    color=(0, 0, 0, 1),
                    size_hint_y=None,
                    height=dp(30),
                    text_size=(None, None),
                    halign='left'
                )
                english_label = Label(
                    text=english, 
                    color=(0, 0, 0, 1),
                    size_hint_y=None,
                    height=dp(30),
                    text_size=(None, None),
                    halign='left'
                )
                
                self.db_editor_screen.ids.translation_details.add_widget(spanish_label)
                self.db_editor_screen.ids.translation_details.add_widget(english_label)
                
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
            cursor.execute("SELECT english FROM translations WHERE spanish = ?", (word.lower(),))
            result = cursor.fetchone()
            
            if not result:
                return
                
            english = result[0]
            
            # Update input fields
            self.db_editor_screen.ids.word_input.text = word
            self.db_editor_screen.ids.translation_input.text = english
            
            # Store selection
            self.selected_translation = (word, english)
            
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
            cursor.execute("SELECT spanish FROM translations WHERE spanish = ?", (word.lower(),))
            result = cursor.fetchone()
            
            if result:
                # Update existing translation
                cursor.execute(
                    "UPDATE translations SET english = ? WHERE spanish = ?",
                    (translation, word.lower())
                )
                action = "Updated"
            else:
                # Add new translation
                cursor.execute(
                    "INSERT OR IGNORE INTO translations (spanish, english) VALUES (?, ?)",
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
            cursor.execute("DELETE FROM translations WHERE spanish = ?", (word.lower(),))
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