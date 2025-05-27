Welcome to the WeatherAlerts application! This project provides real-time weather alerts tailored for your region.


## 🛠 Features

- 🚨 Sends real-time weather alerts via Telegram
- 📋 Logs and displays alerts on a Flask-based web dashboard
- ⚙ Configurable per-county routing and filtering
- 🔍 Filters global events you don't care about
- 🔧 Optional test mode for dev environments


## 🚀 Getting Started

These instructions will get the app up and running on your local machine.

### 📥 Clone the Repository

```bash
apt install Python3 git
git clone [https://github.com/mkarp87/weatheralerts.git](https://github.com/mkarp87/WeatherTelegramAlerts.git)
cd weatheralerts

### 📥 Install the virtual Environment:
python3 -m venv venv
source venv/bin/activate

### 📥 Install dependencies
pip install -r requirements.txt

# Run the application
python3 WeatherAlerts.py
python3 webapp.py
