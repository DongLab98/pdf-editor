import json, re, os, io, zipfile, tarfile, urllib.request, zstandard
d = json.load(open('/tmp/win64_current.json'))
pk = {**d.get('packages', {}), **d.get('packages.conda', {})}
by = {}
for fn, v in pk.items():
    by.setdefault(v['name'], []).append((fn, v))
def best(name, pin=None):
    c = by.get(name, [])
    if pin: c = [x for x in c if x[1]['version'] == pin.split()[0] and (len(pin.split())<2 or x[1]['build']==pin.split()[1])] or c
    c = [x for x in c if not (name=='python' and not x[1]['version'].startswith('3.12'))]
    c = [x for x in c if not (name=='openssl' and not x[1]['version'].startswith('3.'))]  # python 3.12 은 OpenSSL 3 으로 빌드됨
    return max(c, key=lambda kv: (kv[0].endswith('.conda'), kv[1].get('timestamp', 0)))
SKIP = {'tk', 'tzdata', 'ucrt', 'vc', 'vs2015_runtime', 'python_abi'}
todo, seen = [('python', None)], {}
while todo:
    n, pin = todo.pop()
    if n in seen or n in SKIP or n not in by: continue
    fn, v = best(n, pin); seen[n] = fn
    for dep in v['depends']:
        parts = dep.split()
        dn = parts[0]
        dpin = None
        if dn == 'libpython' and len(parts) >= 3: dpin = parts[1] + ' ' + parts[2]
        todo.append((dn, dpin))
print(seen)
for n, fn in seen.items():
    p = f'pkgs/{fn}'
    if not os.path.exists(p):
        urllib.request.urlretrieve(f'https://conda.anaconda.org/conda-forge/win-64/{fn}', p)
    z = zipfile.ZipFile(p)
    for m in z.namelist():
        if m.startswith('pkg-') and m.endswith('.tar.zst'):
            data = zstandard.ZstdDecompressor().stream_reader(io.BytesIO(z.read(m)))
            tarfile.open(fileobj=data, mode='r|').extractall('py', filter='data')
