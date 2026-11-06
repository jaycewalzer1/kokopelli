# Kokopelli Labs Design System

A future that gives us our humanity back. Quiet, precise, warm: a research instrument made of old materials. Fine lines and exact spacing say "future". Earth browns, paper and muted gold say "the past we're restoring".

**Core rule: restraint.** Two browns, one clay, one gold, and a lot of hairline. If a screen feels colorful, remove something.

---

## 1. Color tokens

Light theme is the default. Dark theme applies via `prefers-color-scheme: dark` unless `data-theme="light"` is set, and also via `data-theme="dark"`.

| Token | Light | Dark | Use |
| --- | --- | --- | --- |
| `--surface-100` | `#F3EEE6` | `#14100D` | Page background (bone paper / warm near-black) |
| `--surface-200` | `#EAE3D8` | `#1E1814` | Cards, panels, code blocks |
| `--umber` | `#3B2A22` | `#33271F` | Deep brown fields: hero bands, footers, split layouts |
| `--hairline` | `#CFC4B4` | `#3A302A` | 1px rules, dividers, borders. The main structural element |
| `--ink` | `#2B1E18` | `#EDE5DA` | Body and display text. Dark brown, never pure black |
| `--ink-muted` | `#6E6056` | `#A89A8C` | Captions, metadata, eyebrows |
| `--clay` | `#8F4739` | `#C07A62` | Brand + the ONLY action color. One clay element per screen |
| `--gold` | `#9A7B40` | `#C4A66B` | Muted gold accent. 1px lines, index numerals, active underline. Never large fills, never body text on light |
| `--danger` | `#9E2A22` | `#E8877C` | Errors and destructive actions only |

Text on `--clay` and `--umber`: use `--surface-100` in light theme. On dark theme `--umber`, use `--ink`.

No other hues beyond these and the categorical colors below. No gradients. No shadows. No glows.

```css
:root {
  --surface-100: #F3EEE6;
  --surface-200: #EAE3D8;
  --umber: #3B2A22;
  --hairline: #CFC4B4;
  --ink: #2B1E18;
  --ink-muted: #6E6056;
  --clay: #8F4739;
  --gold: #9A7B40;
  --danger: #9E2A22;

  --font-serif: "Fraunces", Georgia, serif;
  --font-sans: "Work Sans", system-ui, sans-serif;
  --font-mono: "JetBrains Mono", ui-monospace, monospace;

  --space-2: 8px;
  --space-4: 16px;
  --space-6: 24px;
  --space-12: 48px;

  --radius-none: 0px;
  --radius-sm: 2px;
}

@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --surface-100: #14100D;
    --surface-200: #1E1814;
    --umber: #33271F;
    --hairline: #3A302A;
    --ink: #EDE5DA;
    --ink-muted: #A89A8C;
    --clay: #C07A62;
    --gold: #C4A66B;
    --danger: #E8877C;
  }
}

:root[data-theme="dark"] {
  --surface-100: #14100D;
  --surface-200: #1E1814;
  --umber: #33271F;
  --hairline: #3A302A;
  --ink: #EDE5DA;
  --ink-muted: #A89A8C;
  --clay: #C07A62;
  --gold: #C4A66B;
  --danger: #E8877C;
}

body {
  background: var(--surface-100);
  color: var(--ink);
  font-family: var(--font-sans);
  font-size: 16px;
  line-height: 24px;
}
```

Google Fonts:

```html
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,300;9..144,400&family=Work+Sans:wght@400;500&family=JetBrains+Mono:wght@400&display=swap">
```

---

### Categorical colors

For telling groups apart, and only as small markers: dots, tags, 1px chart lines, left-edge ticks. Never large fills.

| Token | Light | Dark | Good for |
| --- | --- | --- | --- |
| `--clay` | `#8F4739` | `#C07A62` | The most important group |
| `--gold` | `#9A7B40` | `#C4A66B` | Highlighted / featured |
| `--sage` | `#5E6B4E` | `#9AA88A` | Done, passed, growth |
| `--slate` | `#4F5F6B` | `#8E9EAA` | Research, info, neutral data |
| `--dust-rose` | `#8A5A62` | `#C2939A` | People, social, human-side stuff |
| `--walnut` | `#5A4334` | `#B39A86` | Archive, misc, "other" |

