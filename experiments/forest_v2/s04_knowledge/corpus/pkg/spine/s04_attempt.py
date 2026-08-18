# Inert corpus target. Comment lines only: no imports, no statements, no
# entrypoint. Its only property under test is its length, so that a cited
# line number can be inside or outside the file.
# 4
# 5
# 6
# 7
# 8
# 9
# 10
# 11
# 12  <- referenced as an in-range line
# 13
# 14  <- last line; a reference to :900 must be reported out of range
