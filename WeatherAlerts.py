#!/usr/bin/env python3
"""
WeatherAlerts.py

Fetches active weather alerts from the National Weather Service,
processes them, sends new or changed alerts to Telegram,
POSTs each event to the webapp for in-memory logging (including full description), and
repeats at the configured interval.
"""
import os
import sys
import json
import logging
import fnmatch
import requests
import re
import argparse
import time
from datetime import datetime, timezone
from dateutil import parser
from ruamel.yaml import YAML

# ----- CLI Argument Parsing -----
BASE_DIR = os.path.dirname(os.path.realpath(__file__))
arg_parser = argparse.ArgumentParser(description='WeatherAlerts System')
arg_parser.add_argument('-c', '--config', help='Path to YAML config file',
                        default=os.path.join(BASE_DIR, 'config.yaml'))
args = arg_parser.parse_args()
CONFIG_PATH = args.config
STATE_FILE  = os.path.join(BASE_DIR, 'last_alerts.json')

# ----- Load Configuration -----
yaml = YAML()
def load_config():
    with open(CONFIG_PATH, 'r') as f:
        return yaml.load(f)
config = load_config()

# ----- Logging -----
LOG_LEVEL = logging.DEBUG if config.get('Logging', {}).get('Debug', False) else logging.INFO
logging.basicConfig(level=LOG_LEVEL, format='%(asctime)s %(levelname)s %(message)s')
LOGGER = logging.getLogger(__name__)

# ----- Telegram Settings -----
tg_cfg = config.get('Telegram', {})
BOT_TOKEN       = tg_cfg.get('BotToken')
DEFAULT_CHAT_ID = tg_cfg.get('ChatID')
if not BOT_TOKEN:
    LOGGER.error("Telegram BotToken missing in config.")
    sys.exit(1)

# ----- Alert Routing & DEV Injection -----
alert_cfg       = config.get('Alerting', {})
county_codes    = alert_cfg.get('CountyCodes', [])
county_chat_map = alert_cfg.get('CountyChatMap', {})
global_blocked  = alert_cfg.get('GlobalBlockedEvents', []) or []
time_type       = alert_cfg.get('TimeType', 'onset').lower()
start_key, end_key = ('effective','expires') if time_type=='effective' else ('onset','ends')

dev_cfg         = config.get('DEV', {})
INJECT          = dev_cfg.get('INJECT', False)
INJECTALERTS    = dev_cfg.get('INJECTALERTS', [])
INJECT_PREFIX   = dev_cfg.get('PrefixMessage', '')
INJECT_CHAT_IDS = dev_cfg.get('InjectChatIDs', [])

# ----- Webapp Logging Endpoint -----
WEBHOOK_URL     = config.get('Webapp', {}).get('LogEndpoint')

# ----- Text Cleanup -----
MAX_WORDS = config.get('SkyDescribe', {}).get('MaxWords', 150) or 150

def modify_description(text: str) -> str:
    import re
    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text)

    # Normalize section headers like *WHAT. → *WHAT:
    text = re.sub(r"\*\s*(WHAT|WHERE|WHEN|IMPACTS|ADDITIONAL DETAILS)\.\s*", r"*\1: ", text, flags=re.IGNORECASE)

    abbreviations = {
        r"\bmph\b": "miles per hour",
        r"\bknots\b": "nautical miles per hour",
        r"\bNm\b": "nautical miles",
        r"\bnm\b": "nautical miles",
        r"\bft\.": "feet",
        r"\bin\.": "inches",
        r"\bm\b": "meter",
        r"\bkm\b": "kilometer",
        r"\bmi\b": "mile",
        r"%": "percent",
        r"\bN\b": "north",
        r"\bS\b": "south",
        r"\bE\b": "east",
        r"\bW\b": "west",
        r"\bNE\b": "northeast",
        r"\bNW\b": "northwest",
        r"\bSE\b": "southeast",
        r"\bSW\b": "southwest",
        r"\bF\b": "Fahrenheit",
        r"\bC\b": "Celsius",
        r"\bUV\b": "ultraviolet",
        r"\bgusts up to\b": "gusts of up to",
        r"\bhrs\b": "hours",
        r"\bhr\b": "hour",
        r"\bmin\b": "minute",
        r"\bsec\b": "second",
        r"\bsq\b": "square",
        r"w/": "with",
        r"c/o": "care of",
        r"\bblw\b": "below",
        r"\babv\b": "above",
        r"\bavg\b": "average",
        r"\bfr\b": "from",
        r"\btill\b": "until",
        r"b/w": "between",
        r"btwn": "between",
        r"N/A": "not available",
        r"&": "and",
        r"\+": "plus",
        r"e\.g\.": "for example",
        r"i\.e\.": "that is",
        r"est\.": "estimated",
        r"\.\.\.": ".",
        r"EDT": "eastern daylight time",
        r"(?<![a-zA-Z])EST(?![a-zA-Z])": "eastern standard time"
        r"CST": "central standard time",
        r"CDT": "central daylight time",
        r"MST": "mountain standard time",
        r"MDT": "mountain daylight time",
        r"PST": "pacific standard time",
        r"PDT": "pacific daylight time",
        r"AKST": "alaska standard time",
        r"AKDT": "alaska daylight time",
        r"HST": "hawaii standard time",
        r"HDT": "hawaii daylight time"
    }

    for abbr, full in abbreviations.items():
        text = re.sub(abbr, full, text, flags=re.IGNORECASE)

    # Clean up dots and spacing
    text = re.sub(r"\s*\.\.+", ".", text)
    text = re.sub(r":\s*\.", ":", text)
    text = re.sub(r"\s{2,}", " ", text)

    words = text.split()
    return " ".join(words[:MAX_WORDS]) if len(words) > MAX_WORDS else text
