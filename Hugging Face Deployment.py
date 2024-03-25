from transformers import pipeline

# Load chatbot model from Hugging Face
chatbot = pipeline("conversational")

# Usage:
response = chatbot("Hello, how are you?")
