# DESIGN.md - mfi-server web page

## Concept
A Home Assistant companion page. It uses a light grey canvas, white rounded cards with a soft shadow and the HA light blue as the only accent. A dark theme follows the operating system automatically. The numbers and the outlet switches are the content. Everything else is quiet.

## Brand values
These live only in `mfi-server/mfi_server/web/style.css`, on `:root`. That is the only CSS file, and there is no other variables file. `@media (prefers-color-scheme: dark) { :root { ... } }` redefines the variables that have a dark value. It adds no new names. `:root` also sets `color-scheme: light dark`. Always write `var(--name)`. Never repeat a value as a literal.

| CSS variable | Light | Dark | Use |
|---|---|---|---|
| `--ink` | `#212121` | `#e1e1e1` | body text, headings, tile values, active tab, text on chips and tags |
| `--ink-muted` | `#727272` | `#9e9e9e` | secondary text: version, model, MAC, last seen, labels, inactive tabs, input borders. **Only on `--surface`**, never on `--paper` |
| `--paper` | `#f5f6f8` | `#111318` | page background |
| `--surface` | `#ffffff` | `#1c1f26` | top bar, cards, tiles, table, inputs, metric buttons |
| `--rule` | `#e0e0e0` | `#2e323b` | 1px dividers, table rows, chart grid. Lines only, never text |
| `--signal` | `#03a9f4` | `#03a9f4` | accent fill: primary button, ON switch, active-tab underline, chart line. **Never text in the light theme** |
| `--on-signal` | `#111318` | `#111318` | text and knob on `--signal` |
| `--link` | `#0277bd` | `#4fc3f7` | link text (on `--surface` only), focus ring, model icon stroke |
| `--chip` | `#e1f5fe` | `#0d2a3a` | 40px icon circle, `.tag--known` background |
| `--switch-off` | `#dfe1e5` | `#3a3f4a` | OFF switch track |
| `--warn-bg` | `#fff4d6` | `#3a3116` | backup warning and `.tag--default` background |
| `--warn-edge` | `#f9a825` | `#f9a825` | 4px left border of the warning. Line only |
| `--state-connected` | `#43a047` | `#43a047` | dot, card left edge, chip border. Fill or line only |
| `--state-lost` | `#e53935` | `#e53935` | same as above, plus the danger button border |
| `--state-unknown` | `#fb8c00` | `#fb8c00` | same as above |
| `--state-lost-text` | `#c62828` | `#ef9a9a` | error text (`.message--error`, `.port__error`, `.errors`) |
| `--shadow-card` | `0 1px 2px rgba(0,0,0,.08), 0 2px 6px rgba(0,0,0,.06)` | `0 1px 3px rgba(0,0,0,.5)` | cards, tiles, top bar |
| `--font-ui` | `Roboto, "Noto Sans", "Segoe UI", "Helvetica Neue", Arial, sans-serif` | - | all text |
| `--font-mono` | `"SFMono-Regular", Menlo, Consolas, "Liberation Mono", monospace` | - | MAC addresses, YAML |
| `--radius-panel` | `12px` | - | cards, tiles, login, chart, table wrapper |
| `--radius-control` | `8px` | - | buttons, inputs, select, metric buttons |
| `--space-1` .. `--space-6` | `4, 8, 12, 16, 24, 40px` | - | the only spacing steps |

`--header-muted` is removed.

## Contrast (WCAG formula, computed)
| Pair | Light | Dark |
|---|---|---|
| `--ink` on `--surface` / `--paper` | 16.1 / 14.9 | 12.6 / 14.2 |
| `--ink-muted` on `--surface` | 4.81 | 6.16 |
| `--ink-muted` on `--paper` | **4.45, forbidden** | 6.9 |
| `--on-signal` on `--signal` | 7.06 | 7.06 |
| `--link` on `--surface` | 4.80 | 8.1 |
| `--state-lost-text` on `--surface` / `--paper` | 5.62 / 5.2 | 7.7 |
| `--ink` on `--switch-off` / `--warn-bg` / `--chip` | >12 | >8 |
| white on `--signal` | **2.63, forbidden** | - |
| `--state-*` as text on white | **3.3 / 4.23 / 2.4, forbidden** | - |

