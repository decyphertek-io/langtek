with open('translations.csv', 'r') as f:
    lines = f.readlines()

with open('translations.csv', 'w') as f:
    for line in lines:
        parts = line.strip().split(',')
        if len(parts) >= 2 and parts[0] != parts[1]:
            f.write(line)