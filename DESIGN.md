# Kokopelli Labs: Design Guide v1

Saved from the brand workbench on 2026-11-11. This is the brand guidelines and the design system in one file. Sections 1 to 8 are the guide as saved; values are what was set in the panel, with the two changes noted in section 1. Sections 9 to 12 are the working rules the guide doesn't set, carried over from the system before it.

**Direction:** Primitive futurism.
**Tagline:** Perspective over optimization.

The tokens and components live in `kokopelli/life/static/design.css`. Pages only lay them out.

## 1. Materials

Everything is one of four materials. Flat color first, texture second.

| Material | Token | Value | Where it goes |
| --- | --- | --- | --- |
| Concrete (ground) | `--ground` | `#D0CCC5` | Page background. Carries the concrete photo texture. |
| Concrete (panel) | `--panel` | `#CEC9C0` | Cards, panels. |
| Concrete (slab) | `--slab` | `#B9B2A6` | Mid concrete blocks, image placeholders. |
| Raw wood | `--wood` | `#B98A5E` | Secondary fields, secondary buttons. Dark text on it. |
| Maroon (brand) | `--maroon` | `#5A2328` | The one brand field per screen, primary buttons, the focus ring. |
| Deep maroon | `--maroon-deep` | `#3E191C` | Hero panels, footers. Light text on it. |
| Pigment | `--pigment` | `#A65A48` | Marks and glyphs only: dots, the key chart series, the agent on a map. |
| Gold | `--gold` | `#B48322` | Rules, bars, numerals. Never body text. |
| Ink | `--ink` | `#2A1B18` | All text on concrete and wood. |
| Muted ink | `--ink-muted` | `#5E524A` | Captions, metadata. On ground and panel only. |

Notes:

- Maroon is the brand color. Pigment (`#A65A48`) is the lighter red for marks and glyphs only; it was tried as the brand color and maroon was put back.
- Light text on `--maroon` and `--maroon-deep` uses `--ground` (7.7:1 on maroon, 9.7:1 on deep maroon).
- **Changed from the workbench:** muted ink was saved as `#685C54`, which is 4.0:1 on ground and 3.9:1 on panel. It is `#5E524A` here (4.7:1 and 4.6:1) so small captions pass the 4.5:1 rule in section 12.
- Muted ink is too light for slab (3.6:1) and wood (2.5:1). Text on those is `--ink`.

### Ground texture

- Source: the light grey concrete photo supplied on 2026-11-11 (1428 x 2000).
- How it's applied: the photo is converted to a grey texture centered on mid grey, then laid over `--ground` with an overlay blend. Changing `--ground` re-tints the texture.
- The photo's own average color is `#BBBBBB`. The saved ground is the lighter, warmer `#D0CCC5`.
- Texture goes on the page background and light tiles only. It is not laid over type, panels or slabs.
- Texture strength in the panel: concrete 35%, wood 60%, maroon 10%.
- **Changed from the workbench:** the file is `kokopelli/life/static/concrete.jpg`, 640 x 944. It is the workbench's 760 x 1064 texture with each edge cross-faded into the opposite one over 120px, so it repeats without a seam on a wide screen. It is drawn at 640px wide, the same scale as in the workbench.

## 2. Finish

| Setting | Value | What it does |
| --- | --- | --- |
| Wash | 20% | Bleaches the whole sheet: `saturate(0.85) contrast(0.96) brightness(1.02)` |
| Wear | 10% | Light chipping on large type, the logo, section joints, and a slightly torn outer edge |

Wash is a preview filter in the workbench. Before production, bake it into the color values instead of shipping a filter.

Neither is in the dev panel yet. See section 8.

## 3. Logo

- **Mark:** the Nazca monkey, traced from the reference image and turned about 60 degrees counterclockwise so it rears up and fills a square (width and height within about 2%).
- **Weight:** 4 on a 120-unit grid. Weight 3 is the exact trace; 4 thickens the line by one unit.
- **Line ends:** round.
- **Colors:** `--ink` on concrete, `--ground` on maroon and deep maroon.
- **Minimum size:** 32px. Below that the spiral tail closes up. This is why there is no favicon.
- **Wordmark:** "Kokopelli Labs" in the display face, set next to or under the mark.
- **Files:** `kokopelli/life/static/logo-ink.svg` and `logo-light.svg`. In a page, use `<i class="logo-mark" aria-hidden="true"></i>`: it draws the mark in the text color of whatever it sits on, so one class covers both.

## 4. Type

