@echo off
chcp 65001 > nul
set PYTHONUTF8=1

cd /d "%~dp0"
python dump_configs.py --format json > configs_dump.json
echo Dumped to configs_dump.json
pause
