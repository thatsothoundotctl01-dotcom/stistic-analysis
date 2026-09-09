# FarmOS Weekly Komport Farm

Generates a weekly statistics report (temperature, humidity, pump/spray activity)
from the farm's sensor data CSV.


## Setup (Ubuntu)

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
```

## Notes
- Threshold, flow rate, and gap settings can be changed in the `config` dict inside `init.py`.
- Sample output already in the repo: `all_weeks_report.json`.
- When done working, exit the virtual environment with `deactivate`.
