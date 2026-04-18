@echo off
cd /d "%~dp0"

echo Setting up environment...

IF NOT EXIST venv (
    py -3.10 -m venv venv
)

call venv\Scripts\activate

pip install --no-cache-dir --use-deprecated=legacy-resolver -r requirements.txt
echo Starting app...
python3 main.py

pause