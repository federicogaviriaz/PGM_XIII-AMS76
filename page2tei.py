#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PAGE XML -> TEI P5 converter with interactive metadata prompts.

Features:
- Reads PAGE-XML from a file or stdin and writes TEI P5 to a file or stdout.
- Builds teiHeader with titleStmt, editionStmt, publicationStmt, msDesc/msIdentifier,
  and msDesc/history/origin (origPlace + origDate with notBefore/notAfter).
- Maps PAGE Page/TextRegion/TextLine to TEI facsimile/surface/zone with polygons
  and links text lines via <lb facs="#zone">, keeping one <ab> per line.
- Applies PAGE TextLine @custom inline annotations:
    abbrev{offset;length;expansion} -> <choice><abbr>…</abbr><expan>…</expan></choice>
    sic{offset;length;correction}   -> <choice><sic>…</sic><corr>…</corr></choice>
    num{offset;length;type;value}   -> <num type="…" value="…">…</num>
    textStyle{bold/italic/underline} -> <hi rend="…">…</hi>
  Any unknown custom kind becomes <seg type="kind">…</seg> with attributes echoed as @data-*
- Emits optional msIdentifier subelements when provided: country, region, settlement,
  district, geogName, institution, repository, collection, idno[*].
- Supports optional page-side labeling (recto/verso) and a foliation note.

CLI:
  page2tei.py --input in.xml --output out.xml [--non-interactive flags...]
  Use "-" for stdin/stdout. Without flags, the script will prompt interactively.

Note: Offsets apply to Python string indices (code points); if combining marks cause
grapheme discrepancies, review spans or normalize upstream as needed.
"""

import sys
import re
import argparse
import xml.etree.ElementTree as ET
from xml.dom import minidom
from typing import List, Dict, Any

PAGE_NS = {'pg': 'http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15'}
TEI_NS = 'http://www.tei-c.org/ns/1.0'
XML_NS = 'http://www.w3.org/XML/1998/namespace'
ET.register_namespace('', TEI_NS)

# -------------------------
# Utilities
# -------------------------

def parse_bool(val) -> bool:
    return str(val).strip().lower() in ('1', 'true', 'yes', 'y')

def parse_int(val, default=0) -> int:
    try:
        return int(val)
    except Exception:
        return default

def qn(name: str) -> ET.QName:
    return ET.QName(TEI_NS, name)

def prettify(elem: ET.Element) -> str:
    raw = ET.tostring(elem, encoding='utf-8')
    return minidom.parseString(raw).toprettyxml(indent='  ', encoding='utf-8').decode('utf-8')

# -------------------------
# PAGE custom parsing
# -------------------------

def parse_custom_ops(custom_str: str) -> List[Dict[str, Any]]:
    """
    Parse PAGE @custom like:
      'readingOrder {index:3;} abbrev {offset:9;length:2;expansion:...;} sic {offset:...;length:...;correction:...;}'
    Return list of ops with keys: kind, offset, length, end, plus any additional attributes as strings.
    """
    ops = []
    if not custom_str:
        return ops
    for m in re.finditer(r'(\w+)\s*\{([^}]*)\}', custom_str):
        kind = m.group(1)
        body = m.group(2)
        kv = {}
        for part in re.finditer(r'(\w+)\s*:\s*([^;]+);', body):
            kv[part.group(1)] = part.group(2)
        off = parse_int(kv.get('offset', '0'), 0)
        length = parse_int(kv.get('length', '0'), 0)
        end = off + length
        op = {'kind': kind, 'offset': off, 'length': length, 'end': end}
        for k, v in kv.items():
            if k in ('offset', 'length'):
                continue
            op[k] = v
        if kind == 'textStyle':
            for k in ('bold', 'italic', 'underline'):
                if k in op:
                    op[k] = 'true' if parse_bool(op[k]) else 'false'
        ops.append(op)
    return ops

# -------------------------
# Inline TEI builders
# -------------------------

def slice_text_nodes(text: str, ranges: List[tuple]) -> List[tuple]:
    """
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
    if not s:
        return
    if parent.text is None and len(parent) == 0:
        parent.text = s
    else:
        if len(parent):
            last = list(parent)[-1]
            last.tail = (last.tail or '') + s
        else:
            parent.text = (parent.text or '') + s

