# PNG to SVG

Keep these files together. The root is the folder containing `trace_pngs.py`;
currently that folder is `Code`. You can move the whole folder anywhere.

```text
Code/
  trace_pngs.py
  create_inspection.py
  requirements-tracing.txt
  picture/                 <-- put your PNG pictures here
  output/                  <-- created automatically
    preview.png            <-- grid of every traced picture
    inspection.png         <-- source, alpha mask, saved SVG comparison
    picture-name.svg       <-- one detailed SVG per input PNG
    picture-name-preview.png
    trace-report.json
    simplified/
      picture-name.svg     <-- SVGs affected by MIN_AREA and SIMPLIFY
      picture-name-preview.png
      preview.png
      inspection.png
```

## Run

From the Code folder:

```powershell
py -m pip install -r requirements-tracing.txt
py trace_pngs.py
```

The first command installs dependencies if needed. Existing `.trace-deps`
is supported. The script resolves its default folders relative to itself,
so it also works when launched from another working folder. Uppercase `.PNG`
extensions and different image dimensions are supported. Subfolders are not scanned.

## Settings to experiment with

Edit the settings near the top of `trace_pngs.py`:

- `COLOR_COUNT = 8`: number of colors for opaque pictures (2 through 256).
  Fewer colors give a simpler, more posterized result.
- `MIN_AREA = 6`: removes small islands and fills small holes in simplified
  SVGs, measured in square source pixels.
- `SIMPLIFY = 0.65`: outline simplification tolerance in source pixels.
  Larger values give fewer points and less detail in simplified SVGs.
- `ALPHA_FRACTION = 0.5`: transparency cutoff relative to the image's maximum
  alpha. Applies to transparent input pixels before tracing.
- `TRACE_MODE = 'auto'`: opaque pictures use color quantization; pictures with
  transparency use a single alpha silhouette with a representative color.
  Set to `'colors'` for multicolor transparent pictures, or `'alpha'` to force
  silhouette tracing. A fully transparent PNG produces an empty SVG.

Detailed SVGs retain the pixel boundaries after color quantization or alpha
thresholding. `MIN_AREA` and `SIMPLIFY` affect only `output/simplified` and its
previews. Photographs will look posterized; this is a polygon tracer, not a
photorealistic vectorizer. Independently simplified color boundaries can leave
small gaps or overlaps. The detailed set preserves the quantized color regions.

Each image keeps its dimensions and aspect ratio. SVG scale defaults to 1 source
pixel = 1 mm; this is a reference scale, not a recommended physical print size.
Use `--width-mm 600` to choose a different width.

Optional overrides:

```powershell
py trace_pngs.py --colors 12 --min-area 10 --simplify 1.2
py trace_pngs.py --input picture --output output
```

Rebuild only the inspection image from the existing SVGs:

```powershell
py create_inspection.py
py create_inspection.py --simplified --output output/simplified/inspection.png
```

Inspection rows follow `trace-report.json`. The transparency mask is normalized
per image; opaque pictures show a white mask. The SVG column renders saved vector
paths. The inspection reader supports this tracer's polygon SVG format only.
Sources are never edited. Reruns replace generated outputs with the same names.
When you remove an input PNG, its old SVGs and individual previews are removed
if they were recorded by the previous run. Unrelated files are kept.
