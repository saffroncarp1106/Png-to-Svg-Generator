"""Build a PNG / alpha mask / saved SVG comparison for a tracing run.

Uses trace-report.json to match original filenames with their SVG outputs.
The SVG reader supports the closed M/L/Z polygon paths written by trace_pngs.py,
not arbitrary third-party SVGs. Requires the same dependencies as the tracer.
"""
from pathlib import Path
import argparse
import json
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
if (ROOT / '.trace-deps').exists():
    # Prefer packages installed for the running Python over bundled dependencies.
    sys.path.append(str(ROOT / '.trace-deps'))

from PIL import Image, ImageDraw, ImageOps
import numpy as np
import shapely
from shapely.geometry import Polygon

NS = '{http://www.w3.org/2000/svg}'


def svg_thumbnail(path, size, background='#444444'):
    """Rasterize the actual saved tracer paths, preserving their holes."""
    root = ET.parse(path).getroot()
    left, top, width, height = map(float, root.attrib['viewBox'].split())
    scale = min(size / width, size / height)
    w, h = max(1, round(width * scale)), max(1, round(height * scale))
    # Supersampling keeps thin outlines visible in the small comparison.
    factor = 3
    canvas = Image.new('RGB', (w * factor, h * factor), background)
    xx = left + (np.arange(canvas.width) + 0.5) * width / canvas.width
    yy = top + (np.arange(canvas.height) + 0.5) * height / canvas.height
    for group in root.findall(f'{NS}g'):
        parts = []
        for node in group.findall(f'{NS}path'):
            rings = []
            for subpath in node.attrib['d'].split('M')[1:]:
                rings.append([tuple(map(float, point.split(',')))
                              for point in subpath.replace('Z', '').strip().split(' L')])
            parts.append(Polygon(rings[0], rings[1:]))
        geometry = shapely.union_all(parts)
        shapely.prepare(geometry)
        mask = (shapely.contains_xy(geometry, xx[None, :], yy[:, None]) * 255).astype('uint8')
        canvas.paste(group.attrib['fill'], (0, 0, *canvas.size), Image.fromarray(mask))
    return canvas.resize((w, h), Image.Resampling.LANCZOS)


def create_inspection(input_dir, svg_dir, output, thumbnail_size=150, simplified=False):
    input_dir, svg_dir, output = map(Path, (input_dir, svg_dir, output))
    report = json.loads((svg_dir / 'trace-report.json').read_text(encoding='utf-8'))
    layers = report['layers']
    if not layers:
        raise ValueError('The tracing report contains no images.')
    if thumbnail_size < 32:
        raise ValueError('Thumbnail size must be at least 32 pixels.')
    background = '#444444'
    gap, header = 20, 40
    measure = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    label_width = max(150, max(int(measure.textlength(layer['source'])) + 20 for layer in layers))
    row_height = thumbnail_size + gap
    sheet = Image.new('RGB', (label_width + 3 * row_height, header + len(layers) * row_height), background)
    draw = ImageDraw.Draw(sheet)
    headings = ['Source PNG', 'Transparency mask', 'Simplified SVG' if simplified else 'Traced SVG']
    for column, heading in enumerate(headings):
        draw.text((label_width + column * row_height, 12), heading, fill='white')
    selected_dir = svg_dir / 'simplified' if simplified else svg_dir
    for row, layer in enumerate(layers):
        y = header + row * row_height
        draw.text((0, y + 22), layer['source'], fill='white')
        with Image.open(input_dir / layer['source']) as source:
            rgba = source.convert('RGBA')
        source_thumb = ImageOps.contain(rgba, (thumbnail_size, thumbnail_size), Image.Resampling.LANCZOS)
        color = Image.new('RGBA', source_thumb.size, background)
        color.alpha_composite(source_thumb)
        # Normalize each layer's alpha so faint layers remain easy to inspect.
        alpha = rgba.getchannel('A')
        maximum = alpha.getextrema()[1]
        if maximum:
            alpha = alpha.point([round(value * 255 / maximum) if value <= maximum else 255
                                 for value in range(256)])
        alpha = ImageOps.contain(alpha, (thumbnail_size, thumbnail_size), Image.Resampling.LANCZOS)
        svg = svg_thumbnail(selected_dir / layer['svg'], thumbnail_size, background)
        for column, thumb in enumerate((color.convert('RGB'), alpha.convert('RGB'), svg)):
            x = label_width + column * row_height
            sheet.paste(thumb, (x + (thumbnail_size - thumb.width) // 2,
                               y + (thumbnail_size - thumb.height) // 2))
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=ROOT / 'picture')
    parser.add_argument('--svg-dir', type=Path, default=ROOT / 'output')
    parser.add_argument('--output', type=Path, help='Defaults to SVG directory / inspection.png.')
    parser.add_argument('--thumbnail-size', type=int, default=150)
    parser.add_argument('--simplified', action='store_true', help='Show the simplified SVG outputs.')
    args = parser.parse_args()
    try:
        path = create_inspection(args.input, args.svg_dir, args.output or args.svg_dir / 'inspection.png',
                                 args.thumbnail_size, args.simplified)
    except (OSError, ValueError, KeyError, ET.ParseError) as error:
        parser.exit(1, f'Cannot create inspection image: {error}\n')
    print(f'Created: {path}')


if __name__ == '__main__':
    main()
