"""
SmartPay Flow — Dynamic Payment Routing MVP
============================================
Purpose: Validate the routing decision layer for SME payment orchestration.
         This MVP deliberately does NOT implement payment execution —
         a Lean Startup choice to test the core business assumption first.

What this code implements from the business plan:
  - Routing decision engine with MCDA scoring
  - Merchant-specific priority profiles (SaaS, Webshop, Marketplace, Digital Services)
  - Transparent recommendation with full score breakdown
  - Dynamic rerouting when a PSP becomes unreliable
  - ROI quantification and no-cure-no-pay pricing model

What this code does NOT yet implement (Our honest MVP limitations):
  - Live PSP API integrations (synthetic data used instead)
  - Real payment execution or fund movement
  - Merchant authentication / login
  - PSD2 compliance layer (needed before production)
  - Historical transaction analytics dashboard

Feedback concerns addressed directly in code:
  [1] "How do you obtain inputs?"        -> API Webhook Simulator (sidebar)
  [2] "Dynamic vs static value?"         -> Live Stress Test slider
  [3] "Economies of scale discounted?"   -> Volume Penalty in MCDA score
  [4] "No-cure-no-pay hurdle?"           -> ROI Calculator + dynamic pricing
"""

import streamlit as st
import pandas as pd
import time


# ======================================================================
# BLOCK B — THE ROUTING ENGINE
# ======================================================================
#
# This class is the core value-enhancing process of SmartPay Flow.
# It implements Multi-Criteria Decision Analysis (MCDA): a validated
# operations research method for choosing between alternatives scored
# on multiple criteria with different units.
#
# WHY MCDA and not a simple rule like "always pick cheapest"?
# Because the business plan says different merchants have different
# priorities. A SaaS company needs high approval rates. A marketplace
# needs low fees. A webshop needs fast settlement. One rule cannot
# serve all three. MCDA applies different weights for each merchant type.
#
# The complete formula executed by this class:
#
#   S_i = sum_j(W_j * V_norm_ij) - P_scale
#
#   S_i        = Final score for provider i (higher = better)
#   W_j        = Priority weight for criterion j (sums to 1.0)
#   V_norm_ij  = Normalized [0-1] score of provider i on criterion j
#   P_scale    = Volume discount penalty for non-primary PSPs (0.05)

