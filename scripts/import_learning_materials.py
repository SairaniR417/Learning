"""Import the supplied Word/ZIP library as static, sanitized Learning chapters.

Usage: python scripts/import_learning_materials.py --source-dir PATH --imported-on YYYY-MM-DD
Word paragraphs, headings, lists, tables, equations and embedded images are kept.
Source files are read only; archive members are never extracted to source paths.
"""
import argparse
from collections import Counter
import hashlib
from html import escape
from io import BytesIO
import json
from pathlib import Path, PurePosixPath
import re
import posixpath
import xml.etree.ElementTree as ET
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
M = '{http://schemas.openxmlformats.org/officeDocument/2006/math}'
R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
A = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
TEXT_TAGS = {W + 't', W + 'delText', M + 't'}
SOURCE_FILES = [
    'Capital Warfare_ Risk & Position Sizing Battle Plan.docx', 'Candlestick Chart Patterns.docx',
    'Camarilla Pivots.docx', 'Breakouts & Pullbacks.docx', 'Bollinger Bands.docx',
    'Advanced Options Structures.docx', '📘 MODULE 4 — ORDER BLOCKS.docx',
    'drive-download-20261109T171343Z-1-001.zip', 'options-20261109T171143Z-1-001.zip']
# Match a unique portion of each original filename; every supplied document must match once.
CURRICULUM = [
    ('Risk & discipline', [
        ('Capital Warfare', 'Risk & position sizing'), ('The Mind of a Trader', 'The mind of a trader'),
        ('Trade Like a Monk', 'Trading discipline & daily routines'), ('Entry Edge Engineering', 'Entry planning & emotional control')]),
    ('Reading the market', [
        ('Dow Theory', 'Dow theory'), ('THE LINE CHART', 'Reading line charts'),
        ('Trendlines, Supply', 'Trendlines, supply, demand & support / resistance'),
        ('Candlestick Chart', 'Candlestick patterns'), ('The Master Guide', 'Chart patterns'),
        ('The Fibonacci', 'Fibonacci retracements & extensions'), ('Breakouts & Pullbacks', 'Breakouts & pullbacks'),
        ('Gaps-', 'Market gaps'), ('RIP and FLIP', 'Rip & flip')]),
    ('Volume & trading levels', [
        ('The Volume Bible', 'Understanding volume'), ('Volume Profile', 'Volume profile'),
        ('VWAP.docx', 'VWAP'), ('The CPR', 'Central Pivot Range (CPR)'), ('Camarilla Pivots', 'Camarilla pivots')]),
    ('Indicators', [
        ('The RSI.docx', 'Relative Strength Index (RSI)'), ('RSI and divergence', 'RSI divergence'),
        ('The MACD', 'MACD'), ('The ADX', 'Trend strength with ADX'), ('The ATR', 'Volatility & ATR'),
        ('Bollinger Bands', 'Bollinger Bands'), ('Stochastic Oscillator', 'Stochastic oscillator'),
        ('The Parabolic SAR', 'Parabolic SAR')]),
    ('Smart money concepts', [
        ('SMART MONEY CONCEPTS', 'Smart money concepts: foundations'), ('SMC- MODULE 2', 'Liquidity'),
        ('MODULE 3', 'Imbalances & displacement'), ('MODULE 4', 'Order blocks'),
        ('MODULE 6', 'Order block refinement, mitigation & entries')]),
    ('Options foundations', [
        ('DAY 1_', 'Options 1: the basics'), ('DAY 2_', 'Options 2: premium & moneyness'),
        ('DAY 3_', 'Options 3: the Greeks'), ('DAY 4_', 'Options 4: buyer versus seller'),
        ('OPTIONS DAY 5', 'Options 5: option flow & edge mapping'), ('BAAHUBALI', 'Options Greeks in practice'),
        ('The Complete Open Interest', 'Open interest (OI)'), ('Put-Call Ratio', 'Put–call ratio (PCR)')]),
    ('Advanced options', [('Advanced Options Structures', 'Advanced options structures'), ('RATIO SPREAD', 'Ratio spreads')])]


