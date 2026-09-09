# FarmOS Weekly Farm Report Generator

Computes a weekly statistics report (environment, actuator behaviour, data health)
from raw Automated Cooling and Spraying System logs for Kampot Farm.

## Requirements
```
pip install -r requirements.txt
```
(pandas, numpy, matplotlib — see `requirements.txt`)

## Reproduce every number in the report with one command
```
python init.py --file "Automated_Cooling_and_Spraying_Data.csv" --start 2026-05-11 --out week_report.json
```
This reads the raw CSV, computes the week starting `2026-05-11`, and writes
`report.json` containing every metric quoted in the report.

## Configuration
`config` in `compute_weekly_report()` — do not hard-code these:
| Key | Meaning | Default |
|---|---|---|
| `temp_threshold` | °C above which time is flagged "hot" | 35.0 |
| `flow_rate_lpm` | pump flow rate, used to estimate litres sprayed | 5.0 |
| `gap_threshold_sec` | gap length counted as a logger outage | 300.0 |

## Output
See `week_report_sample.json` for one full example output. Every metric
carries the coverage (`uptime_percent`) it was computed from; `warnings`
lists anything that limits how the numbers should be read (e.g. low uptime).

## Known data issues in our window
- (fill in once you've plotted your data — e.g. "3.5 hours missing on 2026-05-13")
- (out-of-order timestamps? bursty intervals? state here what you found)