| Role | Face | Weight | Use |
| --- | --- | --- | --- |
| Display | Fraunces | 300 | Headlines, the wordmark. Sentence case, not all caps. |
| Body | Work Sans | 400 / 500 | Paragraphs, buttons, labels. |
| Mono | JetBrains Mono | 400 | Eyebrows, metadata, numbers. Uppercase, letter-spacing 0.12em, 11px. |

Fallbacks: `Georgia, serif` / `system-ui, sans-serif` / `ui-monospace, monospace`.

```html
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,300&family=Work+Sans:wght@400;500&family=JetBrains+Mono:wght@400&display=swap">
```

## 5. Shape and layout

| Setting | Value |
| --- | --- |
| Slab corners | 0px |
| Button corners | 2px |
| Line weight | 1px |
| Composition | Quiet: floating blocks, hairline rules, generous space |
| Pattern | None |

- Rules and card borders are 1px ink at about 22% opacity. In CSS that is `--hairline` (section 9).
- A gold bar sits under the tagline on the cover.
- One maroon field per screen. Wood and concrete blocks sit beside it, never stacked on it.

## 6. Components

- **Primary button:** `--maroon` fill, `--ground` label, 2px corners. Class `btn-primary`. One per screen.
- **Secondary button:** `--wood` fill, `--ink` label. Class `btn-secondary`.
- **Ghost button:** transparent, `--ink` label, 1px `--ink-muted` border. This is a bare `<button>`.
- **Card:** `--panel` fill, 1px hairline border, square corners. Header is a small mark, a mono eyebrow, and a hairline under them. Classes `card` and `card-head`.
- **Hero panel:** `--maroon-deep` fill, `--ground` text, gold rule under the header. Class `hero-band`.

## 7. CSS tokens

```css
:root {
  --ground: #D0CCC5;
  --panel: #CEC9C0;
  --slab: #B9B2A6;
  --ink: #2A1B18;
  --ink-muted: #5E524A;
  --maroon: #5A2328;
  --maroon-deep: #3E191C;
  --wood: #B98A5E;
  --pigment: #A65A48;
  --gold: #B48322;

  --radius-slab: 0px;
  --radius-button: 2px;
  --rule: 1px;

  --font-display: "Fraunces", Georgia, serif;
  --font-body: "Work Sans", system-ui, sans-serif;
  --font-mono: "JetBrains Mono", ui-monospace, monospace;
  --display-weight: 300;
}
```

## 8. Open items

From the workbench:

- **Cover mark:** the saved cover still shows the concentric rings, which is one of the stock glyphs. Switch "Mark on the cover" to the logo, or leave the cover without a mark.
- **Glyph set:** empty apart from the monkey. The eight stock glyphs are switched off. Real glyphs get traced in from source images, each labeled with its site.
- **Monkey source:** the trace is from a modern rendering of the Nazca geoglyph (Peru), not from the geoglyph itself. For the final logo, trace from an aerial photo of the actual lines.
- **Concrete photo:** looks like a stock image. Get the license, or replace it with your own photo, before anything public. The texture made from it is in this repo.
- **Fecal Matter reference:** not studied yet. The wash and wear settings are a first guess at "washed, faded, tattered".
- **Maroon vs deep maroon:** `#5A2328` and `#3E191C` are close. Side by side they read as nearly the same field, so either lighten the brand maroon a step or drop deep maroon and use one.
- **Dark theme:** not designed. The dev panel and the benchmark report are light only until it is.
- **Heavier layouts:** Monolith, Monument and Ruin are still in the workbench as presets if you want a poster treatment alongside this quiet one.

From moving the dev panel onto the guide:

- **Muted ink:** darkened from the saved value so captions pass contrast (section 1). Confirm, or pick another value that reaches 4.5:1 on panel.
- **Wash:** not applied. The tokens are the unwashed values. Baking it in changes every hex in section 7.
- **Wear:** not applied. It needs an SVG filter inside every page, and the panel has little large type to chip.
- **Section 11:** the old rule said wordmark only, no mascot. It now allows the monkey and site-labeled traces. Confirm the wording.
- **Film overlay:** `kokopelli/body/overlay.py` draws its panel into videos with the old dark colors. It waits on the dark theme.
- **Carried-over tokens:** `--danger` and the four category colors in section 9 were not in the workbench. They were tuned for the old, lighter page.

## 9. Working tokens

These are not in the workbench. They come from the system before this guide and are in `design.css` beside the tokens in section 7.

