from quart import Quart, render_template, request, redirect, url_for, flash, session, Response
from datastar_py.quart import ServerSentEventGenerator as SSE, DatastarResponse
from datastar_py.consts import ElementPatchMode
from quart_session import Session
from dotenv import load_dotenv
from google import genai
from google.genai import types
import os
import re
import json
from datetime import timedelta

load_dotenv()

app = Quart(__name__)

MAX_CHOICES = 3
END_SIMULATION = 'SIMULATION ENDED.'

# Security: Ensure SECRET_KEY is set
app.config.from_prefixed_env()
if not app.secret_key:
    raise ValueError("SECRET_KEY environment variable is required. Please set it in your .env file.")

# Configure Google Generative AI
if not app.config['GEMINI_API_KEY']:
    raise ValueError("GEMINI_API_KEY or GEMINI_API_KEY environment variable is required. Please set it in your .env file.")

client = genai.Client(api_key=app.config['GEMINI_API_KEY'])

Session(app)

SYSTEM_PROMPT = (
    "You are the Animus from Assassin's Creed. You are going to write me into a story involving one of my ancestors. "
    "You will ask me where I want to go in history. From that point on, we enter a simulation mode where you present me "
    "with some context from that part of history along with a couple of choices. "
    "After each story segment, present exactly 3 choices in this format: "
    "~~~ A) Choice B) Choice C) Choice --- "
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

    if not interest:
        flash('Please complete the questionnaire first.', 'warning')
        return redirect(url_for('questionnaire'))

    return await render_template('simulation.html')

@app.route("/updates", methods=['GET', 'POST'])
async def updates():
    config = types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT)
    # Get data from session, with defaults
    current_story = session.get('story', '')
    choice_count = session.get('choice_count', 1)
    convo_history = session.get('convo_history', [])
    interest = session.get('interest')
    ancestor_name = session.get('ancestor_name')
    birth_date = session.get('birth_date')

    async def event_stream():

        # If it's a GET request and there's a story, just reload it from cache
        if request.method == 'GET' and current_story:
            story_content = extract_story(current_story)
            choices = extract_choices(current_story)
            choices_html = build_choices_html(choices, choice_count)
            yield SSE.patch_elements(f'<div id="story-content">{story_content}</div>')
            yield SSE.patch_elements(choices_html, selector="#decision-form", mode=ElementPatchMode.INNER)
            return

        # --- Handles both initial GET and subsequent POSTs that require streaming from the API ---
        
        full_response_text = ""
        
        # For POST requests, update history with the user's decision
        if request.method == 'POST':
            form = await request.form
            decision = form.get('decision')
            if not decision:
                # Handle cases where the form is submitted empty to prevent errors
                return 

            # Display the user's choice in the UI and clear the old options
            yield SSE.patch_elements(f'<p class="text-info mt-3"><i>Your choice: {decision}</i></p>', selector="#story-content", mode=ElementPatchMode.APPEND)
            yield SSE.patch_elements('', selector='#decision-form')
            
            convo_history.append({'role': 'user', 'parts': [decision]})
        # For an initial GET request, create the first user message from the questionnaire
        else:
            user_input = f"I want to explore {interest}. My ancestor's name is {ancestor_name or 'unknown'} and they were born around {birth_date or 'an unknown time'}."
            convo_history.append({'role': 'user', 'parts': [user_input]})

        # Convert the history from serializable dicts to API-compatible Content objects
        api_history = [types.Content(**c) for c in convo_history]
        
        # Stream the new story segment from the Gemini API
        try:
            async for chunk in await client.aio.models.generate_content_stream(model='gemini-1.5-flash', contents=api_history, config=config):
                full_response_text += chunk.text
                yield SSE.patch_elements(f"<span>{chunk.text}</span>", selector="#story-content", mode=ElementPatchMode.APPEND)
        except Exception as e:
            # Handle potential API errors gracefully
            await flash(f"An error occurred with the AI service: {e}", "danger")
            yield SSE.patch_elements(f'<div class="alert alert-danger">Error generating story. Please try again later.</div>', selector="#story-content", mode=ElementPatchMode.APPEND)
            return

        # After streaming, update the session and render the new choices
        if full_response_text:
            convo_history.append({'role': 'model', 'parts': [full_response_text]})
            
            session['story'] = session.get('story', '') + full_response_text
            session['convo_history'] = convo_history
            session['choice_count'] = choice_count + 1

            choices = extract_choices(full_response_text)
            choices_html = build_choices_html(choices, session['choice_count'])
            yield SSE.patch_elements(choices_html, selector="#decision-form", mode=ElementPatchMode.INNER)

    return DatastarResponse(event_stream())

def extract_story(text: str) -> str:
    """Extracts the story part from the text, which is everything before the last choice separator."""
    if '~~~' in text:
        return text.rsplit('~~~', 1)[0]
    return text


def extract_choices(text):
    if not text or END_SIMULATION in text.upper():
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


def build_choices_html(choices, choice_count):
    content = ""
    if choices:
        content += '<fieldset id="decision-fieldset">'
        for key, value in choices:
            sim_state = ""
            if choice_count < MAX_CHOICES - 1:
                sim_state = "Simulation middle"
            elif choice_count == MAX_CHOICES - 1:
                sim_state = "Simulation climax"
            elif choice_count >= MAX_CHOICES:
                sim_state = f"state {END_SIMULATION} and present no choices"
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
