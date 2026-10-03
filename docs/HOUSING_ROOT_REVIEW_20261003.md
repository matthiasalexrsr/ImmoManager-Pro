# Wohnungsgeberbestätigung — independent integration review

Backend source `b11f9f9` was integrated as `9b5aadc`; Root registered its actual
router in the product. Frontend integration is being completed in the existing
frontend assistant's separate worktree and is not yet deployed.

## Corrections from actual counterexamples

- Original PDF rows had an extra nested list: full resident names wrapped in
  the 16 mm number column. Two actual cells now use the intended wide name
  column. A 45-person case shrank from 13 pages to 3 readable pages.
- The signature's literal escaped `<br/>` is now trusted static paragraph markup.
- Fact labels have adequate width; displayed dates use German day/month/year.
- Local, pinned, licensed Noto fonts provide real Latin/Greek/Cyrillic glyphs
  where ReportLab Vera previously produced missing-character boxes. Broader
  script coverage and shaping remain explicit renderer work.
- A native SQLite outer-commit barrier proved Memory account management could
  enter after the final rights recheck but before commit. The account fence now
  remains held through actual SQL commit/rollback; SQLite takes its writer
  before the account mutex. The same original regression failed before the
  fix and passed afterwards.
- PostgreSQL housing tests now use actual persistent SQL accounts and their
  management lock carrier, rather than a mocked account reader.
- Existing privacy writer ordering was sound: its stale preview expectation
  was incorrect. It now requires refusal with unchanged tenant data and a new
  preview after the independent writer's actual change.

## Evidence

- Initial composed housing/PG/privacy run: 35 passed, 4 explicit store-variant
  skips (actual PG cases executed); 49.42 s.
- Native commit-fence regression before fix: failed because account management
  acquired the mutex inside the publication commit window.
- After correction, actual SQLite account-fence + two actual PG housing cases:
  3 passed, no skips, 39.23 s.
- Real PDF geometry, name-column placement, all 45 names, repeated headings,
  German dates, signature and embedded Greek/Cyrillic glyphs: 3 passed, 1.82 s.
- Normal and all long-case PDF pages rendered and visually reviewed; font
  change received a fresh rendered review. Issuer facts and signature now
  stay together on the same page instead of orphaning only the signature.
- Composed housing, SQL-account PostgreSQL and PDF suite: 38 passed, 3 explicit
  Memory/SQL-only store-variant skips, 70.66 s; actual PostgreSQL cases executed.

These are package checks, not a full release acceptance. Shared recovery,
frontend browser flows and the final combined release gates remain required.
