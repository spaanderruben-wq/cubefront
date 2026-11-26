# Cubefront pieces: file formats (for step B)

Game coordinates as in GELDERLAND.md. A piece `(ix, iz)` is the square x in [ix*4096, (ix+1)*4096), z likewise. Folder: `pieces/<ix>_<iz>/`.
`base/index.json` lists every piece with its file sizes and counts (`stats`: B buildings, H roads, W water, F forest, S/G/K/D/R areas, V waterways,
T rail, stop, fuel, tower). `done.json` in a piece folder is only the build marker.

| File | What |
|---|---|
| `map.bin` | Raw-deflate (windowBits -15) of the feature stream, **the same format v4 as the old `mapdata.js` field `f`** (see `check/decode_map.py` for a complete decoder). Header region = the piece square. Roads/rails/waterways are cut at the piece edge; the cut point is whole metres and identical in both neighbours. Bridge and rail height profiles are cut with them. Buildings and points belong to the piece holding their centre/position (half-open). Trees are at the end of the stream. |
| `terr.bin` | Raw-deflate of: version 2, then zigzag varints x0, z0 (grid origin = piece corner minus 64 m), cell (5 or 10 m), n; then n x n bytes (row-major, z rows) predicted as left + up - upleft (mod 256). Byte `q`: height = (q/2) - 10 in metres NAP-ish game level as in the old terrain (`q8`); 0 = no data (use `base/terrain_bg.bin`). |
| `street.bin` | Raw-deflate, same layers as the old `streetdata.js`, version byte **2**: the z deltas of each layer start at `iz*4096 - 1` (not -40000). |
| `ground.bin` | The old `grounddata.js` blob (adaptive range coder, 15 classes, 1 km squares of 500 x 500 cells of 2 m) holding the BGT squares whose centre lies in the piece. Decode with `gcDecode` in `real.js`. |
| `names.json` | Same object as the old `arnnames.js` (`c` cities, `a` areas, `s` streets, `p` places) for this piece. |
| `nav.bin`, `nav.json` | Street-name chains (raw-deflate, same format as the old `navdata.js` field `w`) and `{n: names, p: places by category h/a/b/p/t/m}`. `m` = military (new). Chains are cut at the piece edge at the same cut points as `map.bin`. |
| `extra.json` | For step B: `calming` [x, z, kind, road angle 0..179 or -1], `speed` (cut road lines with `v` km/h), `parking` (kind, capacity, rings), `air` (runways, aprons, helipads, hangars, aerodromes), `harbour` (marinas, piers, slipways, moorings). |
| `stats.json` | Feature counts of the piece. |

`base/terrain_bg.bin`: raw-deflate, version 1, x0, z0, cell 32, nx, nz, then bytes with the same prediction; the coarse terrain of the whole province.
`base/towns.json`: [name, x, z, city|town|village|hamlet]. `base/search.json`: [name, x, z, town] for all street and place names.
`base/index.json` also holds `bg` (the terrain_bg frame) and a thin `outline` of the province.

Known limits: the extract ends at the province border, so border pieces are partly empty (piece -6_-11 is empty). Forest height and water level of one big
forest or lake are computed per piece, so they can differ a little across a piece edge. BGT no longer has power pylons.

`base/roads.bin` (part 2): the big roads (classes 0-3) of every piece with exact vertices, for far routes; format in `tools/mkroads.py`.
`base/places.json`: every piece's places by category (h a b p t m), merged.
