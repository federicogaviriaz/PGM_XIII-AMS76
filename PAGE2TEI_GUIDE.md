# PAGE2TEI Conversion Guide

Complete guide for converting Transkribus PAGE-XML to TEI P5 format with full semantic markup.

## Overview

The `page2tei.py` script converts PAGE-XML files (exported from Transkribus) into TEI P5 XML format with comprehensive support for:

- ✅ **Auto-detection** of edition type (diplomatic vs translation)
- ✅ **Preset metadata** for both edition types
- ✅ **Full semantic markup** for all annotation types
- ✅ **Interactive prompts** with sensible defaults
- ✅ **Image path correction** (adds `images/` prefix)
- ✅ **Language-aware** output (Ancient Greek for diplomatic, Spanish for translation)

## Supported Annotations

The script converts these PAGE custom annotations to TEI:

| PAGE Annotation | TEI Output | Example |
|----------------|------------|---------|
| `abbrev` | `<choice><abbr>...</abbr><expan>...</expan></choice>` | Abbreviations |
| `sic` | `<choice><sic>...</sic><corr>...</corr></choice>` | Corrections |
| `num` | `<num type="..." value="...">...</num>` | Numbers |
| `person` | `<persName type="..." ref="...">...</persName>` | Person names |
| `place` | `<placeName><country>...</country></placeName>` | Place names |
| `ref` | `<ref type="..." target="...">...</ref>` | References |
| `unclear` | `<unclear reason="...">...</unclear>` | Unclear text |
| `textStyle` | `<hi rend="bold italic underline">...</hi>` | Text styling |

### Detailed Tag Behavior

#### `person` → `<persName>`
```xml
<!-- PAGE: person {offset:39;length:7;firstname:Moisés;type:humano;wikiData:Q19968214;} -->
<!-- TEI output: -->
<persName type="humano" ref="https://www.wikidata.org/wiki/Q19968214">Moisés</persName>
```
- **`type` attribute**: Always set if present in PAGE
- **`ref` attribute**: Optional, only if `wikiData` is provided

#### `place` → `<placeName>`
```xml
<!-- PAGE: place {offset:41;length:6;country:Egipto;} -->
<!-- TEI output: -->
<placeName>
  <country>Egipto</country>
</placeName>
```
- Nested elements for: `country`, `region`, `settlement`, `district`

#### `ref` → `<ref>`
```xml
<!-- PAGE: ref {offset:30;length:6;type:libro;target:#desconocido;} -->
<!-- TEI output: -->
<ref type="libro" target="#desconocido">Hermes</ref>
```

#### `unclear` → `<unclear>`
```xml
<!-- PAGE: unclear {offset:10;length:5;reason:obscure;} -->
<!-- TEI output: -->
<unclear reason="obscure">text</unclear>
```

## Quick Start

### 1. Basic Usage (Interactive)

```bash
python3 page2tei.py --input page_p1_dip.xml --output p1_dip.xml
```

The script will:
1. Auto-detect edition type from filename (`_dip` → diplomatic, `_trad` → translation)
2. Ask for confirmation
3. Show preset metadata
4. Ask if you want to modify defaults
5. Convert and save

### 2. Non-Interactive (Use All Defaults)

```bash
python3 page2tei.py -i page_p1_dip.xml -o p1_dip.xml --title "My Title"
```

### 3. Batch Conversion

```bash
# Diplomatic edition
for f in page_*_dip.xml; do
    out=$(echo $f | sed 's/page_//' | sed 's/_dip//')
    python3 page2tei.py -i "$f" -o "tei_dip_$out"
done

# Translation edition
for f in page_*_trad.xml; do
    out=$(echo $f | sed 's/page_//' | sed 's/_trad//')
    python3 page2tei.py -i "$f" -o "tei_trad_$out"
done
```

## Edition Type Detection

The script auto-detects edition type from filename patterns:

| Pattern | Detected Type |
|---------|---------------|
| `*_dip.xml` | Diplomatic |
| `*diplomatic*.xml` | Diplomatic |
| `*_trad.xml` | Translation |
| `*translation*.xml` | Translation |
| `*trans*.xml` | Translation |

If no pattern matches, you'll be prompted to choose.

## Metadata Presets

### Diplomatic Edition Preset

