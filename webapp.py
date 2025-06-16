#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WeatherAlerts Web Dashboard

Usage:
  python webapp.py -c /path/to/config.yaml -p PORT

Routes:
  /                          → redirects to /weatheralerts
  /weatheralerts             → Current Alerts page
  /weatheralerts/log         → POST endpoint for CLI app to log events
  /weatheralerts/logs.html   → Alert Event Logs page (timestamps in ET)
  /weatheralerts/logs.json   → JSON dump of in-memory log (raw UTC)
  /api/alerts                → JSON endpoint for current alerts
"""
import os
import argparse
import requests
import re
import logging
from datetime import datetime, timezone, timedelta
from dateutil import parser
from flask import Flask, render_template, jsonify, abort, redirect, request
from ruamel.yaml import YAML
import fnmatch

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except ImportError:
    from backports.zoneinfo import ZoneInfo  # Requires `pip install backports.zoneinfo` for <3.9

from werkzeug.middleware.proxy_fix import ProxyFix

logging.basicConfig(level=logging.INFO)

BASE_DIR = os.path.dirname(os.path.realpath(__file__))
arg_parser = argparse.ArgumentParser(description='WeatherAlerts Dashboard')
arg_parser.add_argument('-c', '--config',
                    default=os.path.join(BASE_DIR, 'config.yaml'),
                    help='Path to YAML config file')
arg_parser.add_argument('-p', '--port', type=int, default=5000,
                    help='Port to run the web server on')
args = arg_parser.parse_args()

yaml = YAML()
def load_config():
    with open(args.config) as f:
        return yaml.load(f)

config = load_config()

USER_AGENT = config.get('Webapp', {}).get('UserAgent', 'WeatherAlertsBot/1.0 (no-contact@example.com)')

blocked_events = config.get('Alerting', {}).get('GlobalBlockedEvents', []) or []

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.url_map.strict_slashes = False

alert_logs = []
last_prune_date = datetime.now(timezone.utc).date()

def prune_logs():
    global alert_logs, last_prune_date
    today = datetime.now(timezone.utc).date()
    if today != last_prune_date:
        cutoff = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
        new_logs = []
        for entry in alert_logs:
            ts = entry.get('timestamp')
            try:
                dt = parser.isoparse(ts)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt >= cutoff:
                    new_logs.append(entry)
            except Exception:
                continue
        alert_logs = new_logs
        last_prune_date = today

@app.route('/weatheralerts/log', methods=['POST'])
def log_event():
    data = request.get_json() or {}
    event = data.get('event', '')
    if any(fnmatch.fnmatch(event, pat) for pat in blocked_events):
        app.logger.info(f"Blocked log event: {event}")
        return ('', 204)

    ts = data.get('timestamp') or datetime.now(timezone.utc).isoformat()
    entry = {
        'timestamp':   ts,
        'county':      data.get('county', 'UNKNOWN'),
        'event':       event,
        'description': data.get('description', '')
    }
    app.logger.info("Received log event: {}".format(entry))
    alert_logs.append(entry)
    return ('', 204)

@app.before_request
def reload_cfg():
    global config, blocked_events
    config = load_config()

USER_AGENT = config.get('Webapp', {}).get('UserAgent', 'WeatherAlertsBot/1.0 (no-contact@example.com)')

    blocked_events = config.get('Alerting', {}).get('GlobalBlockedEvents', []) or []

@app.after_request
def no_cache(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma']        = 'no-cache'
    response.headers['Expires']       = '0'
    return response

def get_settings():
    a = config.get('Alerting', {})
    counties = a.get('CountyCodes', [])
    labels   = a.get('CountyLabels', {})
    tt       = a.get('TimeType', 'onset').lower()
    sk, ek   = ('effective','expires') if tt=='effective' else ('onset','ends')

    d      = config.get('DEV', {})
    inject = d.get('INJECT', False)
    tests  = d.get('INJECTALERTS', [])
    prefix = d.get('PrefixMessage','')

    maxw = config.get('SkyDescribe', {}).get('MaxWords', 150) or 150
    return counties, labels, sk, ek, inject, tests, prefix, maxw

def modify_description(text, maxw):
    text = re.sub(r'\s+', ' ', text.replace('\n', ' '))
    text = re.sub(r'\*\s*(WHAT|WHERE|WHEN|IMPACTS|ADDITIONAL DETAILS)\.\s*', r'*\1: ', text, flags=re.IGNORECASE)
    # abbreviation replacements omitted for brevity...
    words = text.split()
    return ' '.join(words[:maxw]) if len(words) > maxw else text

def fetch_alerts_for_zone(zone, sk, ek, maxw):
    try:
        r = requests.get(
            'https://api.weather.gov/alerts/active?zone={}'.format(zone),
            timeout=10,
            headers={'Cache-Control':'no-cache'}
        )
        r.raise_for_status()
    except requests.RequestException:
        return []
    now = datetime.now(timezone.utc)
    outs = []
    for feat in r.json().get('features', []):
        p  = feat.get('properties',{})
        ev = p.get('event')
        if not ev or any(fnmatch.fnmatch(ev, pat) for pat in blocked_events):
            continue
        st = p.get(sk)
        ed = p.get(ek) or p.get('expires')
        if not (ev and st and ed):
            continue
        sdt = parser.isoparse(st).astimezone(timezone.utc)
        edt = parser.isoparse(ed).astimezone(timezone.utc)
        if sdt <= now < edt:
            desc  = p.get('description','')
            clean = modify_description("{}: {}".format(ev, desc), maxw)
            outs.append({'event':ev, 'description':clean})
    return outs

def build_dashboard():
    counties, labels, sk, ek, inject, tests, prefix, maxw = get_settings()
    inj_map, global_tests = {}, []
    if inject:
        for t in tests:
            code = t.get('Code')
            if code in counties:
                inj_map.setdefault(code,[]).append(t)
            else:
                global_tests.append(t)

    dashboard = {}
    for code in counties:
        label = labels.get(code, code)
        real  = fetch_alerts_for_zone(code, sk, ek, maxw)
        injected = []
        for t in inj_map.get(code, []):
            ev   = t['Title']
            desc = (prefix + t['Description']) if prefix else t['Description']
            injected.append({'event':ev,'description':desc})
        for t in global_tests:
            ev   = t['Title']
            desc = (prefix + t['Description']) if prefix else t['Description']
            injected.append({'event':ev,'description':desc})
        dashboard[label] = injected + real
    return dashboard

@app.route('/')
def root():
    return redirect('/weatheralerts')

@app.route('/weatheralerts')
@app.route('/weatheralerts/')
def current():
    try:
        data = build_dashboard()
    except Exception:
        abort(502)
    dev_flag = get_settings()[4]
    prune_logs()
    return render_template('index.html', dashboard=data, dev=dev_flag)

@app.route('/weatheralerts/logs.html')
def logs():
    prune_logs()

    def format_est(ts):
        try:
            dt = parser.isoparse(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            est = dt.astimezone(ZoneInfo("America/New_York"))
            return est.strftime('%Y-%m-%d %H:%M:%S %Z')
        except Exception:
            return ts

    labels = config.get('Alerting', {}).get('CountyLabels', {})
    formatted_logs = []
    for log in alert_logs:
        ts = format_est(log['timestamp'])
        zone = log.get('county', 'UNKNOWN')
        label = labels.get(zone, zone)
        new_log = dict(log, timestamp=ts, county_label=label)
        formatted_logs.append(new_log)

    used_zones = sorted(set(log.get('county', '') for log in alert_logs))
    county_labels = {z: labels.get(z, z) for z in used_zones}

    return render_template('logs.html', logs=formatted_logs, labels=county_labels)

@app.route('/weatheralerts/logs.json')
def logs_json():
    prune_logs()
    return jsonify(alert_logs)

@app.route('/api/alerts')
def api_alerts():
    return jsonify(build_dashboard())

if __name__ == '__main__':
    port = config.get('Webapp', {}).get('Port', 5000)
    app.run(host='0.0.0.0', port=port, debug=False)