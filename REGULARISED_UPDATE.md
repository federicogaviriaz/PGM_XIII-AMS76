# Regularised Tag and TextStyle Updates

## Summary

The `page2tei.py` converter and TEI viewer have been updated to support additional PAGE XML custom annotations found in the test.xml file, specifically:

1. **`regularised` tag** - for original/regularized spelling variations
2. **`superscript` and `subscript`** in `textStyle` - for typographical variations

## Changes Made

### 1. PAGE to TEI Converter (`page2tei.py`)

#### New Tag Support: `regularised`

**PAGE XML Format:**
```xml
<TextLine custom="regularised {offset:0;length:1;original:i;}">
    <Unicode>jnueni...</Unicode>
</TextLine>
```

**TEI Output:**
```xml
<choice>
    <orig>i</orig>
    <reg>j</reg>
</choice>
```

**Key Implementation Details:**
- The text in the PAGE file contains the **regularised** form
- The `original` attribute contains the **original** manuscript form
- In TEI output:
  - `<orig>` receives the value from the `original` attribute
  - `<reg>` receives the actual text from the witness (regularised form)
- This is the opposite order from `abbrev` and `sic` tags

#### Extended TextStyle Support

**Previous Support:**
- `bold`
- `italic`
- `underline`

**New Support:**
- `superscript`
- `subscript`

**PAGE XML Example:**
```xml
<TextLine custom="textStyle {offset:27;length:1;superscript:true;}">
    <Unicode>...huma^n^o...</Unicode>
</TextLine>
```

**TEI Output:**
```xml
<hi rend="superscript">n</hi>
```

### 2. TEI Viewer Updates

#### Data Model (`src/tei_data.rs`)

Added new `TextNode` variant:
```rust
Regularised {
    orig: String,
    reg: String,
}
```

#### Parser (`src/tei_parser.rs`)

- Extended choice element parsing to handle `<orig>` and `<reg>` tags
- Added state tracking for `in_orig` and `in_reg` flags
- Properly extracts text content from both elements

#### Rendering (`src/components/tei_viewer.rs`)

Added rendering for regularised text:
```rust
TextNode::Regularised { orig, reg } => html! {
    <span class="regularised" title={format!("[Regularización] Original: {}", orig)}>
        { reg }
    </span>
}
```

Features:
- Displays the regularised form in the text
- Shows original form in tooltip on hover
- Green underline styling to distinguish from corrections (red) and abbreviations (blue)

#### Styling (`static/styles.css`)

**New Classes:**

1. `.regularised` - Green dotted underline for regularised text
2. `.hi-superscript` - Vertical alignment and sizing for superscript
3. `.hi-subscript` - Vertical alignment and sizing for subscript

**Legend Update:**
- Added "Regularización" entry to the color legend panel

## Testing

### Test Files

1. **`test.xml`** - Original PAGE XML with all tag types
2. **`test_output.xml`** - Converted TEI output demonstrating proper handling

### Verified Features

✅ **Regularised tag conversion:**
- `regularised {offset:0;length:1;original:i;}` → `<choice><orig>i</orig><reg>j</reg></choice>`
- Proper text ordering (original in `<orig>`, regularised in `<reg>`)

✅ **Superscript rendering:**
- `textStyle {offset:27;length:1;superscript:true;}` → `<hi rend="superscript">n</hi>`

✅ **Person names with WikiData:**
- `person {offset:13;length:7;firstname:Sócrates;wikiData:Q913;}` → `<persName ref="https://www.wikidata.org/wiki/Q913">socrate</persName>`

✅ **Complex multi-annotation lines:**
- Lines with multiple `abbrev`, `sic`, `regularised`, and `person` tags parse correctly
- Proper nesting and non-overlapping annotation handling

## Tag Summary

The converter now supports the following PAGE XML custom annotations:

| PAGE Attribute | TEI Output | Viewer Class |
|---------------|------------|--------------|
| `abbrev` | `<choice><abbr>...</abbr><expan>...</expan></choice>` | `.abbreviation` |
| `sic` | `<choice><sic>...</sic><corr>...</corr></choice>` | `.correction` |
| **`regularised`** | **`<choice><orig>...</orig><reg>...</reg></choice>`** | **`.regularised`** |
| `num` | `<num type="..." value="...">...</num>` | `.number` |
| `person` | `<persName type="..." ref="...">...</persName>` | `.person-name` |
| `place` | `<placeName><country>...</country></placeName>` | `.place-name` |
| `ref` | `<ref type="..." target="...">...</ref>` | `.ref` |
| `unclear` | `<unclear reason="...">...</unclear>` | `.unclear` |
| `textStyle` (bold) | `<hi rend="bold">...</hi>` | `.hi-bold` |
| `textStyle` (italic) | `<hi rend="italic">...</hi>` | `.hi-italic` |
| `textStyle` (underline) | `<hi rend="underline">...</hi>` | `.hi-underline` |
| **`textStyle` (superscript)** | **`<hi rend="superscript">...</hi>`** | **`.hi-superscript`** |
| **`textStyle` (subscript)** | **`<hi rend="subscript">...</hi>`** | **`.hi-subscript`** |

## Usage

### Converting PAGE XML to TEI

```bash
python3 page2tei.py --input test.xml --output output.xml \
    --title "Document Title" \
    --author "Author Name" \
    --edition-editor "Editor Name"
```

The script will:
1. Auto-detect edition type from filename
2. Parse all custom annotations including `regularised` and extended `textStyle`
3. Generate valid TEI P5 XML with proper encoding

### Viewing in TEI Viewer

1. Place TEI file in `tei-viewer/public/projects/PGM-XIII/`
2. Build viewer: `cd tei-viewer && trunk build`
3. Open in browser and select the document
4. Hover over regularised text to see original form in tooltip
5. Check legend for color coding guide

## Commits

**PGM_XIII-AMS76 repository:**
- Commit: `ebbdf89` - "Add support for regularised tag and superscript/subscript in textStyle"

**tei-viewer repository:**
- Commit: `5c66aec` - "Add support for regularised (orig/reg) tags and superscript/subscript"

## Notes

- **Text Ordering:** The `regularised` tag requires special handling because the PAGE text contains the regularised form while the attribute contains the original - this is the reverse of `abbrev` and `sic`.
- **Styling Consistency:** Each semantic tag type has a distinct color and underline style for easy visual identification.
- **Tooltip Information:** All annotations display their semantic type and relevant metadata on hover in Spanish.