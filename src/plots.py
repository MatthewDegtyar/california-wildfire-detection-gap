"""Generate the figures used in the README and the memo PDF.

Figure-size convention: every rectangular figure is authored at FIG_WIDTH_IN
inches wide so that when LaTeX scales it to \\linewidth on the page, the text
inside scales by the same factor across figures and reads at a consistent
size. The one exception is the calibration plot, which is square and uses a
narrower markdown width.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.config import CA_BBOX, PROCESSED, ROOT

FIG_DIR = ROOT / "figures"
FIG_DIR.mkdir(exist_ok=True)

# All rectangular figures use this authored width. Heights vary by content.
FIG_WIDTH_IN = 10.0
# Tightened global font sizes so on-page text reads at ~9pt after scaling.
mpl.rcParams.update({
    "font.size": 13,
    "axes.titlesize": 14,
    "axes.labelsize": 13,
    "xtick.labelsize": 12,
    "ytick.labelsize": 12,
    "legend.fontsize": 12,
    "figure.titlesize": 15,
})


def fig_hit_rate_by_size():
    df = pd.read_parquet(PROCESSED / "fpafod_with_firms_match_v1.parquet")
    bins = [0, 0.25, 1, 10, 100, 300, 1000, 10_000, 100_000, 1_500_000]
    labels = ["<0.25", "0.25-1", "1-10", "10-100", "100-300", "300-1k", "1k-10k", "10k-100k", "100k+"]
    df = df.assign(sb=pd.cut(df["FIRE_SIZE"], bins=bins, labels=labels, include_lowest=True, right=False))
    g = df.groupby("sb", observed=True).agg(n=("FOD_ID", "size"), hit=("firms_hit", "sum"))
    g["rate"] = g["hit"] / g["n"]

    fig, ax = plt.subplots(figsize=(FIG_WIDTH_IN, 4.5))
    bars = ax.bar(range(len(g)), g["rate"], color="#cc3322", edgecolor="black")
    for i, (rate, n) in enumerate(zip(g["rate"], g["n"])):
        ax.text(i, rate + 0.02, f"{rate*100:.0f}%", ha="center", fontsize=9)
        ax.text(i, -0.04, f"n={n}", ha="center", fontsize=8, color="dimgray")
    ax.set_xticks(range(len(g)))
    ax.set_xticklabels(g.index, rotation=20, ha="right")
    ax.set_xlabel("Fire size at containment (acres)")
    ax.set_ylim(-0.08, 1.05)
    ax.set_ylabel("FIRMS hit rate")
    ax.set_title("FIRMS detection vs fire size — California, Jun–Nov 2020\n(FPA-FOD ground truth, n=7,500)")
    ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout()
    out = FIG_DIR / "hit_rate_by_size.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"wrote {out}")


def fig_sensitivity():
    s = pd.read_parquet(PROCESSED / "sensitivity_v1.parquet")
    fig, axes = plt.subplots(1, 2, figsize=(FIG_WIDTH_IN, 3.9), sharey=True)
    for ax, col, title in zip(axes, ["small_lt10", "big_ge1k"],
                              ["Small fires (<10 acres)", "Large fires (≥1k acres)"]):
        for r, group in s.groupby("radius_km"):
            g = group.copy()
            g["pp"] = g["pre_days"].astype(str) + "/" + g["post_days_no_cont"].astype(str)
            ax.plot(g["pp"], g[col], "-o", label=f"{r:.1f} km radius")
        ax.set_title(title)
        ax.set_xlabel("pre_days / post_days_no_cont")
        ax.set_ylabel("hit rate")
        ax.grid(True, axis="y", alpha=0.3)
        ax.set_ylim(0, 1)
        ax.legend(loc="best", fontsize=8)
    fig.suptitle("Sensitivity of hit-rate estimates to match-envelope settings")
    plt.tight_layout()
    out = FIG_DIR / "sensitivity.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"wrote {out}")


def fig_metrics_summary():
    base = pd.read_parquet(PROCESSED / "baseline_metrics.parquet")
    mod = pd.read_parquet(PROCESSED / "model_metrics.parquet")
    all_metrics = pd.concat([base, mod], ignore_index=True)
    keep = ["constant_no", "base_rate", "size_class", "size_class_x_lat",
            "logreg_calibrated", "gbm_calibrated"]
    all_metrics = all_metrics.set_index("model").loc[keep].reset_index()

    fig, axes = plt.subplots(1, 2, figsize=(FIG_WIDTH_IN, 4.0))
    colors = ["#999999"] * 4 + ["#3377cc", "#cc3322"]

    axes[0].barh(all_metrics["model"], all_metrics["brier"], color=colors)
    axes[0].invert_yaxis()
    axes[0].set_xlabel("Brier score (lower is better)")
    axes[0].set_title("Brier")
    brier_max = float(all_metrics["brier"].max())
    axes[0].set_xlim(0, brier_max * 1.25)
    for i, v in enumerate(all_metrics["brier"]):
        axes[0].text(v + brier_max * 0.015, i, f"{v:.4f}", va="center", fontsize=9)

    axes[1].barh(all_metrics["model"], all_metrics["auc"], color=colors)
    axes[1].invert_yaxis()
    axes[1].set_xlabel("ROC AUC (higher is better)")
    axes[1].set_xlim(0.5, 0.95)
    axes[1].set_title("AUC")
    for i, v in enumerate(all_metrics["auc"]):
        axes[1].text(v + 0.005, i, f"{v:.3f}", va="center", fontsize=9)

    fig.suptitle("Baselines vs calibrated models — 5-fold OOF, California 2020")
    plt.tight_layout()
    out = FIG_DIR / "metrics_summary.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"wrote {out}")


def fig_calibration():
    rel = pd.read_parquet(PROCESSED / "model_reliability.parquet")
    fig, ax = plt.subplots(figsize=(7.0, 7.0))
    ax.plot([0, 1], [0, 1], "k--", lw=1, alpha=0.5, label="Perfect calibration")
    series = [
        ("logreg_calibrated",         "logreg",                    "#3377cc"),
        ("gbm_calibrated",            "GBM v1",                    "#cc3322"),
        ("gbm_v2_with_elevation",     "GBM v2 (+ elevation)",      "#cc7733"),
        ("gbm_v3_elev_terrain_fuel",  "GBM v3 (+ terrain + fuel)", "#669944"),
    ]
    for name, label, color in series:
        sub = rel[rel["model"] == name].sort_values("mean_pred")
        if sub.empty:
            continue
        ax.plot(sub["mean_pred"], sub["mean_actual"], "-o",
                label=label, color=color, markersize=5, linewidth=1.4)
    ax.set_xlabel("Mean predicted probability")
    ax.set_ylabel("Mean observed FIRMS hit rate")
    ax.set_title("Reliability diagram (10 bins, OOF predictions)")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.legend(loc="lower right", fontsize=10)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    out = FIG_DIR / "calibration.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"wrote {out}")


def fig_gap_surface():
    g = pd.read_parquet(PROCESSED / "gap_surface.parquet")
    fpa = pd.read_parquet(PROCESSED / "fpafod_with_firms_match_v1.parquet")

    fig, axes = plt.subplots(1, 3, figsize=(FIG_WIDTH_IN, 3.7), sharey=True)
    w, s, e, n = CA_BBOX
    for ax, name in zip(axes, ["1ac_peakseason_morning", "1ac_peakseason_afternoon",
                               "100ac_peakseason_morning"]):
        sub = g[g["scenario"] == name]
        lats = np.sort(sub["LATITUDE"].unique())
        lons = np.sort(sub["LONGITUDE"].unique())
        grid = sub.pivot(index="LATITUDE", columns="LONGITUDE", values="marginal_aerial_value").values

        im = ax.imshow(grid, origin="lower", extent=[lons.min(), lons.max(), lats.min(), lats.max()],
                       vmin=0, vmax=1, cmap="magma", aspect="equal")
        ax.set_xlim(w, e); ax.set_ylim(s, n)
        ax.set_title(name.replace("_", " "))
        ax.set_xlabel("Longitude");
        if ax is axes[0]:
            ax.set_ylabel("Latitude")

    cbar = fig.colorbar(im, ax=axes.ravel().tolist(), shrink=0.85,
                        label="Marginal aerial value  (= 1 - P(FIRMS detects))")
    fig.suptitle("Where do drones add the most marginal detection value?  (California)")
    out = FIG_DIR / "gap_surface.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {out}")


def fig_miss_map():
    df = pd.read_parquet(PROCESSED / "fpafod_with_firms_match_v1.parquet")
    w, s, e, n = CA_BBOX
    fig, axes = plt.subplots(1, 2, figsize=(FIG_WIDTH_IN, 5.0), sharex=True, sharey=True)

    small = df[df["FIRE_SIZE"] < 10]
    big = df[df["FIRE_SIZE"] >= 100]

    for ax, sub, title in zip(axes, [small, big],
                              [f"Small fires (<10 ac), n={len(small):,}",
                               f"Medium/large fires (≥100 ac), n={len(big):,}"]):
        miss = sub[~sub["firms_hit"]]
        hit = sub[sub["firms_hit"]]
        ax.scatter(miss["LONGITUDE"], miss["LATITUDE"], s=3, alpha=0.4,
                   color="#cc3322", label=f"Miss ({len(miss):,})")
        ax.scatter(hit["LONGITUDE"], hit["LATITUDE"], s=5, alpha=0.6,
                   color="#3377cc", label=f"Hit ({len(hit):,})")
        ax.set_xlim(w, e); ax.set_ylim(s, n)
        ax.set_title(title)
        ax.set_xlabel("Longitude")
        ax.legend(loc="lower left", fontsize=8)
    axes[0].set_ylabel("Latitude")
    fig.suptitle("FIRMS hits vs misses across California — 2020 fire season")
    plt.tight_layout()
    out = FIG_DIR / "miss_map.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"wrote {out}")


def fig_latency():
    if not (PROCESSED / "perimeter_latency.parquet").exists():
        return
    df = pd.read_parquet(PROCESSED / "perimeter_latency.parquet")
    m = df.dropna(subset=["latency_h"])
    if m.empty:
        return

    fig, axes = plt.subplots(1, 2, figsize=(FIG_WIDTH_IN, 4.4))

    # Histogram with log-spaced x
    axes[0].hist(m["latency_h"].clip(lower=0.1), bins=np.logspace(-1, 3, 30),
                 color="#cc3322", edgecolor="white")
    axes[0].set_xscale("log")
    axes[0].set_xlabel("FIRMS latency (hours, log)")
    axes[0].set_ylabel("Perimeters")
    med = m["latency_h"].median()
    axes[0].axvline(med, color="black", linestyle="--", lw=1, label=f"median = {med:.1f}h")
    axes[0].set_title(f"Distribution  (n={len(m)})")
    axes[0].legend()

    # Boxplot by size bucket
    bins = [0, 100, 1000, 10000, 1_500_000]
    labels = ["10-100", "100-1k", "1k-10k", "10k+"]
    m = m.assign(size_bucket=pd.cut(m["GIS_ACRES"], bins=bins, labels=labels, include_lowest=True, right=False))
    data = [m.loc[m["size_bucket"] == lab, "latency_h"].dropna().values for lab in labels]
    counts = [len(d) for d in data]
    bp = axes[1].boxplot(data, tick_labels=[f"{lab}\nn={n}" for lab, n in zip(labels, counts)],
                         showmeans=True, patch_artist=True)
    for patch in bp["boxes"]:
        patch.set_facecolor("#cc3322")
        patch.set_alpha(0.4)
    axes[1].set_yscale("log")
    axes[1].set_ylabel("FIRMS latency (hours, log)")
    axes[1].set_xlabel("Perimeter size (acres)")
    axes[1].set_title("By perimeter size")
    axes[1].grid(True, axis="y", alpha=0.3)

    fig.suptitle("FIRMS detection latency — hours from reported alarm to first pixel inside perimeter",
                 fontsize=13)
    plt.tight_layout(rect=[0, 0, 1, 0.95])
    out = FIG_DIR / "latency.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"wrote {out}")


def fig_metrics_summary_v2():
    """Bar chart of Brier + AUC per model with 5-fold ±1σ error bars.

    Reads from `model_metrics_with_uncertainty.parquet` so the visible numbers
    match the per-fold mean used in the memo's metrics table — not the pooled
    metric from `model_metrics.parquet`.
    """
    uncert = PROCESSED / "model_metrics_with_uncertainty.parquet"
    if not uncert.exists():
        # Fall back to the old (pooled) presentation if uncertainty parquet missing.
        fig_metrics_summary()
        return
    all_metrics = pd.read_parquet(uncert)
    keep = ["constant_no", "base_rate", "size_class", "size_class_x_lat",
            "logreg_calibrated", "gbm_calibrated", "gbm_v2_with_elevation",
            "gbm_v3_elev_terrain_fuel"]
    keep = [k for k in keep if k in all_metrics["model"].values]
    all_metrics = all_metrics.set_index("model").loc[keep].reset_index()

    fig, axes = plt.subplots(1, 2, figsize=(FIG_WIDTH_IN, 4.6))
    colors = ["#999999"] * 4 + ["#3377cc", "#cc3322", "#cc7733", "#669944"]
    colors = colors[: len(all_metrics)]

    # Brier (lower is better)
    brier_mean = all_metrics["brier_mean"].values
    brier_std = all_metrics["brier_std"].values
    axes[0].barh(all_metrics["model"], brier_mean, xerr=brier_std,
                 color=colors, error_kw=dict(ecolor="black", capsize=3, lw=1.0))
    axes[0].invert_yaxis()
    axes[0].set_xlabel("Brier score (lower is better)")
    axes[0].set_title("Brier")
    brier_xmax = float((brier_mean + brier_std).max()) * 1.30
    axes[0].set_xlim(0, brier_xmax)
    for i, (m, s) in enumerate(zip(brier_mean, brier_std)):
        axes[0].text(m + s + brier_xmax * 0.012, i, f"{m:.4f}", va="center", fontsize=9)

    # AUC (higher is better)
    auc_mean = all_metrics["auc_mean"].values
    auc_std = all_metrics["auc_std"].values
    axes[1].barh(all_metrics["model"], auc_mean, xerr=auc_std,
                 color=colors, error_kw=dict(ecolor="black", capsize=3, lw=1.0))
    axes[1].invert_yaxis()
    axes[1].set_xlabel("ROC AUC (higher is better)")
    axes[1].set_xlim(0.45, 0.98)
    axes[1].set_title("AUC")
    for i, (m, s) in enumerate(zip(auc_mean, auc_std)):
        axes[1].text(m + s + 0.006, i, f"{m:.3f}", va="center", fontsize=9)

    fig.suptitle("Baselines vs calibrated models — 5-fold stratified OOF, California 2020\n"
                 "(bars = mean across folds, whiskers = ±1σ)")
    plt.tight_layout()
    out = FIG_DIR / "metrics_summary.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"wrote {out}")


def fig_gap_surface_v2():
    # Prefer the cause-mix-weighted v3 surface (averages predictions across
    # the 2020 CA cause distribution instead of conditioning on Natural cause).
    if (PROCESSED / "gap_surface_v3_unbiased.parquet").exists():
        src = PROCESSED / "gap_surface_v3_unbiased.parquet"
        title_suffix = "model v3, cause-mix weighted"
    elif (PROCESSED / "gap_surface_v3.parquet").exists():
        src = PROCESSED / "gap_surface_v3.parquet"
        title_suffix = "model v3, conditioned on cause=Natural"
    elif (PROCESSED / "gap_surface_v2.parquet").exists():
        src = PROCESSED / "gap_surface_v2.parquet"
        title_suffix = "model v2, with elevation"
    else:
        fig_gap_surface()
        return
    g = pd.read_parquet(src)

    # Three CA-shaped panels are ~tall, and the right-edge colorbar was eating
    # into the third panel and clipping its label. Move the colorbar to the
    # bottom (horizontal) and let the panels use the full width.
    fig, axes = plt.subplots(1, 3, figsize=(FIG_WIDTH_IN, 6.2), sharey=True)
    w, s, e, n = CA_BBOX
    panel_titles = {
        "1ac_peakseason_morning":   "1 acre — morning ignition",
        "1ac_peakseason_afternoon": "1 acre — afternoon ignition",
        "100ac_peakseason_morning": "100 acres — morning ignition",
    }
    for ax, name in zip(axes, ["1ac_peakseason_morning", "1ac_peakseason_afternoon",
                               "100ac_peakseason_morning"]):
        sub = g[g["scenario"] == name]
        lats = np.sort(sub["LATITUDE"].unique())
        lons = np.sort(sub["LONGITUDE"].unique())
        grid = sub.pivot(index="LATITUDE", columns="LONGITUDE",
                         values="marginal_aerial_value").values
        im = ax.imshow(grid, origin="lower",
                       extent=[lons.min(), lons.max(), lats.min(), lats.max()],
                       vmin=0, vmax=1, cmap="magma", aspect="equal")
        ax.set_xlim(w, e); ax.set_ylim(s, n)
        ax.set_title(panel_titles[name], fontsize=12)
        ax.set_xlabel("Longitude")
        if ax is axes[0]:
            ax.set_ylabel("Latitude")

    fig.suptitle("Predicted marginal aerial value across California\n"
                 f"(peak-season ignition; {title_suffix})", fontsize=14)

    # Reserve a horizontal strip at the bottom for the colorbar; leave enough
    # room beneath it for the colorbar label so it doesn't clip the figure
    # canvas edge.
    fig.subplots_adjust(left=0.06, right=0.98, top=0.88, bottom=0.22, wspace=0.10)
    cbar_ax = fig.add_axes([0.20, 0.11, 0.60, 0.025])  # [left, bottom, width, height]
    cbar = fig.colorbar(im, cax=cbar_ax, orientation="horizontal")
    cbar.set_label("Marginal aerial value  (= 1 − P(FIRMS detects))", fontsize=12, labelpad=6)

    out = FIG_DIR / "gap_surface.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"wrote {out}")


def fig_perimeter_vs_centroid():
    src = PROCESSED / "fpafod_with_firms_match_v2.parquet"
    if not src.exists():
        return
    fpa = pd.read_parquet(src)
    sub = fpa[fpa["INCIDENT"].notna()].copy()
    bins = [0, 10, 100, 1000, 10_000, 1_500_000]
    labels = ["<10", "10-100", "100-1k", "1k-10k", "10k+"]
    sub["sb"] = pd.cut(sub["FIRE_SIZE"], bins=bins, labels=labels, include_lowest=True, right=False)
    g = sub.groupby("sb", observed=True).agg(
        n=("FOD_ID", "size"),
        v1=("firms_hit", "mean"),
        v2=("firms_hit_v2", "mean"),
    )
    fig, ax = plt.subplots(figsize=(FIG_WIDTH_IN, 5.1))
    x = np.arange(len(g))
    w = 0.38
    ax.bar(x - w / 2, g["v1"], width=w, color="#3377cc", label="centroid + 3 km radius (v1)")
    ax.bar(x + w / 2, g["v2"], width=w, color="#cc3322", label='inside burn polygon (v2)')
    ax.set_xticks(x)
    ax.set_xticklabels([f"{lab}\nn={int(n)}" for lab, n in zip(g.index, g["n"])])
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("FIRMS hit rate")
    ax.set_xlabel("Fire size (acres)")
    ax.set_title(f"Apples-to-apples: FIRMS hit rate when we have a real burn perimeter\n"
                 f"(n={len(sub):,} FPA-FOD fires that fall inside a 2020 perimeter)")
    for i, (v1, v2) in enumerate(zip(g["v1"], g["v2"])):
        ax.text(i - w / 2, v1 + 0.02, f"{v1*100:.0f}%", ha="center", fontsize=8)
        ax.text(i + w / 2, v2 + 0.02, f"{v2*100:.0f}%", ha="center", fontsize=8, fontweight="bold")
    ax.legend(loc="upper left")
    ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout()
    out = FIG_DIR / "perimeter_vs_centroid.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"wrote {out}")


def fig_swath():
    src = PROCESSED / "swath_hit_summary.parquet"
    if not src.exists():
        return
    df = pd.read_parquet(src)
    pivot = df.pivot(index="size_bucket", columns="swath_bucket", values="hit_rate")
    pivot = pivot.reindex(["<10", "10-100", "100-1k", "1k-10k", "10k+"])
    pivot = pivot[["nadir", "mid", "edge"]]

    fig, ax = plt.subplots(figsize=(FIG_WIDTH_IN, 5.2))
    x = np.arange(len(pivot))
    w = 0.27
    colors = {"nadir": "#3377cc", "mid": "#9999cc", "edge": "#cc3322"}
    for i, b in enumerate(["nadir", "mid", "edge"]):
        ax.bar(x + (i - 1) * w, pivot[b], width=w, color=colors[b], label=b)
        for j, v in enumerate(pivot[b]):
            if pd.notna(v):
                ax.text(x[j] + (i - 1) * w, v + 0.01, f"{v*100:.0f}%", ha="center", fontsize=7)
    ax.set_xticks(x)
    ax.set_xticklabels(pivot.index)
    ax.set_xlabel("Fire size (acres)")
    ax.set_ylabel("FIRMS hit rate (any pixel in this swath bucket)")
    ax.set_title("Hit rate when restricted to FIRMS pixels by swath geometry\n"
                 "(pixel area, km²: nadir ≤ 0.18, mid 0.18–0.24, edge > 0.24)")
    ax.set_ylim(0, 1.0)
    ax.legend(title="swath bucket")
    ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout()
    out = FIG_DIR / "swath_hit_rate.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"wrote {out}")


def main():
    fig_hit_rate_by_size()
    fig_sensitivity()
    fig_metrics_summary_v2()
    fig_calibration()
    fig_gap_surface_v2()
    fig_miss_map()
    fig_latency()
    fig_perimeter_vs_centroid()
    fig_swath()


if __name__ == "__main__":
    main()
