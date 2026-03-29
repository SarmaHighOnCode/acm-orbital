lines=open('README.md', encoding='utf-8').readlines()
lines[25]='Wait for \AUTO_SEED | Complete — dashboard ready\ in the terminal (~60 seconds), then open **http://localhost:8000**.\n'.replace('\\', '\')
open('README.md', 'w', encoding='utf-8').writelines(lines)

