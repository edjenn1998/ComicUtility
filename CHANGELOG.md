# Changelog

## 1.1.0

- Fully decode image frames before accepting additions or verified archive saves;
  reject truncated JPEGs without replacing existing output.
- Normalize CMYK and other preview image modes without changing archive originals.
- Render previews off the UI thread, ignore stale results, and retain only one
  large preview plus up to 256 small thumbnails.
- Enforce workspace limits during editing and PDF staging, roll back failed
  additions, reclaim unused files, and honor PDF cancellation at safe steps.
- Keep additions synchronized with the current document; avoid duplicate names
  across separate Add operations.
- Add redo, saved-state-aware undo, preserved multiselection, multiline summaries,
  remembered settings, and updated document names after Save As.
- Preserve untouched XML bytes and retain comments/processing instructions when
  metadata needs rewriting; expose generated metadata in the file list.
- Preflight extraction, preserve folders by default, and roll back new extracted
  files on error/cancellation. Export/copy batch results with full outcome totals.
- Restore tracked AppImage sources; consolidate packaging, pin Python build
  dependencies and AppImage tools, generate current notices including PDFium,
  and fail explicitly on incomplete ABI inspection.
- Add regression tests and automated Ubuntu 22.04 test/build checks.
- Document first-time AppImage launching, executable permissions, the static
  runtime, and a no-FUSE extraction fallback.
