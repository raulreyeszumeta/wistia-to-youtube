#!/bin/bash
# Weekly YouTube Report — runs Mondays at 5am via cron
cd "$(dirname "$0")"
/usr/bin/python3 youtube_report.py >> logs/cron_weekly_report.log 2>&1