# ----- Telegram Sender -----
def send_telegram(text: str, chat_id: str):
    if config.get('WeatherAlerts', {}).get('Uppercase', False):
        text = text.upper()
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        LOGGER.info(f"Sent alert to chat {chat_id}")
    except Exception as e:
        LOGGER.error(f"Error sending to {chat_id}: {e}")

# ----- Fetch Active Alerts -----
def fetch_active_alerts():
    now = datetime.now(timezone.utc)
    alerts = []
    for zone in county_codes:
        try:
            r = requests.get(f"https://api.weather.gov/alerts/active?zone={zone}", timeout=10)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            LOGGER.error(f"Fetch error for {zone}: {e}")
            continue
        for feat in data.get('features', []):
            p = feat.get('properties', {})
            event = p.get('event'); aid = feat.get('id')
            if not event or any(fnmatch.fnmatch(event, pat) for pat in global_blocked):
                continue
            st = p.get(start_key); ed = p.get(end_key) or p.get('expires')
            if not (st and ed): continue
            sdt = parser.isoparse(st).astimezone(timezone.utc)
            edt = parser.isoparse(ed).astimezone(timezone.utc)
            if sdt <= now < edt:
                desc = p.get('description','').strip()
                chat = county_chat_map.get(zone) or DEFAULT_CHAT_ID
                alerts.append({'id':aid,'zone':zone,'chat_id':chat,
                               'Title':event,'Description':desc})
    return alerts

# ----- State Persistence -----
def load_state():
    try: return json.load(open(STATE_FILE))
    except: return []
def save_state(state):
    try: json.dump(state, open(STATE_FILE,'w'))
    except Exception as e: LOGGER.error(f"State save error: {e}")

# ----- Main Iteration -----
def main_iteration():
    prev = load_state()
    if INJECT:
        LOGGER.info("DEV mode: injecting test alerts")
        current=[]; targets = INJECT_CHAT_IDS or list(set(county_chat_map.values())|{DEFAULT_CHAT_ID})
        for a in INJECTALERTS:
            title = a['Title']; desc = a.get('Description','')
            if INJECT_PREFIX: desc = INJECT_PREFIX + desc
            for chat in targets:
                current.append({'id':f"inject_{chat}_{title}", 'zone':None,
                                'chat_id':chat, 'Title':title,'Description':desc})
    else:
        current = fetch_active_alerts()

    if not current:
        if prev:
            for e in prev:
                chat = e.get('chat_id') or DEFAULT_CHAT_ID
                send_telegram("ALL CLEAR: The national weather service has cleared all alerts for this area.", chat)
                if WEBHOOK_URL:
                    payload = {"timestamp":datetime.now(timezone.utc).isoformat(),
                               "county":e.get('zone') or 'ALL',
                               "event":"ALL CLEAR",
                               "description":""}
                    try: requests.post(WEBHOOK_URL, json=payload, timeout=5)
                    except: LOGGER.debug("Failed POST ALL CLEAR to webapp")
        save_state([])
        return

    pm = {e['id']:e for e in prev}
    to_send = [a for a in current if a['id'] not in pm or a['Description']!=pm[a['id']]['Description']]
    if not to_send:
        LOGGER.info("No new or changed alerts.")
    else:
        for a in to_send:
            chat = a['chat_id'] or DEFAULT_CHAT_ID
            text = f"Detailed alert for {a['Title']}. {a['Description']}"
            clean = modify_description(text)
            send_telegram(clean, chat)
            if WEBHOOK_URL:
                payload = {"timestamp":datetime.now(timezone.utc).isoformat(),
                           "county":a.get('zone') or 'DEV',
                           "event":a['Title'],
                           "description":a['Description']}
                try: requests.post(WEBHOOK_URL, json=payload, timeout=5)
                except: LOGGER.debug("Failed POST alert to webapp")
    save_state([{'id':a['id'],'chat_id':a['chat_id'],'Description':a['Description']} for a in current])

# ----- Poll Loop -----
if __name__=='__main__':
    interval = config.get('WeatherAlerts', {}).get('PollInterval', 300)
    LOGGER.info(f"Starting polling every {interval}s")
    while True:
        try: main_iteration()
        except Exception as e: LOGGER.exception(f"Unhandled exception: {e}")
        time.sleep(interval)