def build_styled_nodes(parent: ET.Element, text: str, style_ops: List[Dict[str, Any]]):
    ranges = []
    for op in style_ops:
        rend = []
        if op.get('bold', 'false') == 'true':
            rend.append('bold')
        if op.get('italic', 'false') == 'true':
            rend.append('italic')
        if op.get('underline', 'false') == 'true':
            rend.append('underline')
        if not rend:
            continue
        ranges.append((op['offset'], op['end'], ' '.join(rend)))
    if not ranges:
        append_text(parent, text)
        return
    for s, e, seg_text, labels in slice_text_nodes(text, ranges):
        if not labels:
            append_text(parent, seg_text)
        else:
            hi = ET.Element(qn('hi'))
            hi.set('rend', ' '.join(sorted(labels)))
            hi.text = seg_text
            parent.append(hi)

def build_choice_with_styles(kind: str, witness_text: str, alt_text: str,
                             inner_style_ops: List[Dict[str, Any]], global_offset: int) -> ET.Element:
    choice = ET.Element(qn('choice'))
    a_tag = 'abbr' if kind == 'abbrev' else 'sic'
    a = ET.SubElement(choice, qn(a_tag))
    # adjust local styles
    adj_styles = []
    for op in inner_style_ops:
        if op['offset'] >= global_offset and op['end'] <= global_offset + len(witness_text):
            cp = dict(op)
            cp['offset'] = cp['offset'] - global_offset
            cp['end'] = cp['end'] - global_offset
            adj_styles.append(cp)
    build_styled_nodes(a, witness_text, adj_styles)
    b_tag = 'expan' if kind == 'abbrev' else 'corr'
    b = ET.SubElement(choice, qn(b_tag))
    b.text = alt_text or ''
    return choice

def build_num_with_styles(witness_text: str, num_op: Dict[str, Any],
                          inner_style_ops: List[Dict[str, Any]], global_offset: int) -> ET.Element:
    num = ET.Element(qn('num'))
    if 'type' in num_op:
        num.set('type', num_op['type'])
    if 'value' in num_op:
        num.set('value', num_op['value'])
    adj_styles = []
    for op in inner_style_ops:
        if op['offset'] >= global_offset and op['end'] <= global_offset + len(witness_text):
            cp = dict(op)
            cp['offset'] = cp['offset'] - global_offset
            cp['end'] = cp['end'] - global_offset
            adj_styles.append(cp)
    build_styled_nodes(num, witness_text, adj_styles)
    return num

def build_fallback_seg(witness_text: str, op: Dict[str, Any],
                       inner_style_ops: List[Dict[str, Any]], global_offset: int) -> ET.Element:
    seg = ET.Element(qn('seg'))
    seg.set('type', op.get('kind', 'custom'))
    # echo unknown attributes as data-*
    for k, v in op.items():
        if k in ('kind', 'offset', 'length', 'end'):
            continue
        seg.set(f'data-{k}', v)
    # styles relative to this span
    adj_styles = []
    for s in inner_style_ops:
        if s['offset'] >= global_offset and s['end'] <= global_offset + len(witness_text):
            cp = dict(s)
            cp['offset'] = cp['offset'] - global_offset
            cp['end'] = cp['end'] - global_offset
            adj_styles.append(cp)
    build_styled_nodes(seg, witness_text, adj_styles)
    return seg

