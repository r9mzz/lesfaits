import requests, urllib.parse

def test_kw(kw):
    hdrs = {'User-Agent': 'LesFaits/1.1'}
    params = urllib.parse.urlencode({
        'action':'query','format':'json','generator':'search',
        'gsrnamespace':'6','gsrsearch':kw,'gsrlimit':'8',
        'prop':'imageinfo','iiprop':'url|size|mime','iiurlwidth':'1200'
    })
    r = requests.get(f'https://commons.wikimedia.org/w/api.php?{params}', timeout=10, headers=hdrs)
    pages = r.json().get('query',{}).get('pages',{}).values()
    results = []
    for p in pages:
        ii = p.get('imageinfo',[{}])[0]
        url = ii.get('thumburl') or ii.get('url','')
        fname = url.rsplit('/',1)[-1][:60]
        w = ii.get('thumbwidth') or ii.get('width',0)
        h = ii.get('thumbheight') or ii.get('height',0)
        mime = ii.get('mime','')
        ok = mime in ('image/jpeg','image/png','image/webp') and w >= 600 and h >= 300
        tag = 'OK' if ok else '--'
        results.append(f'  {tag} {fname} [{w}x{h}] {mime[:10]}')
    return results

tests = [
    ('cracked dry soil earth', 'secheresse'),
    ('heatwave hot summer street', 'canicule'),
    ('factory chimney smoke pollution', 'co2'),
    ('used clothes second hand pile', 'fashion'),
    ('ebola virus outbreak Africa', 'ebola'),
    ('robot surgery hospital operating', 'ia-sante'),
    ('health clinic waiting room patients', 'ars'),
    ('french parliament paris building', 'delsol'),
]
for kw, name in tests:
    print(f'\n[{name}] kw: {kw}')
    for line in test_kw(kw):
        print(line)
