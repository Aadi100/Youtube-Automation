"""Clip Studio server.   python worker.py   ->  http://127.0.0.1:8765

Thin entry point: the application lives in the `app` package (models / views / controllers / services / engine).
Options:  --role web | worker | all     --show-setup-code
"""
from app.cli import main

if __name__ == "__main__":
    main()
