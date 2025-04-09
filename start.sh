#!/usr/bin/bash

export DISPLAY=:0.0
source .venv/bin/activate
python3 pymedia.py config_audio.ini > audio.log 2>&1 & 
python3 pymedia.py config_video_monitor0.ini > video0.log 2>&1 &
python3 pymedia.py config_video_monitor1.ini > video1.log 2>&1 &