- Max 6 groups. If you need more, the grouping is wrong: use a hierarchy or text labels.
- Always pair color with a label or shape. Clay and dust rose are close for colorblind readers, so never rely on color alone.
- Fixed order: assign in the order above, so a group is the same color everywhere. Skip clay or gold when the screen already uses them for action or highlight.
- `--danger` stays separate. It's for errors only, never a category.

---

## 2. Typography

| Style | Family | Size / line height | Weight | Notes |
| --- | --- | --- | --- | --- |
| display | Fraunces | 64 / 64 | 300 | letter-spacing -0.02em |
| h1 | Fraunces | 40 / 44 | 300 | |
| h2 | Fraunces | 28 / 34 | 400 | |
| body | Work Sans | 16 / 24 | 400 | max line length ~65ch |
| label | Work Sans | 14 / 20 | 500 | buttons, form labels |
| small | Work Sans | 13 / 18 | 400 | |
| mono | JetBrains Mono | 13 / 20 | 400 | logs, metrics, numbers |
| eyebrow | JetBrains Mono | 11 / 16 | 400 | UPPERCASE, letter-spacing 0.12em, `--ink-muted` |

**Signature move:** small uppercase mono eyebrow, then a 1px hairline, then a big light Fraunces headline.

---

## 3. Line, shape, space

- **Hairlines are the system.** 1px `--hairline` rules divide sections, frame cards, underline inputs, draw chart axes.
- **One gold hairline per page** marks the thing that matters (active tab, key stat, hero divider).
- **Square corners.** `--radius-none` everywhere. `--radius-sm` (2px) on buttons and inputs only.
- **Generous space.** `--space-12` between sections, `--space-6` page margins, `--space-4` card padding. Nothing crowded.
- Mobile: 16px side gutter, no horizontal scroll.

---

## 4. Components

- **Primary button:** `--clay` background, `--surface-100` text, label style, `--radius-sm`, padding 10px 16px. Hover: darken ~8%. Only one per screen.
- **Secondary button:** transparent, 1px `--hairline` border, `--ink` text. Hover: border becomes `--ink`.
- **Text link:** `--ink` with 1px `--gold` underline, offset 4px.
- **Card:** `--surface-200` background, 1px `--hairline` border, no radius, no shadow, `--space-4` padding.
- **Input:** transparent, bottom border only (1px `--hairline`), focus border `--clay`.
- **Tabs:** mono eyebrow labels; active tab gets a 1px `--gold` underline.
- **Hero / footer:** full-bleed `--umber` field, `--surface-100` text, gold hairline accents.
- **Charts:** `--ink` lines, `--clay` for the series that matters, `--gold` for reference lines, `--hairline` grid. No fills.
- **Focus ring:** 1px solid `--clay`, offset 2px.

---

## 5. Voice

Direct, specific, calm. A researcher who also makes things.

- Yes: "Models optimize what you measure. We're building ones with a point of view."
- Yes: "Taste is learned by living. So we let models live."
- No: "Unlocking the ancient wisdom of creativity through AI."
- No spiritual language: no "sacred", no "spirit of".

---

## 6. Imagery

Black-and-white or warm-toned photos of human craft: hands, paper, studios, instruments, worn tools. Film grain welcome. Abstract visuals are built from these tokens only: brown fields and fine lines. No neon, no glowing brains, no robots.

---

## 7. Cultural ground rules (hard rules)

Kokopelli is a Hopi katsina with roots in Ancestral Puebloan rock art. Never use, in any UI, asset, placeholder, icon or generated image:

- The humpbacked flute-player figure, in any style
- The Zia sun symbol
- Petroglyph traces, katsina forms, pottery, weaving or sand-painting motifs, "tribal" borders, feathers, dreamcatchers, arrows
- Imagery prompted with "Native American", "Pueblo", "tribal" or any nation's name

"Kokopelli" appears as a plain-type wordmark only. No mascot. "Our past" means the shared human past (craft, letters, paper), never Indigenous peoples as a symbol of the past.

---

## 8. Checklist before shipping a screen

- [ ] Only tokens from section 1. No hard-coded colors outside them
- [ ] At most one `--clay` element and one gold hairline emphasis
- [ ] No shadows, gradients, rounded cards
- [ ] Text contrast 4.5:1 in both themes
- [ ] Works at 375px wide
- [ ] Nothing from section 7
