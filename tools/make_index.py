# Rebuilds the game (index.html) on GitHub: applies the code patch named in tools/patch/go.txt to the previous
# build (index.html or tools/skeleton.html), then adds the map made by tools/osm2map.py from the data in data/.
import os, sys, glob, hashlib, subprocess
def sha(s): return hashlib.sha256(s.encode('utf-8')).hexdigest()
def rd(f): return open(f, encoding='utf-8', newline='').read()
tag = rd('tools/patch/go.txt').strip()
P = sorted(glob.glob('tools/patch/%s/p*.txt' % tag), key=lambda f: int(os.path.basename(f)[1:-4]))
if not P: sys.exit('no patch files for ' + tag)
L = []
for f in P: L += rd(f).split('\n')[:-1]
meta = {}
for l in L[:3]:
    if l.startswith('@@BASE ') or l.startswith('@@RESULT '): k, v = l.split(' ', 1); meta[k] = v
base = None
for c in ['tools/skeleton.html', 'index.html']:
    if os.path.exists(c) and sha(rd(c)) == meta['@@BASE']: base = rd(c); print('patch base:', c); break
if base is None: sys.exit('patch base not found')
a = base.split('\n'); out = []; i = 0
while i < len(L):
    l = L[i]
    if l.startswith('@@BASE ') or l.startswith('@@RESULT ') or l == '': i += 1
    elif l.startswith('@@C '): _, x, y = l.split(); out += a[int(x):int(y)]; i += 1
    elif l.startswith('@@I '): n = int(l[4:]); out += L[i + 1:i + 1 + n]; i += 1 + n
    else: sys.exit('bad patch line: ' + l[:80])
skel = '\n'.join(out)
if sha(skel) != meta['@@RESULT']: sys.exit('patched code does not match its checksum')
open('tools/skeleton.html', 'w', encoding='utf-8', newline='').write(skel)
os.makedirs('/tmp/mapout', exist_ok=True)
subprocess.run([sys.executable, 'tools/osm2map.py', 'data', '/tmp/mapout'], check=True)
md = rd('/tmp/mapout/mapdata.js'); an = rd('/tmp/mapout/arnnames.js')
html = skel.replace('/*@MAPDATA@*/', md.replace('</script', '<\\/script'), 1).replace('/*@ARNNAMES@*/', an.replace('</script', '<\\/script'), 1)
open('index.html', 'w', encoding='utf-8', newline='').write(html)
print('index.html', len(html) // 1024, 'KB', 'build', tag)
