"""Import the player's STS2 Reference XLSX into local, searchable JSON caches.

No Excel runtime or third-party parser is required. The importer reads the XLSX
(Open XML) archive and preserves all non-empty worksheet cell values, formulas
and hyperlinks. The 31 or more embedded images are not interpreted as data.

Usage: python data/import_reference.py "C:/path/Slay the Spire 2 Reference.xlsx"

The generated caches are deliberately gitignored. The workbook's public viewing
link is not a license to redistribute its contents on a public GitHub fork.
"""
from __future__ import annotations

import argparse
import json
import posixpath
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile

MAIN = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
P = 'http://schemas.openxmlformats.org/package/2006/relationships'
CELL_RE = re.compile(r'([A-Z]+)(\d+)$')


def _relmap(z: ZipFile, name: str) -> dict[str, dict]:
    try:
        node = ET.fromstring(z.read(name))
    except KeyError:
        return {}
    return {n.get('Id'): n.attrib for n in node if n.get('Id')}


def _resolve_target(base: str, target: str) -> str:
    # OOX relationships are relative to the parent part.
    return posixpath.normpath(posixpath.join(posixpath.dirname(base), target.lstrip('/'))) if not target.startswith('/') else target.lstrip('/')


def _shared_strings(z: ZipFile) -> list[str]:
    try:
        root = ET.fromstring(z.read('xl/sharedStrings.xml'))
    except KeyError:
        return []
    return [''.join((t.text or '') for t in e.iter(f'{{{MAIN}}}t')) for e in root]


def _cell_value(cell, strings: list[str]):
    kind = cell.get('t', '')
    v = cell.find(f'{{{MAIN}}}v')
    inline = cell.find(f'{{{MAIN}}}is')
    formula = cell.find(f'{{{MAIN}}}f')
    raw = v.text if v is not None else None
    if kind == 's' and raw is not None:
        try:
            value = strings[int(raw)]
        except (ValueError, IndexError):
            value = raw
    elif kind == 'inlineStr' and inline is not None:
        value = ''.join(t.text or '' for t in inline.iter(f'{{{MAIN}}}t'))
    elif kind == 'b' and raw is not None:
        value = raw == '1'
    else:
        # Retain numeric cells as their displayed, lossless XML representation.
        value = raw
    # Formula without a cached value must still be represented.
    if value is None and formula is not None:
        value = ''
    if value is None or (isinstance(value, str) and not value.strip() and formula is None):
        return None
    result = {'value': value}
    if formula is not None:
        result['formula'] = formula.text or ''
    if kind == 'e':
        result['error'] = True
    return result


def _sheet_rows(z: ZipFile, part: str, strings: list[str]) -> list[dict]:
    root = ET.fromstring(z.read(part))
    srel = _relmap(z, posixpath.join(posixpath.dirname(part), '_rels', posixpath.basename(part) + '.rels'))
    links = {}
    hl_node = root.find(f'{{{MAIN}}}hyperlinks')
    if hl_node is not None:
        for h in hl_node:
            loc = h.get('ref')
            rel_id = h.get(f'{{{R}}}id')
            if loc and rel_id and rel_id in srel:
                links[loc] = srel[rel_id].get('Target')
            elif loc and h.get('location'):
                links[loc] = '#' + h.get('location')
    out = []
    sheet_data = root.find(f'{{{MAIN}}}sheetData')
    if sheet_data is None:
        return out
    for row in sheet_data:
        cells = {}
        for c in row:
            if c.tag != f'{{{MAIN}}}c':
                continue
            ref = c.get('r', '')
            parsed = _cell_value(c, strings)
            if not parsed and ref not in links:
                continue
            if not parsed:
                parsed = {'value': ''}
            if ref in links:
                parsed['hyperlink'] = links[ref]
            m = CELL_RE.fullmatch(ref)
            if m:
                cells[m.group(1)] = parsed
        if cells:
            out.append({'row': int(row.get('r') or 0), 'cells': cells})
    return out


