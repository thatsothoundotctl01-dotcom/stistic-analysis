# FarmOS Weekly Komport Farm

Generates a weekly statistics report (temperature, humidity, pump/spray activity)
from the farm's sensor data CSV.


## Setup (only linux ) 

```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv -y

```

## How to run

```bash
python3 init.py --file "Automated Cooling and Spraying Data.csv" --start 2026-05-11 --out report.json
```

This creates `week_report.json` with all the numbers.

## Run tests

```bash
python3 init.py --test 
for date in 2026-05-04 2026-05-11 2026-05-18 2026-05-25 2026-06-01 2026-06-08 2026-06-15 2026-06-22 2026-06-29 2026-07-06 2026-07-13 2026-07-20 2026-07-27 2026-08-03 2026-08-10 2026-08-17 2026-08-24 2026-08-31; do echo "========== WEEK $date =========="; python3 init2.py --file "Automated Cooling and Spraying Data.csv" --start "$date" --out "report_$date.json"; done
```

## Notes
- Threshold, flow rate, and gap settings can be changed in the `config` dict inside `init.py`.
- Sample output already in the repo: `all_weeks_report.json`.
- When done working, exit the virtual environment with `deactivate`.
