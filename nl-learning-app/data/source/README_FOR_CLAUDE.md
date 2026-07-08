# Claude Code Learning Materials Package

This package contains Dutch learning materials prepared for Claude Code.

## Important preservation rule

Do not translate, rewrite or "improve" the source materials unless explicitly requested.
The original files are preserved unchanged in `source_originals/`, `app_data_json/` and `reference_prototype/`.

## Folder structure

```txt
source_originals/        Original PDF files copied unchanged
converted_json/          Raw extracted PDF text as page-by-page JSON
converted_txt/           Raw extracted PDF text as page-by-page TXT
app_data_json/           Existing JSON/TXT/JSONL learning data copied unchanged
reference_prototype/     HTML prototype copied unchanged
MANIFEST.json            File index with sha256 hashes and converted paths
combined_all_pdf_text_raw.json
combined_all_pdf_text_raw.md
```

## How to use in the app

1. Use `app_data_json/dutch_a1_a2_5000_learning_items.json` as the existing app-importable learning item dataset.
2. Use files in `converted_json/` for raw worksheet text by page.
3. Use `source_originals/` whenever you need exact layout, images, worksheets, diagrams, cards or page formatting.
4. Use `MANIFEST.json` to discover every included source and converted file.

## Extraction method

PDF text was extracted with PyMuPDF:

```txt
page.get_text('text', sort=False)
```

No translation was added. No semantic content was intentionally changed. JSON escaping and page wrappers are only technical formatting.

## Next recommended development step

Create a stable import pipeline:

```txt
converted_json/*.raw_text.json
↓
parser by theme / page / worksheet number
↓
normalized lesson objects
↓
app exercises / vocabulary / speaking tasks
```
