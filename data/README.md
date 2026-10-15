# Jewellery redesign dataset

Source: Instagram posts from @gewelsbymona (gm*) and @kivlojewels (kl*). Private style reference only — do not republish.

- `pairs/<id>/` — one transformation each: `before_*.jpg`, `after_*.jpg`, optional `combined_*`, `process_*`, `worn_*`, `inspiration_*`, plus `meta.json` (description, confidence, source file/frame).
- `dataset.json` — index of all pairs.
- `style_refs/` — finished pieces with no matching "before" (good for style only).
- `incomplete/` — before/process with no after.
- `src/` — renamed originals (A = first download batch, B = second); `manifest.csv` maps to Instagram filenames. `raw/` = untouched copies.
- `sheets/` — contact sheets used for review.

Rebuild: edit the spec in `tools/build.py`, then `python tools/build.py data` (needs pillow, ffmpeg).
