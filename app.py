from flask import Flask, render_template, request, redirect, url_for, flash, session, Response
from datastar_py import ServerSentEventGenerator as SSE, attribute_generator as data
from dotenv import load_dotenv
import google.generativeai as genai
import os
import asyncio
from datetime import datetime
import re

load_dotenv()

app = Flask(__name__)
# Ensure you have a SECRET_KEY in your .env file for session management
app.secret_key = os.getenv("SECRET_KEY")

# Ensure you have GOOGLE_API_KEY in your .env file
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

SYSTEM_PROMPT = (
    "You are the Animus from Assassin's Creed. You are going to write me into a story involving one of my ancestors. "
    "You will ask me where I want to go in history. From that point on, we enter a simulation mode where you present me "
    "with some context from that part of history along with a couple of choices. "
    "**Always present choices in the format: 'A) Choice 1 B) Choice 2 C) Choice 3'.** "
    "Every choice I make in the story you will take into account and continue the story, but only three times. "
    "After I make three choices, the story wraps up and the simulation ends. "
    "When the simulation ends, clearly state 'SIMULATION ENDED.' at the very end of the story. "
    "Ensure your responses are engaging and continue the narrative seamlessly based on user choices."
)

# Function to extract choices from the story text (e.g., "A) Option 1 B) Option 2")
def extract_choices(text):
    # This regex looks for a capital letter followed by ')', then captures the text until
    # another choice starts, or 'SIMULATION ENDED.', or the end of the string.
    choices = re.findall(r'([A-Z])\)\s(.*?)(?=\s[A-Z]\)|\s*SIMULATION ENDED\.|\Z)', text, re.DOTALL)
    # Filter out empty choices and clean up whitespace
    return [(key.strip(), value.strip()) for key, value in choices if key and value]

@app.route('/', methods=['GET', 'POST'])
def questionnaire():
    """
    Handles the initial questionnaire to gather user's ancestry interest.
    Initializes session variables for the simulation.
    """
    if request.method == 'POST':
        interest = request.form.get('interest')
        ancestor_name = request.form.get('ancestor_name')
        birth_date = request.form.get('birth_date')

        if not interest:
            flash('Your interest in ancestry is required!', 'danger')
            return redirect(url_for('questionnaire'))

        # Save data to session and initialize simulation state
        session['interest'] = interest
        session['ancestor_name'] = ancestor_name
        session['birth_date'] = birth_date
        session['choice_count'] = 0 # Track how many choices the user has made
        session['story'] = "" # Stores the cumulative story text
        session['convo_history'] = [] # Stores the raw conversation history for the model

        return redirect(url_for('simulation'))

    # For GET method, render the questionnaire form
    return render_template('questionnaire.html')

@app.route('/simulation', methods=['GET'])
def simulation():
    """
    Initiates or continues the Animus simulation.
    Generates the initial story segment based on questionnaire data.
    """
    interest = session.get('interest')
    ancestor_name = session.get('ancestor_name')
    birth_date = session.get('birth_date')
    current_story = session.get('story')
    choice_count = session.get('choice_count', 0)

    if not current_story: # Only generate initial story if not already present
        user_input = f"""
        I want to explore {interest}.
        My ancestor's name is {ancestor_name or 'unknown'} and they were born around {birth_date or 'an unknown time'}.
        """
        try:
            model = genai.GenerativeModel("gemini-2.0-flash")
            convo = model.start_chat()
            convo.send_message(SYSTEM_PROMPT)
            convo.send_message(user_input)
            initial_story_segment = convo.last.text

            session['story'] = initial_story_segment
            # Corrected: Store conversation history by extracting text from parts
            session['convo_history'] = [{"role": m.role, "parts": [{"text": part.text} for part in m.parts]} for m in convo.history]

        except Exception as e:
            flash(f"Failed to generate story: {str(e)}. Please try again.", 'danger')
            return redirect(url_for('questionnaire'))
    else:
        initial_story_segment = current_story # Use existing story if already in session

    choices = extract_choices(initial_story_segment)
    return render_template('simulation.html', story=initial_story_segment, choices=choices, choice_count=choice_count)