Text on `--paper` uses `--ink` only. Do not add a text colour that is not in this table.

## Typography
All numbers use `font-variant-numeric: tabular-nums`.

| Role | Size | Weight | Line height | Letter spacing |
|---|---|---|---|---|
| App title (h1, top bar) | 20px | 500 | 1.2 | -0.01em |
| Section heading (h2) | 22px | 500 | 1.15 | -0.02em |
| Card title (device name, chart h3) | 17px | 500 | 1.25 | 0 |
| Body, inputs | 16px | 400 | 1.5 | 0 |
| Buttons, tabs | 14px | 500 | 1 | 0.01em |
| Secondary (meta, messages, table) | 14px | 400 | 1.5 | 0 |
| Tile value | 28px (32px from 600px) | 500 | 1.05 | -0.02em |
| Tile label, metric label, th | 13px | 500 | 1.3 | 0.02em |
| Metric value | 18px, with the unit at 13px `--ink-muted` | 500 | 1.1 | 0 |

Prose (messages, empty state) has `max-width: 65ch`.

## Grid and spacing
- Mobile first. The wrapper `main.page` has `max-width: 1280px; margin: 0 auto`. Padding is `--space-4` below 600px and `--space-5` from 600px.
- `.tab-section` has `padding-top: var(--space-5)`. Its h2 has `margin: 0 0 var(--space-4)`.
- `.tiles`: grid, `gap: var(--space-4)`. 2 columns below 600px, 4 columns from 600px.
- `#devices`: grid, `gap: var(--space-4)`. 1 column, `repeat(2, minmax(0,1fr))` from 600px, `repeat(3, minmax(0,1fr))` from 1200px.
- Card padding is `--space-4`. Login padding is `--space-6` `--space-5`.
- No horizontal page scroll at 320px. Long names use `overflow-wrap: anywhere`. Only `.tabs` and `.table-wrap` may scroll sideways on their own.

## Components
- **Top bar** `.topbar`: full width, `--surface`, `--shadow-card`, `position: sticky; top: 0; z-index: 10`.
  - Row 1 is the inner max-width 1280px, padding `--space-3` `--space-4`, flex with space-between. It holds the h1 and `#version` (14px `--ink-muted`) on the left, and the `#lang` select (36px) and `#logout-button` on the right.
  - Row 2 is `.tabs`.
- **Tabs** `.tabs`: `display: flex; overflow-x: auto`, padding 0 `--space-2`.
  - `.tab`: height 48px, padding 0 `--space-4`, inline-flex centered, `--ink-muted`, no underline, `border-bottom: 3px solid transparent`, `white-space: nowrap`.
  - Hover: `--ink`.
  - `.tab[aria-current="page"]`: `--ink`, weight 700, `border-bottom-color: var(--signal)`.
- **Card** (`.panel`, `.tile`, `.device-card`, `.auto`): `--surface`, `--radius-panel`, `--shadow-card`, no border.
- **Tile**: `.tile__label` (`--ink-muted`) above `.tile__value` (`--ink`), `gap: var(--space-2)`, min-height 104px.
- **Device card**: `border-left: 4px solid` in the state colour (`.device-card--connected` / `--lost` / `--unknown`).
  - `.device-card__head` is a flex row with `gap: var(--space-3)`: icon, then name and meta, then the state chip on the right.
  - `.device-card__icon` is a 40px circle in `--chip`, padding 8px, colour `--link`. The SVG uses `fill: none; stroke: currentColor; stroke-width: 1.75; stroke-linecap: round; stroke-linejoin: round`.
