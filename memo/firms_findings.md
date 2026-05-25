---
title: "Where satellite wildfire detection fails, and where drones add the most marginal value"
subtitle: "FIRMS / VIIRS detection-gap analysis, California, Jun--Nov 2020"
author: ""
date: ""
---

# Headline finding

A California wildfire that gets contained under 10 acres has a **\~97% probability of never producing a coincident FIRMS detection**. For a drone product that closes the resulting gap, the conflation below is fine; for a "satellite detection fails" narrative, it is over-claiming and needs unpacking.

| Fire size at containment | n | FIRMS detection rate |
|---|---:|---:|
| **\< 10 acres** (92.5% of all CA fires) | 6,939 | **3.2%** |
| 10--1,000 acres | 472 | 25.2% |
| ≥ 1,000 acres | 89 | 79.8% |

Ground truth: FPA-FOD v6 (Short 2022, RDS-2013-0009.6) restricted to California, June--November 2020 (n = 7,500 fires). Detection product: FIRMS VIIRS VNP14 (Suomi-NPP, archived `_SP` source, 233,261 pixel detections).

**What "miss" actually means here, and what it does not.** The 97% combines two distinct failure modes that this version of the analysis does not separate:

1. *Sensor miss.* VIIRS overpassed the fire while it was burning and the thermal signal was too weak or too brief to fire a pixel.
2. *Temporal sampling miss.* VIIRS did not overpass the fire while it was burning. Suomi-NPP is a single sun-synchronous satellite (one day + one night equator crossing); at California latitudes a given point gets typically 1--2 distinct overpasses per 24 h. A 90-minute grass fire between overpasses produces no detection regardless of sensor sensitivity.

Both fail the same way from a "did the satellite alert us?" standpoint, and a loitering drone closes both. But the framing matters: the headline is *not* "VIIRS sensors are bad at small fires" — it is "satellites do not alert on small CA fires, for some combination of sensor sensitivity and overpass timing." Separating those would require joining per-fire ignition--containment windows to VIIRS overpass timetables, which is in the next-steps queue.

**A second caveat that compounds the first.** Fire size at containment is an *outcome*, and detection is a predictor of that outcome — fires that get detected get suppressed faster and stay smaller. So "small fires get missed" and "missed fires stay small" are partly the same arrow, viewed from two sides. The 97% measurement is still correct; the causal phrasing "FIRMS misses *because* fires are small" is not fully defensible from this data alone.

![Hit rate by NWCG fire-size class. Bars are the share of FPA-FOD records in each bucket for which any FIRMS pixel fell within 3 km / +1 day of the discovery point.](../figures/hit_rate_by_size.png){ width=100% }

# Decision impact

The question has the same answer for both plausible product directions:

- **Loiter / early detection.** Marginal value of a drone over a square kilometer is approximately the satellite-miss probability at that location:

    $$\text{marginal aerial value}(x) \;=\; 1 - P\!\left(\text{FIRMS detects} \mid x\right).$$

    The gap surface (Figure 8) is a first-pass priority map for where to base or patrol assets.

- **Active suppression.** Suppression needs a *trustworthy* ignition trigger. FIRMS does not emit an all-clear signal — it emits silence. But silence is exactly what a triggering pipeline would have to interpret as "no fire here." Given that 97% of CA small fires produce no FIRMS pixel, treating FIRMS silence as evidence of no fire has a ~97% miss rate at the small-fire end. The same gap surface is the surface over which a confirmatory aerial layer must operate.

In both cases the foundation is identical: a calibrated estimate of the satellite miss probability,

$$P_{\text{miss}}(x) \;=\; 1 - P\!\left(\text{FIRMS detects fire} \,\big|\, \text{size, location, season, time-of-day}\right).$$

# Methodology robustness

The headline picture is robust to envelope settings. The default match envelope is 3 km radius, +1 day from discovery through `min(CONT_DATE, DISCOVERY_DATE + 14d)`. Sweeping radius across $\{1.5, 3, 5\}$ km and post-days across $\{1, 3, 5\}$:

![Sensitivity of hit-rate estimates to match-envelope settings. Small fires cap at ~7% hit rate even at the most generous envelope.](../figures/sensitivity.png){ width=100% }

