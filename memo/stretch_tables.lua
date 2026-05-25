-- Pandoc Lua filter: make every table stretch to \textwidth by assigning
-- proportional column widths that sum to 1.0.
--
-- Pandoc pipe tables don't carry column widths by default, which makes pandoc
-- emit `\begin{longtable}[]{@{}llr@{}}` (natural-width columns) and the table
-- ends up only as wide as its content. By overwriting colspecs with widths
-- that sum to 1, pandoc instead emits the proper `>{\raggedright\arraybackslash}p{W}`
-- column specs and the table fills the page width.
--
-- Default: equal-width columns. The first column tends to hold labels and the
-- rest tend to hold numbers — equal width usually gives the label column more
-- room than pandoc's default sizing while still spreading the numeric columns.

function Table(el)
  local ncols = #el.colspecs
  if ncols == 0 then return el end
  local new_colspecs = {}
  for i = 1, ncols do
    local align = el.colspecs[i][1]
    -- Slight bias to the first column (labels) at 1.3x, rest split the
    -- remainder. Keeps numeric columns from getting absurdly wide when there
    -- are 4+ of them and the labels are short.
    local width
    if ncols >= 3 and i == 1 then
      width = 1.3 / (ncols + 0.3)
    else
      width = 1.0 / (ncols + 0.3)
    end
    new_colspecs[i] = {align, width}
  end
  el.colspecs = new_colspecs
  return el
end