def build_inline_nodes_for_line(text: str, ops: List[Dict[str, Any]]) -> List[Any]:
    # Separate ops
    choice_ops = [o for o in ops if o['kind'] in ('abbrev', 'sic') and o['length'] > 0]
    num_ops = [o for o in ops if o['kind'] == 'num' and o['length'] > 0]
    style_ops = [o for o in ops if o['kind'] == 'textStyle' and o['length'] > 0]
    other_ops = [o for o in ops if o['kind'] not in ('abbrev', 'sic', 'num', 'textStyle') and o['length'] > 0]

    # Primary wrapper ops in document order (start asc, end desc)
    wrappers = sorted(choice_ops + num_ops + other_ops, key=lambda x: (x['offset'], -x['end']))

    nodes: List[Any] = []
    cursor = 0
    for w in wrappers:
        start, end = w['offset'], w['end']
        if start < cursor:
            # Overlap already consumed; skip to keep a valid tree
            continue
        pre = text[cursor:start]
        if pre:
            tmp = ET.Element('tmp')
            # styles entirely within [cursor, start]
            pre_styles = [s for s in style_ops if cursor <= s['offset'] and s['end'] <= start]
            build_styled_nodes(tmp, pre, pre_styles)
            if tmp.text:
                nodes.append(tmp.text)
            for ch in list(tmp):
                nodes.append(ch)
                if ch.tail:
                    nodes.append(ch.tail)
                    ch.tail = None
        witness = text[start:end]
        inner_styles = [s for s in style_ops if start <= s['offset'] and s['end'] <= end]
        if w['kind'] in ('abbrev', 'sic'):
            alt = w.get('expansion') if w['kind'] == 'abbrev' else w.get('correction')
            el = build_choice_with_styles(w['kind'], witness, alt or '', inner_styles, start)
        elif w['kind'] == 'num':
            el = build_num_with_styles(witness, w, inner_styles, start)
        else:
            el = build_fallback_seg(witness, w, inner_styles, start)
        nodes.append(el)
        cursor = end

    # Tail after last wrapper
    if cursor < len(text):
        tail = text[cursor:]
        tmp = ET.Element('tmp')
        tail_styles = [s for s in style_ops if cursor <= s['offset'] and s['end'] <= len(text)]
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
# Metadata prompts
# -------------------------

def prompt_or_flag(ns: Dict[str, Any], key: str, prompt_text: str, default: str = '') -> str:
    if ns.get(key) is not None:
        return ns.get(key)
    try:
        return input(f'{prompt_text} [{default}]: ').strip() or default
    except EOFError:
        return default

def collect_metadata(args: argparse.Namespace) -> Dict[str, Any]:
    ns = vars(args).copy()
    meta = {}
    # Title and roles
    meta['title'] = prompt_or_flag(ns, 'title', 'Title', 'PGM XIII — Diplomatic transcription (from Transkribus PAGE)')
    meta['author'] = prompt_or_flag(ns, 'author', 'Author (work)', 'Anonymous')
    meta['edition_editor'] = prompt_or_flag(ns, 'edition_editor', 'Editor of diplomatic edition', 'Rober W. Daniel')
    meta['resp'] = prompt_or_flag(ns, 'resp', 'Your responsibility', 'digital edition preparation and TEI encoding')
    meta['resp_name'] = prompt_or_flag(ns, 'resp_name', 'Your name', 'Federico Gaviria Zambrano')
    meta['publisher'] = prompt_or_flag(ns, 'publisher', 'Publisher', 'Springer Fachmedien Wiesbaden GMBH')
    meta['pub_date'] = prompt_or_flag(ns, 'pub_date', 'Publication date (year)', '1991')

    # msIdentifier fields
    meta['country'] = prompt_or_flag(ns, 'country', 'Current holding country', 'Netherlands')
    meta['region'] = prompt_or_flag(ns, 'region', 'Current region', '')
    meta['settlement'] = prompt_or_flag(ns, 'settlement', 'Current settlement (city)', '')
    meta['district'] = prompt_or_flag(ns, 'district', 'Current district', '')
    meta['geogName'] = prompt_or_flag(ns, 'geogName', 'Geographic name (if used)', '')
    meta['institution'] = prompt_or_flag(ns, 'institution', 'Holding institution', '')
    meta['repository'] = prompt_or_flag(ns, 'repository', 'Repository', '')
    meta['collection'] = prompt_or_flag(ns, 'collection', 'Collection', 'PGM')
    meta['idno_old'] = prompt_or_flag(ns, 'idno_old', 'idno (old catalog, type=oldCatalog)', 'J395')
    meta['idno_new'] = prompt_or_flag(ns, 'idno_new', 'idno (new museum, type=museumNew)', 'AMS76')
    meta['idno_siglum'] = prompt_or_flag(ns, 'idno_siglum', 'idno (siglum, type=siglum)', 'PGM XIII')

    # Origin: always ask date range and place
    meta['orig_place'] = prompt_or_flag(ns, 'orig_place', 'Original place (e.g., Egypt)', 'Egypt')
    meta['orig_notBefore'] = prompt_or_flag(ns, 'orig_notBefore', 'Origin notBefore (e.g., -0100 for 100 BCE)', '-0100')
    meta['orig_notAfter'] = prompt_or_flag(ns, 'orig_notAfter', 'Origin notAfter (e.g., 0400 for 400 CE)', '0400')
    meta['orig_label'] = prompt_or_flag(ns, 'orig_label', 'Origin date label', '1st c. BCE–4th c. CE')

    # Page info
    meta['page_n'] = prompt_or_flag(ns, 'page_n', 'Current collection page number/label (e.g., 1r)', '')
    meta['page_side'] = prompt_or_flag(ns, 'page_side', 'Side (recto/verso)', '')

    return meta

