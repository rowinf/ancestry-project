from flask import Flask, render_template, request, Response, stream_with_context
from dotenv import load_dotenv
import google.generativeai as genai
import os

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")

genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

SYSTEM_PROMPT = (
    "You are the Animus from Assassin's Creed. You are going to write me into a story involving one of my ancestors. "
    "You will ask me where I want to go in history. From that point on, we enter a simulation mode where you present me "
    "with some context from that part of history along with a couple of choices. Every choice I make in the story you will "
    "take into account and continue the story, but only three times. After I make three choices, the story wraps up and the simulation ends."
)



@app.route('/')
def questionnaire():
    return render_template('questionnaire.html')


@app.route('/stream', methods=['POST'])
def stream():
    interest = request.form.get('interest')
    ancestor_name = request.form.get('ancestor_name', 'unknown')
    birth_date = request.form.get('birth_date', 'an unknown time')

    if not interest:
        def error_stream():
            yield f"data: Interest is required!\n\n"
        return Response(error_stream(), mimetype="text/event-stream")

    user_input = f"""
    I want to explore {interest}.
    My ancestor's name is {ancestor_name} and they were born around {birth_date}.
    """

    def generate():
        try:
            model = genai.GenerativeModel("gemini-2.0-flash")  # or "gemini-2.5-pro" if supported
            chat = model.start_chat()
            chat.send_message(SYSTEM_PROMPT)

            for chunk in chat.send_message(user_input, stream=True):
                if chunk.text:
                    yield f"data: {chunk.text}\n\n"
        except Exception as e:
            yield f"data: [Error] {str(e)}\n\n"

    return Response(generate(), mimetype="text/event-stream")

