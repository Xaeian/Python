# xaeian/pdf/basic.py

"""Basic pdflib usage examples."""
from pdflib import PDF, Align, TableStyle, Style, A4, LETTER

#-------------------------------------------------------------------------------------- Example 1: Simple document

def example_simple():
  """Basic text and formatting."""
  with PDF("simple.pdf") as pdf:
    pdf.font("Helvetica", 24, "Bold")
    pdf.text("Hello World!", align=Align.CENTER)
    pdf.enter(10)

    pdf.font(size=12, mode="Regular")
    pdf.text("This is a simple PDF document.")
    pdf.enter()
    pdf.text("Second line of text.")

#-------------------------------------------------------------------------------------- Example 2: Custom fonts

def example_fonts():
  """Using custom TTF fonts."""
  with PDF("fonts.pdf", font_dir="./font") as pdf:
    # Register fonts (auto-registers on first use too)
    pdf.add_font("Barlow")
    pdf.add_font("Barlow", "Bold")
    pdf.add_font("Barlow", "Italic")

    pdf.font("Barlow", 16, "Bold")
    pdf.text("Custom Font: Barlow Bold")
    pdf.enter()

    pdf.font(mode="Regular")
    pdf.text("Regular weight text")
    pdf.enter()

    pdf.font(mode="Italic")
    pdf.text("Italic style text")

#-------------------------------------------------------------------------------------- Example 3: Tables

def example_tables():
  """Table generation."""
  with PDF("tables.pdf") as pdf:
    pdf.font("Helvetica", 12)

    # Simple table
    data = [
      ["Apple", "Red", "1.20"],
      ["Banana", "Yellow", "0.50"],
      ["Orange", "Orange", "0.80"],
    ]
    header = ["Fruit", "Color", "Price"]

    pdf.text("Simple Table:", height=8)
    pdf.enter(2)
    pdf.table(data, header=header, sizes=[2, 2, 1],
              aligns=[Align.LEFT, Align.CENTER, Align.RIGHT])

    pdf.enter(10)

    # Custom styled table
    style = TableStyle(
      header_bg=(0.2, 0.4, 0.8, 1),
      row_bg_even=(0.95, 0.95, 1, 1),
      row_bg_odd=(0.9, 0.9, 0.95, 1),
      border_width=0.5,
    )
    pdf.text("Styled Table:", height=8)
    pdf.enter(2)
    pdf.table(data, header=header, sizes=[2, 2, 1],
              aligns=[Align.LEFT, Align.CENTER, Align.RIGHT], style=style)

#-------------------------------------------------------------------------------------- Example 4: Graphics

def example_graphics():
  """Shapes and colors."""
  with PDF("graphics.pdf") as pdf:
    pdf.font("Helvetica", 14)
    pdf.text("Shapes and Colors")
    pdf.enter(10)

    # Colored rectangles
    pdf.color(1, 0, 0)  # Red
    pdf.rect(30, 20)
    pdf.move(35, 0)

    pdf.color(0, 1, 0)  # Green
    pdf.rect(30, 20)
    pdf.move(35, 0)

    pdf.color(0, 0, 1)  # Blue
    pdf.rect(30, 20)

    pdf.color_black()
    pdf.enter(25)

    # Lines
    pdf.text("Lines:")
    pdf.enter(5)
    pdf.line(100, 0, 1)
    pdf.enter(3)
    pdf.line(100, 0, 2, dash=(5, 3))
    pdf.enter(3)
    pdf.line(100, 0, 0.5)

#-------------------------------------------------------------------------------------- Example 5: Multi-page

def example_multipage():
  """Multi-page document with headers."""
  def header(pdf, page_num):
    """Header callback."""
    pdf.cursor(0, -10, Align.RIGHT)
    pdf.font("Helvetica", 9)
    pdf.text(f"Page {page_num}", align=Align.RIGHT)

  with PDF("multipage.pdf") as pdf:
    pdf.on_page(header)

    for i in range(3):
      pdf.font("Helvetica", 18, "Bold")
      pdf.text(f"Page {i + 1}")
      pdf.enter(10)

      pdf.font(size=12, mode="Regular")
      for j in range(10):
        pdf.text(f"Line {j + 1} on page {i + 1}")
        pdf.enter()

      if i < 2:
        pdf.new_page()

#-------------------------------------------------------------------------------------- Example 6: Positioning

def example_positioning():
  """Cursor positioning and alignment."""
  with PDF("positioning.pdf") as pdf:
    pdf.font("Helvetica", 12)

    # Left aligned (default)
    pdf.cursor(0, 0, Align.LEFT)
    pdf.text("Left aligned text")

    # Center aligned
    pdf.cursor(0, 10, Align.CENTER)
    pdf.text("Center aligned text")

    # Right aligned
    pdf.cursor(0, 20, Align.RIGHT)
    pdf.text("Right aligned text")

    # Absolute positioning
    pdf.cursor(50, 50)
    pdf.color(0.9, 0.9, 0.9)
    pdf.rect(60, 30)
    pdf.color_black()
    pdf.text("Box at (50, 50)", 60, 30, Align.CENTER)

    # Relative movement
    pdf.cursor(0, 100)
    pdf.text("Start")
    pdf.move(20, 5)
    pdf.text("Moved +20, +5")
    pdf.move(20, 5)
    pdf.text("Moved again")

#-------------------------------------------------------------------------------------- Example 7: Images

def example_images():
  """Images and SVG."""
  with PDF("images.pdf") as pdf:
    pdf.font("Helvetica", 14)
    pdf.text("Images and SVG")
    pdf.enter(10)

    # PNG image (if exists)
    try:
      pdf.image("img/logo.png", 50, 30)
      pdf.enter(35)
    except:
      pdf.text("[logo.png not found]")
      pdf.enter()

    # SVG (if exists)
    try:
      pdf.svg("img/icon.svg", 30, 30)
    except:
      pdf.text("[icon.svg not found]")

#-------------------------------------------------------------------------------------- Main

if __name__ == "__main__":
  print("Running examples...")
  example_simple()
  print("  simple.pdf - done")
  # example_fonts()  # needs font dir
  example_tables()
  print("  tables.pdf - done")
  example_graphics()
  print("  graphics.pdf - done")
  example_multipage()
  print("  multipage.pdf - done")
  example_positioning()
  print("  positioning.pdf - done")
  # example_images()  # needs images
  print("All examples complete!")
