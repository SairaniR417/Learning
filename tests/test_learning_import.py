"""The supplied library stays complete, linked and inert when rendered in Learning."""
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from scripts.import_learning_materials import WordRenderer, W, M

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'frontend/public/assets/learning'


def docx(body, relationships=''):
    buffer = BytesIO()
    with ZipFile(buffer, 'w') as archive:
        archive.writestr('word/document.xml', f'<w:document xmlns:w="{W[1:-1]}" xmlns:m="{M[1:-1]}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><w:body>{body}</w:body></w:document>')
        if relationships:
            archive.writestr('word/_rels/document.xml.rels', relationships)
    return buffer.getvalue()


class LearningImportTests(unittest.TestCase):
    def test_headings_tables_and_math_keep_all_source_text(self):
        data = docx('<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Risk chapter</w:t></w:r></w:p>'
                    '<w:p><m:oMath><m:f><m:num><m:r><m:t>Budget</m:t></m:r></m:num><m:den><m:r><m:t>Stop distance</m:t></m:r></m:den></m:f></m:oMath></w:p>'
                    '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Entry</w:t></w:r></w:p></w:tc></w:tr>'
                    '<w:tr><w:tc><w:p><w:r><w:t>₹100</w:t></w:r></w:p></w:tc></w:tr></w:tbl>')
        with tempfile.TemporaryDirectory() as folder:
            result = WordRenderer(data, Path(folder)).render()
        self.assertEqual(result['verifiedTextNodes'], 5)
        self.assertEqual(result['tables'], 1)
        self.assertIn('(Budget) / (Stop distance)', result['html'])
        self.assertIn('<h2 id="section-1">Risk chapter</h2>', result['html'])
        self.assertIn('₹100', result['text'])
        self.assertEqual(result['headings'][0]['title'], 'Risk chapter')

    def test_source_markup_and_active_links_cannot_become_executable_html(self):
        data = docx('<w:p><w:r><w:t>&lt;script&gt;alert(1)&lt;/script&gt;</w:t></w:r>'
                    '<w:hyperlink r:id="unsafe"><w:r><w:t>Source link</w:t></w:r></w:hyperlink></w:p>',
                    '<Relationships><Relationship Id="unsafe" Target="javascript:alert(1)" TargetMode="External"/></Relationships>')
        with tempfile.TemporaryDirectory() as folder:
            result = WordRenderer(data, Path(folder)).render()
        self.assertNotIn('<script>', result['html'])
        self.assertNotIn('javascript:', result['html'])
        self.assertIn('&lt;script&gt;', result['html'])
        self.assertIn('Source link', result['text'])

    def test_real_library_accounts_for_all_nine_sources_and_41_documents(self):
        manifest = json.loads((ASSETS / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(len(manifest['sources']), 9)
        self.assertEqual(len(manifest['chapters']), 41)
        self.assertEqual(len({c['source'] for c in manifest['chapters']}), 41)
        self.assertEqual(sum(c['tables'] for c in manifest['chapters']), 84)
        self.assertEqual(sum(c['images'] for c in manifest['chapters']), 1)
        for chapter in manifest['chapters']:
            content = json.loads((ASSETS / (chapter['id'] + '.json')).read_text(encoding='utf-8'))
            self.assertEqual(content['id'], chapter['id'])
            self.assertGreater(content['verifiedTextNodes'], 0)
            self.assertEqual(content['text'], (ASSETS / (chapter['id'] + '.txt')).read_text(encoding='utf-8'))
            self.assertTrue(content['html'])
            for heading in content['headings']:
                self.assertIn('id="' + heading['id'] + '"', content['html'])


if __name__ == '__main__':
    unittest.main()