Even at the most generous setting (5 km radius, +5 day window), small-fire hit rate caps at 7%; the tightest setting (1.5 km, +1 day) still shows large fires (≥ 1k ac) at 65--72%. The bias is not an artifact of envelope choice.

# Polygon vs.\ centroid matching

For the 268 FPA-FOD fires that fall inside a 2020 NIFC burn perimeter, we can replace "FIRMS pixel within 3 km of discovery point" with "FIRMS pixel inside the actual burn polygon during the fire's active window." This isolates the cost of the centroid-radius approximation.

![Apples-to-apples polygon vs.\ centroid+radius hit rate, restricted to FPA-FOD fires that fall inside a 2020 perimeter (n = 268).](../figures/perimeter_vs_centroid.png){ width=92% }

| Size (acres) | $n$ inside perim | centroid+radius | polygon | $\Delta$ |
|---|---:|---:|---:|---:|
| \< 10 | 143 | 13% | **39%** | $+26$ pp |
| 10--100 | 44 | 52% | 34% | $-18$ pp |
| 100--1k | 38 | 68% | 61% | $-8$ pp |
| 1k--10k | 20 | 95% | 95% | $0$ |
| 10k+ | 23 | 96% | **100%** | $+4$ pp |
| **All** | **268** | **41%** | **51%** | $+10$ pp |

Two opposite effects fight each other. At the small end, the polygon method *catches* fires the centroid envelope missed: many under-10-acre records sit just outside the eventual burn polygon of a 2020 mega-fire, and a FIRMS pixel inside that polygon during the fire's active window credibly evidences detection. At the middle bucket (10--1k acres), the polygon method is *stricter*: the centroid envelope was over-crediting hits from nearby fires whose pixels happened to lie within 3 km but weren't actually inside this fire's polygon. At the top end, the polygon method recovers the Castle-Fire-style cases where the FPA-FOD coordinate is offset ~130 km from the actual burn (96% → 100%).

Net effect: $+10$ pp lift on the polygon-matchable subset. The headline tables use the centroid-radius numbers across the full 7,500 fires for comparability with the prior literature; the polygon match is the more trustworthy measurement when a perimeter exists.

# Detection latency, when FIRMS does see the fire

Hit/miss is only half the picture. For the perimeters where FIRMS *does* fire, the operationally meaningful number is **how late**. We spatial-join FIRMS pixels with the 566 CA 2020 burn perimeters (NIFC), anchor each perimeter's fire-start time to the matched CAL FIRE incident `Started` timestamp (hour-precision; fallback to FPA-FOD discovery only when name-matched), and contamination-filter any perimeter whose first FIRMS pixel sits **either more than 30 days after the recorded start, or more than 24 hours before it** (the asymmetry is by design: large +30 d gaps almost always indicate an unrelated earlier fire inside what later became this perimeter, but a FIRMS pixel firing >24 h before a CAL FIRE alarm is also suspicious — both directions are dropped, but the negative-side threshold is tighter than the positive).

Of the 110 measurable perimeters, **68 anchor to CAL FIRE's `Started` timestamp** (hour-precision; the trustworthy half), and **42 anchor to FPA-FOD `DISCOVERY_DATE`** (midnight-UTC truncation, up to ±24 h of clock noise). Reporting both:

| Statistic | CAL-FIRE anchor (n=68) | FPA-FOD only (n=42) | Pooled (n=110) |
|---|---:|---:|---:|
| Median latency, hours from alarm to first FIRMS pixel | **7.0** | 33.8 | 15.8 |
| Inter-quartile range | 5.4 -- 15.8 | 20.6 -- 78.8 | 6.5 -- 31.7 |
| Detected within 12 h | 62% | 12% | 43% |
| Detected within 24 h | 96% | 33% | 72% |
| Detected after $>$ 48 h | 0% | 29% | 11% |

![Distribution of FIRMS detection latency for CA 2020 perimeters (n = 110). Left: histogram, log-x. Right: latency by perimeter size. Most of the high-latency tail sits in the FPA-FOD-anchored subset, where midnight-UTC discovery dates inflate the apparent delay.](../figures/latency.png){ width=100% }

**What 7 h actually describes, and what it does not.** The CAL-FIRE-anchored subset is the trustworthy number, but it over-represents *exactly the fires VIIRS is good at catching* — incidents large enough or notable enough to make CAL FIRE's published incident list. Read carefully:

