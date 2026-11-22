# Creator studio contrast evidence — 2026-11-22

This is a static, partial audit of the dark theme in `frontend/src/styles.css`
at master `95c4fc4`. Ratios use WCAG relative luminance for opaque sRGB
colors. They are rounded to two decimal places. CSS inheritance, transparency,
focus indicators, actual adjacent pixels and all interface states still need
rendered-browser verification. This is not a WCAG conformance assessment.

| Foreground | Background | Ratio | Example |
| --- | --- | ---: | --- |
| `#f8fafc` | `#0b1020` | 18.10:1 | Primary text on workspace |
| `#f8fafc` | `#151d30` | 16.05:1 | Primary text on surface |
| `#b8c4d8` | `#151d30` | 9.54:1 | Secondary text on surface |
| `#b8c4d8` | `#202d44` | 7.84:1 | Secondary text on subtle surface |
| `#67e8f9` | `#193444` | 8.96:1 | Current navigation link |
| `#082f49` | `#67e8f9` | 9.57:1 | Accent button text |
| `#ffb4a9` | `#151d30` | 9.88:1 | Form error on surface |
| `#67e8f9` | `#151d30` | 11.59:1 | Focus color against surface |
| `#36445b` | `#151d30` | 1.71:1 | Border token against surface |

The sampled text pairs exceed 4.5:1. The border pair falls below 3:1;
inspect each rendered use to determine whether the boundary is necessary to
identify an active control and compare against every adjacent color. Do not
infer a violation or a pass for every use from the token alone. Disabled
controls, opacity, patterned backgrounds, other theme combinations and focus
against all surroundings are not measured here. Automated browser checks,
keyboard and screen-reader checks remain outstanding.

The 100-node/150-edge responsiveness test remains open until the real editor
and inspector exist. No performance or overall accessibility claim follows
from these color calculations.
