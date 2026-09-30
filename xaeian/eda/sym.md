# KiCad Symbol Library Style

## Units

Standard uses **mil** (1mil = 0.0254mm).
KiCad serializes mm. Code converts: `val_mm = val_mil * 0.0254`.

## Grid

- Pin endpoints: **50mil**
- Pin pitch: **100mil** standard, **50mil** dense (large ICs)

## Size tiers

Tier is a design decision per component series, not per individual symbol.
All symbols in a series share the same tier for visual consistency.

| Tier | Usage                     | font |
| ---- | ------------------------- | ---- |
| S    | Passive (R, C, L, D)      | 30   |
| M    | Connectors, small IC      | 40   |
| L    | IC, complex components    | 50   |

Font thickness: **6mil**.
Details and decorations may use smaller font with recommended thickness of **4mil**.

## Pin length

| pin_len | Usage                                        |
| ------- | -------------------------------------------- |
| 100     | Standard, used everywhere by default         |
| 50      | Allowed for small symbols (R, C), dense ICs  |

## Pin display

Pin names inside body with offset 10mil when space allows.
Pin numbers outside (KiCad default).

| Type      | pin_offset | names | numbers |
| --------- | ---------- | ----- | ------- |
| passive   | 0          | hide  | hide    |
| connector | 0          | hide  | show    |
| ic        | 10         | show  | show    |

## Stroke

| Element      | Width |
| ------------ | ----- |
| Body outline | 0     |
| Body poly    | 5     |
| Detail/decor | 3     |

`width 0` means KiCad default rendering width.

## Fill types

- `background`: body shapes (theme-aware fill)
- `outline`: solid detail shapes (dots, arrows)
- `none`: open shapes, internal wiring

## Properties

Fixed order. Hidden props always use font 30mil with thickness 6mil.

1. **Reference**: visible, font per tier
2. **Value**: visible or hidden, font per tier (IC: bold)
3. **Footprint**: hidden
4. **Datasheet**: hidden
5. **Description**: hidden
6. **Manufacturer**: hidden, custom
7. **Code**: hidden, custom
8. **LCSC**: hidden, custom (optional)

## Reference designators

KiCad standard (IEEE 315):

| Ref  | Component                          |
| ---- | ---------------------------------- |
| `R`  | Resistor                           |
| `RN` | Resistor network/array             |
| `C`  | Capacitor                          |
| `L`  | Inductor                           |
| `FB` | Ferrite bead                       |
| `D`  | Diode, LED                         |
| `Q`  | Transistor, MOSFET                 |
| `U`  | IC, module                         |
| `J`  | Connector                          |
| `SW` | Switch                             |
| `F`  | Fuse                               |
| `K`  | Relay                              |
| `T`  | Transformer                        |
| `Y`  | Crystal, oscillator                |
| `M`  | Motor                              |
| `W`  | Wire, cable                        |
| `JP` | Jumper                             |
| `TP` | Test point                         |
| `H`  | Mounting hole, hardware            |
| `FID`| Fiducial                           |
| `MP` | Mechanical part                    |
| `BT` | Battery                            |
| `SP` | Speaker, buzzer                    |
| `MK` | Microphone                         |
| `FL` | Filter                             |
| `ANT`| Antenna                            |
| `PS` | Power supply                       |