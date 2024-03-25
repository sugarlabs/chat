import speech_recognition as sr

def recognize_speech():
    recognizer = sr.Recognizer()
    with sr.Microphone() as source:
        audio = recognizer.listen(source)
    try:
        user_input = recognizer.recognize_google(audio)
        return user_input
    except sr.UnknownValueError:
        return "Sorry, I couldn't understand that."

# Usage:
user_input = recognize_speech()
