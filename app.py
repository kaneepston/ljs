from flask import Flask, render_template, send_file
import datetime
import io

# Import the functions from your existing script
# Make sure the script is saved as 'parashat_generator.py' in the same directory
try:
    import parashat_generator
except ImportError:
    print("Error: Could not import 'parashat_generator.py'. Make sure the file exists and is in the same directory.")
    exit()


app = Flask(__name__)

@app.route("/")
def index():
    """
    Renders the main page with information about the current weekly Parasha.
    """
    now = datetime.datetime.now()
    
    parasha_data = parashat_generator.get_parasha_data()
    
    english_preview = "Could not load preview."
    hebrew_preview = ""
    parasha_name = "Not Found"
    hebrew_date = "Could not load Hebrew date."
    parasha_ref = "Not Found"

    if parasha_data:
        parasha_name = parasha_data.get('title_en', "Not Found")
        hebrew_date = parasha_data.get('hebrew_date', "Not Found")
        parasha_ref = parasha_data.get('parasha_ref', "Not Found")
        
        if parasha_data.get('verses'):
            verses = parasha_data['verses']
            # Get first 3 verses for preview
            preview_verses = verses[:3] 
            english_preview = " ".join([v['en'] for v in preview_verses])
            hebrew_preview = " ".join([v['he'] for v in preview_verses])


    # Pass all the data to the HTML template
    return render_template("index.html", 
                           gregorian_date=now.strftime("%A, %B %d, %Y"),
                           hebrew_date=hebrew_date,
                           parasha_name=parasha_name,
                           parasha_ref=parasha_ref,
                           english_preview=english_preview,
                           hebrew_preview=hebrew_preview)

@app.route("/generate")
def generate_pptx():
    """
    Generates the PPTX file for the current week.
    """
    print("Fetching data for current week and generating presentation...")
    parasha_data = parashat_generator.get_parasha_data()
    
    if not parasha_data:
        return "Error: Could not fetch Parasha data from Sefaria.", 500
    
    file_stream = io.BytesIO()

    # Generate the presentation into the memory stream
    parashat_generator.create_presentation(parasha_data, output=file_stream)
    
    file_stream.seek(0)
    
    return send_file(
        file_stream,
        as_attachment=True,
        download_name=f"{parasha_data.get('title_en', 'parasha')}.pptx",
        mimetype='application/vnd.openxmlformats-officedocument.presentationml.presentation'
    )

if __name__ == "__main__":
    print("Starting Flask server. Open http://127.0.0.1:5000 in your web browser.")
    app.run(debug=True)
