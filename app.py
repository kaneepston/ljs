from flask import Flask, render_template, send_file, request, jsonify
import datetime
import io
import requests
import re

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
    Renders the main page with information about the current weekly Parashat.
    """
    now = datetime.datetime.now()
    
    # Pass basic data to the HTML template (no API calls)
    return render_template("index.html", 
                           gregorian_date=now.strftime("%A, %B %d, %Y"))

def get_hebrew_date_for_gregorian(year, month, day):
    """
    Get Hebrew date for a given Gregorian date using a Hebrew calendar API.
    """
    try:
        # Use hebcal API to get Hebrew date
        url = f"https://www.hebcal.com/converter?cfg=json&gy={year}&gm={month}&gd={day}&g2h=1"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            # Get the full Hebrew date in English transliteration
            hebrew_year = data.get('hy', '')
            hebrew_month = data.get('hm', '')
            hebrew_day = data.get('hd', '')
            
            if hebrew_year and hebrew_month and hebrew_day:
                # Format as "26th of Sivan, 5785"
                day_suffix = get_day_suffix(hebrew_day)
                return f"{hebrew_day}{day_suffix} of {hebrew_month}, {hebrew_year}"
            
            # Fallback to the original format if individual components aren't available
            eng_date = data.get('hy', '')
            if eng_date:
                return eng_date
            hebrew_date = data.get('hebrew', '')
            if hebrew_date:
                return hebrew_date
    except Exception as e:
        print(f"Error getting Hebrew date: {e}")
    
    # Fallback: return a formatted date
    return f"Hebrew date not available"

def get_day_suffix(day):
    """Get the appropriate suffix for a day number."""
    day = int(day)
    if 10 <= day % 100 <= 20:
        suffix = 'th'
    else:
        suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th')
    return suffix

@app.route("/get_next_4_weeks")
def get_next_4_weeks():
    """
    Returns parashat names and dates for the next 4 weeks (current week + 3 future weeks).
    """
    results = []
    for i in range(0, 4):  # 0 = current week, 1-3 = next 3 weeks
        try:
            target_date = parashat_generator.get_next_shabbat_date(i)
            year = target_date.year
            month = target_date.month
            day = target_date.day
            
            cal_url = f"https://www.sefaria.org/api/calendars?year={year}&month={month}&day={day}"
            cal = requests.get(cal_url).json()
            parashat_item = next(j for j in cal["calendar_items"] if j["title"]["en"] == "Parashat Hashavua")
            
            # Get Hebrew date in English format
            hebrew_date = get_hebrew_date_for_gregorian(year, month, day)
            
            # Format the date string
            gregorian_str = target_date.strftime("%a, %d %B %Y")
            if hebrew_date and hebrew_date != "Hebrew date not available":
                date_display = f"{gregorian_str} · {hebrew_date}"
            else:
                date_display = gregorian_str
            
            results.append({
                'weeks_ahead': i,
                'title': parashat_item["displayValue"]["en"],
                'date_display': date_display,
                'gregorian_date': gregorian_str,
                'hebrew_date': hebrew_date
            })
        except Exception as e:
            print(f"Error getting parashat for week {i}: {e}")
            continue
    return jsonify(results)

@app.route("/get_parashat_data/<int:weeks_ahead>")
def get_parashat_data(weeks_ahead):
    """
    API endpoint to get parashat data for a specific week.
    """
    parashat_data = parashat_generator.get_parasha_data(weeks_ahead=weeks_ahead)
    
    if not parashat_data:
        return jsonify({"error": "Could not fetch Parashat data from Sefaria."}), 500
    
    # Get Hebrew date for this week
    target_date = parashat_generator.get_next_shabbat_date(weeks_ahead)
    hebrew_date = get_hebrew_date_for_gregorian(target_date.year, target_date.month, target_date.day)
    
    # Prepare preview data
    preview_verses = parashat_data['verses'][:3] if parashat_data.get('verses') else []
    english_preview = " ".join([v['en'] for v in preview_verses])
    hebrew_preview = " ".join([v['he'] for v in preview_verses])
    
    return jsonify({
        "title": parashat_data.get('title_en', 'Unknown'),
        "hebrew_date": hebrew_date,
        "ref": parashat_data.get('parasha_ref', 'Unknown'),
        "total_verses": len(parashat_data.get('verses', [])),
        "english_preview": english_preview,
        "hebrew_preview": hebrew_preview,
        "verses": parashat_data.get('verses', []),
        "book": parashat_data.get('book', 'Unknown')
    })

@app.route("/generate")
def generate_pptx():
    """
    Generates the PPTX file for the current week or future week with optional verse ranges.
    Supports both weeks_ahead (for dropdown) and ref (for date picker) parameters.
    """
    # Get parameters from request
    weeks_ahead = request.args.get('weeks_ahead', type=int)
    sefaria_ref = request.args.get('ref', '')
    verse_ranges = request.args.get('verse_ranges', '')  # Format: "1-4,10-14,20-25"
    
    # Determine which method to use
    if weeks_ahead is not None:
        print(f"Fetching data for week {weeks_ahead} weeks ahead and generating presentation...")
        parashat_data = parashat_generator.get_parasha_data(weeks_ahead=weeks_ahead)
    elif sefaria_ref:
        print(f"Fetching data for ref {sefaria_ref} and generating presentation...")
        # Use the same logic as the date endpoint to get the data
        text_version = "vtitle=The_Contemporary_Torah,_JPS,_2006"
        text_url = f"https://www.sefaria.org/api/texts/{sefaria_ref}?{text_version}&context=0"
        text_response = requests.get(text_url)
        
        if text_response.status_code != 200:
            return "Error: Could not fetch Torah text from Sefaria.", 500
            
        text_data = text_response.json()
        
        # Process the text data similar to parashat_generator
        all_verses = []
        for chap_idx, chapter_ref in enumerate(text_data.get('sections', [])):
            chapter_num = int(chapter_ref)
            
            if chap_idx >= len(text_data.get('text', [])) or chap_idx >= len(text_data.get('he', [])):
                continue

            en_verses_for_chap = text_data['text'][chap_idx]
            he_verses_for_chap = text_data['he'][chap_idx]

            try:
                start_vs = int(text_data['sectionNames'][chap_idx].split(':')[1])
            except (IndexError, ValueError):
                start_vs = 1

            for verse_idx, (en, he) in enumerate(zip(en_verses_for_chap, he_verses_for_chap)):
                verse_num = start_vs + verse_idx
                all_verses.append({
                    "chapter": chapter_num,
                    "verse": verse_num,
                    "en": parashat_generator.clean_text(en),
                    "he": parashat_generator.clean_text(he)
                })

        if not all_verses:
            return "Error: No verses found in the Torah portion.", 500
        
        parashat_data = {
            "title_en": text_data.get("collectiveTitle", {}).get("en", sefaria_ref),
            "parasha_ref": sefaria_ref,
            "book": text_data.get("book"),
            "verses": all_verses
        }
    else:
        return "Error: Either weeks_ahead or ref parameter is required.", 400
    
    if not parashat_data:
        return "Error: Could not fetch Parashat data from Sefaria.", 500
    
    # Filter verses if ranges are specified
    if verse_ranges:
        try:
            all_verses = parashat_data['verses']
            selected_verses = []
            
            # Parse verse ranges (e.g., "1-4,10-14,20-25" or "16:1-18:32")
            ranges = [r.strip() for r in verse_ranges.split(',')]
            for range_str in ranges:
                if ':' in range_str:
                    # Chapter-aware format: "16:1-18:32" or "16:1-16:50" or "16:1-3"
                    if '-' in range_str:
                        start_part, end_part = range_str.split('-')
                        start_chapter, start_verse = map(int, start_part.split(':'))
                        
                        # Check if end_part has a colon (different chapter) or not (same chapter)
                        if ':' in end_part:
                            end_chapter, end_verse = map(int, end_part.split(':'))
                        else:
                            # Same chapter format: "16:1-3"
                            end_chapter = start_chapter
                            end_verse = int(end_part)
                        
                        # Filter verses within the chapter range
                        for verse in all_verses:
                            verse_chapter = verse['chapter']
                            verse_verse = verse['verse']
                            
                            # Check if verse is within the range
                            if start_chapter == end_chapter:
                                # Same chapter: check verse range
                                if verse_chapter == start_chapter and start_verse <= verse_verse <= end_verse:
                                    selected_verses.append(verse)
                            else:
                                # Different chapters: check chapter and verse ranges
                                if (start_chapter < verse_chapter < end_chapter) or \
                                   (verse_chapter == start_chapter and verse_verse >= start_verse) or \
                                   (verse_chapter == end_chapter and verse_verse <= end_verse):
                                    selected_verses.append(verse)
                else:
                    # Legacy flat format: "1-4,10-14"
                    if '-' in range_str:
                        start, end = map(int, range_str.split('-'))
                        if 1 <= start <= end <= len(all_verses):
                            selected_verses.extend(all_verses[start-1:end])
            
            if selected_verses:
                parashat_data['verses'] = selected_verses
            else:
                return "Error: Invalid verse ranges. Please check your input.", 400
                
        except Exception as e:
            return f"Error: Invalid verse range format. {str(e)}", 400
    
    file_stream = io.BytesIO()

    # Generate the presentation into the memory stream
    parashat_generator.create_presentation(parashat_data, output=file_stream, verse_ranges=verse_ranges)
    
    file_stream.seek(0)
    
    # Create filename with verse ranges if specified
    filename = f"{parashat_data.get('title_en', 'parashat')}"
    if verse_ranges:
        filename += f"_verses_{verse_ranges.replace(',', '_')}"
    filename += ".pptx"
    
    return send_file(
        file_stream,
        as_attachment=True,
        download_name=filename,
        mimetype='application/vnd.openxmlformats-officedocument.presentationml.presentation'
    )

@app.route("/get_parashat_names")
def get_parashat_names():
    """
    Returns a list of future parashat names (weeks_ahead, title) for weeks 1-52.
    """
    results = []
    for i in range(1, 53):
        try:
            target_date = parashat_generator.get_next_shabbat_date(i)
            year = target_date.year
            month = target_date.month
            day = target_date.day
            cal_url = f"https://www.sefaria.org/api/calendars?year={year}&month={month}&day={day}"
            cal = requests.get(cal_url).json()
            parashat_item = next(j for j in cal["calendar_items"] if j["title"]["en"] == "Parashat Hashavua")
            
            # Get Hebrew date in English format
            hebrew_date = get_hebrew_date_for_gregorian(year, month, day)
            
            # Format the date string
            gregorian_str = target_date.strftime("%a, %d %B %Y")
            if hebrew_date and hebrew_date != "Hebrew date not available":
                date_display = f"{gregorian_str} · {hebrew_date}"
            else:
                date_display = gregorian_str
            
            results.append({
                'weeks_ahead': i,
                'title': parashat_item["displayValue"]["en"],
                'date_display': date_display,
                'gregorian_date': gregorian_str,
                'hebrew_date': hebrew_date
            })
        except Exception as e:
            print(f"Error getting parashat for week {i}: {e}")
            continue
    return jsonify(results)

@app.route("/get_parashat_for_date")
def get_parashat_for_date():
    """
    Get parashat data for a specific date provided by the user.
    Handles holidays and non-Shabbat days gracefully using Sefaria's calendar API.
    """
    try:
        date_str = request.args.get('date')
        if not date_str:
            return jsonify({"error": "Date parameter is required"}), 400
        
        # Parse the date
        target_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
        
        # Use Sefaria's calendar API to find the reading for that day
        cal_url = f"https://www.sefaria.org/api/calendars?year={target_date.year}&month={target_date.month}&day={target_date.day}"
        cal_res = requests.get(cal_url)
        cal_res.raise_for_status()
        cal = cal_res.json()

        # Find the primary Torah reading
        reading = None
        if cal.get("calendar_items"):
            # Look for any Torah reading (not just "Parashat Hashavua")
            for item in cal["calendar_items"]:
                # Check if it's a Torah reading (has a ref and is not a special event)
                if "ref" in item and item.get("category") != "mevarchim":
                    # Prioritize "Parashat Hashavua" but accept any Torah reading
                    if item.get("title", {}).get("en") == "Parashat Hashavua":
                        reading = item
                        break
                    elif not reading:  # Take the first Torah reading if no "Parashat Hashavua" found
                        reading = item

        if not reading:
            return jsonify({"error": f"No Torah portion found for {target_date.strftime('%A, %B %d, %Y')}. This may be a day without a designated public reading."}), 404

        # Get the reference and fetch the text data
        parasha_ref = reading["ref"]
        
        # Use the existing parashat_generator to get the text data
        # We'll need to modify the approach since we don't have weeks_ahead
        # Let's fetch the text directly using the reference
        text_version = "vtitle=The_Contemporary_Torah,_JPS,_2006"
        text_url = f"https://www.sefaria.org/api/texts/{parasha_ref}?{text_version}&context=0"
        text_response = requests.get(text_url)
        
        if text_response.status_code != 200:
            return jsonify({"error": "Could not fetch Torah text from Sefaria."}), 500
            
        text_data = text_response.json()
        
        # Process the text data similar to parashat_generator
        all_verses = []
        for chap_idx, chapter_ref in enumerate(text_data.get('sections', [])):
            chapter_num = int(chapter_ref)
            
            if chap_idx >= len(text_data.get('text', [])) or chap_idx >= len(text_data.get('he', [])):
                continue

            en_verses_for_chap = text_data['text'][chap_idx]
            he_verses_for_chap = text_data['he'][chap_idx]

            try:
                start_vs = int(text_data['sectionNames'][chap_idx].split(':')[1])
            except (IndexError, ValueError):
                start_vs = 1

            for verse_idx, (en, he) in enumerate(zip(en_verses_for_chap, he_verses_for_chap)):
                verse_num = start_vs + verse_idx
                all_verses.append({
                    "chapter": chapter_num,
                    "verse": verse_num,
                    "en": parashat_generator.clean_text(en),
                    "he": parashat_generator.clean_text(he)
                })

        if not all_verses:
            return jsonify({"error": "No verses found in the Torah portion."}), 500
        
        # Get Hebrew date for this date
        hebrew_date = get_hebrew_date_for_gregorian(target_date.year, target_date.month, target_date.day)
        
        # Format the date string for display
        gregorian_str = target_date.strftime("%a, %d %B %Y")
        date_display = f"{gregorian_str} · {hebrew_date}" if hebrew_date and hebrew_date != "Hebrew date not available" else gregorian_str
        
        # Prepare preview data
        preview_verses = all_verses[:3] if all_verses else []
        english_preview = " ".join([v['en'] for v in preview_verses])
        hebrew_preview = " ".join([v['he'] for v in preview_verses])
        
        return jsonify({
            "title": reading["displayValue"]["en"],
            "ref": parasha_ref,
            "date_display": date_display,
            "gregorian_date": gregorian_str,
            "hebrew_date": hebrew_date,
            "total_verses": len(all_verses),
            "english_preview": english_preview,
            "hebrew_preview": hebrew_preview,
            "weeks_ahead": None  # This is not a weekly reading
        })
        
    except ValueError:
        return jsonify({"error": "Invalid date format. Use YYYY-MM-DD"}), 400
    except Exception as e:
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500

@app.route("/get_special_readings")
def get_special_readings():
    """
    Get list of special readings (holidays, festivals, etc.) with their Sefaria references.
    """
    special_readings = {
        "Pesach": {
            "First Day": "Exodus 12:1-51",
            "Second Day": "Exodus 12:37-51",
            "Seventh Day": "Exodus 13:17-15:26",
            "Eighth Day": "Deuteronomy 15:19-16:17"
        },
        "Shavuot": {
            "First Day": "Exodus 19:1-20:23",
            "Second Day": "Deuteronomy 15:19-16:17"
        },
        "Rosh Hashanah": {
            "First Day": "Genesis 21:1-34",
            "Second Day": "Genesis 22:1-24"
        },
        "Yom Kippur": {
            "Morning": "Leviticus 16:1-34",
            "Afternoon": "Isaiah 57:14-58:14"
        },
        "Sukkot": {
            "First Day": "Leviticus 22:26-23:44",
            "Second Day": "Leviticus 22:26-23:44",
            "Intermediate Days": "Numbers 29:17-31"
        },
        "Simchat Torah": {
            "Morning": "Deuteronomy 33:1-34:12",
            "Evening": "Genesis 1:1-2:3"
        },
        "Chanukah": {
            "First Day": "Numbers 7:1-17",
            "Second Day": "Numbers 7:18-29",
            "Third Day": "Numbers 7:24-35",
            "Fourth Day": "Numbers 7:30-41",
            "Fifth Day": "Numbers 7:36-47",
            "Sixth Day": "Numbers 7:42-53",
            "Seventh Day": "Numbers 7:48-59",
            "Eighth Day": "Numbers 7:54-8:4"
        },
        "Purim": {
            "Morning": "Exodus 17:8-16"
        }
    }
    return jsonify(special_readings)

@app.route("/get_custom_verses")
def get_custom_verses():
    """
    Get verses for user-specified reference (book, chapter, verse range).
    """
    try:
        book = request.args.get('book', '').strip()
        start_chapter = request.args.get('start_chapter', '').strip()
        start_verse = request.args.get('start_verse', '').strip()
        end_chapter = request.args.get('end_chapter', '').strip()
        end_verse = request.args.get('end_verse', '').strip()
        
        # Validate inputs
        if not all([book, start_chapter, start_verse, end_chapter, end_verse]):
            return jsonify({"error": "All fields are required: book, start_chapter, start_verse, end_chapter, end_verse"}), 400
        
        # Validate that inputs are numbers
        try:
            int(start_chapter)
            int(start_verse)
            int(end_chapter)
            int(end_verse)
        except ValueError:
            return jsonify({"error": "Chapter and verse numbers must be integers"}), 400
        
        # Build Sefaria reference
        if start_chapter == end_chapter:
            ref = f"{book} {start_chapter}:{start_verse}-{end_verse}"
        else:
            ref = f"{book} {start_chapter}:{start_verse}-{end_chapter}:{end_verse}"
        
        print(f"Fetching custom verses for ref: {ref}")
        
        # Fetch the text data using the same logic as date-based approach
        text_version = "vtitle=The_Contemporary_Torah,_JPS,_2006"
        text_url = f"https://www.sefaria.org/api/texts/{ref}?{text_version}&context=0"
        text_response = requests.get(text_url)
        
        if text_response.status_code != 200:
            return jsonify({"error": f"Could not fetch Torah text for reference: {ref}"}), 500
            
        text_data = text_response.json()
        
        # Process the text data similar to parashat_generator
        all_verses = []
        for chap_idx, chapter_ref in enumerate(text_data.get('sections', [])):
            chapter_num = int(chapter_ref)
            
            if chap_idx >= len(text_data.get('text', [])) or chap_idx >= len(text_data.get('he', [])):
                continue

            en_verses_for_chap = text_data['text'][chap_idx]
            he_verses_for_chap = text_data['he'][chap_idx]

            try:
                start_vs = int(text_data['sectionNames'][chap_idx].split(':')[1])
            except (IndexError, ValueError):
                start_vs = 1

            for verse_idx, (en, he) in enumerate(zip(en_verses_for_chap, he_verses_for_chap)):
                verse_num = start_vs + verse_idx
                all_verses.append({
                    "chapter": chapter_num,
                    "verse": verse_num,
                    "en": parashat_generator.clean_text(en),
                    "he": parashat_generator.clean_text(he)
                })

        if not all_verses:
            return jsonify({"error": "No verses found for the specified reference."}), 500
        
        # Prepare preview data
        preview_verses = all_verses[:3] if all_verses else []
        english_preview = " ".join([v['en'] for v in preview_verses])
        hebrew_preview = " ".join([v['he'] for v in preview_verses])
        
        return jsonify({
            "title": f"Custom Reading: {ref}",
            "ref": ref,
            "date_display": f"Custom selection: {ref}",
            "gregorian_date": f"Custom: {ref}",
            "hebrew_date": "Custom selection",
            "total_verses": len(all_verses),
            "english_preview": english_preview,
            "hebrew_preview": hebrew_preview,
            "weeks_ahead": None  # This is a custom selection
        })
        
    except Exception as e:
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500

if __name__ == "__main__":
    print("Starting Flask server. Open http://127.0.0.1:5000 in your web browser.")
    app.run(debug=True)
