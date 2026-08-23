# UI common-sense brief for the Ikarus + graph hero screen (research, 2026-08-23)

Sources read: NN/g (3 articles), Shape of AI, AI UX Playground Claude-artifacts teardown, WWDC23
"Design for spatial user interfaces" (Apple primary), Cambridge Intelligence graph-UX articles,
Highcharts on 3D, Code Culture on Obsidian graph, Destiner on command palettes, macOS sidebar
guidelines (Guzman), 925 Studios / superdesign on AI-slop tells.

## 1. Chat-first AI UX

1. Put citations next to the claim they support, styled distinctly from body text, with meaningful labels (file/symbol name, not "source") and deep links to the exact location. https://www.nngroup.com/articles/explainable-ai/
2. Do not render fake "step-by-step reasoning" as if it were the model's computation; show sources, tool calls and limitations instead. Neutral, non-anthropomorphic language. https://www.nngroup.com/articles/explainable-ai/
3. Put the "verify this" note near the input, not in a footer, and pair it with an action. https://www.nngroup.com/articles/explainable-ai/
4. Suggestions must be contextual and task-specific; three legitimate kinds only: use-case starters (below empty input), autocomplete (while typing), follow-ups (below the last answer). Generic chips disconnected from context are clutter. https://www.nngroup.com/articles/prompt-suggestions/
5. Prompt controls: standard icons with labels, functional names (no branded labels, no magic-wand icon), grouped by function. https://www.nngroup.com/articles/prompt-controls-genai/
6. Streaming makes dense answers worse; keep answers short and scannable. https://www.nngroup.com/articles/less-chat-more-answer/
7. Show plan / tool calls / checks as a collapsible, auditable trail; citations as inline annotations. https://www.shapeof.ai/
8. Chat + canvas (Claude artifacts pattern): thread = reasoning trail, side pane = the product. A message carries a compact card that opens the pane without losing the thread; pane chrome is visually separated from chat actions; destructive/public actions never share weight with copy. https://www.aiuxplayground.com/teardowns/claude/artifacts/

## 2. Graph visualization

1. Overview first, zoom and filter, details on demand; progressive disclosure via zoom, filter, clustering. https://cambridge-intelligence.com/blog/designing-intuitive-data-experiences-with-graph-visualizations/ · https://infovis-wiki.net/wiki/Visual_Information-Seeking_Mantra
2. Labels only above a zoom threshold; smart-truncate; tooltip the rest; never repeat in text what size/colour already encode.
3. Highlight only the important nodes; one accent reserved for interactive state; colour-blind safe, readable in greyscale; WCAG contrast for labels.
4. Named failure modes: hairball, snowstorm, starburst. Fix with filtering, clustering and pruning, not prettier rendering. https://cambridge-intelligence.com/five-pitfalls-network-visualization/
5. A global graph view is "fun to look at, useless to navigate" past ~200 nodes; what works is the local graph around the current node, filters, and task orientation. https://codeculture.store/blogs/developer-culture/obsidian-graph-view-useful
6. 3D only for inherently spatial data or interactive exploration; costs: perspective distortion, occlusion, load. If 3D: rotation, depth cues (shading, reference grid), tooltips, screen-aligned labels. https://www.highcharts.com/blog/best-practices/3d-graph-useful-visualization-or-misleading-illusion/
7. Level of detail: drop labels and aggregate edges when zoomed out; bundle or curve edges for dense graphs.

## 3. visionOS spatial rules (Apple, WWDC23 session 10076)

https://developer.apple.com/videos/play/wwdc2023/10076/
1. Windows are glass; avoid solid colours on windows; never stack lighter materials on each other.
2. Text on glass: white by default, heavier weights (body medium, titles bold), slightly wider tracking, system fonts at small sizes; vibrancy tiers (primary/secondary/tertiary) and system colours, never custom low-contrast colours.
3. Ornaments: controls float outside the window, overlapping the bottom edge by 20 pt; borderless buttons; hide only when focused on one piece of content.
4. Hover: every interactive element has a hover shape; 60 pt targets, 16 pt between stacked buttons, 4 pt padding so hover regions do not merge.
5. Depth = concentric corners (inner radius + padding = outer radius), continuous corners; hierarchy by layering, not colour.
6. Keep important content centred; prefer wider over taller canvases; selected state = black on white; otherwise avoid white button fills.

## 4. Desktop common sense

1. Sidebar 225–275 pt min, 350–400 pt max; at most two hierarchy levels; section headers; search at top if long; actions in a bottom bar; monochrome icons. https://marioaguzman.github.io/design/sidebarguidelines/
2. Mac apps use sidebar + toolbar + inspector, not tab bars.
3. Command palette: one hotkey that also dismisses; fuzzy + keyword search; recents on empty state; categories and shortcuts inline; prefixes (@symbol, :line) instead of multiple palettes; every action reachable; fully keyboard-operable; no settings inside it. https://destiner.io/blog/post/designing-a-command-palette/
4. Group controls by proximity; name them functionally.

## 5. "AI-generated" tells

https://www.925studios.co/blog/ai-slop-design-tells · https://superdesign.dev/blog/why-ai-design-looks-generic
Inter everywhere; indigo→purple gradient; three rounded feature cards; badge-above-headline; coloured left-border cards; numbered 1-2-3 steps; dark-mode-by-reflex with neon cyan/violet glows; glass on everything; floating gradient orbs; weightless copy; thin generic line icons. Fix: a typeface and palette with a reason, broken symmetry, copy only this product could say.

## Do not

Citations as footnotes; "Source" as a label; fake chain-of-thought; suggestion chips not derived from selection/mission; global hairball by default; labels on every node at every zoom; text over busy content without a glass/vibrancy layer; thin custom fonts on glass; opaque coloured panels; glass on glass; accent-coloured sidebar icons; multiple palettes; settings in the palette; glow borders; orbs; triptychs; dashboards of status tiles.