class RoutingEngine:

    def __init__(self, routes_df: pd.DataFrame):
        # Store the provider dataframe. We always work on a copy,
        # never modify the original — defensive programming.
        self.routes = routes_df

    def _normalize(self, series: pd.Series, reverse: bool = False) -> pd.Series:
        """
        Min-max normalization. Converts raw values to a [0, 1] scale.

        THE PROBLEM THIS SOLVES:
        You cannot directly add €0.30 (a fee) to 0.985 (an approval rate)
        or to 2 (settlement days). They have different units and scales.
        You need to convert everything to the same dimensionless scale first.

        After normalization:
          0 = worst available option on this criterion
          1 = best available option on this criterion

        MATH:
          Standard (higher is better):  V_norm = (V - V_min) / (V_max - V_min)
          Reversed (lower is better):   V_norm = 1 - (V - V_min) / (V_max - V_min)

        reverse=True is used for: transaction cost, settlement days
        reverse=False is used for: approval probability, reliability score
        """
        v_min = series.min()
        v_max = series.max()

        # Edge case: all providers are equal on this criterion.
        # Return 0.5 (neutral) so no provider gets an unfair advantage.
        if v_max == v_min:
            return pd.Series([0.5] * len(series), index=series.index)

        norm = (series - v_min) / (v_max - v_min)
        return (1 - norm) if reverse else norm

    def score_routes(
        self,
        weights: dict,
        amount: float,
        monthly_volume: int,
        apply_volume_penalty: bool = True,
    ) -> pd.DataFrame:
        """
        Execute the full MCDA scoring pipeline.
        Called every time the merchant changes any input in the UI.
        Returns a dataframe sorted from best (rank 1) to worst provider.

        Parameters
        ----------
        weights       : Priority weight dict {cost, speed, approval, reliability}
        amount        : Transaction amount in EUR
        monthly_volume: Number of monthly transactions (for ROI projection)
        apply_volume_penalty: Whether to penalise secondary PSPs
        """
        routes = self.routes.copy()

        # --- STEP 1: Calculate actual transaction fee for this amount ------
        #
        # Every PSP has two fee components:
        #   variable_fee: a % of the transaction amount (e.g. 2.9%)
        #   fixed_fee:    a flat fee per transaction     (e.g. €0.30)
        #
        # For a €150 transaction:
        #   Stripe:  0.029 x 150 + 0.30 = €4.65
        #   Mollie:  0.015 x 150 + 0.25 = €2.50
        #   Adyen:   0.026 x 150 + 0.20 = €4.10
        #
        # This difference is what SmartPay Flow makes visible and acts on.

        routes["estimated_fee"] = (
            amount * routes["variable_fee"] + routes["fixed_fee"]
        ).round(4)

        # --- STEP 2: Normalize all criteria to [0, 1] -----------------------
        #
        # reverse=True  -> lower raw value = better = score closer to 1
        # reverse=False -> higher raw value = better = score closer to 1

        routes["cost_score"]       = self._normalize(routes["estimated_fee"],        reverse=True)
        routes["speed_score"]      = self._normalize(routes["settlement_days"],      reverse=True)
        routes["approval_score"]   = self._normalize(routes["approval_probability"], reverse=False)
        routes["reliability_norm"] = self._normalize(routes["reliability_score"],    reverse=False)

        # --- STEP 3: Weighted sum — the MCDA base score ----------------------
        #
        # Formula: base_score = sum_j(W_j * V_norm_ij)
        #
        # Each normalized score is multiplied by how important it is
        # to THIS specific merchant type, then summed.
        #
        # Example for Subscription SaaS (approval weight = 55%):
        #   If Stripe approval_score = 0.75 and Mollie approval_score = 0.95,
        #   Mollie gains 0.55 x (0.95 - 0.75) = +0.11 points from this alone.
        #
        # This is where the business plan logic becomes math.

        routes["base_score"] = (
            weights["cost"]        * routes["cost_score"]      +
            weights["speed"]       * routes["speed_score"]     +
            weights["approval"]    * routes["approval_score"]  +
            weights["reliability"] * routes["reliability_norm"]
        ).round(4)

        # --- STEP 4: Economies of Scale Penalty -------------------------------
        #
        # FEEDBACK CONCERN: "Don't PSP volume discount plans discourage splitting?"
        #
        # Context: PSPs offer volume discounts. A merchant processing 5,000
        # transactions/month with Stripe gets a better rate than one processing
        # 2,000 — because they split the other 3,000 to Adyen.
        #
        # SmartPay Flow models this as a penalty deducted from any secondary
        # provider's score. The engine will only recommend leaving the primary
        # PSP if the operational gain (speed, approval, reliability) is larger
        # than the financial loss from losing the volume discount.
        #
        # P_scale = 0.05 is a calibrated estimate. In production this would
        # be calculated from the merchant's actual volume tier agreement.
        #
        # This is an honest limitation: the current MVP uses a fixed penalty.
        # A future version would fetch the real discount tier via PSP API.

        if apply_volume_penalty:
            P_SCALE = 0.05
            routes["penalty"] = routes["is_primary_psp"].apply(
                lambda is_primary: 0.0 if is_primary else P_SCALE
            )
        else:
            routes["penalty"] = 0.0

        routes["final_score"] = (routes["base_score"] - routes["penalty"]).round(4)

        # Sort descending: best provider at index 0
        return routes.sort_values("final_score", ascending=False).reset_index(drop=True)


