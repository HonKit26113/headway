# Headway — Postmortem

StormHacks 2026. Didn't place in any track. Here's the honest version of what happened.

## What we actually shipped

A transit housing scorer that works end to end, with nothing mocked:

- Real TransLink GTFS data (stops, routes, schedules, calendars) parsed into a scoring model
- Real geocoding, bounded to the region the data actually covers
- A 0-10 score built from four weighted, normalized factors — not a black box
- The real route drawn on the map, including real SkyTrain track geometry (not straight lines)
- A plain-language verdict via Gemini, architected so the slow call never blocks the fast one
- A toggleable, server-computed heatmap with no H3 dependency
- Deployed to a custom domain with SSL, zero billing, backend + frontend as separate Railway services
- Four people, heavy overlap on the same files all night, zero unresolved merge conflicts

Every one of those was a real decision made under constraint, not a corner cut silently. The product is genuinely done, not demo-faked.

## What went well

- **Nothing in the shipped product is fake.** Every score, every route, every stop marker traces back to real data. That's rare for a 24-hour build and we didn't compromise on it even when it cost time (e.g., rejecting H3 instead of faking the heatmap).
- **We kept finding and fixing real bugs via live testing, not just local dev**, right up to the deadline: a heatmap OOM crash traced to `global_land_mask`'s memory footprint, a Gemini quota wall, a geocoding dead-end on stop-clicks, a silently-missing GTFS zip that made SkyTrain routes fall back to straight lines in production without erroring, and a CORS misconfiguration that quietly broke scoring on the custom domain after it had already "worked." Each of these would have shipped broken if we'd stopped testing once something looked done.
- **Collaboration held up under pressure.** Three people editing `MapContainer.jsx` and `routes.py` repeatedly, all night, and every merge resolved cleanly because changes were additive.
- **The sustainability angle was substantiated, not bolted on.** UN SDG 11 showed up with a real scored address (5.9/10, explained honestly) rather than a paragraph with no teeth.

## What probably cost us

Being honest instead of comforting here:

- **A correct, working product isn't automatically a compelling 2-minute demo.** Judging passes are short. A tool that quietly does the right thing (bounded geocoding, honest scores, graceful fallbacks) doesn't *show* as well live as something with a louder visual hook, even if it's less real underneath.
- **We spread across tracks (SDG, Gemini API, Design) instead of building backward from one track's exact rubric.** Being a legitimate fit for a track isn't the same as being the strongest submission against that track's specific judging criteria, and most tracks here had exactly one winner — a very competitive bar regardless of fit.
- **Scheduling friction.** Requesting a later presentation slot for commute reasons may have mattered — not necessarily who judged it, but whether the team was fully present and settled rather than rushed in.
- **Polish bugs were still being found and fixed on the final day** (CORS, SkyTrain geometry). Those were fixed before judging, but a build that's still actively being debugged hours before presenting is a build that hasn't had time to be rehearsed as a *pitch*, only as a product.
- It's also just possible other teams were stronger on the specific axes judged that round. Not every loss has a root cause to extract — sometimes the bar was just higher elsewhere.

## What we'd do differently

- Pick one track early, read its exact rubric, and build backward from it rather than collecting plausible alignment across several.
- Budget real rehearsal time for the live pitch itself, separate from build time — a working product still needs a performance.
- Run the "does this work from a cold start, on the actual production URL, in an incognito window" check *earlier* than the final hours, so debugging doesn't eat into rehearsal time.
- Keep the discipline that worked: real data over mocks, checkpoint posts, additive merges. That part of the process is worth repeating regardless of outcome.

## What we're keeping

The product itself is real and still live. Nothing here is a reason to take it down — it's a reason to aim the next one more deliberately at how it'll be judged, not just whether it works.
