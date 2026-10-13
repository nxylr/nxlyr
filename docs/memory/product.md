# Product truth — what exists vs. what is planned

Every public claim (site, deck, outreach, prompts) must be traceable to this file.

## Known discrepancies
- The live site on `main` still contains the F10 overclaims (“Sending transcript”, “Updated CRM”, inbound-routing and DPDP claims); F04, F05, F10 and F11 are open. As of 2026-10-13, PRs #29–#31 are closed unmerged; their branches and diffs remain on GitHub, and the work can be reopened.

## Exists today (live demo)
- Public web page with a form; submitting it triggers an outbound AI voice call to the visitor's phone.
- The agent talks about one fictional project (Meridian Heights) using the knowledge base in Supabase.
- Real phone line via Exotel; real-time voice pipeline (Deepgram, GPT-4o, ElevenLabs).

## Built but not wired to anything
- Tools `book_site_visit`, `transfer_to_human`, `end_call` set Redis flags only. No calendar, no CRM, no human is notified.

## Planned (do not claim as existing)
- Persisted bookings and commitments ledger (tables exist; code does not write them yet).
- Transcript storage per call (table exists; not populated by the live agent).
- Human handoff, CRM update, persona classification, DPDP compliance claims, WhatsApp/brochure sending.

## Numbers we may cite (with source)
- HBR 2011 "The Short Life of Online Sales Leads": contacting within 1 hour ≈ 7× more likely to qualify vs 1 hour later (US, all industries — say so).
- Knight Frank India: 348,207 homes sold in 2025 across 8 cities.

## Numbers we may NOT cite
- "₹2 per call", "78% of leads go cold", "$480B / 3.5M units", margins, customer counts — unsupported.
- Estimated voice cost is ~$0.28 per 10-minute call (internal estimate, not a measured figure).
