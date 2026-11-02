import sys
import idna
assert sys.version_info[:2] == (3, 13)
assert idna.encode('bücher.example') == b'xn--bcher-kva.example'
print('locked Pixi Python')
