"""benchmarks/vision holds Molka's MANUAL benchmark scripts (local Ollama + images that are not in git).
Two of them are named test_*.py, so pytest would try to run them and fail at import. They are not tests:
pytest skips them here, and they are still run by hand (python benchmarks/vision/test_moondream.py)."""
collect_ignore_glob = ["test_moondream*.py"]