def bounded_read(archive, name, limit=32 * 1024 * 1024):
    item = archive.getinfo(name)
    if item.file_size > limit:
        raise ValueError(f'Archive member exceeds import limit: {name}')
    return archive.read(item)


class WordRenderer:
    def __init__(self, data, output):
        self.archive = ZipFile(BytesIO(data))
        self.output = output
        self.headings, self.text, self.seen, self.images = [], [], [], set()
        self.rels = {}
        if 'word/_rels/document.xml.rels' in self.archive.namelist():
            for rel in ET.fromstring(bounded_read(self.archive, 'word/_rels/document.xml.rels')):
                self.rels[rel.get('Id')] = (rel.get('Target', ''), rel.get('TargetMode'))
        self.styles = {}
        if 'word/styles.xml' in self.archive.namelist():
            for style in ET.fromstring(bounded_read(self.archive, 'word/styles.xml')).findall(W + 'style'):
                name = style.find(W + 'name')
                self.styles[style.get(W + 'styleId')] = name.get(W + 'val', '') if name is not None else ''
        self.numbering, self.counters = {}, {}
        if 'word/numbering.xml' in self.archive.namelist():
            numbering = ET.fromstring(bounded_read(self.archive, 'word/numbering.xml'))
            abstracts = {n.get(W + 'abstractNumId'): n for n in numbering.findall(W + 'abstractNum')}
            for num in numbering.findall(W + 'num'):
                aid = num.find(W + 'abstractNumId')
                if aid is not None and aid.get(W + 'val') in abstracts:
                    self.numbering[num.get(W + 'numId')] = abstracts[aid.get(W + 'val')]

    def children(self, node):
        return ''.join(self.inline(child) for child in node)

    def inline(self, node):
        tag = node.tag
        if tag in TEXT_TAGS:
            value = node.text or ''
            self.seen.append(value)
            return escape(value)
        if tag in {W + 'br', W + 'cr'}:
            return '<br>'
        if tag == W + 'tab':
            return ' &#8195; '
        if tag.endswith('Pr') or tag in {W + 'instrText', W + 'bookmarkStart', W + 'bookmarkEnd'}:
            return ''
        if tag == W + 'r':
            content = self.children(node)
            props = node.find(W + 'rPr')
            if props is not None:
                for name, html_tag in [('b', 'strong'), ('i', 'em'), ('strike', 's'), ('u', 'u')]:
                    item = props.find(W + name)
                    if item is not None and item.get(W + 'val') not in {'0', 'false', 'none'}:
                        content = f'<{html_tag}>{content}</{html_tag}>'
                vertical = props.find(W + 'vertAlign')
                if vertical is not None:
                    html_tag = 'sup' if vertical.get(W + 'val') == 'superscript' else 'sub'
                    content = f'<{html_tag}>{content}</{html_tag}>'
            return content
        if tag == W + 'hyperlink':
            content = self.children(node)
            target, mode = self.rels.get(node.get(R + 'id'), ('', None))
            if re.match(r'^https?://', target, re.I):
                return f'<a href="{escape(target, quote=True)}" target="_blank" rel="noopener noreferrer">{content}</a>'
            return content
        if tag in {M + 'oMath', M + 'oMathPara'}:
            return '<span class="doc-formula">' + self.children(node) + '</span>'
        if tag == M + 'f':
            num, den = node.find(M + 'num'), node.find(M + 'den')
            return '(' + (self.children(num) if num is not None else '') + ') / (' + (self.children(den) if den is not None else '') + ')'
        if tag in {M + 'sSup', M + 'sSub', M + 'sSubSup'}:
            return ''.join(f'<{kind}>{self.children(child)}</{kind}>' if kind else self.inline(child)
                           for child in node for kind in [('sup' if child.tag == M + 'sup' else 'sub' if child.tag == M + 'sub' else '')])
        if tag == M + 'rad':
            return '√(' + self.children(node) + ')'
        if tag == A + 'blip':
            target, mode = self.rels.get(node.get(R + 'embed'), ('', None))
            if mode == 'External' or not target:
                return ''
            member = posixpath.normpath(posixpath.join('word', target))
            if not member.startswith('word/media/'):
                return ''
            data = bounded_read(self.archive, member, 16 * 1024 * 1024)
            suffix = PurePosixPath(member).suffix.lower()
            signatures = {'.png': b'\x89PNG', '.jpg': b'\xff\xd8', '.jpeg': b'\xff\xd8', '.gif': b'GIF8'}
            if suffix not in signatures or not data.startswith(signatures[suffix]):
                raise ValueError('Unsupported embedded image: ' + member)
            filename = hashlib.sha256(data).hexdigest()[:24] + suffix
            (self.output / 'media').mkdir(parents=True, exist_ok=True)
            (self.output / 'media' / filename).write_bytes(data)
            self.images.add(filename)
            return f'<img src="assets/learning/media/{filename}" alt="Illustration from the supplied chapter" loading="lazy">'
        if tag == W + 'tbl':
            return self.table(node)
        if tag == W + 'p':
            return self.paragraph(node)
        return self.children(node)

    def paragraph(self, node):
        content = self.children(node)
        text = ''.join(t.text or '' for t in node.iter() if t.tag in TEXT_TAGS).strip()
        if not content.strip():
            return ''
        self.text.append(text)
        style = node.find('./' + W + 'pPr/' + W + 'pStyle')
        name = style.get(W + 'val', '') if style is not None else ''
        name = self.styles.get(name, name).lower().replace(' ', '')
        match = re.match(r'heading([1-9])', name)
        if match or name in {'title', 'subtitle'}:
            level = min(4, int(match[1]) + 1) if match else 2 if name == 'title' else 3
            anchor = 'section-' + str(len(self.headings) + 1)
            self.headings.append(dict(id=anchor, title=text, level=level))
            return f'<h{level} id="{anchor}">{content}</h{level}>'
        number = node.find('./' + W + 'pPr/' + W + 'numPr')
        if number is not None:
            num_id, ilvl = number.find(W + 'numId'), number.find(W + 'ilvl')
            key = num_id.get(W + 'val', '') if num_id is not None else ''
            level = ilvl.get(W + 'val', '0') if ilvl is not None else '0'
            abstract = self.numbering.get(key)
            config = next((n for n in abstract.findall(W + 'lvl') if n.get(W + 'ilvl') == level), None) if abstract is not None else None
            fmt = config.find(W + 'numFmt') if config is not None else None
            count = self.counters.get((key, level), 0) + 1
            self.counters[(key, level)] = count
            marker = str(count) + '.' if fmt is not None and fmt.get(W + 'val') in {'decimal', 'decimalZero'} else '•'
            return f'<p class="doc-list"><span aria-hidden="true">{marker}</span> {content}</p>'
        return '<p>' + content + '</p>'

    def table(self, node):
        result = ['<div class="doc-table-scroll"><table><tbody>']
        for index, row in enumerate(node.findall(W + 'tr')):
            result.append('<tr>')
            for cell in row.findall(W + 'tc'):
                tag = 'th' if index == 0 else 'td'
                span = cell.find('./' + W + 'tcPr/' + W + 'gridSpan')
                colspan = min(30, max(1, int(span.get(W + 'val', '1')))) if span is not None else 1
                result.append(f'<{tag} colspan="{colspan}">{self.children(cell)}</{tag}>')
            result.append('</tr>')
        result.append('</tbody></table></div>')
        return ''.join(result)

    def render(self):
        document = ET.fromstring(bounded_read(self.archive, 'word/document.xml'))
        body = document.find(W + 'body')
        html = self.children(body)
        expected = [n.text or '' for n in body.iter() if n.tag in TEXT_TAGS]
        if Counter(expected) != Counter(self.seen):
            raise ValueError('Import would omit document text; refusing partial chapter.')
        # Endnotes and footnotes are chapter content, not executable instructions.
        for name, label in [('word/footnotes.xml', 'Footnotes'), ('word/endnotes.xml', 'Endnotes')]:
            if name in self.archive.namelist():
                notes = ET.fromstring(bounded_read(self.archive, name))
                kept = [n for n in notes if int(n.get(W + 'id', '-1')) > 0]
                if kept:
                    html += '<h2>' + label + '</h2>' + ''.join(self.children(n) for n in kept)
        text = '\n\n'.join(self.text)
        return dict(html=html, text=text, headings=self.headings,
                    words=len(text.split()), tables=len(body.findall('.//' + W + 'tbl')),
                    formulas=len(body.findall('.//' + M + 'oMath')), images=len(self.images),
                    verifiedTextNodes=len(expected))


