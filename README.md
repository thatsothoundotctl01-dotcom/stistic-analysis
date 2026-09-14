# 🌱 FarmOS Weekly Komport Farm

FarmOS Weekly Komport Farm is a Python-based data analysis tool that generates **weekly farm statistics** from sensor data stored in a CSV file.

The system analyzes:

* 🌡️ Temperature
* 💧 Humidity
* 🚿 Pump / spraying activity
* ⏱️ System uptime and activity gaps
* 📊 Weekly statistics and reports

The generated reports can be saved as JSON files for further analysis, reporting, or project deliverables.

---

## 📋 Requirements

This project is currently designed for **Linux / Ubuntu**.

### Software

* Python 3
* pip
* Python virtual environment
* pandas

---

## 🚀 Installation

### 1. Update the system

```bash
sudo apt update
```

### 2. Install Python and required tools

```bash
sudo apt install python3 python3-pip python3-venv -y
```

### 3. Create a virtual environment

From the project directory:

```bash
python3 -m venv venv
```

### 4. Activate the virtual environment

```bash
source venv/bin/activate
```

After activation, your terminal should show something similar to:

```text
(venv) user@ubuntu:~/farmos_project$
```

### 5. Install Python dependencies

If the project contains a `requirements.txt` file:

```bash
pip install -r requirements.txt
```

If not, install pandas directly:

```bash
pip install pandas
```

# ▶️ How to Run

## 1. Generate a weekly report

Use the following command:

```bash
python3 farmos.py --csv "Automated Cooling and Spraying Data.csv" --start 2026-05-11 --out week2_report.json
```

### Parameters

| Parameter | Description                         |
| --------- | ----------------------------------- |
| `--csv`   | Input sensor CSV file               |
| `--start` | Starting date for the weekly report |
| `--out`   | Output JSON file                    |

Example:

```bash
python3 farmos.py \
  --csv "Automated Cooling and Spraying Data.csv" \
  --start 2026-05-11 \
  --out week2_report.json
```

This generates:

```text
week2_report.json
```

---

# 📦 Generate Project Deliverables

To generate the project's deliverables:

```bash
python3 farmos.py --csv "Automated Cooling and Spraying Data.csv" --deliverables
```

This command is intended to generate the required project output/report files from the sensor dataset.

---

# 🧪 Run Tests

If your `farmos.py` supports the test option, run:

```bash
python3 farmos.py --csv "Automated Cooling and Spraying Data.csv" --start 2026-05-11 --out week2_report.json
```

You can also check the available commands and options (json)  with:

```bash
python3 farmos.py --csv "Automated Cooling and Spraying Data.csv" --deliverables
```

---

# 📊 Input Data

The main input dataset is:

```text
Automated Cooling and Spraying Data.csv
```

The CSV contains farm sensor data used to calculate weekly statistics.

The analysis can include measurements such as:

* Temperature
* Humidity
* Pump activity
* Spraying activity
* System activity
* Time intervals between sensor records

---

# 📈 Reports

The program generates JSON reports containing weekly statistics.

Example output file:

```text
week2_report.json
```

For reports covering multiple weeks, the project may also contain:

```text
all_weeks_report.json
```

A report can contain information such as:

```json
{
  "week_start": "2026-05-11",
  "coverage": {
    "uptime_percent": 98.5,
    "gaps_over_5min": 2
  },
  "temperature_c": {
    "median": 31.4
  }
}
```

The exact fields depend on the configuration and implementation in `farmos.py`.

---

# ⚙️ Configuration

Project thresholds and analysis settings can be configured inside:

```text
farmos.py
```

Depending on the implementation, these settings may include:

* Temperature thresholds
* Humidity thresholds
* Flow rate
* Activity gap duration
* Pump/spray detection settings
* Weekly report settings

Before changing configuration values, make sure you understand how they affect the generated statistics.

---

# 🗓️ Weekly Analysis

The project can be used to analyze individual weeks or generate project deliverables covering multiple weeks.

Example:

```bash
python3 farmos.py \
  --csv "Automated Cooling and Spraying Data.csv" \
  --start 2026-05-11 \
  --out week2_report.json
```

For a complete project dataset/report, use:

```bash
python3 farmos.py \
  --csv "Automated Cooling and Spraying Data.csv" \
  --deliverables
```

---

# 🔍 Useful Commands

### Check Python version

```bash
python3 --version
```

### Check pip

```bash
pip --version
```

### Activate virtual environment

```bash
source venv/bin/activate
```

### Run the program

```bash
python3 farmos.py --help
```

### Check available options

```bash
python3 farmos.py --help
```

### Exit the virtual environment

When you finish working:

```bash
deactivate
```

---

# 🛠️ Troubleshooting

### `python3: command not found`

Install Python:

```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv -y
```

### `ModuleNotFoundError: No module named 'pandas'`

Activate the virtual environment:

```bash
source venv/bin/activate
```

Then install pandas:

```bash
pip install pandas
```

Or, if using `requirements.txt`:

```bash
pip install -r requirements.txt
```

### CSV file not found

Make sure the CSV file exists in the current directory:

```bash
ls
```

You should see:

```text
Automated Cooling and Spraying Data.csv
```

If the filename contains spaces, keep it inside quotes:

```bash
--csv "Automated Cooling and Spraying Data.csv"
```

### Check the project files

```bash
ls -lah
```

---

# 💡 Quick Start

For a new Linux/Ubuntu installation, the shortest workflow is:

```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv -y
```

Create and activate the environment:

```bash
python3 -m venv venv
source venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the weekly report:

```bash
python3 farmos.py \
  --csv "Automated Cooling and Spraying Data.csv" \
  --start 2026-05-11 \
  --out week2_report.json
```

Generate deliverables:

```bash
python3 farmos.py \
  --csv "Automated Cooling and Spraying Data.csv" \
  --deliverables
```

Exit when finished:

```bash
deactivate
```

---

