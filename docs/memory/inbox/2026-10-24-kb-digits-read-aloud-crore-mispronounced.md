# The knowledge base still holds digits that the model reads aloud

- Keys with digits: `pricing.bsp_per_sqft` 12500, `pricing.ifms_lakhs` 3, `pricing.gst_percent` 5, `unit_types` `sizes_sqft` and `price_range_cr`, `amenities.clubhouse_sqft` 45000, `amenities.guest_rooms` 12, `overview.towers` 5, `overview.total_area_acres` 12.5.
- Likely cause of the crore mispronunciation on call 9 of the 014 exit test (UNVERIFIED). The prompt tells the model to speak numbers as words, but it reads them from this JSON.
- Fix: rewrite each as a spoken sentence (like `payment_plan.spoken`). SQL only, no deploy; the founder reviews and runs it in the Supabase SQL Editor, guarded like the 014 `UPDATE`s.
- Source: founder, 014 exit test 2026-10-24, call 9.
