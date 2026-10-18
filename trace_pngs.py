"""Trace PNG pictures into closed SVG paths, one SVG per input picture.

Requires Pillow, numpy and shapely (see README).
Defaults: 1 source pixel = 1 mm; this is a reference scale, not a board size.
The source PNGs are never modified. Local .trace-deps is supported.
"""
from pathlib import Path
import argparse
import json
import math
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent

# EDIT THESE SETTINGS, then run this file again. Paths follow this script.
INPUT_FOLDER = ROOT / 'picture'
OUTPUT_FOLDER = ROOT / 'output'
COLOR_COUNT = 8           # Opaque pictures: fewer colors = simpler SVGs (2..256).
ALPHA_FRACTION = 0.5      # Transparent layers: fraction of maximum alpha (0..1].
MIN_AREA = 6              # Simplified SVGs: remove islands/holes below this area.
SIMPLIFY = 0.65           # Simplified SVGs: tolerance in source pixels.
TRACE_MODE = 'auto'       # auto: alpha for transparency, colors for opaque PNGs.
if (ROOT / '.trace-deps').exists():
    # Prefer packages installed for the running Python over bundled dependencies.
    sys.path.append(str(ROOT / '.trace-deps'))

import numpy as np
from PIL import Image, ImageDraw, ImageOps
import shapely
from shapely.geometry import Polygon
from shapely.geometry.polygon import orient

NAMES = {'Pruple': 'purple', 'light purpl': 'light-purple', 'lie': 'lime-green',
         'somegray': 'gray'}
NS = 'http://www.w3.org/2000/svg'
ET.register_namespace('', NS)


def polygons(geometry):
    if geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry]
    return [p for g in geometry.geoms for p in polygons(g)]


def trace_cells(mask):
    rows, starts = np.where(np.diff(np.pad(mask.astype(np.int8), ((0, 0), (1, 1))), axis=1) == 1)
    end_rows, ends = np.where(np.diff(np.pad(mask.astype(np.int8), ((0, 0), (1, 1))), axis=1) == -1)
    assert np.array_equal(rows, end_rows)
    if not len(rows):
        return Polygon()
    boxes = shapely.box(starts, rows, ends, rows + 1)
    result = shapely.union_all(boxes, grid_size=1)
    assert result.is_valid
    assert abs(result.area - int(mask.sum())) < 0.001
    return result


def cleaned_geometry(geometry, minimum_area, tolerance):
    kept = []
    for p in polygons(geometry):
        if p.area < minimum_area:
            continue
        holes = [r.coords for r in p.interiors if Polygon(r).area >= minimum_area]
        kept.append(Polygon(p.exterior.coords, holes))
    # Union after filling tiny holes to absorb any islands within filled holes.
    result = shapely.union_all(kept)
    result = result.simplify(tolerance, preserve_topology=True)
    assert result.is_valid
    return result


def number(v):
    return f'{v:.4f}'.rstrip('0').rstrip('.') if v != int(v) else str(int(v))


def ring_path(ring):
    points = list(ring.coords)[:-1]
    # Remove collinear intermediate pixel-edge vertices without changing shape.
    points = [p for i, p in enumerate(points)
              if (p[0]-points[i-1][0]) * (points[(i+1)%len(points)][1]-p[1]) !=
                 (p[1]-points[i-1][1]) * (points[(i+1)%len(points)][0]-p[0])]
    return 'M' + ' L'.join(f'{number(x)},{number(y)}' for x, y in points) + ' Z'


def add_layer(parent, name, geometry, color):
    group = ET.SubElement(parent, f'{{{NS}}}g', {'id': name, 'fill': color,
                          'fill-rule': 'evenodd', 'stroke': 'none'})
    for i, p in enumerate(polygons(geometry)):
        p = orient(p, sign=1.0)
        data = ' '.join(ring_path(r) for r in [p.exterior, *p.interiors])
        ET.SubElement(group, f'{{{NS}}}path', {'id': f'{name}-{i+1}', 'd': data})


