@echo off
cd /d "%~dp0"
python -m pip install -r requirements.txt --quiet
python -m streamlit run app.py --server.port 8798