| Token | Value | Use |
| --- | --- | --- |
| `--hairline` | `#ABA59F` | Every rule, divider and card border. It is ink at 22% over ground, flattened to one color so crossing lines don't darken. |
| `--danger` | `#9E2A22` | Errors and destructive actions only. 4.7:1 on ground. |
| `--space-2` | 8px | Gaps inside a component. |
| `--space-4` | 16px | Card padding, mobile side gutter. |
| `--space-6` | 24px | Page margins. |
| `--space-12` | 48px | Between sections. |

### Type scale

| Style | Family | Size / line height | Weight | Notes |
| --- | --- | --- | --- | --- |
| display | Fraunces | 64 / 64 | 300 | letter-spacing -0.02em |
| h1 | Fraunces | 40 / 44 | 300 | |
| h2 | Fraunces | 28 / 34 | 300 | |
| body | Work Sans | 16 / 24 | 400 | max line length ~65ch |
| label | Work Sans | 14 / 20 | 500 | buttons, form labels |
| small | Work Sans | 13 / 18 | 400 | |
| mono | JetBrains Mono | 13 / 20 | 400 | logs, metrics, numbers |
| eyebrow | JetBrains Mono | 11 / 16 | 400 | UPPERCASE, letter-spacing 0.12em, `--ink-muted` |

**Signature move:** small uppercase mono eyebrow, then a 1px hairline, then a big light Fraunces headline.

### Categorical colors

For telling groups apart, and only as small markers: dots, tags, 1px chart lines, left-edge ticks. Never large fills, never text.

| Token | Value | Good for |
| --- | --- | --- |
| `--pigment` | `#A65A48` | The most important group |
| `--gold` | `#B48322` | Highlighted / featured |
| `--sage` | `#5E6B4E` | Done, passed, growth |
| `--slate` | `#4F5F6B` | Research, info, neutral data |
| `--dust-rose` | `#8A5A62` | People, social, human-side stuff |
| `--walnut` | `#5A4334` | Archive, misc, "other" |

- Max 6 groups. If you need more, the grouping is wrong: use a hierarchy or text labels.
- Always pair color with a label or shape. Pigment and dust rose are close for colorblind readers, so never rely on color alone.
- Fixed order: assign in the order above, so a group is the same color everywhere. Skip pigment or gold when the screen already uses them for the key series or the highlight.
- `--danger` stays separate. It's for errors only, never a category.

### Smaller components

- **Text link:** `--ink` with 1px `--gold` underline, offset 4px.
- **Input:** transparent, bottom border only (1px `--hairline`), focus border `--maroon`.
- **Tabs:** mono eyebrow labels; active tab gets a 1px `--gold` underline.
- **Charts:** `--ink` lines, `--pigment` for the series that matters, `--gold` for reference lines, `--hairline` grid. No fills.
- **Focus ring:** 1px solid `--maroon`, offset 2px.
- **One gold hairline per page** marks the thing that matters (active tab, key stat, hero divider).
- No shadows, no gradients, no glows. The concrete photo is the only texture.
- Mobile: 16px side gutter, no horizontal scroll.

## 10. Voice and imagery

Direct, specific, calm. A researcher who also makes things.

- Yes: "Models optimize what you measure. We're building ones with a point of view."
- Yes: "Taste is learned by living. So we let models live."
- No: "Unlocking the ancient wisdom of creativity through AI."
- No spiritual language: no "sacred", no "spirit of".

Imagery: black-and-white or warm-toned photos of human craft: hands, paper, studios, instruments, worn tools. Film grain welcome. Abstract visuals are built from the four materials only. No neon, no glowing brains, no robots.

## 11. Cultural ground rules (hard rules)

Kokopelli is a Hopi katsina with roots in Ancestral Puebloan rock art. Never use, in any UI, asset, placeholder, icon or generated image:

- The humpbacked flute-player figure, in any style
- The Zia sun symbol
- Katsina forms, Pueblo pottery, weaving or sand-painting motifs, "tribal" borders, feathers, dreamcatchers, arrows
- Imagery prompted with "Native American", "Pueblo", "tribal" or any nation's name

The mark is the Nazca monkey (section 3). Any other glyph is traced from a named source image and is shown with the name of its site. No invented or generic "ancient" glyphs, and none from the list above.

"Our past" means the shared human past (craft, letters, paper, building), never Indigenous peoples as a symbol of the past.

## 12. Checklist before shipping a screen

- [ ] Only tokens from sections 7 and 9. No hard-coded colors outside them
- [ ] At most one maroon field, one pigment series, and one gold hairline emphasis
- [ ] No shadows, gradients, rounded cards
- [ ] Text contrast 4.5:1. Muted ink only on ground and panel
- [ ] The mark is never below 32px
- [ ] Works at 375px wide
- [ ] Nothing from section 11
