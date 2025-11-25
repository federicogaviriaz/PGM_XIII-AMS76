#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PAGE XML -> TEI P5 converter with interactive metadata prompts and full tag support.

Features:
- Auto-detects edition type (diplomatic/translation) from filename pattern
- Provides preset metadata for diplomatic vs translation editions
- Reads PAGE-XML and writes TEI P5 with comprehensive tag support
- Builds teiHeader with titleStmt, editionStmt, publicationStmt, msDesc
- Maps PAGE TextRegion/TextLine to TEI facsimile/surface/zone with polygons
- Links text lines via <lb facs="#zone"> with line numbers
- Applies PAGE TextLine @custom inline annotations:
    abbrev{offset;length;expansion} -> <choice><abbr>…</abbr><expan>…</expan></choice>
    sic{offset;length;correction}   -> <choice><sic>…</sic><corr>…</corr></choice>
    regularised{offset;length;original} -> <choice><orig>…</orig><reg>…</reg></choice>
    num{offset;length;type;value}   -> <num type="…" value="…">…</num>
    person{...}                      -> <persName type="…" ref="…">…</persName>
    place{...}                       -> <placeName><country>…</country></placeName>
    ref{offset;length;type;target}  -> <ref type="…" target="…">…</ref>
    unclear{offset;length;reason}   -> <unclear reason="…">…</unclear>
    textStyle{bold/italic/underline/superscript/subscript} -> <hi rend="…">…</hi>
- Automatically prefixes image paths with "images/"
- Language-aware based on edition type (grc for diplomatic, es for translation)

CLI:
  page2tei.py --input in.xml --output out.xml [--non-interactive flags...]
  Use "-" for stdin/stdout. Without flags, the script will prompt interactively.