@app.route("/updates", methods=['POST'])
def updates():
    """
    Handles user decisions during the simulation.
    Sends the decision to the AI model, gets the next story segment,
    and streams updates back to the client using SSE.
    """
    decision = request.form.get('decision')
    current_story = session.get('story', '')
    choice_count = session.get('choice_count', 0)
    convo_history = session.get('convo_history', [])

    new_story_segment = ""
    choices_html = ""
    simulation_ended = False

    # Re-initialize the model and conversation with history to maintain context
    # Note: If convo_history is empty, start_chat() will still work, but it means
    # the history wasn't properly saved or the session was reset.
    model = genai.GenerativeModel("gemini-2.0-flash")
    convo = model.start_chat(history=convo_history)


    if choice_count < 3:
        try:
            convo.send_message(decision)
            new_story_segment = convo.last.text
            session['story'] = current_story + "\n\n" + new_story_segment # Append to cumulative story
            session['choice_count'] = choice_count + 1

            # Corrected: Update convo_history by extracting text from parts
            session['convo_history'] = [{"role": m.role, "parts": [{"text": part.text} for part in m.parts]} for m in convo.history]

            if "SIMULATION ENDED." in new_story_segment.upper(): # Check for end phrase
                simulation_ended = True
            elif session['choice_count'] >= 3: # Force end if 3 choices made, regardless of model output
                new_story_segment += "\n\nSIMULATION ENDED."
                simulation_ended = True
            else:
                # Extract new choices for the next turn
                choices = extract_choices(new_story_segment)
                if choices:
                    choices_html = "<p>Your choices:</p>"
                    for key, value in choices:
                        # Use data-on-click to send the full choice text as the decision
                        # Ensure value is properly escaped if it contains quotes
                        escaped_value = value.replace("'", "\\'") # Simple escape for single quotes
                        choices_html += f"""
                        <button class="btn btn-secondary me-2 mb-2"
                                data-on-click="@post('{url_for('updates')}', {{contentType: 'form', body: {{decision: '{key}) {escaped_value}'}}}})">{key}) {value}</button>
                        """
                else:
                    # Fallback if model doesn't provide choices but simulation isn't over
                    choices_html = "<p>Please type your next action or choice:</p>"

        except Exception as e:
            new_story_segment = f"\n\nError continuing story: {str(e)}. Simulation ended due to an unexpected error."
            simulation_ended = True
            session['story'] = current_story + new_story_segment
            session['choice_count'] = 3 # Force end due to error

    else:
        # If 3 choices already made or simulation was already ended
        new_story_segment = "\n\nSIMULATION ENDED. (No more choices allowed.)"
        simulation_ended = True

    # SSE stream generation
    def event_stream():
        # Append the new story segment to the story display
        yield SSE.patch_elements(f"""<div id="story-content" hx-swap-oob="beforeend">{new_story_segment}</div>""")

        if simulation_ended:
            # Replace the choices container with the end message and restart button
            yield SSE.patch_elements(f"""
                <div id="choices-container" class="choices-container" hx-swap-oob="true">
                    <p class="mt-4 text-center">SIMULATION ENDED. Thank you for playing!</p>
                    <div class="d-flex justify-content-center">
                        <button class="btn btn-success" data-on-click="window.location.href='{url_for('questionnaire')}'">Start New Simulation</button>
                    </div>
                </div>
            """)
        else:
            # Update the choices container with new choices and the input field
            yield SSE.patch_elements(f"""
                <div id="choices-container" class="choices-container" hx-swap-oob="true">
                    {choices_html}
                    <form id="decision-form" data-on-submit="@post('{url_for('updates')}', {{contentType: 'form'}})">
                        <input name="decision" data-bind-decision type="text" class="form-control mb-2" placeholder="Type your choice (e.g., A, B, or full text)">
                        <button type="submit" class="btn btn-primary">Send</button>
                    </form>
                </div>
            """)
        # Clear the input field after submission by patching its value
        yield SSE.patch_elements(f"""<input name="decision" data-bind-decision value="" hx-swap-oob="true">""")

    return Response(event_stream(), mimetype="text/event-stream")



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

