#!/bin/bash
eval "$(conda shell.bash hook)"
conda activate dictation
cd "$(dirname "$0")"
echo "" > dictation.log
exec python3 app.py 2>&1