def read_workbook(path: Path) -> dict:
    with ZipFile(path) as z:
        strings = _shared_strings(z)
        w = ET.fromstring(z.read('xl/workbook.xml'))
        rels = _relmap(z, 'xl/_rels/workbook.xml.rels')
        sheets = {}
        for sh in w.find(f'{{{MAIN}}}sheets'):
            name = sh.get('name')
            rid = sh.get(f'{{{R}}}id')
            if not name or not rid or rid not in rels:
                continue
            target = rels[rid]['Target']
            part = _resolve_target('xl/workbook.xml', target)
            sheets[name] = _sheet_rows(z, part, strings)
        media_count = len([x for x in z.namelist() if x.startswith('xl/media/')])
    preface = sheets.get('Preface', [])
    version = next((str(r['cells']['A']['value']).replace('Current Game Version:', '').strip()
                    for r in preface if str(r['cells'].get('A', {}).get('value', '')).startswith('Current Game Version:')), 'unknown')
    return {'schema': 1, 'game_version': version, 'source_filename': path.name,
            'imported_utc': datetime.now(timezone.utc).isoformat(),
            'embedded_images_not_extracted': media_count, 'sheets': sheets}


def _val(cells: dict, col: str) -> str:
    v = cells.get(col, {}).get('value')
    return str(v).strip() if v is not None else ''


def build_monster_index(book: dict) -> dict:
    """Each monster block begins at a named row with an HP value in col B.

    Subsequent rows are move descriptions/effects. The importer preserves all
    original cell text and the original worksheet row numbers as provenance.
    """
    groups = {'Monsters': 'monster', 'Elites': 'elite', 'Bosses': 'boss'}
    entries = []
    for sh, kind in groups.items():
        rows = book['sheets'].get(sh, [])
        active = None
        for row in rows:
            c = row['cells']
            name = _val(c, 'A')
            hp = _val(c, 'B')
            move = any(_val(c, k) for k in 'CDEFGH')
            # Exclude headers and continuation markers like '(3 segments)'.
            new = bool(name and hp and move and not name.lower().endswith(' name')
                       and not name.startswith('(') and not name.lower().startswith('note:'))
            if new:
                active = {'name': name, 'kind': kind, 'hp': hp,
                          'sheet': sh, 'start_row': row['row'],
                          'moves': [], 'notes': [], 'patterns': [], 'detail_rows': []}
                entries.append(active)
            if not active:
                continue
            # Continuation row ending a block is handled by next named start.
            details = {k: _val(c, k) for k in 'ABCDEFGHIJ' if _val(c, k)}
            if not details:
                continue
            active['detail_rows'].append({'row': row['row'], 'cells': details})
            for col in 'CDEFGH':
                val = details.get(col)
                if val:
                    existing = next((m for m in active['moves'] if m['column'] == col), None)
                    if existing is None:
                        existing = {'column': col, 'name': val, 'details': []}
                        active['moves'].append(existing)
                    else:
                        existing['details'].append(val)
            if details.get('I'):
                active['notes'].append(details['I'])
            if details.get('J'):
                active['patterns'].append(details['J'])
    return {'schema': 1, 'source_version': book['game_version'],
            'imported_utc': book['imported_utc'], 'entries': entries}


def import_reference(source: Path, destination: Path) -> dict:
    book = read_workbook(source)
    monster = build_monster_index(book)
    destination.mkdir(parents=True, exist_ok=True)
    # Preserve the workbook's embedded image data as local assets. These images
    # do not form text move descriptions, and are not sent to Claude.
    media_dir = destination / 'reference_media'
    with ZipFile(source) as archive:
        media = [n for n in archive.namelist() if n.startswith('xl/media/') and not n.endswith('/')]
        if media:
            media_dir.mkdir(parents=True, exist_ok=True)
            for n in media:
                (media_dir / Path(n).name).write_bytes(archive.read(n))
    (destination / 'reference_cache.json').write_text(
        json.dumps(book, ensure_ascii=False, indent=2), encoding='utf-8')
    (destination / 'monster_moves.json').write_text(
        json.dumps(monster, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'version': book['game_version'],
            'sheets': {k: sum(len(r['cells']) for r in v) for k, v in book['sheets'].items()},
            'monsters': sum(e['kind']=='monster' for e in monster['entries']),
            'elites': sum(e['kind']=='elite' for e in monster['entries']),
            'bosses': sum(e['kind']=='boss' for e in monster['entries']),
            'embedded_images': book['embedded_images_not_extracted']}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('workbook', type=Path)
    p.add_argument('--output', type=Path, default=Path(__file__).resolve().parent)
    args = p.parse_args()
    result = import_reference(args.workbook, args.output)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
