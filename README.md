# SmartPay Flow

Intelligent payment routing for SMEs. A decision-support layer that sits on top of existing payment providers (Stripe, Adyen, Mollie, PayPal, SEPA) and recommends which one to use for a given transaction.

We're not building a payment processor. We're building the layer that decides which processor to use. Built by two of us — one focused more on the underlying logic and architecture, the other on getting the actual Streamlit app working. More detail on that split is in AGENTS.md.

## What it does

You input a transaction amount, your monthly volume, and what kind of business you are (SaaS, webshop, marketplace, digital services). The app scores all available payment providers and tells you which one is best for that specific situation — and explains why.

It also lets you simulate a provider going down, so you can see what happens to the recommendation in real time. That was a direct response to feedback we got on our pitch: someone asked what dynamic routing actually adds compared to just picking a provider once and sticking with it. This is our answer to that.

## Features

- Routing engine based on multi-criteria decision analysis (cost, speed, approval rate, reliability)
- Different priority weights depending on merchant type
- A penalty in the scoring for switching away from your main provider, because PSPs give volume discounts and we don't want to ignore that
- A "stress test" slider that drops a provider's uptime live so you can watch the recommendation change
- A simple ROI calculator at the bottom that shows projected savings and suggests either a flat fee or a percentage-of-savings pricing model

## What's NOT in here

This is an MVP, so a lot is deliberately missing:
- No real API connections to PSPs — the provider data (fees, settlement times, etc.) is made up but based on real published pricing
- No actual payment processing happens anywhere
- No login/authentication
- No compliance stuff (PSD2 etc.) — would be needed if this became a real product

We decided early on that building any of this would be a waste of time before we know if the core idea (the routing logic) actually makes sense. That's basically the whole MVP philosophy from the course.

## How to run it

pip install -r requirements.txt
streamlit run app.py

Opens at http://localhost:8501.

## The math (briefly)

Each provider gets scored using:

S = (weight_cost × cost_score) + (weight_speed × speed_score) + (weight_approval × approval_score) + (weight_reliability × reliability_score) − penalty

All the individual scores are normalized between 0 and 1 first, because you can't directly compare a fee in euros to a settlement time in days. The weights change depending on what kind of business you say you are — e.g. a SaaS business cares much more about approval rate than a marketplace does, because a failed subscription payment is worse for them than for a one-off webshop sale.

The penalty (currently fixed at 0.05) represents losing a volume discount when you route away from your main provider. We picked 0.05 somewhat arbitrarily — in a real version this would come from actual PSP discount tiers, but we didn't have access to real contract data so we estimated.

## Project files

- `app.py` — the whole thing, one file (kept it simple for the MVP stage)
- `requirements.txt` — just streamlit and pandas
- `AGENTS.md` — how we used AI to build this

## Note on the data

All provider numbers are synthetic, loosely based on what's publicly listed on Stripe/Mollie/Adyen's pricing pages. No real transaction or merchant data anywhere in this project.