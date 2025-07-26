from flask import Flask, render_template, request, redirect, url_for, flash, session, Response
from datastar_py import ServerSentEventGenerator as SSE, attribute_generator as data
from dotenv import load_dotenv
import google.generativeai as genai
import os
import asyncio
from datetime import datetime

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
    story = None

    if request.method == 'POST':
        interest = request.form.get('interest')
        ancestor_name = request.form.get('ancestor_name')
        birth_date = request.form.get('birth_date')

        if not interest:
            flash('Interest is required!', 'danger')
            return redirect(url_for('questionnaire'))

@app.route('/simulation', methods=['GET', 'POST'])
def simulation():
    if request.method == 'GET' and session.get('story'):
        return render_template('simulation.html', story=session.get('story'))
    interest = session.get('interest')
    ancestor_name = session.get('ancestor_name')
    birth_date = session.get('birth_date')

    user_input = f"""
        I want to explore {interest}.
        My ancestor's name is {ancestor_name or 'unknown'} and they were born around {birth_date or 'an unknown time'}.
        """

    try:
        model = genai.GenerativeModel("gemini-2.5-pro")
        convo = model.start_chat()
        convo.send_message(SYSTEM_PROMPT)
        convo.send_message(user_input)
        story = convo.last.text
        session['story'] = story
    except Exception as e:
        flash(f"Failed to generate story: {str(e)}", 'danger')
        return redirect(url_for('questionnaire'))

    return render_template('simulation.html', story=story)


@app.route("/updates", methods=['POST'])
def updates():
    decision = request.form.get('decision')
    def event_stream():
        yield SSE.patch_elements(f"""<span id="decision-1">{decision}</span>""")

    return Response(event_stream(), mimetype="text/event-stream")
