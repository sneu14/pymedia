#!/usr/bin/bash

export DISPLAY=:0.0
source .venv/bin/activate
python3 pymedia.py $1
sleep 5