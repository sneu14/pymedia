#!/usr/bin/bash
#sleep 10
source .venv/bin/activate
python3 pymedia.py config_audio.ini > audio.log 2>&1 & 
python3 pymedia.py config_video.ini > video.log 2>&1 &
