# Cubefront map data fetcher (runs on GitHub Actions; the game's build machine has no access to these servers).
# Sources: OpenStreetMap (c) OpenStreetMap contributors, ODbL, via Geofabrik; AHN4 heights (CC0) via PDOK WCS;
# Mapzen/AWS terrain tiles for the coarse background. Output goes to data/.
import os, re, io, json, math, time, subprocess, urllib.request, traceback
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from pyproj import Transformer
from shapely.geometry import box, Polygon, LineString, mapping
from shapely.ops import unary_union, transform as shp_transform

OUT = 'data'; os.makedirs(OUT, exist_ok=True)
MAN = {'started': time.strftime('%Y-%m-%d %H:%M:%S'), 'errors': []}
def log(*a): print(*a, flush=True)
def get(url, tries=4, timeout=180):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'cubefront-mapdata/1.0 (github.com/spaanderruben-wq/cubefront)'})
            with urllib.request.urlopen(req, timeout=timeout) as r: return r.read()
        except Exception as e:
            last = e; log('  retry', i, url[:150], repr(e)[:200]); time.sleep(2 + 4 * i)
    raise RuntimeError('failed %s: %r' % (url[:150], last))

W2R = Transformer.from_crs('EPSG:4326', 'EPSG:28992', always_xy=True)
R2W = Transformer.from_crs('EPSG:28992', 'EPSG:4326', always_xy=True)
# ---- areas (RD New metres)
ARN = box(184000, 437500, 198000, 452000)                      # all of Arnhem (+ edges of Oosterbeek, Velp, Duiven)
ax0, ay0 = W2R.transform(5.925, 52.186); ax1, ay1 = W2R.transform(6.008, 52.243)
APE = box(math.floor(ax0 / 500) * 500, math.floor(ay0 / 500) * 500, math.ceil(ax1 / 500) * 500, math.ceil(ay1 / 500) * 500)   # Apeldoorn centre + Het Loo
pa = W2R.transform(5.8990, 51.9850); pb = W2R.transform(5.9690, 52.2090)                  # Arnhem Centraal -> Apeldoorn station
BAND = LineString([pa, pb]).buffer(2600, cap_style=2)          # 5 km wide band between the two (the 1 km corridor is cut from it later)
AREA = unary_union([ARN, APE, BAND]).buffer(150)
MAN['area_rd_bounds'] = [round(v) for v in AREA.bounds]
MAN['arnhem_rd'] = [round(v) for v in ARN.bounds]; MAN['apeldoorn_rd'] = [round(v) for v in APE.bounds]; MAN['line_rd'] = [list(map(round, pa)), list(map(round, pb))]
log('area', MAN['area_rd_bounds'], 'km2', round(AREA.area / 1e6))

