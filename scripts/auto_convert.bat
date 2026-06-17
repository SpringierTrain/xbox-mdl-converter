@echo off

for /R %%a in (input\*.mdl) do (
	start /wait python convert_xbox.py %%a .\output --lod 2
)