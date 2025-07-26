from flask import Flask, render_template, request, redirect, url_for, flash

app = Flask(__name__)
app.secret_key = 'your-secret-key'  # Change this to a secure key in production

@app.route('/', methods=['GET', 'POST'])
def questionnaire():
    if request.method == 'POST':
        interest = request.form.get('interest')
        ancestor_name = request.form.get('ancestor_name')
        birth_date = request.form.get('birth_date')

        if not interest:
            flash('Interest is required!', 'error')
            return redirect(url_for('questionnaire'))

        # Store or process the data as needed
        flash('Questionnaire submitted successfully!', 'success')
        return redirect(url_for('questionnaire'))

    return render_template('questionnaire.html')

if __name__ == '__main__':
    app.run(debug=True)
