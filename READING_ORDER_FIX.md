# Reading Order Fix

## Problem

The converter was outputting lines in incorrect reading order when the PAGE XML contained multiple `TextRegion` elements, each with their own line numbering.

### Example of Incorrect Output

**PAGE XML Structure:**
- TextRegion `r` (readingOrder index:0, type:heading)
  - Line `l` (index:0): "Tractatus de fascinatione..."
  - Line `l_355` (index:1): "chanca doctore..."
  - Line `l_359` (index:2): "run nostrorun..."
- TextRegion `tr_3` (readingOrder index:1, type:paragraph)
  - Line `l_577` (index:0): "Interrogatus..."
  - Line `l_366` (index:1): "tui doctus a socrate..."
  - ...
- TextRegion `r_2` (readingOrder index:2, type:page-number)
  - Line `l_685` (index:0): "a ij"

**BEFORE (Incorrect Order):**
```xml
<lb n="1"/> Line l (Tractatus...)        ← Region 0, Line 0 ✓
<lb n="2"/> Line l_577 (Interrogatus...) ← Region 1, Line 0 ✗ WRONG!
<lb n="3"/> Line l_685 (a ij)            ← Region 2, Line 0 ✗ WRONG!
<lb n="4"/> Line l_355 (chanca...)       ← Region 0, Line 1 ✗ WRONG!
```

The lines were sorted only by their individual `readingOrder {index:X}` value, ignoring which TextRegion they belonged to.

## Solution

Updated the sorting logic to consider **BOTH** the TextRegion's reading order AND the TextLine's reading order within that region.

### Code Changes

**Before:**
```python
lines.append((idx, tl_id, points, baseline, text_val, cust))
lines.sort(key=lambda x: (x[0], x[1]))
```

**After:**
```python
# Store region index and line index separately
lines.append((region_idx, line_idx, tl_id, points, baseline, text_val, cust))

# Sort by region first, then by line within region
lines.sort(key=lambda x: (x[0], x[1], x[2]))
```

## Result

**AFTER (Correct Order):**
```xml
<lb n="1"/> Line l (Tractatus...)        ← Region 0, Line 0 ✓
<lb n="2"/> Line l_355 (chanca...)       ← Region 0, Line 1 ✓
<lb n="3"/> Line l_359 (run nostrorun...) ← Region 0, Line 2 ✓
<lb n="4"/> Line l_577 (Interrogatus...) ← Region 1, Line 0 ✓
<lb n="5"/> Line l_366 (tui doctus...)   ← Region 1, Line 1 ✓
...
<lb n="34"/> Line l_685 (a ij)           ← Region 2, Line 0 ✓
```

## Verification

### Test Case: test.xml
Contains 3 TextRegions with different types:

| Region ID | Type | Reading Order | Lines | Line Indices |
|-----------|------|---------------|-------|--------------|
| r | heading | 0 | 3 | 0, 1, 2 |
| tr_3 | paragraph | 1 | 30 | 0-29 |
| r_2 | page-number | 2 | 1 | 0 |

**Verification Commands:**
```bash
# Convert with fixed order
python3 page2tei.py --input test.xml --output test_fixed_order.xml

# Check first 5 lines
grep -o '<lb facs="#z_[^"]*" n="[^"]*"' test_fixed_order.xml | head -5
# Output:
# <lb facs="#z_l" n="1"          ← Tractatus... (region 0, line 0)
# <lb facs="#z_l_355" n="2"      ← chanca... (region 0, line 1)
# <lb facs="#z_l_359" n="3"      ← run nostrorun... (region 0, line 2)
# <lb facs="#z_l_577" n="4"      ← Interrogatus... (region 1, line 0)
# <lb facs="#z_l_366" n="5"      ← tui doctus... (region 1, line 1)

# Check last line
grep -o '<lb facs="#z_[^"]*" n="[^"]*"' test_fixed_order.xml | tail -1
# Output:
# <lb facs="#z_l_685" n="34"     ← a ij (region 2, line 0)
```

### Results
✅ **All 34 lines in correct reading order**
✅ **Heading region (3 lines) appears first**
✅ **Paragraph region (30 lines) appears second**
✅ **Page number region (1 line) appears last**

## Impact

This fix ensures that:
1. **Document structure is preserved** - Headers, paragraphs, and page numbers appear in logical order
2. **Reading flow is natural** - Text can be read sequentially from line 1 to N
3. **Semantic regions maintained** - Different text types (heading, body, footer) stay grouped
4. **Multi-region documents work** - Complex layouts with multiple regions sort correctly

## Commit

- **Repository:** PGM_XIII-AMS76
- **Commit:** `048107b`
- **Message:** "Fix reading order to respect both TextRegion and TextLine indices"

## Technical Details

### Sorting Key

The new 3-level sort key:
1. **Primary:** TextRegion's `readingOrder {index:X}` 
2. **Secondary:** TextLine's `readingOrder {index:Y}` within that region
3. **Tertiary:** TextLine ID (for stable sorting)

This ensures:
- All lines from Region 0 come before Region 1
- Within Region 0, lines are sorted by their index
- If two lines have the same indices, ID provides stable ordering

### Edge Cases Handled

1. **Missing readingOrder:** Defaults to 999999 (sorts to end)
2. **Malformed indices:** Try-except catches parsing errors
3. **Mixed numbering:** Numeric sort works correctly even if indices aren't sequential
4. **Single region:** Works identically to before when there's only one region

## Related Issues

This fix resolves the reading order problem mentioned in the test.xml conversion where lines were appearing out of sequence in the TEI output.