def write_svg(path, width, height, width_mm, layers):
    svg = ET.Element(f'{{{NS}}}svg', {'version': '1.1', 'width': f'{width_mm:g}mm',
                     'height': f'{width_mm*height/width:g}mm', 'viewBox': f'0 0 {width} {height}'})
    ET.SubElement(svg, f'{{{NS}}}title').text = path.stem
    ET.SubElement(svg, f'{{{NS}}}desc').text = 'Closed vector outlines traced from PNG pixel regions.'
    for layer in layers:
        add_layer(svg, *layer)
    ET.indent(svg)
    ET.ElementTree(svg).write(path, encoding='utf-8', xml_declaration=True)
    # Verify actual saved artifact: no embedded images and every subpath closed.
    parsed = ET.parse(path)
    assert not parsed.findall(f'.//{{{NS}}}image')
    saved_polygons = []
    for node in parsed.findall(f'.//{{{NS}}}path'):
        assert node.attrib['d'].count('M') == node.attrib['d'].count('Z')
        rings = []
        for subpath in node.attrib['d'].split('M')[1:]:
            rings.append([tuple(map(float, point.split(',')))
                          for point in subpath.replace('Z', '').strip().split(' L')])
        polygon = Polygon(rings[0], rings[1:])
        assert polygon.is_valid and polygon.area > 0, path
        saved_polygons.append(polygon)
    expected_area = sum(g.area for _, g, _ in layers)
    assert abs(sum(p.area for p in saved_polygons) - expected_area) < 0.01, path


def stats(geometry):
    ps = polygons(geometry)
    return {'regions': len(ps), 'holes': sum(len(p.interiors) for p in ps),
            'area_px2': round(geometry.area, 3), 'valid_geometry': bool(geometry.is_valid)}


