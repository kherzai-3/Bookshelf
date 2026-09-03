---
source: tests/test_storage_series_reading_order.py
last_synced: 2026-09-02T00:00:00Z
source_hash: cbe9f369aa79bb7facd63d0070d96a628c7d43da
---

## Purpose
Covers `storage.series_reading_order`: standalone books return just
themselves; series books return earlier books (by position) then
themselves, in order.