# -------------------------
# TEI header builders
# -------------------------

def build_header(meta: Dict[str, Any]) -> ET.Element:
    teiHeader = ET.Element(qn('teiHeader'))
    fileDesc = ET.SubElement(teiHeader, qn('fileDesc'))

    titleStmt = ET.SubElement(fileDesc, qn('titleStmt'))
    ET.SubElement(titleStmt, qn('title')).text = meta['title']
    ET.SubElement(titleStmt, qn('author')).text = meta['author']
    ET.SubElement(titleStmt, qn('editor')).text = meta['edition_editor']
    rs = ET.SubElement(titleStmt, qn('respStmt'))
    ET.SubElement(rs, qn('resp')).text = meta['resp']
    ET.SubElement(rs, qn('name')).text = meta['resp_name']

    editionStmt = ET.SubElement(fileDesc, qn('editionStmt'))
    ET.SubElement(editionStmt, qn('edition')).text = 'Diplomatic edition'
    ed_rs = ET.SubElement(editionStmt, qn('respStmt'))
    ET.SubElement(ed_rs, qn('resp')).text = 'editor of diplomatic edition'
    ET.SubElement(ed_rs, qn('name')).text = meta['edition_editor']

    publicationStmt = ET.SubElement(fileDesc, qn('publicationStmt'))
    if meta.get('publisher'):
        ET.SubElement(publicationStmt, qn('publisher')).text = meta['publisher']
    if meta.get('pub_date'):
        ET.SubElement(publicationStmt, qn('date')).text = meta['pub_date']
    ET.SubElement(publicationStmt, qn('p')).text = 'Unpublished digital derivation for research and display.'

    sourceDesc = ET.SubElement(fileDesc, qn('sourceDesc'))
    msDesc = ET.SubElement(sourceDesc, qn('msDesc'))
    msIdentifier = ET.SubElement(msDesc, qn('msIdentifier'))

    # msIdentifier location/holding hierarchy (optional fields are omitted if blank)
    if meta.get('country'):
        ET.SubElement(msIdentifier, qn('country')).text = meta['country']
    if meta.get('region'):
        ET.SubElement(msIdentifier, qn('region')).text = meta['region']
    if meta.get('settlement'):
        ET.SubElement(msIdentifier, qn('settlement')).text = meta['settlement']
    if meta.get('district'):
        ET.SubElement(msIdentifier, qn('district')).text = meta['district']
    if meta.get('geogName'):
        ET.SubElement(msIdentifier, qn('geogName')).text = meta['geogName']
    if meta.get('institution'):
        ET.SubElement(msIdentifier, qn('institution')).text = meta['institution']
    if meta.get('repository'):
        ET.SubElement(msIdentifier, qn('repository')).text = meta['repository']
    if meta.get('collection'):
        ET.SubElement(msIdentifier, qn('collection')).text = meta['collection']
    if meta.get('idno_old'):
        ET.SubElement(msIdentifier, qn('idno'), {'type': 'oldCatalog'}).text = meta['idno_old']
    if meta.get('idno_new'):
        ET.SubElement(msIdentifier, qn('idno'), {'type': 'museumNew'}).text = meta['idno_new']
    if meta.get('idno_siglum'):
        ET.SubElement(msIdentifier, qn('idno'), {'type': 'siglum'}).text = meta['idno_siglum']

    # physDesc/foliation if page_n provided
    if meta.get('page_n'):
        physDesc = ET.SubElement(msDesc, qn('physDesc'))
        objectDesc = ET.SubElement(physDesc, qn('objectDesc'))
        supportDesc = ET.SubElement(objectDesc, qn('supportDesc'))
        fol = ET.SubElement(supportDesc, qn('foliation'))
        fol.text = f'Numbered as “{meta["page_n"]}” in the current collection.'

    # History/origin
    history = ET.SubElement(msDesc, qn('history'))
    origin = ET.SubElement(history, qn('origin'))
    if meta.get('orig_place'):
        op = ET.SubElement(origin, qn('origPlace'))
        ET.SubElement(op, qn('placeName')).text = meta['orig_place']
    # Always include origDate with range if provided
    od = ET.SubElement(origin, qn('origDate'))
    if meta.get('orig_notBefore'):
        od.set('notBefore', meta['orig_notBefore'])
    if meta.get('orig_notAfter'):
        od.set('notAfter', meta['orig_notAfter'])
    if meta.get('orig_label'):
        od.text = meta['orig_label']

    # encoding/profile/revision
    encodingDesc = ET.SubElement(teiHeader, qn('encodingDesc'))
    ET.SubElement(encodingDesc, qn('p')).text = ('Converted from PAGE-XML; inline choices for abbreviations and corrections, '
                                                 'semantic numbers, and highlighted styling.')
    profileDesc = ET.SubElement(teiHeader, qn('profileDesc'))
    langUsage = ET.SubElement(profileDesc, qn('langUsage'))
    ET.SubElement(langUsage, qn('language'), ident='grc').text = 'Ancient Greek'
    revisionDesc = ET.SubElement(teiHeader, qn('revisionDesc'))
    ET.SubElement(revisionDesc, qn('change')).text = 'Automated conversion with preservation of PAGE custom annotations.'
    return teiHeader

