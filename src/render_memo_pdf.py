"""Render the discovery memo to PDF via pandoc + tectonic.

Pipeline: markdown -> light preprocess -> pandoc -> LaTeX -> tectonic -> PDF.
See format_guide.md for the rationale behind every choice here.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from src.config import ROOT

MEMO_MD = ROOT / "memo" / "firms_findings.md"
MEMO_PDF = ROOT / "memo" / "firms_findings.pdf"
PREAMBLE = ROOT / "memo" / "_preamble.tex"
TMP_MD = ROOT / "memo" / "_pandoc_input.md"
TABLE_FILTER = ROOT / "memo" / "stretch_tables.lua"

HOME_BIN = Path.home() / "bin"


RE_PAGE_BREAK_HEADING = re.compile(
    r"^(#{1,6}[^\n]*?)\s*\{:\s*\.page-break-before\s*\}",
    re.MULTILINE,
)
# Currency `$` followed by a digit, unless:
#   - escaped already (preceded by `\`)
#   - the very next two chars are `<digit>$` (single-digit math like `$0$`)
#   - it's the CLOSING delimiter of a math span like `$\sim$3,000` — those
#     are preceded by a word char or `}`, never by whitespace / line start.
#     Adding [\w}] to the lookbehind protects them.
RE_CURRENCY_DOLLAR = re.compile(r"(?<![\w\\}])\$(?=\d)(?!\d\$)")


def preprocess(src: str) -> str:
    def page_break_sub(match: re.Match) -> str:
        return f"\\newpage\n\n{match.group(1).rstrip()}"

    src = RE_PAGE_BREAK_HEADING.sub(page_break_sub, src)
    src = RE_CURRENCY_DOLLAR.sub(r"\\$", src)
    # tectonic resolves \includegraphics paths relative to its own working
    # directory (a temp dir). Rewrite the markdown-relative `../figures/...`
    # references to absolute paths so the figures embed regardless of where
    # the engine runs.
    figures_abs = str(ROOT / "figures")
    src = src.replace("../figures/", f"{figures_abs}/")
    return src


PREAMBLE_TEX = r"""
\usepackage{amssymb}
\usepackage{nicefrac}
\usepackage{booktabs}
\usepackage{array}
\usepackage{longtable}
\usepackage{microtype}
\usepackage{xcolor}
\usepackage{hyperref}
\hypersetup{
    colorlinks=true,
    linkcolor=NavyBlue,
    urlcolor=NavyBlue,
    citecolor=NavyBlue,
}
\setlength{\parskip}{0.4em}
\setlength{\parindent}{0pt}
\renewcommand{\arraystretch}{1.05}
% Tables: render one font size below body. Pandoc emits longtable for any
% table that might span pages, and tabular for short ones; hit both via
% etoolbox \AtBeginEnvironment so we don't have to wrap each table by hand.
\usepackage{etoolbox}
\AtBeginEnvironment{longtable}{\footnotesize}
\AtBeginEnvironment{tabular}{\footnotesize}
% No widows / no orphans. Forces LaTeX to push or pull a line rather than
% leave the last (or first) line of a paragraph stranded alone on a page.
\widowpenalty=10000
\clubpenalty=10000
\displaywidowpenalty=10000
% Pin figures to where they appear in source order. Without this LaTeX floats
% them and they end up splitting paragraphs across pages.
\usepackage{float}
\floatplacement{figure}{H}
% Keep figures from crossing section boundaries as a belt-and-suspenders.
\usepackage[section]{placeins}
% Figure captions smaller than body text + italic, arxiv-style.
\usepackage{caption}
% Caption body is upright (NOT italic) so that backtick-coded variable names
% like `gbm_calibrated` render in upright \texttt instead of italic. Only the
% "Figure N:" label is bold for emphasis.
\captionsetup{font={footnotesize}, labelfont={footnotesize,bf}, skip=16pt, belowskip=6pt}
\usepackage{titlesec}
\titleformat{\section}{\normalfont\large\bfseries}{}{0pt}{}
\titleformat{\subsection}{\normalfont\normalsize\bfseries}{}{0pt}{}
\titleformat{\subsubsection}{\normalfont\normalsize\bfseries}{}{0pt}{}
\titlespacing*{\section}{0pt}{1.4em}{0.4em}
\titlespacing*{\subsection}{0pt}{1em}{0.25em}
\titlespacing*{\subsubsection}{0pt}{0.8em}{0.2em}
""".strip()


def main() -> int:
    pandoc = shutil.which("pandoc") or str(HOME_BIN / "pandoc")
    tectonic = shutil.which("tectonic") or str(HOME_BIN / "tectonic")
    if not Path(pandoc).exists():
        raise SystemExit(f"pandoc not found at {pandoc}")
    if not Path(tectonic).exists():
        raise SystemExit(f"tectonic not found at {tectonic}")

    src = MEMO_MD.read_text(encoding="utf-8")
    src = preprocess(src)
    TMP_MD.write_text(src, encoding="utf-8")
    PREAMBLE.write_text(PREAMBLE_TEX, encoding="utf-8")

    env = os.environ.copy()
    env["PATH"] = f"{HOME_BIN}:{env.get('PATH', '')}"

    cmd = [
        pandoc,
        str(TMP_MD),
        "-o", str(MEMO_PDF),
        "--pdf-engine", tectonic,
        "--from", "markdown+tex_math_dollars+pipe_tables+raw_tex+yaml_metadata_block+implicit_figures",
        "--to", "latex",
        # tectonic runs in its own temp dir; tell pandoc + tectonic where
        # the figures actually live.
        "--resource-path", f"{ROOT}:{ROOT / 'memo'}",
        # Lua filter that assigns proportional column widths to every table so
        # pandoc emits stretched longtable specs (fills \textwidth).
        "--lua-filter", str(TABLE_FILTER),
        "--pdf-engine-opt", f"--keep-intermediates",
        "-V", "documentclass=article",
        "-V", "fontsize=11pt",
        "-V", "mainfont=Times New Roman",
        "-V", "geometry:margin=1in",
        "-V", "linestretch=1.15",
        "-V", "colorlinks=true",
        "-V", "linkcolor=NavyBlue",
        "-V", "urlcolor=NavyBlue",
        "-H", str(PREAMBLE),
    ]
    print("running:", " ".join(cmd))
    result = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        print("STDOUT:", result.stdout)
        print("STDERR:", result.stderr)
        raise SystemExit(f"pandoc failed (exit {result.returncode})")

    size_kb = MEMO_PDF.stat().st_size / 1024
    print(f"wrote {MEMO_PDF} ({size_kb:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