```yaml
Title: "PGM XIII — Diplomatic transcription"
Author: "Anonymous"
Editor: "Robert W. Daniel"
Language: grc (Ancient Greek)
Edition Type: "Diplomatic transcription"
Responsibility: "digital edition preparation and TEI encoding"
Publisher: "Springer Fachmedien Wiesbaden GmbH"
Publication Date: "1991"
Collection: "PGM"
Siglum: "PGM XIII"
Institution: "Rijksmuseum van Oudheden"
Settlement: "Leiden"
Country: "Netherlands"
Origin: "Egypt, 1st c. BCE–4th c. CE"
```

### Translation Edition Preset

```yaml
Title: "PGM XIII — Spanish translation"
Author: "Anonymous"
Editor: "Robert W. Daniel"
Translator: "Federico Gaviria Zambrano"
Language: es (Spanish)
Edition Type: "Spanish translation"
Responsibility: "Spanish translation and TEI encoding"
Publisher: "Springer Fachmedien Wiesbaden GmbH"
Publication Date: "1991"
Collection: "PGM"
Siglum: "PGM XIII"
Institution: "Rijksmuseum van Oudheden"
Settlement: "Leiden"
Country: "Netherlands"
Origin: "Egypt, 1st c. BCE–4th c. CE"
```

## Interactive Workflow Example

```
$ python3 page2tei.py -i page_p1_dip.xml -o p1_dip.xml

📋 Detected edition type: diplomatic
Is this correct? (y/n) [y]: y

📋 Using preset metadata for diplomatic edition:
  Title: PGM XIII — Diplomatic transcription
  Language: grc
  Edition type: Diplomatic transcription
  Editor: Robert W. Daniel

Do you want to modify these defaults? (y/n) [n]: n

✅ Successfully converted to p1_dip.xml
```

## Command Line Arguments

### Required
- `--input, -i` - Input PAGE-XML file (or `-` for stdin)
- `--output, -o` - Output TEI-XML file (or `-` for stdout)

### Optional Metadata (Override Presets)

#### Basic Information
- `--title` - Title of the work
- `--author` - Original author
- `--edition-editor` - Editor (for diplomatic edition)
- `--translator` - Translator (for translation edition)
- `--resp` - Your responsibility
- `--resp-name` - Your name
- `--publisher` - Publisher
- `--pub-date` - Publication date

#### Manuscript Identification
- `--country` - Holding country
- `--region` - Region
- `--settlement` - Settlement/city
- `--district` - District
- `--geogName` - Geographic name
- `--institution` - Holding institution
- `--repository` - Repository
- `--collection` - Collection
- `--idno-old` - Old catalog ID
- `--idno-new` - New museum ID
- `--idno-siglum` - Siglum (e.g., "PGM XIII")

#### Origin
- `--orig-place` - Original place (e.g., "Egypt")
- `--orig-notBefore` - Origin notBefore date (e.g., "-0100")
- `--orig-notAfter` - Origin notAfter date (e.g., "0400")
- `--orig-label` - Origin date label (e.g., "1st c. BCE–4th c. CE")

#### Page Information
- `--page-n` - Page number/label (e.g., "1r", "2v")
- `--page-side` - Page side (choices: `recto`, `verso`)

## Output Features

### Facsimile Section

The script creates proper TEI facsimile zones with:
- ✅ Image URL (automatically prefixed with `images/`)
- ✅ Image dimensions (width/height)
- ✅ Polygon coordinates for each line
- ✅ Baseline coordinates
- ✅ Line numbering

Example:
```xml
<facsimile>
  <surface xml:id="p1" n="1">
    <graphic url="images/p1.jpg" width="1072" height="1600"/>
    <zone xml:id="z_tr_1_tl_6" type="line" 
          points="196,267 227,263 ..." 
          baseline="196,257 227,253 ..."/>
  </surface>
</facsimile>
```

### Text Section

Lines are properly linked to zones:
```xml
<body>
  <div type="transcription" xml:lang="grc">
    <pb n="1" facs="#p1"/>
    <lb facs="#z_tr_1_tl_6" n="1"/>
    <ab>βιβλοϲ ϊερα επικαλουμενἡ μοναϲ η ογδοη 
        <persName type="humano" ref="https://www.wikidata.org/wiki/Q19968214">μουcεωc</persName>
    </ab>
  </div>
</body>
```

### Image Path Handling

The script **automatically** adds `images/` prefix to image filenames:

- **Input (PAGE):** `imageFilename="p1.jpg"`
- **Output (TEI):** `url="images/p1.jpg"`

This ensures compatibility with the TEI viewer which expects images in the `images/` subdirectory.

## Examples

### Example 1: Diplomatic Edition with Custom Title

```bash
python3 page2tei.py \
  --input page_p1_dip.xml \
  --output p1_dip.xml \
  --title "PGM XIII.1 - Monas Spell" \
  --page-n "1r"
```

### Example 2: Translation with All Metadata

```bash
python3 page2tei.py \
  --input page_p1_trad.xml \
  --output p1_trad.xml \
  --translator "Federico Gaviria Zambrano" \
  --title "PGM XIII - Traducción al español" \
  --page-n "1r" \
  --page-side recto
```

### Example 3: Pipe from stdin to stdout

```bash
cat page_p1_dip.xml | python3 page2tei.py -i - -o - > output.xml
```

## Workflow for PGM XIII Project

### Step 1: Export from Transkribus
1. Export PAGE XML for each page
2. Name files with pattern: `page_p1_dip.xml`, `page_p1_trad.xml`, etc.

### Step 2: Convert to TEI

```bash
# Diplomatic edition (Ancient Greek)
python3 page2tei.py -i page_p1_dip.xml -o p1_dip.xml

# Translation edition (Spanish)
python3 page2tei.py -i page_p1_trad.xml -o p1_trad.xml
```

### Step 3: Review and adjust
- Check that all annotations were converted correctly
- Verify metadata in `<teiHeader>`
- Ensure image paths are correct

### Step 4: Deploy to viewer
```bash
# Copy to viewer project
cp p1_dip.xml ../tei-viewer/projects/PGM-XIII/
cp p1_trad.xml ../tei-viewer/projects/PGM-XIII/

# Copy images (if not already there)
cp images/p1.jpg ../tei-viewer/projects/PGM-XIII/images/
```

## Troubleshooting

### Issue: "No edition type detected"
**Solution:** Rename file to include `_dip` or `_trad`, or you'll be prompted to select manually.

### Issue: Wrong language in output
**Solution:** The language is set based on edition type. For diplomatic = `grc`, for translation = `es`. Modify presets if needed.

### Issue: Image not loading in viewer
**Solution:** Ensure image exists in `images/` subdirectory relative to TEI file. The script automatically adds this prefix.

### Issue: Missing annotations in output
**Solution:** Check that PAGE XML has correct `custom` attributes. The script only converts properly formatted annotations.

### Issue: Nested annotations conflict
**Solution:** The script handles overlapping annotations by keeping the first occurrence. Review PAGE XML to ensure proper nesting.

## Technical Notes

### Coordinate Handling
- Preserves original coordinate values from PAGE XML
- No scaling or transformation applied
- Baseline points preserved exactly as in PAGE

### Text Encoding
- UTF-8 encoding throughout
- Handles Ancient Greek characters correctly
- Preserves all diacritics and special characters

### XML Validation
- Output conforms to TEI P5 schema
- Uses proper TEI namespace
- Pretty-printed for readability

## Advanced Usage

### Custom Metadata Templates

Create a preset file `my_metadata.txt`:
```
--title="My Custom Title"
--author="My Author"
--publisher="My Publisher"
```

Use it:
```bash
python3 page2tei.py -i input.xml -o output.xml @my_metadata.txt
```

### Integration with Build Scripts

```bash
#!/bin/bash
# convert_all.sh

PAGES=(p1 p2 p3 p4 p5)

for page in "${PAGES[@]}"; do
    echo "Converting $page..."
    
    # Diplomatic
    python3 page2tei.py \
        -i "page_${page}_dip.xml" \
        -o "../tei-viewer/projects/PGM-XIII/${page}_dip.xml" \
        --page-n "$page"
    
    # Translation
    python3 page2tei.py \
        -i "page_${page}_trad.xml" \
        -o "../tei-viewer/projects/PGM-XIII/${page}_trad.xml" \
        --page-n "$page"
done

echo "✅ All pages converted!"
```

## Version History

- **v2.0** (2024-11) - Complete rewrite with auto-detection, presets, and full tag support
- **v1.0** (2024-11) - Initial version with basic tag support

## Support

For issues or questions:
1. Check this guide
2. Verify PAGE XML format
3. Test with example files
4. Check output TEI structure

## License

Same as parent project.