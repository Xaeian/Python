# `xaeian.mf`

Media Files: Compress, convert, and strip metadata from PDFs and images.

**Dependencies:** `pypdf`, `PyMuPDF` _(fitz)_, `Pillow`. PDF compression requires [Ghostscript](https://www.ghostscript.com/).

## Quick start

```py
from xaeian.mf.min import compress
from xaeian.mf.meta import scrub_metadata

compress("report.pdf")              # → report-min.pdf (Ghostscript /ebook)
compress("photo.jpg", max_px=1280)  # → photo-min.jpg
compress("photos/", quality=70)     # → photos-min/ (recursive)

scrub_metadata("report.pdf")        # → report-nometa.pdf
scrub_metadata("photo.jpg")         # → photo-nometa.jpg
```

Both `compress()` and `scrub_metadata()` auto-detect PDF vs image by extension.

## Modules

### `mf.pdf` PDF operations

```py
from xaeian.mf.pdf import *

pdf_compress(src, dst=None, level="1.7", settings="/ebook", inplace=False)
pdf_scrub_metadata(src, dst=None, inplace=False)
pdf_merge(["a.pdf", "b.pdf"], "out.pdf")
pdf_split("doc.pdf", "pages/", prefix="page")  # → pages/page_001.pdf, ...
pdf_extract("doc.pdf", "out.pdf", "1,3,5-7")   # extract specific pages
pdf_add_text(src, dst=None, text="DRAFT", x=50, y=50, size=12, pages=None)
```

Page spec for `pdf_extract`: `"1,3,5-7"`, `[1, 3]`, or `"2-"` (to end).

### `mf.img` Image operations

```py
from xaeian.mf.img import *

img_compress(src, dst=None, max_px=1920, format="keep", quality=80,
  target_kB=None, recursive=True, inplace=False)
img_resize(src, dst=None, width=None, height=None, quality=90)
img_convert("photo.png", "photo.webp", quality=90)
img_scrub_metadata(src, dst=None, inplace=False)
```

`format` options: `"keep"` _(same as source)_, `"auto"` _(smallest)_, `"avif"`, `"webp"`, `"jpg"`, `"png"`.

### `mf.ico` Favicon generation

```py
from xaeian.mf.ico import img_to_ico

img_to_ico("logo.png", "favicon.ico", sizes=[16, 32, 48], fit="pad")
```

`fit`: `"pad"` _(transparent padding)_ or `"crop"` _(center crop)_.

## Output path convention

All functions follow the same `dst` / `inplace` pattern:

| `dst`   | `inplace` | Result                  |
| ------- | --------- | ----------------------- |
| `"out"` | -         | explicit path           |
| `None`  | `False`   | `<name>-<suffix>.<ext>` |
| `None`  | `True`    | overwrite source        |

Suffix depends on operation: `-min` for compression, `-nometa` for metadata removal.

## CLI

```sh
xn min report.pdf                     # compress PDF (ebook preset)
xn min report.pdf -s /screen          # aggressive compression for screen
xn min report.pdf -s /printer -i      # printer quality, in-place
xn min photo.jpg --max-px 1280 -q 70  # compress + resize
xn min photo.jpg -f avif              # convert to AVIF
xn min photo.jpg -f webp -i           # convert to WebP in-place
xn min photo.png --target-kb 200      # fit under 200 kB
xn min photos/                        # batch compress directory
xn min photos/ --max-px 800 -q 60     # batch resize + aggressive quality
xn min photos/ -f auto                # batch, pick smallest format per file
xn min photos/ -f webp -o web/        # batch convert to WebP → web/
xn min photos/ --no-recursive         # flat directory only

xn meta report.pdf                    # strip PDF metadata
xn meta report.pdf -i                 # strip in-place
xn meta photo.jpg -o clean.jpg        # strip EXIF, custom output
xn meta photo.jpg -i                  # strip EXIF in-place

xn ico logo.png                       # auto sizes → logo.ico
xn ico logo.png -o favicon.ico        # custom output
xn ico logo.svg --sizes 16,32,48      # specific sizes only
xn ico photo.jpg --fit crop           # center-crop to square
xn ico logo.png --upscale             # include sizes > source
```