- The 7 h median is the latency *floor*, conditional on the fire eventually being notable enough that CAL FIRE recorded an alarm timestamp. These are mostly fires that grew into the multi-hundred-acre-plus regime.
- For the small fires this whole memo is about (the 92.5% under 10 ac), latency is **effectively infinite**: 97% of them were never detected at all, and the other 3% sit in the noisy FPA-FOD-only subset.
- The 15.8 h pooled median is biased upward by the FPA-FOD date-truncation, but it is also still mostly conditioning on the subset of fires that *had* a FIRMS detection. The right framing is two-tier: *"For fires VIIRS will catch, the median delay is 7--16 h. For the small fires the headline is about, there is no detection to time."*

For the size/latency relationship inside the catchable subset, latency *increases* slightly with perimeter size (median 9 h for 10--100 ac → 21 h for 10k+ ac, pooled). This is the expected dynamic: a fire that ends at 10k acres usually started as a sub-VIIRS-detection-threshold ignition and only crossed the detection threshold after substantial growth.

A loiter-aircraft pitch should say *both* things: it closes the 7-hour window for fires VIIRS would have eventually caught, and it provides the only detection layer at all for the small-fire 97%.

# Swath-edge geometry --- pixel size matters

VIIRS scans a ~3,000 km swath. Pixels near nadir are ~375 m on a side; pixels near the swath edge are 2--3× larger. FIRMS exposes this via the `scan` and `track` fields:

$$\text{pixel\_area}\;[\text{km}^2] \;\approx\; \text{scan} \times \text{track}.$$