# -------------------------
# PAGE -> TEI converter
# -------------------------

def convert_page_to_tei(page_root: ET.Element, meta: Dict[str, Any]) -> ET.Element:
    tei = ET.Element(qn('TEI'))
    tei.append(build_header(meta))

    facsimile = ET.SubElement(tei, qn('facsimile'))
    text_el = ET.SubElement(tei, qn('text'))
    body = ET.SubElement(text_el, qn('body'))
    div = ET.SubElement(body, qn('div'), {'type': 'transcription'})
    div.set(ET.QName(XML_NS, 'lang'), 'grc')

    # Iterate pages
    for page_idx, page in enumerate(page_root.findall('pg:Page', PAGE_NS), start=1):
        image_fn = page.get('imageFilename')
        width = page.get('imageWidth')
        height = page.get('imageHeight')

        surface = ET.SubElement(facsimile, qn('surface'), {'n': str(page_idx)})
        surface.set(ET.QName(XML_NS, 'id'), f'p{page_idx}')
        # Optional page-side metadata
        if meta.get('page_side'):
            surface.set('type', meta['page_side'])
        if meta.get('page_n'):
            surface.set('n', meta['page_n'])

        graphic = ET.SubElement(surface, qn('graphic'))
        if image_fn:
            graphic.set('url', image_fn)
        if width:
            graphic.set('width', width)
        if height:
            graphic.set('height', height)

        # Page break in text
        ET.SubElement(div, qn('pb'), {'n': str(page_idx), 'facs': f'#p{page_idx}'})

        # Map any PAGE Region to a zone (including non-text regions)
        for region in page.findall('.//*', PAGE_NS):
            local = region.tag.split('}')[-1]
            if local.endswith('Region'):
                rid = region.get('id') or f'reg_{local}_{page_idx}'
                coords = region.find('pg:Coords', PAGE_NS)
                if coords is not None:
                    z = ET.SubElement(surface, qn('zone'), {'type': local})
                    z.set(ET.QName(XML_NS, 'id'), f'z_{rid}')
                    pts = coords.get('points')
                    if pts:
                        z.set('points', pts)

        # Collect TextLines with reading order, then create line zones and text
        lines = []
        for tregion in page.findall('.//pg:TextRegion', PAGE_NS):
            for tl in tregion.findall('pg:TextLine', PAGE_NS):
                cust = tl.get('custom') or ''
                idx = 999999
                if 'index:' in cust:
                    try:
                        idx = int(cust.split('index:')[1].split(';')[0].strip(' }'))
                    except Exception:
                        pass
                coords_el = tl.find('pg:Coords', PAGE_NS)
                points = coords_el.get('points') if coords_el is not None else None
                text_val = tl.findtext('pg:TextEquiv/pg:Unicode', default='', namespaces=PAGE_NS) or ''
                tl_id = tl.get('id') or f'tl_{len(lines)+1}'
                lines.append((idx, tl_id, points, text_val, cust))

        lines.sort(key=lambda x: (x[0], x[1]))

        for _, tl_id, points, text_val, cust in lines:
            zid = f'z_{tl_id}'
            z = ET.SubElement(surface, qn('zone'), {'type': 'line'})
            z.set(ET.QName(XML_NS, 'id'), zid)
            if points:
                z.set('points', points)

            ET.SubElement(div, qn('lb'), {'facs': f'#{zid}'})
            ab = ET.SubElement(div, qn('ab'))

            ops = parse_custom_ops(cust)
            inline_nodes = build_inline_nodes_for_line(text_val, ops)
            for node in inline_nodes:
                if isinstance(node, str):
                    append_text(ab, node)
                else:
                    ab.append(node)
            if ab.text is None:
                ab.text = text_val

    return tei

