# AI Agent Orchestration — SmartPay Flow

This is how we actually worked with AI on this project. We split it roughly into two phases: one of us worked mostly with Gemini on the architecture and the underlying math, the other worked mostly with Claude on getting the actual Streamlit app built and running. We weren't strict about it, there was overlap,  but that was the general division.

## Phase 1: Architecture & math (mainly Gemini)

The initial version Gemini generated tried to add cost, settlement time, and approval probability directly together to calculate a score. We immediately pushed back on this, as it’s not mathematically valid to add euros, days, and percentages into a single number. The fix we implemented was a min-max normalization step. This scaled all variables to a 0–1 range first, while flipping the scale for cost and settlement time (since lower is better for those, whereas higher is better for approval and reliability).

Furthermore, the first scoring model blindly routed every transaction to the cheapest provider. This completely ignored a key piece of feedback from our pitch: PSPs offer volume discounts. Splitting transactions across multiple providers can actually increase overall costs, even if an individual transaction seems cheaper elsewhere. We pointed out to Gemini that this didn't align with our business logic, and instructed it to add a penalty variable. This penalty is subtracted from the final score whenever the engine considers routing away from the merchant's primary PSP.

We also had to correct the merchant segmentation more than once. The AI kept defaulting to generic categories like "Webshop" and "SaaS" with made-up weights. We rewrote this to use the actual SME segments and weight reasoning we'd worked out ourselves for the business plan, rather than letting the AI's default categories stand in for our own thinking.

One more thing we explicitly said no to: at one point a credit-card input field got suggested for the demo, to make it feel more "real." We rejected that outright — the whole point of SmartPay Flow is that it's a decision layer, not a payment processor, and adding a card field would have implied we were handling actual payment data, which creates a PCI-DSS compliance problem we deliberately don't want to deal with at this stage. We were strict about keeping the platform scoped to metadata only (amount, region, urgency, business type) and nothing that resembles real payment information.

By the end of this phase we had the logic fully worked out: the normalization approach, the penalty mechanism, the segment weights, and the scope boundary around payment data. That's what we brought into the next phase.

## Phase 2: Building the actual app (mainly Claude)

With the logic already settled, this phase was about turning it into something that actually runs. We gave Claude model OPUS 4.8 the requirements directly — normalize with min-max, apply the volume penalty, keep the scoring logic in its own class separate from the UI, no payment data fields — and Claude built the app to that spec in working form, rather than us debugging math errors at this stage. The corrections had already happened in Phase 1; this phase was mostly implementation and then us testing it ourselves locally.

A few specific things we asked for, based on what the teacher had raised on the pitch:

- During the pitch, the teacher asked how we would obtain inputs without making the system fragile or crash-prone. Since we wanted to avoid a static CSV upload that could easily fail, we prompted Claude to build an "API webhook simulator". This is essentially a button with a short artificial delay that represents fetching live data. It makes the architectural separation between the data layer and the decision layer explicit, even if it is just simulated for the MVP.
- The teacher also asked what dynamic routing actually adds over a one-off static calculation. The only honest way to answer that is to show it happening, not describe it. So we asked for an interactive slider that lets you drop a provider's uptime live and watch the recommendation change in real time. That ended up being the most convincing part of the demo, because it's not a claim, it's something you can actually watch happen.
- We didn't want a "black box" result that just states a winner with no explanation. SMEs aren't going to trust a recommendation they can't see the reasoning behind, so we asked for the full score breakdown to be shown — every weight, every normalized score, and the final number — with the winning option visually highlighted.

## Phase 3: Business model logic

A few things were specifically about making this investor-oriented, since that's a requirement of the assignment:

- We wanted the app to provide more than just a simple "best provider" recommendation. To ensure it was investor-oriented, we asked Claude to build an actual savings calculation. This takes the difference between the worst and best available routes and multiplies it by the monthly transaction volume, showing the tangible value in real euros rather than just outputting a ranked list.
- For the no-cure-no-pay question the feedback raised, we asked for simple conditional logic: if 15% of the calculated savings is less than our flat €99/month fee, recommend the percentage-based fee instead, and show that comparison directly to the merchant.

## What we're not fully confident about

The 0.05 penalty value for the volume discount is an estimate, not something calculated from real PSP contract data — we don't have access to actual discount tiers, so this is a placeholder that's defensible but not verified. Same goes for the provider data itself (fees, settlement times, approval rates): it's based loosely on public PSP pricing pages, not pulled from anywhere live, and we didn't cross-check every number in detail.

## The most time-consuming part

Surprisingly, none of the AI prompting was the hardest part. Getting the app to actually run locally took longer than any of the logic decisions because of a Python environment mismatch. Streamlit was installed under Anaconda's Python, but the terminal kept trying to run the file with a different system Python that didn't have the library installed. It’s a perfect example of how AI can write syntactically correct code that still doesn't "work" the first time you try to deploy it on your own machine.