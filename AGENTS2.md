# AI Agent Orchestration — SmartPay Flow

This is how we actually worked with AI on this project. We split it roughly into two phases: one of us worked mostly with Gemini on the architecture and the underlying math, the other worked mostly with Claude on getting the actual Streamlit app built and running. We weren't strict about it — there was overlap — but that was the general division.

## Phase 1: Architecture & math (mainly Gemini)

The first version Gemini gave us added cost, settlement time, and approval probability directly together to get a score. That's not mathematically valid — you can't add euros to days to a percentage and get a meaningful number. We pushed back on this directly: the fix was a min-max normalization step, scaling everything to a 0–1 range first, with cost and settlement time flipped (since lower is better for those two, but higher is better for approval and reliability).

The first scoring model also just routed every transaction to whichever provider was cheapest, full stop. That ignored something our jury had specifically raised after our pitch — PSPs give volume discounts, so splitting transactions across multiple providers can actually cost more overall, even if one transaction looks cheaper on a secondary provider. We told Gemini this directly didn't match the feedback we got, and asked for a penalty variable subtracted from the score whenever the engine considers routing away from the merchant's primary PSP.

We also had to correct the merchant segmentation more than once. The AI kept defaulting to generic categories like "Webshop" and "SaaS" with made-up weights. We rewrote this to use the actual SME segments and weight reasoning we'd worked out ourselves for the business plan, rather than letting the AI's default categories stand in for our own thinking.

One more thing we explicitly said no to: at one point a credit-card input field got suggested for the demo, to make it feel more "real." We rejected that outright — the whole point of SmartPay Flow is that it's a decision layer, not a payment processor, and adding a card field would have implied we were handling actual payment data, which creates a PCI-DSS compliance problem we deliberately don't want to deal with at this stage. We were strict about keeping the platform scoped to metadata only (amount, region, urgency, business type) and nothing that resembles real payment information.

By the end of this phase we had the logic fully worked out: the normalization approach, the penalty mechanism, the segment weights, and the scope boundary around payment data. That's what we brought into the next phase.

## Phase 2: Building the actual app (mainly Claude)

With the logic already settled, this phase was about turning it into something that actually runs. We gave Claude the requirements directly — normalize with min-max, apply the volume penalty, keep the scoring logic in its own class separate from the UI, no payment data fields — and Claude built the app to that spec in working form, rather than us debugging math errors at this stage. The corrections had already happened in Phase 1; this phase was mostly implementation and then us testing it ourselves locally.

A few specific things we asked for, based on what the jury had raised on the pitch:

- The jury asked how we'd get inputs without the system being fragile or crash-prone. We didn't want a static CSV upload that could fail in unpredictable ways, so we asked for an "API webhook simulator" instead — a button with a short artificial delay that represents fetching live data, making the separation between the data layer and the decision layer explicit, even though it's simulated for the MVP.
- The jury also asked what dynamic routing actually adds over a one-off static calculation. The only honest way to answer that is to show it happening, not describe it. So we asked for an interactive slider that lets you drop a provider's uptime live and watch the recommendation change in real time. That ended up being the most convincing part of the demo, because it's not a claim, it's something you can actually watch happen.
- We didn't want a "black box" result that just states a winner with no explanation. SMEs aren't going to trust a recommendation they can't see the reasoning behind, so we asked for the full score breakdown to be shown — every weight, every normalized score, and the final number — with the winning option visually highlighted.

## Phase 3: Business model logic

A few things were specifically about making this investor-oriented, since that's a requirement of the assignment:

- We wanted more than just "here's the best provider" — we asked for an actual savings calculation, the difference between the worst and best available route, multiplied by monthly transaction volume, so the value is shown in real euros rather than just a ranked list.
- For the no-cure-no-pay question the jury raised, we asked for simple conditional logic: if 15% of the calculated savings is less than our flat €99/month fee, recommend the percentage-based fee instead, and show that comparison directly to the merchant.

## What we're not fully confident about

The 0.05 penalty value for the volume discount is an estimate, not something calculated from real PSP contract data — we don't have access to actual discount tiers, so this is a placeholder that's defensible but not verified. Same goes for the provider data itself (fees, settlement times, approval rates): it's based loosely on public PSP pricing pages, not pulled from anywhere live, and we didn't cross-check every number in detail.

## The most time-consuming part

Surprisingly, none of the above was the hardest part. Getting the app to actually run locally took longer than any of the logic decisions, because of a Python environment mismatch — streamlit was installed under Anaconda's Python, but the terminal kept trying to run the file with a different system Python that didn't have it installed. That's a good example of something AI can write correctly while still not "working" the first time you try it on your own machine.