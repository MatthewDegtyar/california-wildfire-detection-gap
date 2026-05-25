# PDF formatting guide (markdown → LaTeX → PDF)

Lessons from getting `h1b_fee_analysis/memo/h1b_fee_memo.pdf` to render at arxiv quality. Reference for future memos in this repo.

## Toolchain

- **pandoc 3.5** at `~/bin/pandoc` — prebuilt arm64 macOS binary
- **tectonic 0.16.9** at `~/bin/tectonic` — single-binary LaTeX engine, fetches `.sty` packages from CTAN on demand
- No Xcode CLT, no MacTeX, no `brew install`. Both binaries are direct downloads.

Tectonic runs **XeTeX**, not pdfTeX. This matters more than it sounds — it changes which font packages work.

Pipeline: markdown → small Python preprocess → pandoc → LaTeX → tectonic → PDF. Reference script: `h1b_fee_analysis/src/render_memo_pdf.py`.

## Fonts (the one that took the longest)

**Don't use `mathptmx`, `newtxtext`, or any pdfTeX-era font package.** Under XeTeX they either silently no-op (mathptmx) or require workarounds for `\arrowvert` / `\openbox` collisions with pandoc's auto-loaded amsmath (newtxmath).

**Do use fontspec via pandoc's CLI variables:**

```
-V mainfont="Times New Roman"
```

