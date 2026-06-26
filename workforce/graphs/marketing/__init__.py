"""Marketing / growth fleet — the REVENUE-generating roles.

Per Shay's mandate, growth is the first-class revenue function (QA is quality enablement).
These agents PROPOSE revenue moves as drafts for human review — nothing goes live without a
gate:

  - ``conversion_growth_analyst`` — watches the RevenueCat funnel (customers / paid subs / MRR /
    trial uptake) + paywall reachability and proposes concrete conversion EXPERIMENTS as drafts.
  - ``aso_store_listing_agent``   — store-listing repositioning research + ASO copy drafts
    (reposition the mispositioned "to-do" listing to B2B shift scheduling — a no-app-release lever).
  - ``content_campaign_drafter``  — content + campaign drafts (email/social/blog) for review.

All start ``status: probation`` in propose-only mode (drafts only; outward sends/edits are
human-gated). Declared, VERIFIED product facts live in ``docs/growth/scheduler_positioning.json``
so the agents never invent or over-claim features Scheduler does not ship.
"""