# ---- 1. OpenStreetMap: Geofabrik Gelderland extract, cut to the area
def osm():
    pbf = 'gelderland.osm.pbf'
    subprocess.run(['curl', '-sSL', '--retry', '4', '-o', pbf, 'https://download.geofabrik.de/europe/netherlands/gelderland-latest.osm.pbf'], check=True)
    log('gelderland pbf', os.path.getsize(pbf) // 1048576, 'MB')
    poly = shp_transform(lambda x, y, z=None: R2W.transform(x, y), AREA.simplify(50))
    json.dump({'type': 'FeatureCollection', 'features': [{'type': 'Feature', 'properties': {}, 'geometry': mapping(poly)}]}, open('area.geojson', 'w'))
    subprocess.run(['osmium', 'extract', '-p', 'area.geojson', '-s', 'smart', '--overwrite', '-o', os.path.join(OUT, 'area.osm.pbf'), pbf], check=True)
    MAN['osm_mb'] = round(os.path.getsize(os.path.join(OUT, 'area.osm.pbf')) / 1048576, 2)
    log('area.osm.pbf', MAN['osm_mb'], 'MB')

# ---- 2. AHN4 terrain (DTM) and surface (DSM, for building heights) at 5 m, 1 km tiles, from PDOK WCS
WCS = 'https://service.pdok.nl/rws/ahn/wcs/v1_0'
def ahn():
    import tifffile
    caps = get(WCS + '?SERVICE=WCS&REQUEST=GetCapabilities&VERSION=2.0.1').decode('utf8', 'replace')
    ids = re.findall(r'<wcs:CoverageId>([^<]+)</wcs:CoverageId>', caps)
    log('coverages', ids); MAN['coverages'] = ids
    def pick(kind):
        c = [i for i in ids if kind in i.lower()]
        five = [i for i in c if re.search(r'(^|[^0-9])5m', i.lower()) and '05m' not in i.lower()]
        return (five or [i for i in c if '05m' in i.lower()] or c)[0]
    cov = {'dtm': pick('dtm'), 'dsm': pick('dsm')}
    MAN['used'] = cov
    dc = get(WCS + '?SERVICE=WCS&REQUEST=DescribeCoverage&VERSION=2.0.1&COVERAGEID=' + cov['dtm']).decode('utf8', 'replace')
    m = re.search(r'axisLabels="([^"]+)"', dc); labels = m.group(1).split() if m else ['x', 'y']
    lx, ly = labels[0], labels[1]; MAN['axis'] = labels
    log('axis labels', labels, 'using', cov)
    x0, y0, x1, y1 = [int(math.floor(v / 1000) * 1000) if k < 2 else int(math.ceil(v / 1000) * 1000) for k, v in enumerate(AREA.bounds)]
    nx, ny = (x1 - x0) // 5, (y1 - y0) // 5
    arr = {k: np.full((ny, nx), -32768, np.int16) for k in cov}
    tiles = [(tx, ty) for ty in range(y0, y1, 1000) for tx in range(x0, x1, 1000) if AREA.intersects(box(tx, ty, tx + 1000, ty + 1000))]
    log('tiles', len(tiles), 'grid', nx, ny)
    fails = []
    base = WCS + '?SERVICE=WCS&VERSION=2.0.1&REQUEST=GetCoverage&COVERAGEID={cid}&FORMAT=image/tiff&SUBSET=%s({x0},{x1})&SUBSET=%s({y0},{y1})' % (lx, ly)
    variants = [base + '&SCALESIZE=%s(200),%s(200)' % (lx, ly), base + '&SCALESIZE=i(200),j(200)', base + '&SCALEFACTOR=0.1', base]
    tpl = None
    tx, ty = tiles[len(tiles) // 2]
    for v in variants:                                     # find a request form this server accepts
        try:
            b = get(v.format(cid=cov['dtm'], x0=tx, x1=tx + 1000, y0=ty, y1=ty + 1000), tries=2)
            if b[:1] != b'<': a = tifffile.imread(io.BytesIO(b)); log('probe ok', v[-40:], a.shape, a.dtype); tpl = v; break
            log('probe refused', v[-40:], b[:200])
        except Exception as e: log('probe error', v[-40:], repr(e)[:200])
    if not tpl: raise RuntimeError('no WCS request form worked')
    MAN['wcs_form'] = tpl[-60:]
    def one(job):
        kind, tx, ty = job
        url = tpl.format(cid=cov[kind], x0=tx, x1=tx + 1000, y0=ty, y1=ty + 1000)
        try:
            b = get(url, tries=3)
            if b[:1] == b'<': raise RuntimeError(b[:300].decode('utf8', 'replace'))
            a = tifffile.imread(io.BytesIO(b)).astype(np.float32)
            if a.ndim > 2: a = a[..., 0] if a.shape[-1] < 8 else a[0]
            if a.shape != (200, 200):
                yy = (np.arange(200) * a.shape[0] / 200).astype(int); xx = (np.arange(200) * a.shape[1] / 200).astype(int); a = a[yy][:, xx]
            q = np.where((a > -50) & (a < 400), np.round(a * 10), -32768).astype(np.int16)
            r0 = (y1 - (ty + 1000)) // 5; c0 = (tx - x0) // 5
            arr[kind][r0:r0 + 200, c0:c0 + 200] = q
        except Exception as e:
            fails.append((kind, tx, ty, repr(e)[:300]))
    jobs = [(k, tx, ty) for k in cov for (tx, ty) in tiles]
    t0 = time.time()
    with ThreadPoolExecutor(6) as ex:
        for i, _ in enumerate(ex.map(one, jobs)):
            if i % 50 == 0: log('  ahn', i, '/', len(jobs), round(time.time() - t0), 's, fails', len(fails))
    if fails: log('first fails', fails[:5]); MAN['ahn_fails'] = len(fails); MAN['ahn_fail_sample'] = fails[:5]
    np.savez_compressed(os.path.join(OUT, 'ahn5.npz'), dtm=arr['dtm'], dsm=arr['dsm'], meta=np.array([x0, y1, 5, nx, ny], np.int64))
    MAN['ahn'] = {'x0': x0, 'ytop': y1, 'cell': 5, 'nx': nx, 'ny': ny, 'mb': round(os.path.getsize(os.path.join(OUT, 'ahn5.npz')) / 1048576, 2)}
    log('ahn5.npz', MAN['ahn'])

# ---- 3. coarse background terrain for everything around (terrarium tiles, zoom 12, ~24 m)
def background():
    from PIL import Image
    z = 12; n = 2 ** z
    def txy(lon, lat): return (lon + 180) / 360 * n, (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n
    xa, ya = txy(5.70, 52.33); xb, yb = txy(6.18, 51.86)
    X0, X1, Y0, Y1 = int(xa), int(xb), int(ya), int(yb)
    big = np.zeros(((Y1 - Y0 + 1) * 256, (X1 - X0 + 1) * 256), np.float32)
    for ty in range(Y0, Y1 + 1):
        for tx in range(X0, X1 + 1):
            b = get('https://s3.amazonaws.com/elevation-tiles-prod/terrarium/%d/%d/%d.png' % (z, tx, ty))
            im = np.asarray(Image.open(io.BytesIO(b)).convert('RGB')).astype(np.float32)
            big[(ty - Y0) * 256:(ty - Y0 + 1) * 256, (tx - X0) * 256:(tx - X0 + 1) * 256] = im[..., 0] * 256 + im[..., 1] + im[..., 2] / 256 - 32768
    np.savez_compressed(os.path.join(OUT, 'terrarium12.npz'), h=np.round(big * 10).astype(np.int16), meta=np.array([z, X0, Y0], np.int64))
    MAN['terrarium'] = {'z': z, 'x0': X0, 'y0': Y0, 'shape': list(big.shape)}
    log('terrarium', MAN['terrarium'])

for name, fn in [('osm', osm), ('background', background), ('ahn', ahn)]:
    try:
        t0 = time.time(); fn(); MAN[name + '_s'] = round(time.time() - t0)
    except Exception as e:
        traceback.print_exc(); MAN['errors'].append(name + ': ' + repr(e)[:400])
MAN['finished'] = time.strftime('%Y-%m-%d %H:%M:%S')
json.dump(MAN, open(os.path.join(OUT, 'manifest.json'), 'w'), indent=1)
log(json.dumps(MAN, indent=1))
