"""Photo check (vision): what a customer's photo SHOWS, never what the customer wants.

schema.py  - the fixed answer format, the prompt, the parser (one place for both the model and the tests)
model.py   - Qwen3-VL-2B + the CallVerse QLoRA adapter (Hugging Face), with the base model as fallback
fusion.py  - late fusion: Intake's ticket (text) + the photo's visual evidence -> one ticket for the router
"""