# ======================================================================
# BLOCK E — MERCHANT WEIGHT PROFILES
# ======================================================================
#
# These profiles are the direct translation of business plan logic into code.
# Each SME type has different operational priorities. Those priorities
# are expressed as weight vectors that go into the MCDA formula.
#
# Business plan -> code mapping (explicit):
#
#   BP section 3: "A SaaS company may put priority on approval rates
#   because failed recurring payments directly affect recurring revenue."
#   -> Subscription SaaS: approval weight = 0.55 (highest of all profiles)
#
#   BP section 3: "A webshop may care more about settlement speed
#   because faster settlement improves cash flow."
#   -> Webshop: speed weight = 0.40 (highest of all profiles)
#
#   BP section 3: "A marketplace may focus more on minimising costs."
#   -> Marketplace: cost weight = 0.45 (highest of all profiles)
#
# These weights are judgment-based for the MVP.
# A production version would calibrate them from merchant survey data.

SME_PROFILES = {
    "Subscription SaaS": {
        "description": (
            "Failed recurring payments reduce ARR and increase churn. "
            "Approval rate is the dominant criterion."
        ),
        "weights": {
            "cost": 0.15,
            "speed": 0.10,
            "approval": 0.55,
            "reliability": 0.20,
        },
    },
    "Webshop (cross-border)": {
        "description": (
            "Fast settlement improves liquidity. "
            "Cost matters at transaction volume."
        ),
        "weights": {
            "cost": 0.30,
            "speed": 0.40,
            "approval": 0.15,
            "reliability": 0.15,
        },
    },
    "Marketplace": {
        "description": (
            "High transaction volume makes fee minimisation the top priority. "
            "Even €0.01 per transaction = €500/month at 50k transactions."
        ),
        "weights": {
            "cost": 0.45,
            "speed": 0.20,
            "approval": 0.15,
            "reliability": 0.20,
        },
    },
    "Digital Services": {
        "description": (
            "Balanced profile. Mild approval preference for international sales."
        ),
        "weights": {
            "cost": 0.25,
            "speed": 0.25,
            "approval": 0.30,
            "reliability": 0.20,
        },
    },
    "Custom (set your own weights)": {
        "description": "Define your own priority weights using the sliders below.",
        "weights": None,  # Populated dynamically from UI sliders
    },
}


# ======================================================================
# BLOCK F — SYNTHETIC PROVIDER DATA
# ======================================================================
#
# In production: this data is fetched live via PSP API webhooks.
# In the MVP: synthetic data with realistic values based on public PSP pricing.
#
# Why synthetic and not live API?
# Live API integration requires:
#   - Developer accounts with each PSP
#   - API key management and security
#   - Rate limit handling and caching
#   - Contractual access agreements
# This is appropriate for a post-validation production build,
# not for an MVP whose goal is to validate the routing LOGIC.
#
# is_primary_psp = True marks the merchant's existing main provider.
# This flag activates the economies-of-scale penalty in the engine.
# It is set to Stripe here as a default; in production the merchant
# would specify their primary provider during onboarding.

DEFAULT_PROVIDERS = {
    "provider":             ["Stripe",  "Mollie",  "Adyen",   "PayPal",  "SEPA Instant"],
    "variable_fee":         [0.0290,    0.0150,    0.0260,    0.0340,    0.0015        ],
    "fixed_fee":            [0.30,      0.25,      0.20,      0.35,      0.20          ],
    "settlement_days":      [2,         1,         1,         2,         0             ],
    "approval_probability": [0.965,     0.985,     0.975,     0.950,     0.970         ],
    "reliability_score":    [0.990,     0.990,     0.990,     0.960,     0.950         ],
    "is_primary_psp":       [True,      False,     False,     False,     False         ],
}


# ======================================================================
# BLOCK G — PAGE SETUP & SESSION STATE
# ======================================================================