- **State chip** `.state`: inline-flex, height 24px, padding 0 `--space-3`, radius 999px, 1px border in the state colour, gap 6px, 13px 500 `--ink` text. `.state__dot` is 8px round in the state colour.
- **Switch** `.switch` (and `.toggle`, same rules): a `<button>` with `aria-pressed`.
  - Size: min-width 76px, height 32px, radius 999px, inline-flex, gap `--space-2`, padding 0 `--space-3` 0 `--space-1`, 14px 500.
  - `::before` is the knob: 24px circle.
  - Off: `--switch-off` track, `--ink` text, `--ink-muted` knob.
  - On (`aria-pressed="true"`): `--signal` track, `--on-signal` text and knob, `flex-direction: row-reverse` with mirrored padding.
  - Busy: `disabled`, `opacity: .6`.
- **Port row** `.port`: `border-top: 1px solid var(--rule)`, padding `--space-3` 0. The head row has the label (15px 500) and the switch on the right. `.metrics` is `grid-template-columns: repeat(3, minmax(0,1fr)); gap: var(--space-2)`.
- **Metric** `.metric`: `--surface`, 1px `--rule` border, `--radius-control`, padding `--space-2` `--space-3`, text left aligned. Hover: border `--link`.
- **Buttons**: min-height 40px (44px at login), padding 0 `--space-4`, `--radius-control`.
  - `.button--primary`: `--signal` background, `--on-signal` text, no border.
  - Secondary (logout, chart close): transparent, 1px `--rule` border, `--ink` text.
  - `.button--danger`: transparent, 1px `--state-lost` border, `--ink` text.
- **Input / select**: min-height 44px, `--surface`, 1px `--ink-muted` border, `--radius-control`, `--ink` text.
- **Messages** `.message`: 14px, left border 4px, padding `--space-3` `--space-4`, `--radius-control`.
  - Warning `#backup-message`: `--warn-bg` background, `--warn-edge` border, `--ink` text.
  - `.message--ok`: `--state-connected` edge.
  - `.message--error`: `--state-lost` edge and `--state-lost-text` text.
- **Table**: `.table-wrap` is a card with `overflow-x: auto`. `.table` is 100% wide.
  - `th` is 13px 500 `--ink-muted`, left aligned, padding `--space-3` `--space-4`.
  - `td` is `height: 48px`, `border-top: 1px solid var(--rule)`.
  - `.mono` uses `--font-mono` at 14px.
- **Tags** `.tag`: 12px 500, padding 2px `--space-2`, radius 999px, `--ink` text.
  - `--default`: `--warn-bg`.
  - `--known`: `--chip`.
  - `--other`: 1px `--rule` border.
- **Chart** `#chart`: a card. The polyline has `stroke: var(--signal); stroke-width: 2; fill: none; vector-effect: non-scaling-stroke`. Grid lines use `--rule`.
- **Focus**: `:focus-visible { outline: 3px solid var(--link); outline-offset: 2px; }` on every interactive element.
- `[hidden] { display: none !important; }` is always present.

## Motion
- Only `transform` and `opacity` animate: the switch knob and the button press, 150ms ease-out. Colour changes are instant.
- No loops and no entrance animations. Nothing is hidden at rest.
- Under `prefers-reduced-motion: reduce`: `transition: none`.

## CSP constraints
CSP is `style-src 'self'; script-src 'self'`.
- No `style=` attributes.
- No `<style>` or inline `<script>`.
- No `setAttribute("style")`.
- JS changes the look only through classes, `hidden`, `aria-pressed` and `aria-current`.

## Do not
- No gradients, glass, emoji, icon fonts, web fonts or network assets.
- No theme switch button.
- No white text on `--signal`. No `--signal` or `--state-*` as text colour.
- No `--ink-muted` on `--paper`. No text in `--rule`.
- No blue top bar. The bar is `--surface`.
- Never use a radius, shadow, spacing or colour that is not in the table above.
