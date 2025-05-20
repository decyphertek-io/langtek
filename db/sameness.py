import unicodedata

def normalize(text):
    return unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii').lower()

with open('translations.csv', 'r') as f:
    lines = f.readlines()

with open('translations.csv', 'w') as f:
    for line in lines:
        parts = line.strip().split(',')
        if len(parts) >= 2 and normalize(parts[0]) != normalize(parts[1]):
            f.write(line)