# -------------------------
# CLI
# -------------------------

def main():
    ap = argparse.ArgumentParser(description='Convert Transkribus PAGE-XML to TEI P5 with facsimile linkage and inline annotations.')
    ap.add_argument('--input', '-i', default='-', help='Input PAGE-XML file path or "-" for stdin')
    ap.add_argument('--output', '-o', default='-', help='Output TEI-XML file path or "-" for stdout')
    ap.add_argument('--title')
    ap.add_argument('--author')
    ap.add_argument('--edition-editor')
    ap.add_argument('--resp')
    ap.add_argument('--resp-name')
    ap.add_argument('--publisher')
    ap.add_argument('--pub-date')
    # msIdentifier
    ap.add_argument('--country')
    ap.add_argument('--region')
    ap.add_argument('--settlement')
    ap.add_argument('--district')
    ap.add_argument('--geogName')
    ap.add_argument('--institution')
    ap.add_argument('--repository')
    ap.add_argument('--collection')
    ap.add_argument('--idno-old')
    ap.add_argument('--idno-new')
    ap.add_argument('--idno-siglum')
    # Origin
    ap.add_argument('--orig-place')
    ap.add_argument('--orig-notBefore')
    ap.add_argument('--orig-notAfter')
    ap.add_argument('--orig-label')
    # Page info
    ap.add_argument('--page-n')
    ap.add_argument('--page-side', choices=['recto', 'verso'])
    args = ap.parse_args()

    # Read PAGE XML
    if args.input == '-':
        data = sys.stdin.read()
    else:
        with open(args.input, 'r', encoding='utf-8', errors='ignore') as f:
            data = f.read()

    page_tree = ET.ElementTree(ET.fromstring(data))
    page_root = page_tree.getroot()

    # Collect metadata (prompts for missing values)
    meta = collect_metadata(args)

    # Convert
    tei = convert_page_to_tei(page_root, meta)
    out = prettify(tei)

    # Write TEI
    if args.output == '-':
        sys.stdout.write(out)
    else:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(out)

if __name__ == '__main__':
    main()

