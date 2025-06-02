import csv
from unicodedata import normalize, category
import re

def has_numbers(input_string):
    return any(char.isdigit() for char in input_string)

def remove_duplicates(rows):
    seen = set()
    unique_rows = []
    for row in rows:
        # Create a key from the sorted pair to handle cases like ("a", "b") and ("b", "a")
        key = tuple(sorted(row))
        if key not in seen:
            seen.add(key)
            unique_rows.append(row)
    return unique_rows

def remove_accents(input_str):
    # Normalize string to decompose accents
    nfkd = normalize('NFKD', input_str)
    # Remove all combining characters (accents)
    return ''.join(c for c in nfkd if category(c) != 'Mn')

def clean_text(text):
    # Remove parentheses and their contents
    text = re.sub(r'\([^)]*\)', '', text).strip()
    # Remove numbers
    text = re.sub(r'\d+', '', text).strip()
    # Remove commas and other unwanted characters
    text = re.sub(r'[^\w\s]', '', text).strip()
    return text

input_file = 'es-en.csv'
output_file = 'cleaned_es-en.csv'

# Read the CSV file
with open(input_file, 'r', newline='', encoding='utf-8') as infile:
    reader = csv.reader(infile)
    rows = list(reader)

# Clean and sort the rows
cleaned_rows = []
for row in rows:
    # Clean the Spanish and English columns
    spanish = clean_text(row[0])
    english = clean_text(row[1])
    cleaned_rows.append([spanish, english])

# Sort rows by the Spanish column (first column) after removing accents
cleaned_rows.sort(key=lambda row: remove_accents(row[0].lower()))  # Normalize accents for sorting

# Write the sorted rows to the output file
with open(output_file, 'w', newline='', encoding='utf-8') as outfile:
    writer = csv.writer(outfile)
    for row in cleaned_rows:
        writer.writerow(row)

print(f"Cleaned and sorted CSV saved to {output_file}")
