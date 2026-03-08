# `xaeian.pdf`

PDF generation with fluent API. Built on reportlab.

## Install

```bash
pip install reportlab svglib pillow
```

## Quick Start

```py
from xaeian.pdf import PDF, Align

with PDF("output.pdf") as pdf:
  pdf.font("Helvetica", 16, "Bold")
  pdf.text("Hello World")
  pdf.enter()
  pdf.font(size=12, mode="Regular")
  pdf.text("Second line of text.")
```

## Modules

| Module      | Description                               |
| ----------- | ----------------------------------------- |
| `core`      | Main `PDF` class — fluent facade          |
| `text`      | Text measurement, word wrap, box fitting  |
| `tables`    | Table builder and rendering               |
| `fonts`     | Font registration, builtin detection      |
| `graphics`  | Shapes, images, SVG, gradients            |
| `layout`    | Cursor positioning, page geometry         |
| `styles`    | Style inheritance, table style presets    |
| `structure` | Bookmarks, TOC, metadata, hyperlinks      |
| `constants` | Units, page sizes, alignment, defaults    |
| `utils`     | Unit conversion, color parsing, margins   |

## Custom Fonts

```py
pdf = PDF("doc.pdf", font_dir="./font")
pdf.add_font("Barlow").add_font("Barlow", "Bold")
pdf.add_font("Barlow", "Italic")
pdf.font("Barlow", 14, "Bold")
pdf.text("Custom font text")
```

Font lookup: `font_dir/family/Family-Mode.ttf`

Built-in fonts _(no registration needed)_: Helvetica, Times, Courier with standard modes.

## Cursor & Positioning

Cursor origin is top-left, `y` grows downward. Alignment affects how `x` offset is interpreted relative to margins.

```py
pdf.cursor(0, 0, "L")  # top-left, left-aligned
pdf.cursor(0, 0, "R")  # top-right, right-aligned
pdf.cursor(0, 0, "C")  # top-center

pdf.text("Hello")      # advances x by text width
pdf.enter()            # newline: reset x, advance y
pdf.enter(10)          # newline with explicit height (mm)
pdf.move(5, 3)         # relative shift dx=5, dy=3
```

## Text

```py
# Auto-width (measured)
pdf.text("Simple text")
# Fixed width with word wrap
pdf.text("Long text that wraps", width=60)
# Fixed box with vertical centering
pdf.text("Centered", width=60, height=20, align="C")
# Right-aligned with padding
pdf.text("Price: 100 zł", width=40, align="R", padding=1)
```

When both `width` and `height` are specified, font auto-scales down by `0.1pt` steps to fit.

## Tables

```py
body = [
  ["1", "Widget", "10", "szt", "25,00 zł"],
  ["2", "Gadget", "5", "szt", "50,00 zł"],
]
header = ["Lp", "Name", "Qty", "Unit", "Price"]
pdf.font("Helvetica", 11)
pdf.table(
  body,
  header=header,
  sizes=[1, 5, 1, 1, 2],  # relative column widths
  aligns=["C", "L", "C", "L", "R"],
)
```

### TableBuilder

```py
from xaeian.pdf import TableBuilder, TableStyle

style = TableStyle(
  header_bg=(0.3, 0.3, 0.3, 0.8),
  row_bg_even=(0.95, 0.95, 0.95, 0.5),
  row_bg_odd=(0.9, 0.9, 0.9, 0.5),
  border_width=0.5,
  padding=1,
)
builder = TableBuilder(pdf._metrics, style)
builder.header(["Col A", "Col B"])
builder.rows([["a1", "b1"], ["a2", "b2"]])
builder.columns([3, 2], ["L", "R"])
data = builder.build(180, "Barlow", "Regular", 11)
```

## Shapes & Lines

```py
pdf.color(1, 0, 0)               # RGB fill
pdf.rect(40, 20)                 # rectangle at cursor
pdf.color_black()
pdf.line(100, 0, 0.5)            # horizontal line, 0.5pt thick
pdf.line(0, 50, 1)               # vertical line
pdf.line(80, 0, 1, dash=(3, 2))  # dashed line
pdf.circle(10, thickness=0.5)    # circle, r=10mm
pdf.color_hex("#2E75B6")
pdf.rect(60, 30, thickness=1)    # stroked rectangle
```

## Images & SVG

```py
pdf.image("photo.png", 60, 40)  # width=60mm, height=40mm
pdf.svg("icon.svg", 15, 15)
```

## Colors

```py
pdf.color(0.2, 0.4, 0.8)    # RGB (0–1)
pdf.color_hex("#FF6600")  # hex
pdf.color_grey(0.5, 0.8)    # grey with alpha
pdf.color_black()           # reset
pdf.stroke_color(0, 0, 0)   # stroke/line color
```

## Pages

```py
pdf = PDF("doc.pdf", width=210, height=297, margin=15)
pdf.margin(20, 25, 15)  # lr, top, bot
pdf.new_page()          # page break
# Header/footer callback
def header(pdf, page_num):
  pdf.cursor(0, -10, "R")
  pdf.font("Helvetica", 9)
  pdf.text(f"Page {page_num}", align="R")
pdf.on_page(header)
```

## Metadata & Bookmarks

```py
pdf.metadata(title="Report", author="Xaeian")
pdf.bookmark("Chapter 1", level=0)
pdf.bookmark("Section 1.1", level=1)
pdf.link("https://github.com/Xaeian", width=40, height=5)
```

## Units

Default unit is `mm`. Change with `unit` parameter:

```py
pdf = PDF("doc.pdf", unit="pt")  # points
pdf = PDF("doc.pdf", unit="cm")  # centimeters
```

Available: `mm`, `cm`, `in`, `pt`, `px`

## Page Sizes

```py
from xaeian.pdf import A4, A3, A5, LETTER, LEGAL

pdf = PDF("doc.pdf", width=LETTER.width, height=LETTER.height)
landscape = A4.landscape()
```

## Compression

```py
from xaeian.mf.pdf import pdf_compress

pdf.save()
pdf_compress("output.pdf")
```

## Style Presets

```py
from xaeian.pdf import Styles, TableStyle

# Text presets
Styles.BOLD       # font_mode="Bold"
Styles.ITALIC     # font_mode="Italic"
Styles.HEADING1   # size=24, Bold
Styles.HEADING2   # size=18, Bold
Styles.SMALL      # size=10
Styles.CAPTION    # size=9, Italic
```