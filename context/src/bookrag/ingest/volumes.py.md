---
source: src/bookrag/ingest/volumes.py
last_synced: 2026-09-22T20:19:13Z
source_hash: 6908bbfb5160dd913ec844968c3422edd35bbd1a
---

## Purpose
Finds the separately published books stitched into one epub - a bindup, a
"complete collection", a fan-compiled series file - and records them as a map
of chapter spans. The file stays one book; `locate` uses the map to cite
"The Burning Bridge, Chapter Fourteen" instead of "Ranger's Apprentice 1 & 2
Bindup, chapter 48".

## Public Interface
- `Volume` - `title`, `label` (the TOC heading verbatim), `start`, `end`,
  `words`, and `as_metadata()`.
- `VolumePlan` - `volumes`, `chapter_count`, `total_words`, `covered_words`,
  plus `coverage`, `unlabelled_chapters` and `as_metadata()`.
- `detect_volumes(path, chapters, chapter_sources, book_title) -> VolumePlan | None`
- `volume_boundaries(plan) -> frozenset[int]` - indices a merged chapter must
  not run past, for `consolidate_fragments`.
- `remap(plan, groups) -> VolumePlan` - the same volumes in terms of
  consolidated chapters.
- `MIN_VOLUMES`, `MIN_VOLUME_WORDS`, `MIN_TEXT_COVERAGE`.

## Key Decisions
- **This module used to split, and no longer does.** It was `omnibus.py`, and
  it ingested each volume as its own `book_id` re-indexed from zero, on the
  theory that a citation could only be as good as the storage layout. That
  theory was wrong: what a reader needs is a *rendered* location, and
  `locate` renders the same string from a span. The split cost a lot for
  nothing - it **deleted** every chapter outside a volume (on the real
  Ranger's Apprentice bindup, an 8,500-character extract from book 3), it was
  decided once at ingest and undone only by re-ingesting, it needed a
  `--no-split` flag to escape (violating the project's one-ingest-no-options
  rule), and it made a 296 MB source file either duplicated 24 times or
  shared by a back-reference between books. A span in `metadata.json` has
  none of those properties.
- **The detection is unchanged, and so are its measured thresholds.** Three
  guards, each pinned by a real book:

  | book | volumes | overlap | coverage | smallest volume |
  | --- | --- | --- | --- | --- |
  | Ranger's Apprentice | 2 | no | 98.4% | 64,897 words |
  | The Magic Thief | 5 | no | 99.9% | 7,405 words |
  | Reverend Insanity | 24 | no | 100.0% | 73,051 words |
  | Moby Dick | 5 | **yes** | **45.2%** | - |

  Moby Dick is the false positive the guards exist for: Project Gutenberg's
  edition nests five TOC sections that are anchors inside one document, so
  their spans overlap *and* they hold under half the text. It is rejected
  twice over. Eye of the World, The Perfect Run and Atomic Habits have no
  nested sections and never reach the checks.
- **The guards matter less than they did, and stay anyway.** A wrong volume
  is now a wrong word in a citation, where it used to be five books in the
  library. They are cheap and they are measured against real files.
- `MIN_VOLUME_WORDS = 1000` is set by a real volume: "The Magic Thief: A
  Proper Wizard" is a published novella of 7,405 words sitting between three
  full novels, so the floor must stay well under that while still rejecting a
  dedication page.
- **Only depth-0 TOC groups are candidates.** Magic Thief book 5 nests "A
  Guide to People and Places" inside its own section; a recursive scan would
  report six books in a five-book collection and then reject the file for
  overlapping.
- **`_volume_title` requires an ordinal after "Book"/"Volume"/"Part".**
  Matching a bare following word would turn "Book of the New Sun" into "of
  the New Sun". A label that is *only* an ordinal ("Volume 7", the real
  Reverend Insanity shape) is qualified with the file's title, because
  "Volume 7, chapter 13" names no book.
- **`volume_boundaries` covers both edges of a volume, not just the start.**
  A volume's last fragment merging forward into the about-the-author that
  follows it is the same defect as merging across the seam, and it is the
  worse one: `remap` can only keep a group lying wholly inside a volume, so
  that merge would drop the volume's label rather than misplace it.
- **epub only.** `pdf_loader` flattens the outline to level 1, so a nested
  PDF arrives with the nesting already gone. A real gap, not a decision.

## Dependencies
- Internal: `bookrag.ingest.chapter.Chapter`
- External: `ebooklib` (reads the TOC directly - the loader does not keep it)

## Data Contracts
- In: the source path, the loaded chapters, and `chapter_sources[i]` - the
  spine document each chapter came from. The loader splits some spine
  documents at internal headings, so the two lists are not one-to-one and the
  mapping cannot be reconstructed from the epub alone.
- Out: a `VolumePlan`, persisted by `storage.save_book` as
  `metadata.json["volumes"]`: a list of `{"title", "label", "start", "end"}`.
  `words` is not persisted - it is evidence for the decision, not something a
  citation needs.

## Open Questions / TODOs
- PDF omnibuses are undetectable until `pdf_loader` keeps outline depth.
- Detection runs at ingest and is recorded, so a file already in the library
  gains volumes only by re-ingesting. Cheap to fix (the map depends on
  nothing but the source file) and nothing has asked for it.
- Nothing groups the volumes as a series any more. The split used to assign
  `series` automatically; a span map does not, because the chapters are one
  book. Cross-book entity seeding therefore does not fire between the
  volumes of a bindup - it never did within a single ingested book either.
