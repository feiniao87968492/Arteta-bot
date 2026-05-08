import sys
with open('/tmp/debug.log', 'rb') as f:
    content = f.read()
idx = content.find('区间'.encode('utf-8'))
if idx >= 0:
    chunk = content[idx:idx+80]
    print('Hex:', chunk.hex())
    print('Chars:', chunk.decode('utf-8', errors='replace'))
    for i, b in enumerate(chunk):
        if b == 0x5c:
            print(f'  POS {idx+i}: ASCII backslash (0x5c)')
    chunk2 = content[idx+200:idx+400]
    print('\n--- Another region ---')
    print('Hex:', chunk2.hex())
    print('Chars:', chunk2.decode('utf-8', errors='replace'))
    for i, b in enumerate(chunk2):
        if b == 0x5c:
            print(f'  POS {idx+200+i}: ASCII backslash (0x5c)')
