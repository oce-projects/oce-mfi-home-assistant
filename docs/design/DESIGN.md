# DESIGN.md - mfi-server web page

## Concept
A meter panel, not a dashboard template. It feels like the front of an electrical cabinet: warm off-white paper, near-black ink and one copper-orange "signal" colour that marks live power. The numbers are the content. Every device is a plain bordered panel, and its state shows as a coloured left edge.

## Brand values
These live only in `mfi-server/mfi_server/web/style.css` on `:root`. That is the project's only CSS file. There is no other variables file. Use them by name, as `var(--signal)`, and never repeat the values as literals.

| CSS variable | Value | Use |
|---|---|---|
| `--ink` | `#1b1f1d` | body text, header band background, borders of off toggles |
| `--ink-muted` | `#545b57` | secondary text (model, last contact, metric labels), input borders |
| `--paper` | `#f4f2ec` | page background, metric hover background |
| `--surface` | `#ffffff` | device panels, login panel, chart panel, inputs |
| `--rule` | `#d9d5cb` | 1px panel borders, chart grid lines, dividers. Lines only, never text |
| `--signal` | `#9c4209` | the accent: ON toggle, primary button, chart line, focus ring |
| `--on-signal` | `#ffffff` | text on `--signal` |
| `--header-muted` | `#b9bdb9` | version text on the `--ink` header |
| `--state-connected` | `#1e7a46` | connected dot, left edge, state text |
| `--state-lost` | `#b3261e` | lost dot, left edge, state text, error text |
| `--state-unknown` | `#6b716d` | unknown dot, left edge, state text |
| `--font-ui` | `"Avenir Next", "Segoe UI", "Helvetica Neue", Arial, sans-serif` | all text |
| `--font-mono` | `"SFMono-Regular", Menlo, Consolas, "Liberation Mono", monospace` | MAC addresses only |
| `--radius-panel` | `10px` | device, login and chart panels |
| `--radius-control` | `6px` | buttons, inputs, select, metric buttons |
| `--space-1` .. `--space-6` | `4px, 8px, 12px, 16px, 24px, 40px` | the only spacing steps |

## Contrast (computed with the WCAG formula)
| Pair | Ratio |
|---|---|
| `--ink` on `--paper` / `--surface` | about 15:1 / 16:1 |
| `--ink-muted` on `--paper` / `--surface` | 6.2:1 / 7.0:1 |
| `--on-signal` on `--signal` | 6.6:1 |
| `--signal` on `--paper` (text) | 5.9:1 |
| `--header-muted` on `--ink` | 8.8:1 |
| `--state-connected` on `--surface` / `--paper` | 5.3:1 / 4.8:1 |
| `--state-lost` on `--surface` | 6.5:1 |
| `--state-unknown` on `--surface` | 5.0:1 |

`--rule` is never used for text. You may not add a text colour that is not in this table.

## Typography
- One family: `var(--font-ui)`. No web fonts, no network.
- All numbers use `font-variant-numeric: tabular-nums`.

| Role | Size | Weight | Line height | Letter spacing |
|---|---|---|---|---|
| App title (h1) | 22px (below 600px), 28px (600px and up) | 700 | 1.1 | -0.02em |
| Section heading (h2) | 20px | 700 | 1.15 | -0.01em |
| Chart title (h3), device name | 18px | 600 | 1.2 | 0 |
| Body, buttons, inputs | 16px | 400 / 600 for buttons | 1.5 | 0 |
| Secondary text (meta, messages) | 14px | 400 | 1.5 | 0 |
| Metric label | 12px, uppercase | 600 | 1.3 | 0.06em |
| Metric value | 20px | 600 | 1.1 | -0.01em |
| Metric unit | 14px | 400, `--ink-muted` | - | 0 |

- Prose (messages, empty state) has `max-width: 65ch`.