"""

import argparse
import os
import re
import sys
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional
from xml.dom import minidom

PAGE_NS = {"pg": "http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15"}
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
ET.register_namespace("", TEI_NS)

# -------------------------
# Utilities
# -------------------------


def parse_bool(val) -> bool:
    """Parse boolean from string."""
    return str(val).strip().lower() in ("1", "true", "yes", "y")


def parse_int(val, default=0) -> int:
    """Parse integer with fallback."""
    try:
        return int(val)
    except Exception:
        return default


def qn(name: str) -> ET.QName:
    """Create qualified name in TEI namespace."""
    return ET.QName(TEI_NS, name)


def prettify(elem: ET.Element) -> str:
    """Pretty-print XML element."""
    raw = ET.tostring(elem, encoding="utf-8")
    return (
        minidom.parseString(raw)
        .toprettyxml(indent="  ", encoding="utf-8")
        .decode("utf-8")
    )


def detect_edition_type(filename: str) -> Optional[str]:
    """
    Auto-detect edition type from filename pattern.
    Returns 'diplomatic', 'translation', or None.
    """
    basename = os.path.basename(filename).lower()
    if "_dip" in basename or "diplomatic" in basename:
        return "diplomatic"
    elif "_trad" in basename or "translation" in basename or "trans" in basename:
        return "translation"
    return None


# -------------------------
# PAGE custom parsing
# -------------------------


def parse_custom_ops(custom_str: str) -> List[Dict[str, Any]]:
    """
    Parse PAGE @custom like:
      'readingOrder {index:3;} abbrev {offset:9;length:2;expansion:...;}
       person {offset:X;length:Y;firstname:Name;type:humano;wikiData:Q...;}'
    Return list of ops with keys: kind, offset, length, end, plus additional attributes.
    """
    ops = []
    if not custom_str:
        return ops

    # Match pattern: word{key:value;key:value;}
    for m in re.finditer(r"(\w+)\s*\{([^}]*)\}", custom_str):
        kind = m.group(1)
        body = m.group(2)
        kv = {}

        # Parse key:value pairs
        for part in re.finditer(r"(\w+)\s*:\s*([^;]+);", body):
            kv[part.group(1)] = part.group(2).strip()

        off = parse_int(kv.get("offset", "0"), 0)
        length = parse_int(kv.get("length", "0"), 0)
        end = off + length

        op = {"kind": kind, "offset": off, "length": length, "end": end}

        # Add all other attributes
        for k, v in kv.items():
            if k in ("offset", "length"):
                continue
            op[k] = v

        # Special handling for textStyle
        if kind == "textStyle":
            for k in ("bold", "italic", "underline", "superscript", "subscript"):
                if k in op:
                    op[k] = "true" if parse_bool(op[k]) else "false"

        ops.append(op)

    return ops


# -------------------------
# Inline TEI builders
# -------------------------


def slice_text_nodes(text: str, ranges: List[tuple]) -> List[tuple]:
    """
    Slice text into segments based on annotation ranges.
    ranges: list of (start, end, label)
    returns list of (start, end, segment_text, labels_set)
    """
    cut_points = {0, len(text)}
    for s, e, _ in ranges:
        cut_points.add(max(0, min(len(text), s)))
        cut_points.add(max(0, min(len(text), e)))

    cuts = sorted(cut_points)
    segments = []

    for i in range(len(cuts) - 1):
        s, e = cuts[i], cuts[i + 1]
        if s == e:
            continue
        segment = text[s:e]
        labels = {lab for ss, ee, lab in ranges if ss <= s and e <= ee and ss < ee}
        segments.append((s, e, segment, labels))

    return segments


def append_text(parent: ET.Element, s: str):
    """Append text to element, handling text vs tail."""
    if not s:
        return
    if parent.text is None and len(parent) == 0:
        parent.text = s
    else:
        if len(parent):
            last = list(parent)[-1]
            last.tail = (last.tail or "") + s
        else:
            parent.text = (parent.text or "") + s


def build_styled_nodes(parent: ET.Element, text: str, style_ops: List[Dict[str, Any]]):
    """Build text with <hi rend="..."> styling."""
    ranges = []
    for op in style_ops:
        rend = []
        if op.get("bold", "false") == "true":
            rend.append("bold")
        if op.get("italic", "false") == "true":
            rend.append("italic")
        if op.get("underline", "false") == "true":
            rend.append("underline")
        if op.get("superscript", "false") == "true":
            rend.append("superscript")
        if op.get("subscript", "false") == "true":
            rend.append("subscript")
        if not rend:
            continue
        ranges.append((op["offset"], op["end"], " ".join(rend)))

    if not ranges:
        append_text(parent, text)
        return

    for s, e, seg_text, labels in slice_text_nodes(text, ranges):
        if not labels:
            append_text(parent, seg_text)
        else:
            hi = ET.Element(qn("hi"))
            hi.set("rend", " ".join(sorted(labels)))
            hi.text = seg_text
            parent.append(hi)


def build_choice_with_styles(
    kind: str,
    witness_text: str,
    alt_text: str,
    inner_style_ops: List[Dict[str, Any]],
    global_offset: int,
) -> ET.Element:
    """Build <choice> element with abbreviation, correction, or regularisation."""
    choice = ET.Element(qn("choice"))

    if kind == "abbrev":
        a_tag = "abbr"
        b_tag = "expan"
        first_text = witness_text
        second_text = alt_text
    elif kind == "sic":
        a_tag = "sic"
        b_tag = "corr"
        first_text = witness_text
        second_text = alt_text
    elif kind == "regularised":
        # For regularised, witness_text is the regularised form (goes in <reg>)
        # and alt_text (from 'original' attribute) is the original form (goes in <orig>)
        a_tag = "orig"
        b_tag = "reg"
        first_text = alt_text  # original goes first in <orig>
        second_text = witness_text  # regularised goes second in <reg>
    else:
        a_tag = "orig"
        b_tag = "reg"
        first_text = witness_text
        second_text = alt_text

    a = ET.SubElement(choice, qn(a_tag))

    # Adjust styles relative to this span
    adj_styles = []
    for op in inner_style_ops:
        if op["offset"] >= global_offset and op["end"] <= global_offset + len(
            witness_text
        ):
            cp = dict(op)
            cp["offset"] = cp["offset"] - global_offset
            cp["end"] = cp["end"] - global_offset
            adj_styles.append(cp)

    # For regularised, styles apply to the second element (reg), not the first (orig)
    if kind == "regularised":
        a.text = first_text or ""
        b = ET.SubElement(choice, qn(b_tag))
        build_styled_nodes(b, second_text, adj_styles)
    else:
        build_styled_nodes(a, first_text, adj_styles)
        b = ET.SubElement(choice, qn(b_tag))
        b.text = second_text or ""

    return choice


def build_num_with_styles(
    witness_text: str,
    num_op: Dict[str, Any],
    inner_style_ops: List[Dict[str, Any]],
    global_offset: int,
) -> ET.Element:
    """Build <num> element with type and value."""
    num = ET.Element(qn("num"))
    if "type" in num_op:
        num.set("type", num_op["type"])
    if "value" in num_op:
        num.set("value", num_op["value"])

    adj_styles = []
    for op in inner_style_ops:
        if op["offset"] >= global_offset and op["end"] <= global_offset + len(
            witness_text
        ):
            cp = dict(op)
            cp["offset"] = cp["offset"] - global_offset
            cp["end"] = cp["end"] - global_offset
            adj_styles.append(cp)

    build_styled_nodes(num, witness_text, adj_styles)
    return num


def build_persName(
    witness_text: str,
    person_op: Dict[str, Any],
    inner_style_ops: List[Dict[str, Any]],
    global_offset: int,
) -> ET.Element:
    """Build <persName> element with type and optional ref."""
    persName = ET.Element(qn("persName"))

    # Type is always set
    if "type" in person_op:
        persName.set("type", person_op["type"])

    # Ref is optional (for wikiData)
    if "wikiData" in person_op:
        wikidata_id = person_op["wikiData"]
        persName.set("ref", f"https://www.wikidata.org/wiki/{wikidata_id}")

    adj_styles = []
    for op in inner_style_ops:
        if op["offset"] >= global_offset and op["end"] <= global_offset + len(
            witness_text
        ):
            cp = dict(op)
            cp["offset"] = cp["offset"] - global_offset
            cp["end"] = cp["end"] - global_offset
            adj_styles.append(cp)

    build_styled_nodes(persName, witness_text, adj_styles)
    return persName


def build_placeName(
    witness_text: str,
    place_op: Dict[str, Any],
    inner_style_ops: List[Dict[str, Any]],
    global_offset: int,
) -> ET.Element:
    """Build <placeName> element with nested attributes like <country>."""
    placeName = ET.Element(qn("placeName"))

    # Nest attributes as child elements
    nested_attrs = ["country", "region", "settlement", "district"]
    has_nested = False

    for attr in nested_attrs:
        if attr in place_op:
            child = ET.SubElement(placeName, qn(attr))
            child.text = place_op[attr]
            has_nested = True

    # If no nested attributes, just add text
    if not has_nested:
        adj_styles = []
        for op in inner_style_ops:
            if op["offset"] >= global_offset and op["end"] <= global_offset + len(
                witness_text
            ):
                cp = dict(op)
                cp["offset"] = cp["offset"] - global_offset
                cp["end"] = cp["end"] - global_offset
                adj_styles.append(cp)
        build_styled_nodes(placeName, witness_text, adj_styles)

    return placeName


def build_ref(
    witness_text: str,
    ref_op: Dict[str, Any],
    inner_style_ops: List[Dict[str, Any]],
    global_offset: int,
) -> ET.Element:
    """Build <ref> element with type and target."""
    ref = ET.Element(qn("ref"))

    if "type" in ref_op:
        ref.set("type", ref_op["type"])
    if "target" in ref_op:
        ref.set("target", ref_op["target"])

    adj_styles = []
    for op in inner_style_ops:
        if op["offset"] >= global_offset and op["end"] <= global_offset + len(
            witness_text
        ):
            cp = dict(op)
            cp["offset"] = cp["offset"] - global_offset
            cp["end"] = cp["end"] - global_offset
            adj_styles.append(cp)

    build_styled_nodes(ref, witness_text, adj_styles)
    return ref


def build_unclear(
    witness_text: str,
    unclear_op: Dict[str, Any],
    inner_style_ops: List[Dict[str, Any]],
    global_offset: int,
) -> ET.Element:
    """Build <unclear> element with reason attribute."""
    unclear = ET.Element(qn("unclear"))

    if "reason" in unclear_op:
        unclear.set("reason", unclear_op["reason"])

    adj_styles = []
    for op in inner_style_ops:
        if op["offset"] >= global_offset and op["end"] <= global_offset + len(
            witness_text
        ):
            cp = dict(op)
            cp["offset"] = cp["offset"] - global_offset
            cp["end"] = cp["end"] - global_offset
            adj_styles.append(cp)

    build_styled_nodes(unclear, witness_text, adj_styles)
    return unclear


def build_fallback_seg(
    witness_text: str,
    op: Dict[str, Any],
    inner_style_ops: List[Dict[str, Any]],
    global_offset: int,
) -> ET.Element:
    """Build generic <seg> for unknown tag types."""
    seg = ET.Element(qn("seg"))
    seg.set("type", op.get("kind", "custom"))

    # Echo unknown attributes as data-*
    for k, v in op.items():
        if k in ("kind", "offset", "length", "end"):
            continue
        seg.set(f"data-{k}", v)

    adj_styles = []
    for s in inner_style_ops:
        if s["offset"] >= global_offset and s["end"] <= global_offset + len(
            witness_text
        ):
            cp = dict(s)
            cp["offset"] = cp["offset"] - global_offset
            cp["end"] = cp["end"] - global_offset
            adj_styles.append(cp)

    build_styled_nodes(seg, witness_text, adj_styles)
    return seg


def build_inline_nodes_for_line(text: str, ops: List[Dict[str, Any]]) -> List[Any]:
    """
    Build inline TEI nodes from text and operations.
    Returns list of strings and ET.Elements.
    """
    # Separate operations by type
    choice_ops = [
        o
        for o in ops
        if o["kind"] in ("abbrev", "sic", "regularised") and o["length"] > 0
    ]
    num_ops = [o for o in ops if o["kind"] == "num" and o["length"] > 0]
    person_ops = [o for o in ops if o["kind"] == "person" and o["length"] > 0]
    place_ops = [o for o in ops if o["kind"] == "place" and o["length"] > 0]
    ref_ops = [o for o in ops if o["kind"] == "ref" and o["length"] > 0]
    unclear_ops = [o for o in ops if o["kind"] == "unclear" and o["length"] > 0]
    style_ops = [o for o in ops if o["kind"] == "textStyle" and o["length"] > 0]

    # Known wrapper types
    known_kinds = {
        "abbrev",
        "sic",
        "regularised",
        "num",
        "person",
        "place",
        "ref",
        "unclear",
        "textStyle",
    }
    other_ops = [o for o in ops if o["kind"] not in known_kinds and o["length"] > 0]

    # Primary wrapper ops in document order (start asc, end desc for nesting)
    wrappers = sorted(
        choice_ops
        + num_ops
        + person_ops
        + place_ops
        + ref_ops
        + unclear_ops
        + other_ops,
        key=lambda x: (x["offset"], -x["end"]),
    )

    nodes: List[Any] = []
    cursor = 0

    for w in wrappers:
        start, end = w["offset"], w["end"]

        # Skip overlapping annotations (keep first occurrence)
        if start < cursor:
            continue

        # Text before this wrapper
        pre = text[cursor:start]
        if pre:
            tmp = ET.Element("tmp")
            pre_styles = [
                s for s in style_ops if cursor <= s["offset"] and s["end"] <= start
            ]
            build_styled_nodes(tmp, pre, pre_styles)
            if tmp.text:
                nodes.append(tmp.text)
            for ch in list(tmp):
                nodes.append(ch)
                if ch.tail:
                    nodes.append(ch.tail)
                    ch.tail = None

        # The annotated span
        witness = text[start:end]
        inner_styles = [
            s for s in style_ops if start <= s["offset"] and s["end"] <= end
        ]

        # Build appropriate element
        if w["kind"] in ("abbrev", "sic", "regularised"):
            if w["kind"] == "abbrev":
                alt = w.get("expansion")
            elif w["kind"] == "sic":
                alt = w.get("correction")
            else:  # regularised
                alt = w.get("original")
            el = build_choice_with_styles(
                w["kind"], witness, alt or "", inner_styles, start
            )
        elif w["kind"] == "num":
            el = build_num_with_styles(witness, w, inner_styles, start)
        elif w["kind"] == "person":
            el = build_persName(witness, w, inner_styles, start)
        elif w["kind"] == "place":
            el = build_placeName(witness, w, inner_styles, start)
        elif w["kind"] == "ref":
            el = build_ref(witness, w, inner_styles, start)
        elif w["kind"] == "unclear":
            el = build_unclear(witness, w, inner_styles, start)
        else:
            el = build_fallback_seg(witness, w, inner_styles, start)

        nodes.append(el)
        cursor = end

    # Tail after last wrapper
    if cursor < len(text):
        tail = text[cursor:]
        tmp = ET.Element("tmp")
        tail_styles = [
            s for s in style_ops if cursor <= s["offset"] and s["end"] <= len(text)
        ]
        build_styled_nodes(tmp, tail, tail_styles)
        if tmp.text:
            nodes.append(tmp.text)
        for ch in list(tmp):
            nodes.append(ch)
            if ch.tail:
                nodes.append(ch.tail)
                ch.tail = None

    return nodes


# -------------------------
# Metadata prompts and presets
# -------------------------


def get_default_metadata(edition_type: str) -> Dict[str, Any]:
    """Get default metadata based on edition type."""
    if edition_type == "diplomatic":
        return {
            "title": "PGM XIII — Diplomatic transcription",
            "author": "Anonymous",
            "edition_editor": "Robert W. Daniel",
            "resp": "digital edition preparation and TEI encoding",
            "resp_name": "Federico Gaviria Zambrano",
            "publisher": "Springer Fachmedien Wiesbaden GmbH",
            "pub_date": "1991",
            "country": "Netherlands",
            "region": "",
            "settlement": "Leiden",
            "district": "",
            "geogName": "",
            "institution": "Rijksmuseum van Oudheden",
            "repository": "",
            "collection": "PGM",
            "idno_old": "J395",
            "idno_new": "AMS76",
            "idno_siglum": "PGM XIII",
            "orig_place": "Egypt",
            "orig_notBefore": "-0100",
            "orig_notAfter": "0400",
            "orig_label": "1st c. BCE–4th c. CE",
            "page_n": "",
            "page_side": "",
            "edition_type": "Diplomatic transcription",
            "language": "grc",
            "translator": "",
        }
    else:  # translation
        return {
            "title": "PGM XIII — Spanish translation",
            "author": "Anonymous",
            "edition_editor": "Robert W. Daniel",
            "translator": "Federico Gaviria Zambrano",
            "resp": "Spanish translation and TEI encoding",
            "resp_name": "Federico Gaviria Zambrano",
            "publisher": "Springer Fachmedien Wiesbaden GmbH",
            "pub_date": "1991",
            "country": "Netherlands",
            "region": "",
            "settlement": "Leiden",
            "district": "",
            "geogName": "",
            "institution": "Rijksmuseum van Oudheden",
            "repository": "",
            "collection": "PGM",
            "idno_old": "J395",
            "idno_new": "AMS76",
            "idno_siglum": "PGM XIII",
            "orig_place": "Egypt",
            "orig_notBefore": "-0100",
            "orig_notAfter": "0400",
            "orig_label": "1st c. BCE–4th c. CE",
            "page_n": "",
            "page_side": "",
            "edition_type": "Spanish translation",
            "language": "es",
        }


def prompt_or_flag(value: Any, prompt_text: str, default: str = "") -> str:
    """Prompt user or use provided value."""
    if value is not None:
        return str(value)
    try:
        result = input(f"{prompt_text} [{default}]: ").strip()
        return result if result else default
    except (EOFError, KeyboardInterrupt):
        return default


def collect_metadata(args: argparse.Namespace, input_file: str) -> Dict[str, Any]:
    """Collect metadata interactively or from arguments."""

    # Auto-detect edition type from filename
    detected_type = detect_edition_type(input_file)

    # Confirm edition type
    if detected_type:
        print(f"\n📋 Detected edition type: {detected_type}")
        confirm = input(f"Is this correct? (y/n) [y]: ").strip().lower()
        if confirm and confirm not in ("y", "yes"):
            detected_type = None

    if not detected_type:
        print("\n📋 Select edition type:")
        print("  1) Diplomatic transcription")
        print("  2) Translation")
        choice = input("Enter choice (1/2): ").strip()
        detected_type = "diplomatic" if choice == "1" else "translation"

    # Get preset metadata
    meta = get_default_metadata(detected_type)

    # Show presets and ask if user wants to modify
    print(f"\n📋 Using preset metadata for {detected_type} edition:")
    print(f"  Title: {meta['title']}")
    print(f"  Language: {meta['language']}")
    print(f"  Edition type: {meta['edition_type']}")
    if meta["translator"]:
        print(f"  Translator: {meta['translator']}")
    else:
        print(f"  Editor: {meta['edition_editor']}")

    modify = (
        input("\nDo you want to modify these defaults? (y/n) [n]: ").strip().lower()
    )

    if modify in ("y", "yes"):
        # Allow modification of key fields
        meta["title"] = prompt_or_flag(args.title, "Title", meta["title"])
        meta["author"] = prompt_or_flag(
            args.author, "Author (original work)", meta["author"]
        )

        if detected_type == "translation":
            meta["translator"] = prompt_or_flag(
                getattr(args, "translator", None), "Translator", meta["translator"]
            )
        else:
            meta["edition_editor"] = prompt_or_flag(
                args.edition_editor,
                "Editor of diplomatic edition",
                meta["edition_editor"],
            )

        meta["resp"] = prompt_or_flag(args.resp, "Your responsibility", meta["resp"])
        meta["resp_name"] = prompt_or_flag(
            args.resp_name, "Your name", meta["resp_name"]
        )
        meta["publisher"] = prompt_or_flag(
            args.publisher, "Publisher", meta["publisher"]
        )
        meta["pub_date"] = prompt_or_flag(
            args.pub_date, "Publication date", meta["pub_date"]
        )

        # msIdentifier
        meta["country"] = prompt_or_flag(args.country, "Country", meta["country"])
        meta["settlement"] = prompt_or_flag(
            args.settlement, "Settlement (city)", meta["settlement"]
        )
        meta["institution"] = prompt_or_flag(
            args.institution, "Institution", meta["institution"]
        )
        meta["collection"] = prompt_or_flag(
            args.collection, "Collection", meta["collection"]
        )
        meta["idno_siglum"] = prompt_or_flag(
            args.idno_siglum, "Siglum", meta["idno_siglum"]
        )

        # Origin
        meta["orig_place"] = prompt_or_flag(
            args.orig_place, "Original place", meta["orig_place"]
        )
        meta["orig_label"] = prompt_or_flag(
            args.orig_label, "Origin date label", meta["orig_label"]
        )

    return meta


# -------------------------
# TEI header builder
# -------------------------


def build_header(meta: Dict[str, Any]) -> ET.Element:
    """Build TEI header from metadata."""
    teiHeader = ET.Element(qn("teiHeader"))
    fileDesc = ET.SubElement(teiHeader, qn("fileDesc"))

    # titleStmt
    titleStmt = ET.SubElement(fileDesc, qn("titleStmt"))
    ET.SubElement(titleStmt, qn("title")).text = meta["title"]
    ET.SubElement(titleStmt, qn("author")).text = meta["author"]

    if meta.get("translator"):
        # For translations
        ET.SubElement(titleStmt, qn("editor"), {"role": "translator"}).text = meta[
            "translator"
        ]

    if meta.get("edition_editor"):
        ET.SubElement(titleStmt, qn("editor")).text = meta["edition_editor"]

    rs = ET.SubElement(titleStmt, qn("respStmt"))
    ET.SubElement(rs, qn("resp")).text = meta["resp"]
    ET.SubElement(rs, qn("name")).text = meta["resp_name"]

    # editionStmt
    editionStmt = ET.SubElement(fileDesc, qn("editionStmt"))
    ET.SubElement(editionStmt, qn("edition")).text = meta.get(
        "edition_type", "Digital edition"
    )

    # publicationStmt
    publicationStmt = ET.SubElement(fileDesc, qn("publicationStmt"))
    if meta.get("publisher"):
        ET.SubElement(publicationStmt, qn("publisher")).text = meta["publisher"]
    if meta.get("pub_date"):
        ET.SubElement(publicationStmt, qn("date")).text = meta["pub_date"]
    ET.SubElement(
        publicationStmt, qn("p")
    ).text = "Digital edition for research and display purposes."

    # sourceDesc
    sourceDesc = ET.SubElement(fileDesc, qn("sourceDesc"))
    msDesc = ET.SubElement(sourceDesc, qn("msDesc"))
    msIdentifier = ET.SubElement(msDesc, qn("msIdentifier"))

    # msIdentifier fields
    if meta.get("country"):
        ET.SubElement(msIdentifier, qn("country")).text = meta["country"]
    if meta.get("region"):
        ET.SubElement(msIdentifier, qn("region")).text = meta["region"]
    if meta.get("settlement"):
        ET.SubElement(msIdentifier, qn("settlement")).text = meta["settlement"]
    if meta.get("district"):
        ET.SubElement(msIdentifier, qn("district")).text = meta["district"]
    if meta.get("geogName"):
        ET.SubElement(msIdentifier, qn("geogName")).text = meta["geogName"]
    if meta.get("institution"):
        ET.SubElement(msIdentifier, qn("institution")).text = meta["institution"]
    if meta.get("repository"):
        ET.SubElement(msIdentifier, qn("repository")).text = meta["repository"]
    if meta.get("collection"):
        ET.SubElement(msIdentifier, qn("collection")).text = meta["collection"]
    if meta.get("idno_old"):
        ET.SubElement(msIdentifier, qn("idno"), {"type": "oldCatalog"}).text = meta[
            "idno_old"
        ]
    if meta.get("idno_new"):
        ET.SubElement(msIdentifier, qn("idno"), {"type": "museumNew"}).text = meta[
            "idno_new"
        ]
    if meta.get("idno_siglum"):
        ET.SubElement(msIdentifier, qn("idno"), {"type": "siglum"}).text = meta[
            "idno_siglum"
        ]

    # physDesc
    if meta.get("page_n"):
        physDesc = ET.SubElement(msDesc, qn("physDesc"))
        objectDesc = ET.SubElement(physDesc, qn("objectDesc"))
        supportDesc = ET.SubElement(objectDesc, qn("supportDesc"))
        fol = ET.SubElement(supportDesc, qn("foliation"))
        fol.text = f'Numbered as "{meta["page_n"]}" in the current collection.'

    # history/origin
    history = ET.SubElement(msDesc, qn("history"))
    origin = ET.SubElement(history, qn("origin"))
    if meta.get("orig_place"):
        op = ET.SubElement(origin, qn("origPlace"))
        ET.SubElement(op, qn("placeName")).text = meta["orig_place"]

    od = ET.SubElement(origin, qn("origDate"))
    if meta.get("orig_notBefore"):
        od.set("notBefore", meta["orig_notBefore"])
    if meta.get("orig_notAfter"):
        od.set("notAfter", meta["orig_notAfter"])
    if meta.get("orig_label"):
        od.text = meta["orig_label"]

    # encodingDesc
    encodingDesc = ET.SubElement(teiHeader, qn("encodingDesc"))
    ET.SubElement(encodingDesc, qn("p")).text = (
        "Converted from PAGE-XML with full semantic markup including "
        "abbreviations, corrections, regularisations, numbers, person names, place names, "
        "references, and text styling."
    )

    # profileDesc
    profileDesc = ET.SubElement(teiHeader, qn("profileDesc"))
    langUsage = ET.SubElement(profileDesc, qn("langUsage"))
    lang_code = meta.get("language", "grc")
    lang_name = "Ancient Greek" if lang_code == "grc" else "Spanish"
    ET.SubElement(langUsage, qn("language"), {"ident": lang_code}).text = lang_name

    # revisionDesc
    revisionDesc = ET.SubElement(teiHeader, qn("revisionDesc"))
    ET.SubElement(
        revisionDesc, qn("change")
    ).text = "Automated conversion from PAGE-XML with preservation of all annotations."

    return teiHeader


# -------------------------
# PAGE -> TEI converter
# -------------------------


def convert_page_to_tei(page_root: ET.Element, meta: Dict[str, Any]) -> ET.Element:
    """Convert PAGE XML to TEI."""
    tei = ET.Element(qn("TEI"))
    tei.append(build_header(meta))

    facsimile = ET.SubElement(tei, qn("facsimile"))
    text_el = ET.SubElement(tei, qn("text"))
    body = ET.SubElement(text_el, qn("body"))
    div = ET.SubElement(body, qn("div"), {"type": "transcription"})

    # Set language
    lang_code = meta.get("language", "grc")
    div.set(ET.QName(XML_NS, "lang"), lang_code)

    # Iterate pages
    for page_idx, page in enumerate(page_root.findall("pg:Page", PAGE_NS), start=1):
        image_fn = page.get("imageFilename")
        width = page.get("imageWidth")
        height = page.get("imageHeight")

        surface = ET.SubElement(facsimile, qn("surface"), {"n": str(page_idx)})
        surface.set(ET.QName(XML_NS, "id"), f"p{page_idx}")

        if meta.get("page_side"):
            surface.set("type", meta["page_side"])
        if meta.get("page_n"):
            surface.set("n", meta["page_n"])

        graphic = ET.SubElement(surface, qn("graphic"))
        if image_fn:
            # Add "images/" prefix if not already present
            if not image_fn.startswith("images/"):
                image_fn = f"images/{image_fn}"
            graphic.set("url", image_fn)
        if width:
            graphic.set("width", width)
        if height:
            graphic.set("height", height)

        # Page break
        ET.SubElement(div, qn("pb"), {"n": str(page_idx), "facs": f"#p{page_idx}"})

        # Map regions to zones
        for region in page.findall(".//*", PAGE_NS):
            local = region.tag.split("}")[-1]
            if local.endswith("Region"):
                rid = region.get("id") or f"reg_{local}_{page_idx}"
                coords = region.find("pg:Coords", PAGE_NS)
                if coords is not None:
                    z = ET.SubElement(surface, qn("zone"), {"type": local})
                    z.set(ET.QName(XML_NS, "id"), f"z_{rid}")
                    pts = coords.get("points")
                    if pts:
                        z.set("points", pts)

        # Collect TextLines with reading order
        lines = []
        for tregion in page.findall(".//pg:TextRegion", PAGE_NS):
            for tl in tregion.findall("pg:TextLine", PAGE_NS):
                cust = tl.get("custom") or ""
                idx = 999999
                if "index:" in cust:
                    try:
                        idx = int(cust.split("index:")[1].split(";")[0].strip(" }"))
                    except Exception:
                        pass

                coords_el = tl.find("pg:Coords", PAGE_NS)
                points = coords_el.get("points") if coords_el is not None else None

                baseline_el = tl.find("pg:Baseline", PAGE_NS)
                baseline = (
                    baseline_el.get("points") if baseline_el is not None else None
                )

                text_val = (
                    tl.findtext(
                        "pg:TextEquiv/pg:Unicode", default="", namespaces=PAGE_NS
                    )
                    or ""
                )

                tl_id = tl.get("id") or f"tl_{len(lines) + 1}"
                lines.append((idx, tl_id, points, baseline, text_val, cust))

        # Sort by reading order
        lines.sort(key=lambda x: (x[0], x[1]))

        # Create line zones and text
        for line_num, (_, tl_id, points, baseline, text_val, cust) in enumerate(
            lines, start=1
        ):
            zid = f"z_{tl_id}"
            z = ET.SubElement(surface, qn("zone"), {"type": "line"})
            z.set(ET.QName(XML_NS, "id"), zid)
            if points:
                z.set("points", points)
            if baseline:
                z.set("baseline", baseline)

            # Line break with number
            ET.SubElement(div, qn("lb"), {"facs": f"#{zid}", "n": str(line_num)})
            ab = ET.SubElement(div, qn("ab"))

            # Parse custom annotations and build inline nodes
            ops = parse_custom_ops(cust)
            inline_nodes = build_inline_nodes_for_line(text_val, ops)

            for node in inline_nodes:
                if isinstance(node, str):
                    append_text(ab, node)
                else:
                    ab.append(node)

            # Fallback if ab is empty
            if ab.text is None and len(ab) == 0:
                ab.text = text_val

    return tei


# -------------------------
# CLI
# -------------------------


def main():
    ap = argparse.ArgumentParser(
        description="Convert Transkribus PAGE-XML to TEI P5 with comprehensive semantic markup.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive mode (recommended)
  python page2tei.py --input page_p1_dip.xml --output p1_dip.xml

  # Non-interactive with presets
  python page2tei.py -i page_p1_trad.xml -o p1_trad.xml --title "PGM XIII Translation"

  # Use stdin/stdout
  cat input.xml | python page2tei.py -i - -o - > output.xml
        """,
    )

    ap.add_argument(
        "--input", "-i", default="-", help='Input PAGE-XML file or "-" for stdin'
    )
    ap.add_argument(
        "--output", "-o", default="-", help='Output TEI-XML file or "-" for stdout'
    )

    # Metadata arguments (optional, will prompt if not provided)
    ap.add_argument("--title", help="Title of the work")
    ap.add_argument("--author", help="Original author")
    ap.add_argument(
        "--edition-editor", dest="edition_editor", help="Editor of diplomatic edition"
    )
    ap.add_argument("--translator", help="Translator (for translation editions)")
    ap.add_argument("--resp", help="Your responsibility")
    ap.add_argument("--resp-name", dest="resp_name", help="Your name")
    ap.add_argument("--publisher", help="Publisher")
    ap.add_argument("--pub-date", dest="pub_date", help="Publication date")

    # msIdentifier
    ap.add_argument("--country", help="Holding country")
    ap.add_argument("--region", help="Region")
    ap.add_argument("--settlement", help="Settlement/city")
    ap.add_argument("--district", help="District")
    ap.add_argument("--geogName", help="Geographic name")
    ap.add_argument("--institution", help="Holding institution")
    ap.add_argument("--repository", help="Repository")
    ap.add_argument("--collection", help="Collection")
    ap.add_argument("--idno-old", dest="idno_old", help="Old catalog ID")
    ap.add_argument("--idno-new", dest="idno_new", help="New museum ID")
    ap.add_argument("--idno-siglum", dest="idno_siglum", help="Siglum")

    # Origin
    ap.add_argument("--orig-place", dest="orig_place", help="Original place")
    ap.add_argument(
        "--orig-notBefore", dest="orig_notBefore", help="Origin notBefore date"
    )
    ap.add_argument(
        "--orig-notAfter", dest="orig_notAfter", help="Origin notAfter date"
    )
    ap.add_argument("--orig-label", dest="orig_label", help="Origin date label")

    # Page info
    ap.add_argument("--page-n", dest="page_n", help="Page number/label")
    ap.add_argument(
        "--page-side", dest="page_side", choices=["recto", "verso"], help="Page side"
    )

    args = ap.parse_args()

    # Read PAGE XML
    if args.input == "-":
        data = sys.stdin.read()
        input_file = "stdin"
    else:
        input_file = args.input
        with open(args.input, "r", encoding="utf-8", errors="ignore") as f:
            data = f.read()

    page_tree = ET.ElementTree(ET.fromstring(data))
    page_root = page_tree.getroot()

    # Collect metadata
    meta = collect_metadata(args, input_file)

    # Convert
    tei = convert_page_to_tei(page_root, meta)
    out = prettify(tei)

    # Write TEI
    if args.output == "-":
        sys.stdout.write(out)
    else:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(out)
        print(f"\n✅ Successfully converted to {args.output}")


if __name__ == "__main__":
    main()
