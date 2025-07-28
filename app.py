from quart import Quart, render_template, request, redirect, url_for, flash, session, Response
from datastar_py.quart import ServerSentEventGenerator as SSE, DatastarResponse
from datastar_py.consts import ElementPatchMode
from dotenv import load_dotenv
import google.generativeai as genai
import os
import re
import json
from datetime import timedelta

load_dotenv()

app = Quart(__name__)

# Security: Ensure SECRET_KEY is set
app.secret_key = os.getenv("SECRET_KEY")
if not app.secret_key:
    raise ValueError("SECRET_KEY environment variable is required. Please set it in your .env file.")

# Basic session security configuration
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=2)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# Configure Google Generative AI
google_api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
if not google_api_key:
    raise ValueError("GOOGLE_API_KEY or GEMINI_API_KEY environment variable is required. Please set it in your .env file.")

genai.configure(api_key=google_api_key)

SYSTEM_PROMPT = (
    "You are the Animus from Assassin's Creed. You are going to write me into a story involving one of my ancestors. "
    "You will ask me where I want to go in history. From that point on, we enter a simulation mode where you present me "
    "with some context from that part of history along with a couple of choices. "
    "After each story segment, present exactly 3 choices in this format: "
    "A) Choice B) Choice C) Choice --- "
    "My choices indicate the simulation's progress in (parentheses)"
)

@app.route('/', methods=['GET', 'POST'])
async def questionnaire():
    if request.method == 'POST':
        form = await request.form
        interest = form.get('interest', '').strip()
        ancestor_name = form.get('ancestor_name', '').strip()
        birth_date = form.get('birth_date')

        if not interest:
            flash('Your interest in ancestry is required!', 'danger')
            return redirect(url_for('questionnaire'))

        # Save data to session
        session['interest'] = interest
        session['ancestor_name'] = ancestor_name
        session['birth_date'] = birth_date
        session['choice_count'] = 1
        session['story'] = ""
        session['convo_history'] = []

        return redirect(url_for('simulation'))

    return await render_template('questionnaire.html')

@app.route('/simulation', methods=['GET'])
async def simulation():
    interest = session.get('interest')
    ancestor_name = session.get('ancestor_name')
    birth_date = session.get('birth_date')
    current_story = session.get('story')

    if not interest:
        flash('Please complete the questionnaire first.', 'warning')
        return redirect(url_for('questionnaire'))

    if not current_story:
        user_input = f"""
        I want to explore {interest}.
        My ancestor's name is {ancestor_name or 'unknown'} and they were born around {birth_date or 'an unknown time'}.
        """
        try:
            model = genai.GenerativeModel("gemini-2.5-flash")
            convo = model.start_chat()
            convo.send_message(SYSTEM_PROMPT)
            convo.send_message(user_input)
            initial_story_segment = convo.last.text

            session['story'] = initial_story_segment
            # Convert conversation history to simple format for session storage
            session['convo_history'] = [
                {"role": m.role, "parts": [{"text": part.text} for part in m.parts]}
                for m in convo.history
            ]

        except Exception as e:
            flash(f"Failed to generate story: {str(e)}. Please try again.", 'danger')
            return await redirect(url_for('questionnaire'))
    else:
        initial_story_segment = current_story

    choices = extract_choices(initial_story_segment)

    return await render_template('simulation.html', story=initial_story_segment, choices=choices)

@app.route("/updates", methods=['GET', 'POST'])
async def updates():
    form = await request.form
    decision = form.get('decision')
    current_story = session.get('story', '')
    choice_count = session.get('choice_count', 1)
    convo_history = session.get('convo_history', [])
    print(f"choice_count: {choice_count}")
        

    new_story_segment = ""
    choices_html = ""
    simulation_ended = False

    def build_choices_html(choices):
        content = ""
        if choices:
            content += '<fieldset id="decision-fieldset">'
            for key, value in choices:
                sim_state = ""
                if choice_count == 1:
                    sim_state = "Simulation middle"
                elif choice_count == 2:
                    sim_state = "Simulation climax"
                else:
                    sim_state = "state 'SIMULATION ENDED.' and present no choices"
                escaped_value = json.dumps(f"{key} {value.replace('\'', '').replace("\"", '')} ({sim_state})")
                action = "@post('/updates', {contentType:'form'})"
                content += f"""
                <div class="form-check">
                <label class="form-check-label">
                <input type="radio" class="form-check-input" name="decision" id="{key}_{choice_count}" value={escaped_value} data-on-click="{action}" data-indicator-fetching></input>
                {key}) {value}
                </label>
                </div>
                """
            content += '</fieldset>'
        return content

    if request.method == 'GET':
        choices = extract_choices(current_story)
        choices_html = build_choices_html(choices)
    else:
        model = genai.GenerativeModel("gemini-2.0-flash")
        convo = model.start_chat(history=convo_history)

        if choice_count <= 3:
            try:
                print(decision)
                convo.send_message(decision)
                new_story_segment = convo.last.text
                session['story'] = new_story_segment
                # Convert conversation history to simple format for session storage
                session['convo_history'] = [
                    {"role": m.role, "parts": [{"text": part.text} for part in m.parts]}
                    for m in convo.history[-3:]
                ]
                choice_count = choice_count + 1
                session['choice_count'] = choice_count

                if "SIMULATION ENDED." in new_story_segment.upper():
                    simulation_ended = True
                elif session['choice_count'] > 3:
                    new_story_segment += "\n\nSIMULATION ENDED."
                    simulation_ended = True
                else:
                    choices = extract_choices(new_story_segment)
                    choices_html = build_choices_html(choices)

            except Exception as e:
                new_story_segment = f"\n\nError continuing story: {str(e)}. Simulation ended due to an unexpected error."
                simulation_ended = True
                session['story'] = new_story_segment
                session['choice_count'] = 4

        else:
            new_story_segment = "\n\nSIMULATION ENDED. (No more choices allowed.)"
            simulation_ended = True

    async def event_stream():
        if new_story_segment:
            yield SSE.patch_elements(f"""<div id="story-content">{new_story_segment}</div>""")

        if simulation_ended:
            yield SSE.patch_elements(f"""
                <div id="choices-container" class="choices-container">
                    <p class="mt-4 text-center">SIMULATION ENDED. Thank you for playing!</p>
                    <div class="d-flex justify-content-center">
                        <button class="btn btn-success" data-on-click="window.location.href='/'">Start New Simulation</button>
                    </div>
                </div>
            """)
        else:
            yield SSE.patch_elements(
                choices_html,
                selector="#decision-form",
                mode=ElementPatchMode.INNER
            )

    return DatastarResponse(event_stream())

def extract_choices(text):
    if not text or 'SIMULATION ENDED' in text.upper():
        return []

    # Split by '---' and get the last part
    parts = text.split('---')
    if len(parts) >= 2:
        token = parts[-1]
        if token.strip() == "":
            token = parts[-2]
    else:
        token = text
    # Look for choices in the format A) Choice B) Choice C) Choice
    choices = re.findall(r'([A-Z])\)\s*(.*?)(?=\s*[A-Z]\)|\Z)', token, re.DOTALL)

    # Filter out empty choices and clean up whitespace
    result = [(key.strip(), value.strip()) for key, value in choices if key and value]

    return result




