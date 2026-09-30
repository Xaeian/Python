# KiCad Library Style

## Size tiers

Tier zależy od rozmiaru fizycznego elementu, nie od typu.

| Tier | Rozmiar | Przykłady                             | Silk | Detail | CrtYd | Fab  | Font     |
| ---- | ------- | ------------------------------------- | ---- | ------ | ----- | ---- | -------- |
| XXS  | <2mm    | 0201, 01005                           | 0.08 | 0.05   | 0.05  | 0.06 | 0.4/0.06 |
| XS   | 2–3mm   | 0402, 0603, SC-70                     | 0.1  | 0.06   | 0.05  | 0.08 | 0.6/0.08 |
| S    | 3–6mm   | 0805, 1206, SOT-23, SOD-123           | 0.12 | 0.08   | 0.05  | 0.1  | 0.8/0.1  |
| M    | 6–15mm  | SOIC, QFN, JST-PH, SOT-89             | 0.15 | 0.1    | 0.05  | 0.12 | 1.0/0.12 |
| L    | 15–30mm | DIP, QFP, terminal blocks, THT 2.54mm | 0.2  | 0.12   | 0.05  | 0.15 | 1.2/0.14 |
| XL   | >30mm   | transformatory, heatsinks, duże relay | 0.25 | 0.15   | 0.05  | 0.2  | 1.5/0.16 |

Courtyard zawsze 0.05: nie rośnie z tierem. To clearance check, nie wizualna warstwa.

## Reference designators

`J**` connector, `R**` resistor, `C**` capacitor, `U**` IC, `Q**` transistor,
`D**` diode/LED, `L**` inductor, `Y**` crystal, `SW**` switch, `F**` fuse,
`K**` relay, `T**` transformer, `M**` motor.

## Properties

Oba na `F.Fab`: celowo nie na SilkS, bo Fab to warstwa montażowa.

```
Reference: (at 0 0 0)     layer F.Fab  font: tier default
Value:     (at 0 1.6 180)  layer F.Fab  font: tier default
```

Datasheet i Description ukryte, font 1.27/0.15 (KiCad default).

## Pads: THT

- Pin 1: `roundrect`, `rratio 0.1666666667`: subtelny marker
- Reszta: `oval`
- Wymiary dobierane per seria (np. JST-PH: 1.5×2.5, drill 1.1)
- `drill_offset` tylko gdy pin zagięty (horizontal connectors)
- `remove_unused_layers no` zawsze

## Naming

Footprinty: `V-02.kicad_mod`, `H-02.kicad_mod`: orientacja + pin count, zero-padded.
Foldery `.pretty`: per seria: `JST-PH.pretty`, `JST-XH.pretty`, `Socket.pretty`.

## 3D model path

```
${L3D}/Connectors/JST-PH/V-02.step
```

`L3D`: zmienna KiCad wskazująca na root biblioteki 3D.
Struktura: `L3D / Kategoria / Seria / Footprint.step`.

## STEP cleaning (`clean_step`)

Zostaje: autor, data.
Leci: komentarze `/* */`, FILE_DESCRIPTION (zastąpione stem), puste pola,
schema version cruft, stare PRODUCT names.

`FILE_NAME` ustawiane na `folder/plik.step` (np. `JST-PH/V-02.step`).

## Silkscreen detail

- Outer box: `s.silk` (gruba)
- Inner features (latche, shelf, pockety, dividers): `s.silk_detail` (cienka)
- Pin dividers (horizontal): `filled_rect` 0.4mm szeroki, od 3+ pinów
- Pin dividers (vertical): `line`: tylko 2 skrajne
- Latch marks: krótkie linie między inner a outer wall

## Biblioteki

```
JST-PH.pretty/   V-02..V-15, H-02..H-16
JST-XH.pretty/   analogicznie
Socket.pretty/   MicroSD-Hinge, SIM-Push, NanoSIM-Hinge
```

Nazwa `.pretty` = seria lub kategoria. Nazwa footprintu = orientacja-piny lub typ-mechanizm.