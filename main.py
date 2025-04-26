import kivy
import os
import json
import feedparser
import re
import threading
import time
import urllib.request
import subprocess
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
import html
from pyglossary.glossary import Glossary

class TranslationService:
    def __init__(self):
        self.from_lang = 'es'
        self.to_lang = 'en'
        self.word_dict = {}
        self.translator_available = False
        
        # Initialize pyglossary
        Glossary.init()
        
        # Look for dictionary in various locations and formats
        dict_paths = [
            # MOBI format
            os.path.join(os.path.dirname(__file__), 'db', 'Spanish-English-Dictionary.mobi'),
            '/home/adminotaur/Documents/git/langtek/db/Spanish-English-Dictionary.mobi',
            
            # SLOB format
            os.path.join(os.path.dirname(__file__), 'db', 'freedict-spa-eng-0.3.1.slob'),
            '/home/adminotaur/Documents/git/langtek/db/freedict-spa-eng-0.3.1.slob',
            
            # StarDict format
            os.path.join(os.path.dirname(__file__), 'db', 'spa-eng', 'spa-eng.ifo'),
            '/home/adminotaur/Documents/git/langtek/db/spa-eng/spa-eng.ifo',
            
            # Data file (tab-separated) format
            os.path.join(os.path.dirname(__file__), 'db', 'es-en.data'),
            '/home/adminotaur/Documents/git/langtek/db/es-en.data'
        ]
        
        for dict_path in dict_paths:
            if os.path.exists(dict_path):
                print(f"Found dictionary at {dict_path}")
                try:
                    if dict_path.endswith('.data'):
                        # Handle .data format (tab-separated values)
                        self.load_data_dictionary(dict_path)
                        if self.translator_available:
                            print(f"Successfully loaded .data dictionary: {dict_path}")
                            break
                    else:
                        # Handle other formats with PyGlossary (MOBI, SLOB, StarDict)
                        self.glossary = Glossary()
                        success = self.glossary.read(dict_path)
                        if not success:
                            print(f"Failed to read dictionary: {dict_path}")
                            continue
                        
                        # Cache first 10000 common words for faster access
                        count = 0
                        for entry in self.glossary:
                            word = entry[0]
                            defi = entry[1]
                            if word and defi:
                                self.word_dict[word.lower()] = defi.split(',')[0] if ',' in defi else defi
                                count += 1
                                if count >= 10000:  # Limit number of cached entries
                                    break
                                    
                        self.translator_available = True
                        print(f"Successfully loaded {os.path.splitext(dict_path)[1]} dictionary: {dict_path}")
                        break
                except Exception as e:
                    print(f"Error loading dictionary {dict_path}: {e}")
        
        if not self.translator_available:
            print("No dictionary found or loaded. Translation will not be available.")
            
    def load_data_dictionary(self, file_path):
        """Load a dictionary from a tab-separated .data file"""
        try:
            print(f"Loading tab-separated dictionary file: {file_path}")
            count = 0
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    parts = line.split('\t')
                    if len(parts) >= 2:
                        word = parts[0].strip()
                        definition = parts[1].strip()
                        if word and definition:
                            self.word_dict[word.lower()] = definition
                            count += 1
                            if count >= 50000:  # Limit entries in memory
                                break
            
            self.translator_available = count > 0
            print(f"Loaded {count} words from {file_path}")
        except Exception as e:
            print(f"Error loading .data dictionary {file_path}: {e}")
                
    def lookup_word(self, word):
        if not word or not self.translator_available:
            return "[no translation found]"
        
        try:
            # First check in cache
            if word.lower() in self.word_dict:
                return self.word_dict[word.lower()]
            
            # If not in cache and glossary is available, try lookup in glossary
            if hasattr(self, 'glossary'):
                try:
                    result = self.glossary.lookup(word)
                    if result:
                        definition = result
                        # Store in cache for future lookups
                        self.word_dict[word.lower()] = definition
                        return definition
                except Exception as lookup_error:
                    print(f"Error during glossary lookup for '{word}': {lookup_error}")
            
            return "[no translation found]"
        except Exception as e:
            print(f"Lookup error: {e}")
            return "[lookup error]"

    def translate_text(self, text):
        if not text or not self.translator_available:
            return text
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
        return '\n'.join(translated_lines)
    
    def translate_title(self, title):
        if not title or not self.translator_available:
            return title
        return self.word_for_word_line(title)

    def word_for_word_line(self, line):
        words = line.split()
        translated_words = []
        for word in words:
            clean_word = word.strip('.,!?:;()"\'')
            prefix = word[:len(word)-len(clean_word)] if len(clean_word) < len(word) else ''
            suffix = word[len(clean_word):] if len(clean_word) < len(word) else ''
            if clean_word:
                translation = self.lookup_word(clean_word.lower())
                if translation in ("[no translation found]", "[lookup error]"):
                    translated_words.append(prefix + clean_word + suffix)
                else:
                    translated_words.append(prefix + translation + suffix)
            else:
                translated_words.append(word)
        return ' '.join(translated_words)

    def set_languages(self, from_lang, to_lang):
        self.from_lang = from_lang
        self.to_lang = to_lang
        print(f"Using {from_lang}-{to_lang} dictionary for translations")

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

class RSSApp(App):
    def __init__(self, **kwargs):
        super(RSSApp, self).__init__(**kwargs)
        self.article_screen = None
        self.translator = TranslationService()
        self.article_translation_enabled = False
        self.current_article = None

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
        self.current_article = {
            'title': clean_title,
            'content': clean_content,
            'translated_title': stacked_title,
            'translated_content': stacked_content
        }
        self.article_translation_enabled = True
        if hasattr(self.article_screen.ids, 'article_translate_btn'):
            self.article_screen.ids.article_translate_btn.text = 'O'  # 'O' for Original
    
    def close_article(self):
        if self.article_screen:
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

if __name__ == '__main__':
    RSSApp().run()