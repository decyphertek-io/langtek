from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.label import Label
import sqlite3

class DatabaseEditor(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'vertical'
        
        # Connect to database
        self.conn = sqlite3.connect('translations.db')
        self.cursor = self.conn.cursor()
        
        # Create UI elements
        self.spanish_input = TextInput(hint_text='Spanish word', multiline=False)
        self.english_input = TextInput(hint_text='English translation', multiline=False)
        self.result_label = Label(text='Database Editor')
        
        # Add buttons
        add_button = Button(text='Add Translation')
        add_button.bind(on_press=self.add_translation)
        
        search_button = Button(text='Search Translation')
        search_button.bind(on_press=self.search_translation)
        
        # Layout
        self.add_widget(self.spanish_input)
        self.add_widget(self.english_input)
        self.add_widget(add_button)
        self.add_widget(search_button)
        self.add_widget(self.result_label)
        
    def add_translation(self, instance):
        spanish = self.spanish_input.text.strip()
        english = self.english_input.text.strip()
        if spanish and english:
            try:
                # First check if the word exists
                self.cursor.execute("SELECT * FROM translations WHERE word = ? COLLATE NOCASE", (spanish.lower(),))
                existing = self.cursor.fetchone()
                
                if existing:
                    # Update existing record
                    self.cursor.execute(
                        "UPDATE translations SET translation = ? WHERE word = ?",
                        (english, spanish.lower())
                    )
                else:
                    # Insert new record
                    self.cursor.execute(
                        "INSERT INTO translations (word, translation) VALUES (?, ?)",
                        (spanish.lower(), english)
                    )
                
                self.conn.commit()
                self.result_label.text = f'Updated: {spanish} → {english}'
            except Exception as e:
                self.result_label.text = f'Error: {str(e)}'
        else:
            self.result_label.text = 'Please enter both words'
    
    def search_translation(self, instance):
        spanish = self.spanish_input.text.strip()
        if spanish:
            self.cursor.execute("SELECT translation FROM translations WHERE word = ? COLLATE NOCASE", (spanish.lower(),))
            result = self.cursor.fetchone()
            if result:
                self.english_input.text = result[0]
                self.result_label.text = f'Found: {spanish} → {result[0]}'
            else:
                self.result_label.text = f'No translation found for {spanish}'
        else:
            self.result_label.text = 'Please enter a word to search'

class DatabaseEditorApp(App):
    def build(self):
        return DatabaseEditor()

if __name__ == '__main__':
    DatabaseEditorApp().run()
