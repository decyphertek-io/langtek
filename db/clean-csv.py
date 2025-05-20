import csv
from unicodedata import normalize, category

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

input_file = 'translations.csv'
output_file = 'cleaned.csv'

with open(input_file, newline='', encoding='utf-8') as infile, \
     open(output_file, 'w', newline='', encoding='utf-8') as outfile:
    
    reader = csv.reader(infile)
    writer = csv.writer(outfile)
    
    # Process all rows first
    processed_rows = []
    for row in reader:
        # Skip rows with numbers in either column
        if not has_numbers(row[0]) and not has_numbers(row[1]):
            # Lowercase all columns
            processed_rows.append([col.strip().lower() for col in row])
    
    # Remove duplicates
    unique_rows = remove_duplicates(processed_rows)
    
    # Sort by Spanish word, ignoring accents
    sorted_rows = sorted(unique_rows, key=lambda x: remove_accents(x[0]))
    
    # Write the sorted rows
    for row in sorted_rows:
        writer.writerow(row)