## Grid and spacing
- Mobile first. Page padding is `--space-4` (16px) below 600px and `--space-6` (40px) at 600px and up. Content `max-width: 1200px`, aligned left (`margin: 0 auto` on the wrapper, text never centred).
- Header: full-bleed `--ink` band, padding `--space-4` vertical. The title sits on the left and the controls (language, logout) on the right. Below 600px it wraps to two rows with `--space-2` between them.
- Device list: `display: grid; gap: var(--space-4)`. One column, and from 1024px `grid-template-columns: repeat(2, minmax(0, 1fr))`.
- Between sections: `--space-6`. Inside a panel: padding `--space-4` (below 600px `--space-3`).
- There must be no horizontal scroll at 320px. Long names use `overflow-wrap: anywhere`.

## Components
- **Device panel** `.device`: `--surface`, 1px `--rule` border, `--radius-panel`, a 4px left border in the state colour (`.device--connected`, `.device--lost`, `.device--unknown`). No shadow.
- **State** `.state`: a 10px round `.state__dot` in the state colour, then the translated text in the same colour, 14px 600.
- **Port row** `.port`: separated by a 1px `--rule` top border, padding `--space-3` 0. Line 1 has the label (`.port__label`, 16px 600) and the toggle on the right. Line 2 has the metrics.
- **Toggle** `.toggle` (a `<button>` with `aria-pressed`): min-height 36px, min-width 72px, padding 0 `--space-4`, radius 999px, 14px 600.
  - Off: `--surface` background, 1px `--ink-muted` border, `--ink` text.
  - On (`aria-pressed="true"`): `--signal` background and border, `--on-signal` text.
  - Busy: `disabled`, `opacity: .6`.
- **Metric** `.metric` (a `<button>`): `.metric__label` above, then `.metric__value` plus `.metric__unit`. Transparent background, 1px `--rule` border, `--radius-control`, padding `--space-2` `--space-3`, text left aligned. On hover it gets a `--paper` background.
  - Group `.metrics`: `display: grid; grid-template-columns: repeat(auto-fit, minmax(96px, 1fr)); gap: var(--space-2)`.
- **Primary button** (login): min-height 44px, `--signal` background, `--on-signal` text, 16px 600, `--radius-control`.
- **Secondary button** (logout, chart close): min-height 36px, transparent background, 1px border in the text colour, `--radius-control`.
- **Input / select**: min-height 44px (36px for the select in the header), `--surface`, 1px `--ink-muted` border, `--radius-control`, padding 0 `--space-3`, `--ink` text.
- **Messages** `.message`: 14px, a 3px left border and padding-left `--space-3`. Errors (`.message--error`, `.port__error`) use `--state-lost`.
- **Focus**: every interactive element has `:focus-visible { outline: 3px solid var(--signal); outline-offset: 2px; }`. On the `--ink` header, use `outline-color: var(--surface)`.
- **Chart**: an SVG with `viewBox="0 0 600 200"`, `width: 100%`, `height: 200px`. One `polyline`: `fill: none`, `stroke: var(--signal)`, `stroke-width: 2`, `vector-effect: non-scaling-stroke`. Horizontal grid lines at 0/50/100% in `--rule`.
- `[hidden] { display: none !important; }` is always present.

## Motion
- Only `opacity` and `transform` animate, in 150ms ease-out. Colour changes are instant.
- No loops, no entrance animations, nothing hidden at rest.
- Under `prefers-reduced-motion: reduce`, set `transition: none`.

## CSP constraints
The CSP is `style-src 'self'; script-src 'self'`.
- No `style=` attributes in the HTML.
- No `<style>` or inline `<script>`.
- No `setAttribute("style", ...)`.
- JS changes look only through classes and `hidden`.

## Do not
- No gradients, glass, shadows on panels, emoji, icon fonts or external assets.
- Never use `--signal` as large surfaces. It is only for ON toggles, the primary button, the chart line and focus.
- Never put grey text on `--paper` lighter than `--ink-muted`, and never put text in `--rule`.
- Never centre the page or the login panel horizontally.
- Never use a radius, spacing or colour that is not in the table above.
- No dark theme or theme switch (out of scope).
