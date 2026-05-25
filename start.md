# start.md — Wildfire Detection-Gap & Aerial-Value Project

## What this project is

A data science portfolio project that quantifies **where and when satellite
wildfire detection is weak**, and therefore **where aerial (drone) detection adds
the most marginal value**. It is a *deployment-economics* project, not a
fire-prediction project.

The deliverable: a finished, legible repo with a README that leads with
decision-impact, real baselines, calibrated confidence estimates, and an honest
treatment of the satellite detection-bias problem.

## Why this framing

- The audience is a domain expert at a (stealth) autonomous-drone wildfire
  startup. The product is unknown — either persistent **loiter/detection** or
  active **suppression**.
- Both product directions share one foundation: knowing where satellite
  detection is unreliable, and having a confidence/triage layer on detections.
- So we build the **shared foundation** and map it to both directions in the
  README. Not knowing the product is not a blocker.

## The one real methodological trap

FIRMS (the satellite fire product) **misses most small fires** — detection rates
for small fires are very low, and satellites cannot reliably date or locate fires
below a size threshold. Treating "no FIRMS detection" as "no fire" is a known
error baked into most prior work.

**This bias IS the project's contribution.** The core task is to measure it:
compare FIRMS detections against independent ground-truth fire records, quantify
what FIRMS missed and under what conditions (size, terrain, time-of-day,
overpass gaps), and turn that into a map/model of marginal aerial value.

This is the part that needs human judgment. Do not delegate the conclusion.

## Scope discipline

One region, finished completely, beats three half-done projects.

- **Region:** California (public, rich ground-truth via CAL FIRE incidents and
  the FPA-FOD federal fire-occurrence dataset).
- **Time window:** one fire season to start. Expand only after the pipeline works.
- **Done means:** baseline + analysis + calibration + README, all shipped.

## Task breakdown (parallelizable across subagents)

Subagents can work these in parallel where marked [P]; sequential where marked [S].

1. **[S] Data acquisition**
   - Register a FIRMS MAP_KEY; pull VIIRS active-fire detections for California,
     one fire season. (Use VIIRS, not MODIS — see notes.)
   - Pull CAL FIRE incident records and FPA-FOD records for the same window.
2. **[P] Data cleaning & spatial join**
   - Normalize coordinates/timestamps; build a spatial+temporal join between
     FIRMS detections and ground-truth fire records.
3. **[S] The core comparison**
   - For each ground-truth fire, was there a corresponding FIRMS detection?
   - Stratify hit/miss rate by fire size, terrain, time-of-day, overpass timing.
4. **[P] Baselines**
   - Establish naive baselines BEFORE any model. A result with no baseline is
     not a result.
5. **[S] Detection-gap model**
   - Model P(FIRMS detects | fire characteristics). Output a gap/marginal-value
     surface over the region.
6. **[P] Calibration**
   - Calibrate probability outputs (e.g. isotonic regression / conformal
     prediction). Report honest coverage, not just accuracy.
7. **[S] README & decision framing**
   - Lead with decision-impact. Include a "loiter vs. suppression" section
     mapping the findings to both possible product directions.
   - Include a "what I'd do with more time" section.

## Verification approach

Instead of abstract autonomous "red-teaming," verification here is concrete and
built into the tasks:

- The FIRMS-vs-ground-truth comparison **is** the validity check — it tests
  whether the data we'd otherwise trust is actually trustworthy.
- Every model result must be checked against a documented naive baseline.
- Calibration is verified by held-out coverage, not in-sample accuracy.
- A subagent may draft an adversarial review of claims in the README, but a
  human signs off on every conclusion. Do not let an agent self-certify
  findings against data it cannot independently ground-truth.

## Notes / decisions on record

- **Use VIIRS (VNP14), not MODIS (MOD14).** Comparative work found the MODIS
  fire mask highly stochastic and unsuitable for next-day prediction tasks;
  VIIRS is the better product.
- FIRMS is excellent as a near-real-time feed and for the detection side — the
  caution is specifically about treating its silence as confirmed "no fire."
- Keep the project narrow. Resist adding new angles. Starting and finishing is
  the bottleneck, not the idea.

## Research & data links

Data portals:
- FIRMS archive download — https://firms.modaps.eosdis.nasa.gov/download/
- FIRMS API (MAP_KEY) — https://firms.modaps.eosdis.nasa.gov/api/

Research surfaced for this project:
- Wildfire Risk Prediction: A Survey of Recent Advances Using Deep Learning
  Techniques (2024) — https://arxiv.org/html/2405.01607v4
  (Documents that MODIS/VIIRS hotspot products are not suitable for ignition
  estimation; cites low small-fire detection rates.)
- Deep learning for wildfire risk prediction: integrating remote sensing and
  environmental data (2025) —
  https://www.sciencedirect.com/science/article/pii/S0924271625002217
  (Satellite data cannot reliably date most fires below ~500 ha.)
- Comparing Next-Day Wildfire Predictability of MODIS and VIIRS Satellite Data
  (2025) — https://arxiv.org/html/2503.08580v2
  (Finds MODIS MOD14 mask unsuitable; VIIRS VNP14 preferred.)
- Geospatial System for Wildfire Monitoring and Prediction Using Aerospace Data
  (2025) — https://www.sciencedirect.com/science/article/pii/S2666592125001167
  (Unified ML-detection + cellular-automata early-warning system; note most
  operational systems give categorical danger levels, not calibrated pixel-level
  probabilities — a genuine gap.)
- A Multi-Modal Wildfire Prediction and Personalized Early-Warning System Based
  on a Novel Machine Learning Framework (2022) — https://arxiv.org/pdf/2208.09079

## Next 48 hours

1. Confirm California (or chosen alternative).
2. Register FIRMS MAP_KEY; pull one season of VIIRS detections.
3. Pull CAL FIRE + FPA-FOD records for the same window.
4. Run the first comparison: how many recorded fires does FIRMS show, and how
   big are the ones it misses?

That comparison is the moment the project becomes real. Get there first.