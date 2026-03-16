
import os

filepath = 'repro_output.txt'
if os.path.exists(filepath):
    with open(filepath, 'rb') as f:
        content = f.read()
    
    # Try different encodings
    for encoding in ['utf-16', 'utf-16le', 'utf-8']:
        try:
            text = content.decode(encoding)
            print(f"--- Decoded with {encoding} ---")
            print(text)
            break
        except:
            pass
else:
    print(f"File {filepath} not found")
