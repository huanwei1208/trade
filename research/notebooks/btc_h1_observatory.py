# ---
# jupyter:
#   jupytext:
#     formats: ipynb,py:percent
#     text_representation:
#       extension: .py
#       format_name: percent
#   kernelspec:
#     display_name: Python 3
#     language: python
#     name: python3
# ---

# %% [markdown]
# # BTC H1 Observatory — thin reproducible notebook (WP8)
#
# This notebook is intentionally **thin**. It contains research parameters and
# narrative only. All reading, feature, label, and validation logic lives in the
# versioned `trade_py.observatory` package — the notebook never re-implements
# formal metric logic (docs/26 §16.2).
#
# It:
# 1. takes a `SNAPSHOT_ID` parameter (fixes an immutable snapshot),
# 2. imports `observe` from `trade_py.observatory.query.sdk`,
# 3. reads bars + findings + context from the SDK,
# 4. can be re-run from a clean kernel deterministically.
#
# The paired `.ipynb` is committed with cleared outputs. Regenerate the pairing
# with `jupytext --sync btc_h1_observatory.py` if you edit either file.

# %% [markdown]
# ## Parameters
#
# `SNAPSHOT_ID` is the ONLY thing that pins the dataset. Pass the value shown by
# the Web "Open in Lab" panel (it fixes `snapshot_id`, never a moving
# latest/current alias). `DATA_ROOT` defaults to `$TRADE_DATA_ROOT` or `data`.

# %% tags=["parameters"]
SNAPSHOT_ID = None  # e.g. "snapshot_formal_0007" — injected by papermill / edited here
CHANNEL = "formal"  # observe H1 against the formal baseline by default
KNOWLEDGE_AS_OF = None  # None => latest; or an RFC3339 / date string for PIT replay

# %%
import os
from pathlib import Path

DATA_ROOT = Path(os.environ.get("TRADE_DATA_ROOT", "data"))

# Resolve repo root so the package import works from a clean kernel regardless of
# the working directory the notebook was launched from.
_here = Path.cwd()
for _candidate in [_here, *_here.parents]:
    if (_candidate / "trade_py").is_dir():
        import sys

        if str(_candidate) not in sys.path:
            sys.path.insert(0, str(_candidate))
        break

# %% [markdown]
# ## Resolve the immutable snapshot via the shared SDK
#
# Web and Jupyter consume the SAME snapshot resolver + research kernel; the
# notebook does not join parquet paths itself.

# %%
from trade_py.observatory.query.sdk import observe  # noqa: E402

query = observe("crypto.BTC", DATA_ROOT)

# When SNAPSHOT_ID is provided it fixes every identity parameter. Otherwise we
# resolve the requested channel/knowledge cut (useful for exploration only).
handle = query.snapshot(
    channel=CHANNEL,
    knowledge_as_of=KNOWLEDGE_AS_OF,
    snapshot_id=SNAPSHOT_ID,
)

context = handle.context
print("resolved snapshot_id:", handle.snapshot_id)
print("resolved channel   :", context.resolved_channel)
print("market watermark   :", context.market_watermark)
print("quality_state      :", context.quality_state.value)
print("lifecycle_state    :", context.lifecycle_state.value)

# %% [markdown]
# ## Read bars and findings (from the package, not recomputed here)

# %%
bars = handle.bars()
findings = handle.findings()

print(f"rows: {len(bars)}")
if bars:
    first, last = bars[0], bars[-1]
    print("first bar:", first.get("date"), "close:", first.get("close"))
    print("last  bar:", last.get("date"), "close:", last.get("close"))
print("findings summary:", findings)

# %% [markdown]
# ## Optional: load into pandas for exploratory plots
#
# Prices are decimal STRINGS on the wire. Convert to float ONLY for plotting;
# never hash or persist the float form. This cell degrades gracefully if pandas
# is unavailable so the notebook still runs from a clean kernel.

# %%
try:
    import pandas as pd

    frame = pd.DataFrame(bars)
    if not frame.empty and "close" in frame:
        frame["close_float"] = pd.to_numeric(frame["close"], errors="coerce")
    display_cols = [c for c in ["date", "close", "availability_state", "revision_state", "quality_flags"] if c in frame]
    frame_head = frame[display_cols].head() if display_cols else frame.head()
    print(frame_head.to_string(index=False))
except ImportError:
    print("pandas not installed — skipping DataFrame view (SDK read above still works).")

# %% [markdown]
# ## H1 research evidence (read-only)
#
# The notebook reads the current H1 research run through the same read-only
# adapter the Web uses. It NEVER promotes results — formal ResearchRun creation
# is a separate explicit CLI workflow (`trade research btc run ...`).

# %%
from trade_py.observatory.research import adapter as research_adapter  # noqa: E402

hypotheses = research_adapter.hypotheses(DATA_ROOT)
for h in hypotheses:
    print(h["hypothesis_id"], h["hypothesis_version"], "->", h["research_state"])
    print("  ", h["statement"])

# %% [markdown]
# ## Reproducibility note
#
# Re-running this notebook from a clean kernel with the same `SNAPSHOT_ID`
# yields the same `snapshot_id`, bars, and findings because the SDK is read-only
# and the snapshot is immutable. Clear large cell outputs before committing.