def preview(path, layers, width, height):
    canvas = Image.new('RGB', (width, height), '#555555')
    for _, geometry, color in layers:
        mask = Image.new('1', (width, height))
        # Pixel-center membership gives a faithful raster of the traced geometry.
        shapely.prepare(geometry)
        xx = np.arange(width) + 0.5
        bitmap = np.zeros((height, width), dtype=np.uint8)
        for y in range(height):
            bitmap[y] = shapely.contains_xy(geometry, xx, y + 0.5) * 255
        mask = Image.fromarray(bitmap)
        canvas.paste(color, (0, 0, width, height), mask)
    canvas.save(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=INPUT_FOLDER)
    parser.add_argument('--output', type=Path, default=OUTPUT_FOLDER)
    parser.add_argument('--colors', type=int, default=COLOR_COUNT)
    parser.add_argument('--mode', choices=['auto', 'alpha', 'colors'], default=TRACE_MODE)
    parser.add_argument('--width-mm', type=float, default=None,
                        help='Common SVG width in mm (default: source width, 1 px = 1 mm).')
    parser.add_argument('--alpha-fraction', type=float, default=ALPHA_FRACTION,
                        help='Threshold as a fraction of each layer maximum alpha.')
    parser.add_argument('--min-area', type=float, default=MIN_AREA,
                        help='Simplified set only: discard islands/fill holes below this pixel area.')
    parser.add_argument('--simplify', type=float, default=SIMPLIFY,
                        help='Simplified set only: maximum simplification tolerance in source pixels.')
    args = parser.parse_args()
    if (not 0 < args.alpha_fraction <= 1 or not math.isfinite(args.min_area)
            or not math.isfinite(args.simplify) or args.min_area < 0 or args.simplify < 0):
        parser.error('Invalid threshold, minimum area or simplification tolerance.')
    if args.width_mm is not None and (not math.isfinite(args.width_mm) or args.width_mm <= 0):
        parser.error('--width-mm must be positive and finite.')
    if not 2 <= args.colors <= 256:
        parser.error('--colors must be between 2 and 256.')
    args.input.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in args.input.iterdir() if p.is_file() and p.suffix.lower() == '.png')
    if not files:
        parser.error(f'Put one or more PNG files in {args.input}, then run again.')
    args.output.mkdir(parents=True, exist_ok=True)
    simple_dir = args.output / 'simplified'
    simple_dir.mkdir(exist_ok=True)
    report_path = args.output / 'trace-report.json'
    previous_layers = []
    if report_path.exists():
        try:
            previous_layers = json.loads(report_path.read_text(encoding='utf-8')).get('layers', [])
        except (ValueError, OSError):
            pass
    report = {'alpha_fraction': args.alpha_fraction, 'colors': args.colors,
              'simplified_min_area_px2': args.min_area,
              'simplified_tolerance_px': args.simplify, 'layers': []}
    used_names = set()
    for source in files:
        name = NAMES.get(source.stem, source.stem.lower())
        base, suffix = name, 2
        while name.casefold() in used_names:
            name = f'{base}-{suffix}'
            suffix += 1
        used_names.add(name.casefold())
        with Image.open(source) as im:
            image = im.convert('RGBA')
        width, height = image.size
        width_mm = args.width_mm or width
        rgba = np.array(image)
        alpha = rgba[:, :, 3]
        threshold = max(1, math.ceil(int(alpha.max()) * args.alpha_fraction))
        visible = alpha >= threshold
        mode = args.mode
        if mode == 'auto':
            mode = 'alpha' if np.any(alpha < 255) else 'colors'
        regions = []
        if mode == 'alpha':
            if visible.any():
                rgb = np.median(rgba[:, :, :3][visible], axis=0).astype(int)
                regions.append((name, visible, '#' + ''.join(f'{c:02x}' for c in rgb)))
        else:
            # Quantize visible pixels only, so hidden RGB does not consume colors.
            pixels = rgba[:, :, :3][visible]
            if len(pixels):
                palette_image = Image.fromarray(pixels.reshape(1, -1, 3)).quantize(
                    colors=args.colors, method=Image.Quantize.MEDIANCUT,
                    dither=Image.Dither.NONE)
                indices = np.full((height, width), -1, dtype=np.int16)
                indices[visible] = np.asarray(palette_image).reshape(-1)
                palette = palette_image.getpalette()
                for index in sorted(np.unique(indices[visible])):
                    color = '#' + ''.join(f'{c:02x}' for c in palette[index*3:index*3+3])
                    regions.append((f'{name}-color-{index}', indices == index, color))
        print(f'Tracing {source.name}: {mode}, {len(regions)} color region(s)...', flush=True)
        detailed, simplified = [], []
        for region_name, mask, color in regions:
            print(f'  Tracing {region_name}...', flush=True)
            geometry = trace_cells(mask)
            simple = cleaned_geometry(geometry, args.min_area, args.simplify)
            detailed.append((region_name, geometry, color))
            simplified.append((region_name, simple, color))
        write_svg(args.output / f'{name}.svg', width, height, width_mm, detailed)
        write_svg(simple_dir / f'{name}.svg', width, height, width_mm, simplified)
        preview(args.output / f'{name}-preview.png', detailed, width, height)
        preview(simple_dir / f'{name}-preview.png', simplified, width, height)
        report['layers'].append({
            'source': source.name, 'svg': f'{name}.svg', 'preview': f'{name}-preview.png',
            'mode': mode, 'canvas_px': [width, height], 'alpha_threshold': threshold,
            'colors': len(regions),
            'detailed': [stats(g) for _, g, _ in detailed],
            'simplified': [stats(g) for _, g, _ in simplified]})
    # Exactly one SVG per input in each set; a preview grid supports mixed sizes.
    columns = min(3, len(files))
    rows = math.ceil(len(files) / columns)
    for directory in (args.output, simple_dir):
        sheet = Image.new('RGB', (columns * 300, rows * 330), '#555555')
        draw = ImageDraw.Draw(sheet)
        for i, entry in enumerate(report['layers']):
            with Image.open(directory / entry['preview']) as im:
                thumb = ImageOps.contain(im, (290, 290), Image.Resampling.LANCZOS)
            x, y = (i % columns)*300, (i // columns)*330
            sheet.paste(thumb, (x + (300-thumb.width)//2, y+30+(290-thumb.height)//2))
            draw.text((x+8, y+8), entry['source'], fill='white')
        sheet.save(directory / 'preview.png')
    (args.output / 'trace-report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    from create_inspection import create_inspection
    create_inspection(args.input, args.output, args.output / 'inspection.png')
    create_inspection(args.input, args.output, simple_dir / 'inspection.png', simplified=True)
    # Remove only obsolete files explicitly recorded by our previous run.
    current = {entry[key] for entry in report['layers'] for key in ('svg', 'preview')}
    for entry in previous_layers:
        for key in ('svg', 'preview'):
            filename = entry.get(key)
            if not filename or filename in current or Path(filename).name != filename:
                continue
            if Path(filename).suffix.lower() != ('.svg' if key == 'svg' else '.png'):
                continue
            for directory in (args.output, simple_dir):
                target = directory / filename
                if target.resolve().parent == directory.resolve():
                    target.unlink(missing_ok=True)
    print(f'Done: {args.output}', flush=True)


if __name__ == '__main__':
    main()