That single flag gives Times Roman + Times Bold + Times Italic + Times Bold-Italic, all properly embedded as TrueType subsets. Math symbols stay in Latin Modern Math (handles all the Greek and operators — don't fight it).

Tectonic does **not** fetch font files, only `.sty` packages. So the font must be available on the system. `Times New Roman` ships with macOS; `TeX Gyre Termes` requires a manual install.

Verify the bold variant actually got embedded:

```
pdffonts out.pdf | grep -i bold
```

If you don't see `Times*-Bold*` or `LMRoman*-Bold*`, `\bfseries` has nothing to pull and headings will render at body weight regardless of `\titleformat`.

## Currency `$` vs math `$`

`tex_math_dollars` treats every `$` as a math delimiter. `$100,000` → math mode containing `100,000`; `$8.5 million in revenue against an estimated $19.5 million` → one bogus math span that eats the prose between the two currency figures.

**The fix is a single-pass regex, not masking:**

```python
RE_CURRENCY_DOLLAR = re.compile(r"(?<!\\)\$(?=\d)(?!\d\$)")
src = RE_CURRENCY_DOLLAR.sub(r"\\$", src)
```

Reads as: escape `$` followed by a digit UNLESS the next two characters are `<digit>$` (which is a single-digit math expression like `$0$`).

**Dead end to avoid:** mask `$...$` regions first → escape currency on the remainder → restore. The math regex can't distinguish a real math span from a currency-bracketed prose span — they're both shaped `$<stuff>$`. The masker greedily ate `$8.5 million in revenue against an estimated $` as one "math region", currency escape found nothing to escape, restore put the bogus math back. Burned ~30 min on this approach before realizing direct smart regex was the right shape.

## Headings: plain bold, controlled hierarchy

`article` class default has `\subsubsection` in bold italic and `\section` at `\Large`. For memo-style docs, simpler is better. Use `titlesec`:

```
\usepackage{titlesec}
\titleformat{\section}{\normalfont\large\bfseries}{}{0pt}{}
\titleformat{\subsection}{\normalfont\normalsize\bfseries}{}{0pt}{}
\titleformat{\subsubsection}{\normalfont\normalsize\bfseries}{}{0pt}{}
\titlespacing*{\section}{0pt}{1.4em}{0.4em}
\titlespacing*{\subsection}{0pt}{1em}{0.25em}
\titlespacing*{\subsubsection}{0pt}{0.8em}{0.2em}
```

`\large` on `\section` provides hierarchy at a glance; sub- and subsub- are body-sized bold. No italic anywhere.

## Page breaks

python-markdown attr syntax `## Heading {: .page-break-before }` is not pandoc-native. Preprocess to a raw-LaTeX `\newpage` before the heading and strip the attribute:

```python
RE_PAGE_BREAK_HEADING = re.compile(
    r"^(#{1,6}[^\n]*?)\s*\{:\s*\.page-break-before\s*\}",
    re.MULTILINE,
)
def page_break_sub(m):
    return f"\\newpage\n\n{m.group(1).rstrip()}"
```

## Equations

Write them in standard LaTeX between `$...$` (inline) and `$$...$$` (display). Pandoc passes them through as-is. With `mainfont="Times New Roman"` the inline math italic visually matches body italic.

**Don't:**
- Rasterize equations to PNG via matplotlib mathtext and embed in HTML — fails silently on inline math, oversized display, weird super/subscripts.
- Use `\text{}` heavily in display math; mathtext-style preprocessing isn't needed under real LaTeX.

**Do:**
- Use `\hat\beta_2` for estimators, `z_{1-\alpha/2}` and `z_{1-\beta}` for critical values (not `z_{\text{power}}` — multi-word subscripts read poorly).
- Use `\frac{}{}` in display math; for inline fractions use `\nicefrac{}{}` (loaded via `nicefrac` package).

## Pandoc invocation (canonical)

```
pandoc input.md \
  -o out.pdf \
  --pdf-engine ~/bin/tectonic \
  --from "markdown+tex_math_dollars+pipe_tables+raw_tex+yaml_metadata_block" \
  -V documentclass=article \
  -V fontsize=11pt \
  -V mainfont="Times New Roman" \
  -V geometry:margin=1in \
  -V linestretch=1.15 \
  -V colorlinks=true \
  -V linkcolor=NavyBlue \
  -V urlcolor=NavyBlue \
  -H preamble.tex
```

Prepend `~/bin` to PATH so tectonic is discoverable.

## Verification recipe

After every render, before declaring done:

1. `pdffonts out.pdf` — confirm bold variants are embedded.
2. `pdftotext out.pdf - | grep <currency-figure>` — confirm dollar amounts render as text, not eaten by math.
3. `pdftoppm -r 200 out.pdf /tmp/p -png -f <equation-page> -l <equation-page>` — visually inspect equation pages, confirm math italic stroke weight matches surrounding prose.

If any of those three fail, the user *will* notice.

## Dead-end ledger (do not repeat)

- matplotlib mathtext → PNG → weasyprint
- newtxmath (XeTeX no-op + amsmath conflicts)
- mathptmx (XeTeX no-op, leaves LMRoman with no bold variant)
- TeX Gyre Termes (tectonic doesn't fetch font files)
- Mask-then-escape currency `$`s (greedy regex eats currency-bracketed prose)
- `z_{\text{power}}` for the statistical-power critical value (reads as crammed text)
- CSS-based equation height limits (`max-height: 4em`) — only relevant for the matplotlib hack, which we no longer use

## Figures: the second-pass lessons (FIRMS-Russia memo)

### Images silently don't embed when paths are relative

Markdown like `![caption](../figures/foo.png)` works in any preview tool. It does **not** work when pandoc hands the resulting `\includegraphics{../figures/foo.png}` to tectonic, because tectonic resolves that path relative to its own temp working directory, not the markdown file. LaTeX silently drops the missing image and renders only the caption — you don't see an error, you see a floating caption with nothing above it.

Symptoms: caption text appears in the middle of an otherwise-empty page; `pdfimages -list out.pdf` shows zero embedded images; PDF file size suspiciously small (~100 KB for a 6-page memo).

Fix in the preprocessor (cleanest):

```python
figures_abs = str(PROJECT_ROOT / "figures")
src = src.replace("../figures/", f"{figures_abs}/")
```

Belt-and-suspenders: also pass `--resource-path "<project root>:<memo dir>"` to pandoc.

Always verify with `pdfimages -list out.pdf`. Zero images = silent failure. Don't trust visual inspection at small thumbnail size.

### pandoc's `tex_math_dollars` rule kills `$math$<digit>`

Pandoc's `tex_math_dollars` extension explicitly does **not** treat `$...$` as math if the closing `$` is followed by a digit. The thinking is currency disambiguation (`$100` shouldn't open math). But this also kills perfectly real inline math like `$\sim$70%`, `$\to$2020`, `$\geq$3,000`, etc. — the closing `$` is followed by a digit, so pandoc passes the whole thing through as literal text and you get `$￿$70%` in the PDF (the missing-glyph box character is `\sim` rendered outside math mode).

Two-part fix:

1. **For simple symbols, just use Unicode.** Times Roman has all of these and they don't need math mode at all: `$\sim$` → `~` (pandoc converts to `\textasciitilde`), `$\to$` → `→`, `$\geq$` → `≥`, `$\pm$` → `±`, `$\times$` → `×`.
2. **For real inline math that starts with a digit**, rewrite to start with a letter or symbol. `$1 - P(\text{detects})$` becomes `$P_{\text{miss}}$` or just plain prose with a Unicode minus: `1 − P(detects)`. The closing-`$`-followed-by-digit rule also fires for any math that ends adjacent to a digit, so reword to put space + non-digit after the closing `$`.

Also: the currency-escape regex from earlier in this guide needs to tolerate math-closing `$`. Use a richer lookbehind so it doesn't escape the closing `$` of a math span whose content is alphabetic (and thus preceded by `\w`):

```python
# Don't escape $ if preceded by a word char, backslash, or closing brace —
# those are all math-closing contexts, not start-of-currency.
RE_CURRENCY_DOLLAR = re.compile(r"(?<![\w\\}])\$(?=\d)(?!\d\$)")
```

### Figures float into the middle of paragraphs

pandoc emits `\begin{figure} ... \end{figure}` without an explicit placement specifier, which defaults to `[tbp]`. LaTeX will move that figure to wherever its float algorithm prefers — which is often *between two halves of the sentence that surrounded the markdown image*. The reader sees "Brier nudges back up to" → page break → image → "and AUC drops 0.001" two pages later.

Pin floats with the `float` package, and prevent them from crossing section boundaries:

```latex
\usepackage{float}
\floatplacement{figure}{H}
\usepackage[section]{placeins}
```

`[H]` (capital H from `float`, not the standard `[h]`) means "exactly here, do not float." Combined with `placeins`, figures land where the source put them. Prose stays continuous.

To force a single figure onto its own page, wrap its markdown with `\clearpage` raw-LaTeX blocks (pandoc passes them through with `raw_tex` enabled):

```markdown
\clearpage

![caption](../figures/big_figure.png){ width=100% }

\clearpage
```

### Captions: smaller than body, with breathing room

Defaults are too prominent for a research memo. Use the `caption` package:

```latex
\usepackage{caption}
\captionsetup{font={footnotesize}, labelfont={footnotesize,bf}, skip=16pt, belowskip=6pt}
```

- `footnotesize` for caption body and label (one step below `small`; at 11pt body that's ~8.5pt).
- **Do NOT add `it` to the body font.** Italic captions look fine in pure prose but break the moment you reference a code identifier — backtick-coded variable names like `gbm_v2_with_elevation` get rendered with italic `\texttt`, which under Times Roman + fontspec produces a slanted, hard-to-read monospace. The upright `bf` on the label alone is enough to mark the caption as a distinct chip; the body stays upright Roman.
- `skip=16pt` (≥14pt) is the gap above the caption. Anything tighter (the default `skip=10pt` or below) and the caption looks like part of the figure's title bar; matplotlib charts already have their own tick labels at the bottom, so the eye needs real whitespace to recognize "this is a caption, not chart chrome."
- `belowskip=6pt` keeps the caption from kissing the next paragraph.

### Figure text size: standardize matplotlib `figsize` widths

If figure A is authored at `figsize=(14, 5)` and figure B at `figsize=(5.5, 5.5)`, and both go through `\includegraphics[width=\linewidth]`, A gets scaled to ~0.46× and B gets *up*-scaled to ~1.18×. A 10pt label inside A renders at ~4.6pt on the page; the same label in B renders at ~11.8pt. Result: some figures look microscopic and others look "blown up."

Fix: pick one canonical width for all rectangular figures (e.g. 10 in) and let height vary by content. For square figures, downsize them and use markdown `width=` attribute so they scale by the same factor as the rectangles.

```python
# In your plotting module:
FIG_WIDTH_IN = 10.0
mpl.rcParams.update({
    "font.size": 13,
    "axes.titlesize": 14,
    "axes.labelsize": 13,
    "xtick.labelsize": 12,
    "ytick.labelsize": 12,
    "legend.fontsize": 12,
})

fig, ax = plt.subplots(figsize=(FIG_WIDTH_IN, 4.5))   # rectangles
fig, ax = plt.subplots(figsize=(7.0, 7.0))            # square (use width=72%)
```

### Bar-chart labels bleed past the axis frame

`ax.barh(model, value); ax.text(value + 0.001, i, f"{value:.4f}")` — the label position is hard-coded relative to the value, but `ax.set_xlim` defaults to "fit the bars exactly," so the label gets clipped off the right edge of the chart.

Always add an explicit xlim with label headroom:

```python
vmax = float(values.max())
ax.set_xlim(0, vmax * 1.25)
for i, v in enumerate(values):
    ax.text(v + vmax * 0.015, i, f"{v:.4f}", va="center", fontsize=9)
```

### Tables: stretch to `\textwidth` via a Lua filter

Pandoc pipe tables don't carry column widths in their AST, so pandoc emits `\begin{longtable}[]{@{}llr@{}}` — natural-width columns. The result: a small headline table (e.g. 3 narrow columns) renders as a thin slab hugging the left margin, with most of the page width wasted on its right. On the same page as a wide multi-panel figure, the visual mismatch reads as "this table was an afterthought."

Fix: a one-screen Lua filter that walks the AST and assigns proportional widths summing to 1.0, which pandoc then translates into proper `>{\raggedright\arraybackslash}p{0.??\textwidth}` column specs:

```lua
-- memo/stretch_tables.lua
function Table(el)
  local ncols = #el.colspecs
  if ncols == 0 then return el end
  local new = {}
  for i = 1, ncols do
    local align = el.colspecs[i][1]
    -- First column (labels) gets 1.3x weight; numeric columns share the rest.
    local w
    if ncols >= 3 and i == 1 then
      w = 1.3 / (ncols + 0.3)
    else
      w = 1.0 / (ncols + 0.3)
    end
    new[i] = {align, w}
  end
  el.colspecs = new
  return el
end
```

Wire it into the pandoc invocation: `--lua-filter memo/stretch_tables.lua`. Every table in the document now fills the available width, with a slight bias toward the first column for descriptive labels. Combine with the `\AtBeginEnvironment{longtable}{\footnotesize}` shrink above — the two together give you full-width tables in compact body-minus-one font, scannable in a single glance.

Why a Lua filter and not a `\renewcommand` or `tabularx` wrapper: pandoc emits `longtable` for anything that could page-break, and longtable doesn't compose cleanly with `tabularx`. The AST modification is upstream of the LaTeX generation, so it's the only place to inject widths that pandoc will actually respect.

### Tables: drop one font size to stop label wrapping

A markdown table with descriptive row labels ("HistGradientBoosting v1 (calibrated)", "HGB v2 (calibrated, + elevation)") plus wide numeric cells ("0.0367 ± 0.0017") at 11pt body font gives pandoc no room to fit either — the row labels wrap onto a second line in every other row, breaking visual scan.

Two fixes, do both:

1. **Shrink the table font globally** via `etoolbox` + `\AtBeginEnvironment`:

   ```latex
   \usepackage{etoolbox}
   \AtBeginEnvironment{longtable}{\footnotesize}
   \AtBeginEnvironment{tabular}{\footnotesize}
   ```

   Pandoc emits `longtable` for tables that might page-break and plain `tabular` for short ones; hit both so you don't have to guess. `footnotesize` (one notch below `small`) is the sweet spot — readable on screen and on paper, and gives the label column ~25% more width than the body.

2. **Shorten the labels themselves.** Move parenthetical qualifiers like "(calibrated)" out of every row and into a one-sentence note above the table ("All calibrated rows below use isotonic `CalibratedClassifierCV(cv=5)`"). Row labels should be ~20 characters or fewer. The font shrink alone won't save you if the label is "HistGradientBoosting v3 (+ slope/aspect/TPI + LANDFIRE fuel)" — that needs to become "GBM v3 (+ terrain + fuel)".

The two together: every row fits on one line, no orphaned descenders, scannable in a quick read.

### matplotlib subplot titles overflow the panel

A long-form descriptive title set via `ax.set_title("Hours from reported alarm to first FIRMS pixel inside perimeter  (n=110)")` on a panel ~5 inches wide will overflow the panel on the left side and get clipped when `tight_layout()` runs. The clipping is silent — the PNG saves with the truncation.

Two fixes:

1. **Move the long descriptive title to a `fig.suptitle()`** spanning all panels of the figure.
2. **Give each subplot a short panel label** as its `ax.set_title()` ("Distribution (n=110)", "By perimeter size").

When using a suptitle, call `plt.tight_layout(rect=[0, 0, 1, 0.95])` so the suptitle has room above the panels — `tight_layout()` alone doesn't know about the suptitle and will overlap it.

### Multi-panel maps: put the colorbar on the bottom, not the side

A three-panel map with `aspect="equal"` for geographic shapes plus a right-side colorbar at default placement squeezes the rightmost panel and clips the rotated colorbar label off the canvas edge. On a 10-inch-wide figure with three CA-shaped panels, there is simply no room left for a vertical colorbar.

Switch to a horizontal colorbar in a dedicated bottom strip:

```python
fig.subplots_adjust(left=0.06, right=0.98, top=0.88, bottom=0.22, wspace=0.10)
cbar_ax = fig.add_axes([0.20, 0.11, 0.60, 0.025])  # [left, bottom, w, h]
cbar = fig.colorbar(im, cax=cbar_ax, orientation="horizontal")
cbar.set_label("...", labelpad=6)
```

The panels keep the full figure width; the colorbar gets its own row; the `labelpad` keeps the label from hugging the colorbar ticks. Don't use `bbox_inches="tight"` here — the manual `subplots_adjust` is doing the layout work and `tight` will fight it.

### Widows and orphans across page breaks

LaTeX's default page-breaking is willing to leave the last line of a paragraph alone at the top of the next page (a *widow*) — e.g. a 3-line paragraph ends with "this data alone." stranded as the only prose on page N+1. Visually jarring, especially on the page following the headline.

Force the typesetter to push or pull rather than strand:

```latex
\widowpenalty=10000
\clubpenalty=10000
\displaywidowpenalty=10000
```

`10000` is the maximum penalty; LaTeX treats it as "infinitely costly" and will adjust earlier line-breaking to avoid it. `\widowpenalty` covers the last-line-of-paragraph-at-top-of-page case; `\clubpenalty` covers the inverse (first-line-of-paragraph-at-bottom); `\displaywidowpenalty` covers the corresponding case around display math.

### Verification additions

Add to the verification recipe whenever the document has figures:

4. `pdfimages -list out.pdf | wc -l` — confirm the expected number of figures embedded. Zero is the silent failure mode.
5. `pdftoppm -r 200 out.pdf /tmp/p -png -f <fig-page> -l <fig-page>` — visually inspect at least one page with a figure. Caption sitting alone with no image above it = the path-resolution bug.