We split FIRMS into nadir / mid / edge thirds by pixel area (33rd and 66th percentiles of the season's distribution) and re-ran the hit-rate calculation restricted to each:

![Hit rate when the match envelope is restricted to FIRMS pixels by swath bucket. The detection-vs-resolution trade-off is visible without any model: edge pixels detect big fires more often (more area covered) but small fires less often (higher per-pixel threshold).](../figures/swath_hit_rate.png){ width=100% }

- **Big fires (≥ 1k ac):** edge pixels have a *higher* hit rate (1k--10k: 47% nadir vs **61% edge**; 10k+: 76% vs **81%**). A larger pixel covers more area, so any given fire is more likely to fall under one.
- **Small fires ($<$ 10 ac):** edge pixels have a *lower* hit rate (1% vs 2%). The same physics that helps for big fires hurts here: larger pixels have a higher per-pixel detection threshold.

This is the textbook detection-vs-resolution trade-off, visible in the data without any model. For an aerial product, it implies that nadir-only filtering *tightens* the FIRMS "no" signal but throws away ~70% of detections; for small-fire alerting, ignoring edge pixels is the right call because they contribute almost nothing.

# Modeling the gap

Target:

$$\hat P\!\left(\text{FIRMS detects fire} \,\Big|\, \text{size, lat, lon, DOY, time-of-day, terrain, fuel}\right).$$

All metrics are computed *per fold* on a 5-fold stratified split (same `RNG=0` as the OOF predictions); reported as **mean ± standard deviation across the five held-out folds** (except the deterministic baselines, noted below). The calibrated rows in the table below all use isotonic `CalibratedClassifierCV(cv=5)`; "(cal)" is omitted in their row labels for brevity.

| Model | Brier $\downarrow$ | Log-loss $\downarrow$ | AUC $\uparrow$ |
|---|---:|---:|---:|
| Constant: predict no | 0.0547 ± 0.0000 | 0.755 ± 0.000 | 0.500 |
| Train base rate | 0.0517 ± 0.0000 | 0.212 ± 0.000 | 0.500 |
| Size-class lookup | 0.0418 ± 0.0014 | 0.171 ± 0.006 | 0.725 ± 0.040 |
| Size-class × lat-band | 0.0422 ± 0.0017 | 0.192 ± 0.015 | 0.753 ± 0.020 |
| Logistic regression | 0.0421 ± 0.0013 | 0.171 ± 0.006 | 0.771 ± 0.026 |
| GBM v1 | 0.0381 ± 0.0012 | 0.152 ± 0.005 | 0.838 ± 0.029 |
| **GBM v2 (+\ elevation)** | **0.0367 ± 0.0017** | **0.148 ± 0.006** | **0.843 ± 0.017** |
| GBM v3 (+\ terrain + fuel) | 0.0370 ± 0.0013 | 0.148 ± 0.004 | 0.844 ± 0.017 |

(`constant_no` and `base_rate` show 0.0000 std because they are deterministic over the same data — Brier is pooled across folds but does not depend on fold structure. The Brier of "predict no" equals the empirical positive rate; the log-loss spike to 0.755 vs.\ 0.212 for "predict base rate" is purely a calibration penalty for putting probability mass at zero when the truth is sometimes one — they do not disagree on whether the model is useful, only on whether it is *calibrated*.)

\clearpage

![Baselines vs.\ calibrated models, 5-fold stratified OOF. Bars are per-fold means; whiskers are ±1σ across the 5 held-out folds. The visible overlap among `gbm_calibrated`, `gbm_v2_with_elevation`, and `gbm_v3_elev_terrain_fuel` is the central point: their differences are smaller than the fold-to-fold sampling spread.](../figures/metrics_summary.png){ width=100% }

\clearpage

The size-class baseline is strong; it captures the dominant signal (small fires get missed). The v1 GBM clears it cleanly: Brier 0.0381 ± 0.0012 vs 0.0418 ± 0.0014, AUC 0.838 ± 0.029 vs 0.725 ± 0.040. The continuous features (size, lat/lon, season, time-of-day, hours-since-overpass) buy real lift.

(Caveat on the `hours_since_overpass` feature: it is computed from FPA-FOD `DISCOVERY_TIME`, which is missing in ~22% of records, and is built against a hardcoded Suomi-NPP overpass schedule of 02:00 / 14:00 local — an approximation of the actual orbit, which precesses over time and whose local-overpass time varies by several minutes across CA latitudes. A proper version would compute the overpass timetable per cell from the FIRMS pixel timestamps themselves. The feature is included because it is directionally right; it should not be read as a high-fidelity sensor-timing model.)

**v2 (+ elevation) and v1 are statistically indistinguishable on this dataset.** Brier 0.0367 ± 0.0017 vs 0.0381 ± 0.0012 — a 0.0014 gap with ±1σ bands that overlap. Either model is defensible as headline; we keep v2 nominal because elevation is a sensible physical predictor of detection probability and the point estimate is the right side of v1, but a sceptical reader is entitled to call this a coin flip on the metric. (We avoid the otherwise-tempting argument "v2's gap surface looks more terrain-shaped, therefore v2 is better." A model can produce more spatially-structured output because it is picking up real signal *or* because it is overfitting to elevation; the held-out metric does not distinguish those, so neither do we.)

**The v3 vs v2 comparison is a null result, and that is the honest read.** Brier 0.0370 ± 0.0013 vs 0.0367 ± 0.0017 and AUC 0.844 ± 0.017 vs 0.843 ± 0.017 — the differences are an order of magnitude smaller than the fold-to-fold standard deviations. Adding slope, aspect, TPI, and LANDFIRE fuel produced no detectable improvement on this single-year sample. Four readings are consistent with the data:

1. The features really are collinear with lat/lon/elevation, and there is no extra signal to extract.
2. There is signal, but 7,500 fires in one year is not enough sample to resolve it.
3. The information is there but the GBM hyperparameters were not retuned for the larger feature set.
4. **The LANDFIRE feature, as ingested, is degenerate for this dataset.** 61% of FPA-FOD ignitions snap to a non-burnable LANDFIRE FBFM40 cell (codes 91--99: urban, developed, agricultural, barren), because human-caused ignitions cluster in the wildland-urban interface where the 30 m raster classifies the actual ignition pixel as built environment. A "fuel" feature that's mostly "Non-burnable" cannot teach the model much.

We cannot distinguish (1)--(4) here. The honest claim is "v3 added features that did not move the metric on this sample, and at least one of those features (fuel) is suspect on inspection" — not "terrain and fuel don't help." The right next test for the fuel question is to sample LANDFIRE on a 100 m neighborhood mode rather than the nearest-cell value, or to restrict v3 to lightning-cause ignitions where the WUI-snap problem doesn't apply.

![Reliability diagram, 10 bins on OOF predictions, all four calibrated models. Calibration is mixed in the operational range: in the 10--20% predicted-probability bin, GBM v2 *over*-predicts hit rate by ~4 pp (the unsafe direction for a detection product — model says fire more likely caught than it is); in the 30--60% bins it *under*-predicts by 8--16 pp (the safer direction). The 0--10% bin (where ~90% of fires live) is well-calibrated to within 1 pp. Bins above 70% have ≤35 fires each and are data-limited.](../figures/calibration.png){ width=72% }

# Where the gap is largest

For a hypothetical fire ignited at peak season (mid-July, mid-day local), we evaluate

$$g(x) \;=\; \sum_{c} \pi_c \cdot \bigl[1 - \hat P\!\left(\text{FIRMS detects} \,\big|\, \text{1-acre fire},\, \text{July 15},\, \text{11:00 local},\, \text{cause}=c,\, x\right)\bigr]$$

on a 0.1° latitude/longitude grid covering California, where $x$ is the cell's spatial / terrain / fuel context and $\pi_c$ is the empirical 2020 CA cause distribution (56% undetermined, 11% arson, 9% equipment, 8% lightning/Natural, ...). The earlier version of this analysis conditioned on $c=\text{Natural}$ alone, which over-represented lightning-dominated terrain (Klamath / Sierra); the cause-mix-weighted version below is the right read.

![Predicted marginal aerial value (1 -- P(FIRMS detects)) across CA on a 0.1$^\circ$ grid, three scenarios. Predictions are mixed over the 2020 CA cause distribution (rather than conditioned on a single cause). Light = high gap (drones add value); dark = low gap (FIRMS likely catches it).](../figures/gap_surface.png){ width=100% }

The 1-acre map is uniformly high (median 0.98) --- VIIRS rarely catches small fires anywhere. **The lever is detecting fires that haven't grown yet.**

For 100-acre fires the surface separates by terrain: the Klamath / Trinity Alps and the northern Sierra--Cascades show high gap (FIRMS will probably miss), while the Central Valley and southern basins show low gap (FIRMS catches them). Detection failures concentrate in the heavily forested, high-elevation interior --- exactly where ground-based detection is also hardest.

**Trust the size finding; do not yet trust the spatial specifics.** 2020 was an outlier lightning-siege year for California — most of the season's big fires concentrated in the northern interior. The "FIRMS misses small fires" headline is a sensor-physics result and is almost certainly universal. The shape of the 100-acre gap surface, in contrast, partly reflects *where 2020 happened to burn*, and the Klamath / Sierra story should not be used as a basing decision until the same pipeline is run on Oregon and Idaho (or a multi-year CA window) and the spatial structure replicates. A founder reading Figure 8 to choose where to position aircraft is reading exactly the layer this dataset cannot defend yet.

![Spatial distribution of FIRMS hits vs.\ misses across California, split by fire size. Small-fire misses cover the state; medium/large-fire misses concentrate along the Coast Range and Sierra--Cascade interior.](../figures/miss_map.png){ width=100% }

# Honest limitations

- **"Hit" = any pixel in the envelope** (or polygon), not "FIRMS correctly identified *this* fire." Two fires burning within a few km can both be credited as hits.
- **FPA-FOD coordinates are noisy.** The 174k-acre Castle Fire (2020) shows up at 34.95$^\circ$N / -118.93$^\circ$W, ~130 km from the actual burn perimeter in Sequoia NF. The polygon-match approach above resolves this case; centroid-radius cannot.
- **FPA-FOD covers 1992--2020 only.** Extending past 2020 requires a different ground-truth source (MTBS, ICS-209, or CAL FIRE perimeters).
- **Elevation feature is from a ~500 m neighbor offset on SRTM via Open-Elevation**, not a proper 30 m USGS 3DEP raster. The slope estimates are fine for "is it mountainous"; coarse for "is this a steep canyon."
- **Single-year, single-region — the load-bearing caveat.** 2020 was an outlier lightning-siege year for California; most of the season's burned acreage concentrated in the northern interior. The size-by-detection-rate finding (3.2% / 25% / 80%) is a sensor-physics result and is robust. The *spatial* gap-surface specifics — the Klamath / Sierra / Trinity hot-zones in Figure 8 — partly reflect where 2020 happened to burn and should not be acted on (e.g.\ for aircraft basing) until the pipeline replicates on Oregon and Idaho or on a 5+ year CA window.