st.set_page_config(
    page_title="SmartPay Flow",
    page_icon="💳",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Session state explanation (important for the presentation):
#
# Streamlit works by re-running the ENTIRE Python script from top to
# bottom every single time a user interacts with the UI — a button
# click, a slider move, a dropdown change.
#
# Without session state, the provider dataframe would reset to DEFAULT
# on every interaction. The stress test slider would be useless because
# changing Adyen's uptime would immediately reset when Streamlit reruns.
#
# st.session_state is a persistent dictionary that survives reruns.
# We store the live provider dataframe here so stress-test edits persist.

if "routes_df" not in st.session_state:
    st.session_state.routes_df = pd.DataFrame(DEFAULT_PROVIDERS)
if "api_synced" not in st.session_state:
    st.session_state.api_synced = False

# --- Header --------------------------------------------------------------
st.title("💳 SmartPay Flow")
st.markdown(
    "**Intelligent payment routing for SMEs** — "
    "transparent decision-support on top of Stripe, Adyen, Mollie and more."
)
st.divider()


# ======================================================================
# BLOCK H — SIDEBAR: API WEBHOOK SIMULATOR
# ======================================================================
#
# FEEDBACK CONCERN [1]: "How do you obtain the inputs?"
#
# Architecture answer: DECOUPLING.
# The data ingestion layer is separated from the routing engine.
# In production, a webhook is triggered periodically to pull:
#   - Current pricing from each PSP's API
#   - Live uptime / reliability metrics
#   - Exchange rates for cross-border transactions
#
# This separation means:
#   - If a PSP API goes down, the routing engine falls back on cache
#   - Pricing updates don't require redeploying the routing logic
#   - The decision layer never crashes due to a data layer problem
#
# The button below simulates what this webhook call looks like.
# time.sleep(1.8) represents realistic API network latency.

st.sidebar.header("⚙️ System Controls")
st.sidebar.subheader("1. Live Data Sync")
st.sidebar.caption(
    "Production: fetches real-time fees, FX rates, and uptime via PSP API webhooks. "
    "MVP: simulates the call with synthetic data."
)

if st.sidebar.button("🔄 Fetch Live Provider Data (API Webhook)"):
    with st.spinner("Connecting to PSP endpoints…"):
        time.sleep(1.8)   # Simulates network roundtrip
    st.session_state.api_synced = True
    st.sidebar.success("✅ Live data synced. All PSP feeds healthy.")

if st.session_state.api_synced:
    st.sidebar.info("Last sync: just now · 5 feeds active")

st.sidebar.divider()


# ======================================================================
# BLOCK I — SIDEBAR: DYNAMIC STRESS TEST
# ======================================================================
#
# FEEDBACK CONCERN [2]: "What does dynamic optimization add beyond static?"
#
# This is answered empirically, not verbally.
#
# A static setup cannot react to unexpected changes. If Stripe goes down,
# a merchant with a static Stripe integration loses the transaction.
# SmartPay Flow monitors reliability in real time and reroutes automatically.
#
# HOW THE LIVE UPDATE WORKS (the key technical line):
#
#   st.session_state.routes_df.loc[mask, "reliability_score"] = new_uptime
#
# This directly overwrites a cell in the live dataframe stored in session state.
# Because Streamlit reruns the script on every slider move, and because the
# RoutingEngine always reads from session state, the recommendation in the
# main panel updates INSTANTLY with every millimeter the slider moves.
# No button press. No page refresh. No manual intervention.
# That is dynamic routing.

st.sidebar.subheader("2. Dynamic Stress Test")
st.sidebar.caption(
    "Drop any provider below 85% uptime to simulate an outage. "
    "Watch the routing recommendation change in real time."
)

target = st.sidebar.selectbox(
    "Simulate outage for provider:",
    st.session_state.routes_df["provider"].tolist(),
)

# Read current uptime from session state to initialise slider correctly
current_uptime = float(
    st.session_state.routes_df.loc[
        st.session_state.routes_df["provider"] == target,
        "reliability_score"
    ].values[0]
)

new_uptime = st.sidebar.slider(
    f"{target} — live uptime",
    min_value=0.0,
    max_value=1.0,
    value=current_uptime,
    step=0.01,
    format="%.2f",
)

# THE KEY LINE: overwrite the live dataframe with the stress-test value
mask = st.session_state.routes_df["provider"] == target
st.session_state.routes_df.loc[mask, "reliability_score"] = new_uptime

if new_uptime < 0.85:
    st.sidebar.warning(
        f"⚠️ {target} is below SLA threshold ({new_uptime:.0%} uptime). "
        "Routing engine is rerouting transactions automatically."
    )

st.sidebar.divider()


# ======================================================================
# BLOCK J — SIDEBAR: ECONOMIES OF SCALE TOGGLE
# ======================================================================
#
# FEEDBACK CONCERN [3]: "Don't PSP volume discount plans discourage splitting?"
#
# This toggle lets you demonstrate the penalty live:
#   Toggle ON  -> secondary PSPs lose 0.05 from their final score
#   Toggle OFF -> all providers scored without penalty
#
# The comparison table visibly changes when you toggle this.
# That visual change is your proof that the code models this trade-off.

st.sidebar.subheader("3. Volume Discount Penalty")
st.sidebar.caption(
    "When ON: secondary PSPs are penalised 0.05 points for "
    "the volume discount that would be lost by splitting transactions."
)

apply_penalty = st.sidebar.toggle(
    "Apply economies-of-scale penalty",
    value=True,
)

# Reset provider data button — useful during demo to restore defaults
st.sidebar.divider()
if st.sidebar.button("↺ Reset all providers to default"):
    st.session_state.routes_df = pd.DataFrame(DEFAULT_PROVIDERS)
    st.session_state.api_synced = False
    st.sidebar.success("Providers reset.")


# ======================================================================
# BLOCK K — MAIN PANEL: TRANSACTION INPUTS
# ======================================================================

st.header("Transaction Context")
col_l, col_r = st.columns(2)

with col_l:
    amount = st.number_input(
        "Transaction amount (€)",
        min_value=1.0,
        max_value=100_000.0,
        value=150.0,
        step=10.0,
        help="Affects the absolute fee calculation. Higher amounts amplify fee differences.",
    )
    monthly_volume = st.number_input(
        "Monthly transaction volume",
        min_value=1,
        max_value=100_000,
        value=500,
        step=50,
        help="Used to project monthly and annual savings in the ROI section.",
    )

with col_r:
    segment = st.selectbox(
        "Merchant profile",
        list(SME_PROFILES.keys()),
        help="Loads the priority weight vector for this merchant type.",
    )
    st.caption(f"ℹ️ {SME_PROFILES[segment]['description']}")

# Custom weights — only shown when merchant selects "Custom"
if segment == "Custom (set your own weights)":
    st.subheader("Set Custom Priority Weights")
    st.caption("All four weights must sum to exactly 1.0.")
    c1, c2, c3, c4 = st.columns(4)
    w_cost        = c1.slider("Cost",        0.0, 1.0, 0.25, 0.05)
    w_speed       = c2.slider("Speed",       0.0, 1.0, 0.25, 0.05)
    w_approval    = c3.slider("Approval",    0.0, 1.0, 0.25, 0.05)
    w_reliability = c4.slider("Reliability", 0.0, 1.0, 0.25, 0.05)
    total = round(w_cost + w_speed + w_approval + w_reliability, 2)
    if abs(total - 1.0) > 0.01:
        st.warning(f"⚠️ Weights sum to {total} — must equal 1.0 for MCDA to work correctly.")
        st.stop()   # Stop execution — don't show broken results
    weights = {
        "cost": w_cost, "speed": w_speed,
        "approval": w_approval, "reliability": w_reliability,
    }
else:
    weights = SME_PROFILES[segment]["weights"]


# ======================================================================
# BLOCK L — ROUTING RESULTS AND EXPLANATION
# ======================================================================
#
# This section runs the engine and displays results.
#
# The explanation panel is the "transparency" feature from the business plan:
# "Many payment systems operate like black boxes... SmartPay Flow aims to
# visualise these trade-offs." (BP section 3)
#
# Showing the weight table + score breakdown is not just cosmetic —
# it is the feature that builds merchant trust and enables automation.
# An SME will not let a system auto-route their payments if they
# don't understand why the recommendation was made.

st.divider()
st.header("Routing Recommendation")

engine  = RoutingEngine(st.session_state.routes_df)
results = engine.score_routes(weights, amount, monthly_volume, apply_penalty)
best    = results.iloc[0]

# --- Winner banner --------------------------------------------------------
st.success(
    f"🏆 **Recommended: {best['provider']}** "
    f"· Score: {best['final_score']:.3f} "
    f"· Fee: €{best['estimated_fee']:.4f} "
    f"· Settles in: {int(best['settlement_days'])} day(s) "
    f"· Approval rate: {best['approval_probability']:.1%}"
)

# --- Full transparency: score breakdown -----------------------------------
with st.expander("📋 Why this provider? — Full scoring breakdown", expanded=True):
    st.markdown(f"""
**{best['provider']}** scored highest for a **{segment}** merchant profile.

The following weights were applied to each normalized criterion:

| Criterion | Weight | {best['provider']} normalized score | Weighted contribution |
|-----------|--------|-------------------------------------|----------------------|
| Transaction cost | {weights['cost']:.0%} | {best['cost_score']:.3f} | {weights['cost'] * best['cost_score']:.3f} |
| Settlement speed | {weights['speed']:.0%} | {best['speed_score']:.3f} | {weights['speed'] * best['speed_score']:.3f} |
| Approval probability | {weights['approval']:.0%} | {best['approval_score']:.3f} | {weights['approval'] * best['approval_score']:.3f} |
| Reliability / uptime | {weights['reliability']:.0%} | {best['reliability_norm']:.3f} | {weights['reliability'] * best['reliability_norm']:.3f} |
| | | **Base score** | **{best['base_score']:.3f}** |
| | | Volume penalty | -{best['penalty']:.3f} |
| | | **Final score** | **{best['final_score']:.3f}** |
    """)

    if best["penalty"] > 0:
        st.info(
            f"A 0.05 volume discount penalty was applied because {best['provider']} "
            "is not your primary PSP. SmartPay Flow still recommends it because "
            "the operational gain exceeds the penalty."
        )

# --- Full provider comparison table ---------------------------------------
st.subheader("All providers ranked")

display_map = {
    "provider":            "Provider",
    "estimated_fee":       "Est. fee (€)",
    "settlement_days":     "Settlement (days)",
    "approval_probability":"Approval rate",
    "reliability_score":   "Uptime",
    "penalty":             "Volume penalty",
    "final_score":         "Final score ↓",
}
display_df = results[list(display_map.keys())].rename(columns=display_map).copy()
display_df["Approval rate"] = display_df["Approval rate"].map("{:.1%}".format)
display_df["Uptime"]        = display_df["Uptime"].map("{:.1%}".format)
display_df["Est. fee (€)"]  = display_df["Est. fee (€)"].map("€{:.4f}".format)

st.dataframe(
    display_df.style.highlight_max(subset=["Final score ↓"], color="#d4f5d4"),
    use_container_width=True,
    hide_index=True,
)

# --- Scenario analysis ------------------------------------------------------
st.subheader("What if your priorities were different?")
st.caption(
    "There is no universally best provider. Rankings shift with merchant priorities. "
    "This proves the routing is adaptive, not hardcoded."
)

sc1, sc2, sc3 = st.columns(3)
scenarios = {
    ("💰 Cost-first",     sc1): {"cost": 0.70, "speed": 0.10, "approval": 0.10, "reliability": 0.10},
    ("⚡ Speed-first",    sc2): {"cost": 0.10, "speed": 0.70, "approval": 0.10, "reliability": 0.10},
    ("✅ Approval-first", sc3): {"cost": 0.10, "speed": 0.10, "approval": 0.70, "reliability": 0.10},
}
for (label, col), w in scenarios.items():
    res = engine.score_routes(w, amount, monthly_volume, apply_penalty)
    col.markdown(f"**{label}**")
    for i, row in res.head(3).iterrows():
        col.markdown(f"{'🥇🥈🥉'[i]} {row['provider']} · {row['final_score']:.3f}")


# ======================================================================
# BLOCK M — ROI CALCULATOR AND PRICING MODEL
# ======================================================================
#
# FEEDBACK CONCERN [4]: "No-cure-no-pay to overcome the adoption hurdle?"
#
# The adoption hurdle for SMEs is real: they won't pay a monthly SaaS fee
# for a tool whose value they can't immediately see.
#
# This section makes the value visible in euros — before the merchant commits.
#
# Calculation logic:
#   - "Without SmartPay Flow": merchant stays on most expensive available route
#   - "With SmartPay Flow":    merchant uses the recommended route
#   - Saving per transaction:  difference between those two fees
#   - Monthly saving:          saving x monthly transaction volume
#   - Annual saving:           monthly saving x 12
#
# Pricing recommendation:
#   - Option A: Flat SaaS fee (€99/month) — predictable, good at high volume
#   - Option B: Performance fee (15% of savings) — no-cure-no-pay
#   - The dashboard automatically recommends whichever is lower for THIS merchant.

st.divider()
st.header("ROI Calculator & Pricing Model")
st.caption(
    "SmartPay Flow quantifies the value it creates in euros, then recommends "
    "the pricing model that is most favourable for this specific merchant."
)

worst_fee     = results["estimated_fee"].max()
best_fee      = best["estimated_fee"]
saving_per_tx = round(worst_fee - best_fee, 4)

monthly_savings = round(saving_per_tx * monthly_volume, 2)
annual_savings  = round(monthly_savings * 12, 2)

# Four headline metrics
m1, m2, m3, m4 = st.columns(4)
m1.metric("Saving per transaction", f"€{saving_per_tx:.4f}")
m2.metric("Monthly saving",         f"€{monthly_savings:,.2f}")
m3.metric("Annual saving",          f"€{annual_savings:,.2f}")
m4.metric("Recommended route",      best["provider"])

# Pricing recommendation
st.subheader("SmartPay Flow pricing recommendation")

FLAT_FEE        = 99.0
PERFORMANCE_PCT = 0.15
performance_fee = round(monthly_savings * PERFORMANCE_PCT, 2)

p1, p2 = st.columns(2)
with p1:
    st.markdown("**Option A — Flat SaaS fee**")
    st.markdown(f"### €{FLAT_FEE:.2f} / month")
    st.caption("Predictable. Best value when monthly savings exceed €660.")

with p2:
    st.markdown("**Option B — No-cure-no-pay (15% of realised savings)**")
    st.markdown(f"### €{performance_fee:,.2f} / month")
    st.caption("Zero financial risk. Best for merchants uncertain about their savings.")

if performance_fee <= FLAT_FEE:
    st.success(
        f"✅ **Recommended for this merchant: Performance fee (€{performance_fee:,.2f}/mo)** — "
        "lower than the flat SaaS rate. Zero upfront risk."
    )
else:
    st.success(
        f"✅ **Recommended for this merchant: Flat SaaS fee (€{FLAT_FEE:.2f}/mo)** — "
        f"better value at this savings volume (performance fee: €{performance_fee:,.2f}/mo)."
    )

# --- Footer ----------------------------------------------------------------
st.divider()
st.caption(
    "SmartPay Flow MVP · RSM Erasmus FinTech & Business Solutions · "
    "Routing engine: Multi-Criteria Decision Analysis (MCDA) · "
    "Provider data: synthetic, based on public PSP pricing · "
    "Built with Streamlit 1.36+ and Python 3.10+"
)