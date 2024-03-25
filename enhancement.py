def parental_controls(message):
    if "math" in message:
        if is_parental_control_enabled() and not is_math_topic_allowed():
            return "Sorry, this topic is restricted by parental controls."
    return None

# Usage:
restricted_response = parental_controls("Let's learn advanced calculus!")