def import_library(source_dir, output, imported_on):
    documents, sources = [], []
    for filename in SOURCE_FILES:
        path = source_dir / filename
        data = path.read_bytes()
        sources.append(dict(name=filename, sha256=hashlib.sha256(data).hexdigest(), bytes=len(data)))
        if filename.endswith('.docx'):
            documents.append(dict(filename=filename, source=filename, data=data))
        else:
            with ZipFile(BytesIO(data)) as archive:
                for item in archive.infolist():
                    if item.is_dir():
                        continue
                    if not item.filename.lower().endswith('.docx'):
                        raise ValueError('Unaccounted archive member: ' + item.filename)
                    documents.append(dict(filename=PurePosixPath(item.filename).name,
                                          source=filename + ' → ' + item.filename,
                                          data=bounded_read(archive, item.filename)))
    output.mkdir(parents=True, exist_ok=True)
    chapters = []
    used = set()
    for category, specs in CURRICULUM:
        for pattern, title in specs:
            candidates = [(i, d) for i, d in enumerate(documents) if pattern.casefold() in d['filename'].casefold()]
            if len(candidates) != 1 or candidates[0][0] in used:
                raise ValueError('Chapter match is missing or ambiguous: ' + pattern)
            index, document = candidates[0]
            used.add(index)
            slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')
            content = WordRenderer(document['data'], output).render()
            (output / (slug + '.json')).write_text(json.dumps(dict(id=slug, **content), ensure_ascii=False), encoding='utf-8')
            (output / (slug + '.txt')).write_text(content['text'], encoding='utf-8')
            chapters.append(dict(id=slug, title=title, category=category, number=len(chapters) + 1,
                                 source=document['source'], filename=document['filename'],
                                 sha256=hashlib.sha256(document['data']).hexdigest(),
                                 minutes=max(1, round(content['words'] / 180)),
                                 headings=content['headings'], searchText=content['text'],
                                 **{key: content[key] for key in ('words', 'tables', 'formulas', 'images', 'verifiedTextNodes')}))
    if len(used) != len(documents):
        raise ValueError('Some documents were not assigned a chapter.')
    manifest = dict(version=1, importedOn=imported_on, sources=sources, chapters=chapters,
                    totalWords=sum(c['words'] for c in chapters), totalDocuments=len(documents))
    (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(dict(chapters=len(chapters), sources=len(sources), words=manifest['totalWords'],
                          tables=sum(c['tables'] for c in chapters), formulas=sum(c['formulas'] for c in chapters),
                          images=sum(c['images'] for c in chapters), allTextVerified=True)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'frontend/public/assets/learning')
    parser.add_argument('--imported-on', required=True)
    args = parser.parse_args()
    import_library(args.source_dir, args.output, args.imported_on)
