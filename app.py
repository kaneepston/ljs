from flask import Flask, render_template, send_file, request, jsonify
import datetime
import io
import requests
import re
import logging
import sys
import json

# Import the functions from your existing script
# Make sure the script is saved as 'parashat_generator.py' in the same directory
try:
    import parashat_generator
except ImportError:
    print("Error: Could not import 'parashat_generator.py'. Make sure the file exists and is in the same directory.")
    exit()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
        "gregorian_date": parashat_data.get('gregorian_date', ''),
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
    Now supports multiple, arbitrary ranges and logs all steps for debugging.
    """
    logging.basicConfig(stream=sys.stdout, level=logging.INFO)
    logger = logging.getLogger("generate_pptx")

    # Get parameters from request
    weeks_ahead = request.args.get('weeks_ahead', type=int)
    sefaria_ref = request.args.get('ref', '')
    verse_ranges = request.args.get('verse_ranges', '')  # Can be JSON array or old string

    logger.info(f"Received request: ref={sefaria_ref}, verse_ranges={verse_ranges}, weeks_ahead={weeks_ahead}")

    # Helper to fetch and log a single range
    def fetch_range(book, range_str):
        ref = f"{book} {range_str}"
        url = f"https://www.sefaria.org/api/texts/{ref}?context=0"
        logger.info(f"Fetching Sefaria API: {url}")
        resp = requests.get(url)
        logger.info(f"Sefaria API response for {ref}: {resp.status_code}")
        try:
            data = resp.json()
            logger.info(f"Sefaria API JSON for {ref}: {data}")
        except Exception as e:
            logger.error(f"Failed to parse JSON for {ref}: {e}")
            data = {}
        return data

    # Determine which method to use
    if weeks_ahead is not None:
        logger.info(f"Fetching data for week {weeks_ahead} weeks ahead and generating presentation...")
        parashat_data = parashat_generator.get_parasha_data(weeks_ahead=weeks_ahead)
        if not parashat_data:
            return "Error: Could not fetch parashat data.", 500
        default_book = parashat_data['book']
        # If no verse_ranges, use the full parashat range
        if not verse_ranges:
            first = parashat_data['verses'][0]
            last = parashat_data['verses'][-1]
            verse_ranges = json.dumps([{"book": default_book, "range": f"{first['chapter']}:{first['verse']}-{last['chapter']}:{last['verse']}"}])
    elif sefaria_ref:
        default_book = sefaria_ref
    else:
        return "Error: Either weeks_ahead or ref parameter is required.", 400

    # Parse and fetch all ranges
    all_verses = []
    # Try to parse as JSON array first
    try:
        range_objs = json.loads(verse_ranges)
        if not isinstance(range_objs, list):
            raise ValueError
    except Exception:
        # Fallback: treat as old comma-separated string, all from default_book
        range_list = [r.strip() for r in verse_ranges.split(',') if r.strip()]
        range_objs = [{"book": default_book, "range": r} for r in range_list]
    logger.info(f"Parsed range objects: {range_objs}")

    # Process each verse range
    for range_obj in range_objs:
        book = range_obj['book']
        range_str = range_obj['range']
        
        logger.info(f"Processing range: {book} {range_str}")
        
        # Split multi-chapter ranges to avoid Sefaria API issues
        split_ranges = split_multi_chapter_range(range_str)
        range_verses = []
        
        for split_range in split_ranges:
            logger.info(f"Fetching split range: {book} {split_range}")
            data = fetch_range(book, split_range)
            
            if not data or not isinstance(data, dict):
                logger.error(f"Failed to fetch data for {book} {split_range}")
                continue
            
            # Process the fetched data
            verses_for_range = process_verse_data(data, split_range, book)
            range_verses.extend(verses_for_range)
        
        # Add all verses for this range to the combined list
        if range_verses:
            all_verses.append({
                'range': range_str,
                'book': book,
                'verses': range_verses
            })
            logger.info(f"Added {len(range_verses)} verses for range {range_str}")
        else:
            logger.warning(f"No verses found for range {range_str}")

    logger.info(f"All combined verses for presentation: {all_verses}")
    # Prepare data for presentation generator
    # Flatten all verses for legacy compatibility, but keep range info for slides
    flat_verses = []
    for group in all_verses:
        flat_verses.extend(group['verses'])
    parashat_data = {
        "title_en": f"{default_book} {verse_ranges}",
        "parasha_ref": default_book,
        "book": default_book,
        "verses": flat_verses,
        "ranges": all_verses  # Pass the grouped ranges for correct slide splitting
    }
    file_stream = io.BytesIO()
    # Pass the original verse_ranges for slide splitting
    parashat_generator.create_presentation(parashat_data, output=file_stream, verse_ranges=verse_ranges)
    file_stream.seek(0)
    filename = f"{default_book}_verses.pptx"
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

def split_multi_chapter_range(range_str):
    """Split multi-chapter ranges that might cause issues with Sefaria API"""
    if ':' not in range_str or '-' not in range_str:
        return [range_str]
    
    try:
        start_part, end_part = range_str.split('-')
        start_chapter, start_verse = map(int, start_part.split(':'))
        end_chapter, end_verse = map(int, end_part.split(':'))
        
        if start_chapter == end_chapter:
            # Single chapter range, no need to split
            return [range_str]
        
        # Multi-chapter range - split into individual chapter requests
        ranges = []
        
        # First chapter: from start_verse to end of chapter
        ranges.append(f"{start_chapter}:{start_verse}-{start_chapter}:999")
        
        # Middle chapters (if any): entire chapters
        for chapter in range(start_chapter + 1, end_chapter):
            ranges.append(f"{chapter}:1-{chapter}:999")
        
        # Last chapter: from beginning to end_verse
        ranges.append(f"{end_chapter}:1-{end_chapter}:{end_verse}")
        
        logger.info(f"Split multi-chapter range {range_str} into: {ranges}")
        return ranges
        
    except (ValueError, IndexError) as e:
        logger.warning(f"Could not parse range {range_str}: {e}")
        return [range_str]

def process_verse_data(data, range_str, book):
    """Process verse data from Sefaria API response"""
    verses = []
    text_verses = data.get('text', [])
    hebrew_verses = data.get('he', [])
    sections = data.get('sections', [])
    section_names = data.get('sectionNames', [])
    
    logger.info(f"Raw API response structure for {range_str}:")
    logger.info(f"  text_verses type: {type(text_verses)}, length: {len(text_verses) if isinstance(text_verses, list) else 'N/A'}")
    logger.info(f"  hebrew_verses type: {type(hebrew_verses)}, length: {len(hebrew_verses) if isinstance(hebrew_verses, list) else 'N/A'}")
    logger.info(f"  sections: {sections}")
    logger.info(f"  section_names: {section_names}")
    
    # Parse the range to get start/end chapters and verses
    range_match = re.match(r'(\d+):(\d+)-(\d+):(\d+)', range_str)
    if range_match:
        start_chapter = int(range_match.group(1))
        start_verse = int(range_match.group(2))
        end_chapter = int(range_match.group(3))
        end_verse = int(range_match.group(4))
        logger.info(f"Parsed multi-chapter range: {start_chapter}:{start_verse}-{end_chapter}:{end_verse}")
    else:
        # Single chapter range
        range_match = re.match(r'(\d+):(\d+)-(\d+)', range_str)
        if range_match:
            start_chapter = int(range_match.group(1))
            start_verse = int(range_match.group(2))
            end_chapter = start_chapter
            end_verse = int(range_match.group(3))
            logger.info(f"Parsed single-chapter range: {start_chapter}:{start_verse}-{end_verse}")
        else:
            logger.error(f"Could not parse range: {range_str}")
            return verses
    
    # If text_verses is a list of lists (multi-chapter), enumerate by chapter
    if text_verses and isinstance(text_verses[0], list):
        logger.info(f"Detected multi-chapter structure for {range_str}")
        logger.info(f"Sefaria sections array: {sections}")
        logger.info(f"Number of chapters in response: {len(text_verses)}")
        
        # Create a mapping of expected chapters to their data
        expected_chapters = list(range(start_chapter, end_chapter + 1))
        logger.info(f"Expected chapters for range {range_str}: {expected_chapters}")
        
        # Track which chapters we actually process
        processed_chapters = []
        
        for chap_idx, (en_chap, he_chap) in enumerate(zip(text_verses, hebrew_verses)):
            logger.info(f"Processing chapter index {chap_idx}")
            
            # Try to determine chapter number from sections array first
            if sections and chap_idx < len(sections):
                chapter_num = sections[chap_idx]
                logger.info(f"Using chapter number from sections array: {chapter_num}")
            else:
                # Fallback: assume chapters are in order starting from start_chapter
                chapter_num = start_chapter + chap_idx
                logger.info(f"Using fallback chapter number: {chapter_num}")
            
            logger.info(f"Processing chapter {chapter_num} (start_chapter={start_chapter}, end_chapter={end_chapter})")
            
            # Only process chapters within our expected range
            if chapter_num not in expected_chapters:
                logger.info(f"Skipping chapter {chapter_num} - not in expected chapters {expected_chapters}")
                continue
            
            processed_chapters.append(chapter_num)
            
            # Determine verse start/end for this chapter
            if chapter_num == start_chapter:
                verse_start = start_verse
            else:
                verse_start = 1
            if chapter_num == end_chapter:
                verse_end = end_verse
            else:
                # For intermediate chapters, get all verses
                verse_end = len(en_chap)
            
            logger.info(f"Chapter {chapter_num}: verses {verse_start}-{verse_end} (chapter has {len(en_chap)} verses)")
            
            for verse_idx, (en, he) in enumerate(zip(en_chap, he_chap), start=1):
                verse_num = verse_idx
                if verse_num < verse_start or verse_num > verse_end:
                    logger.info(f"Skipping verse {chapter_num}:{verse_num} - outside range {verse_start}-{verse_end}")
                    continue
                clean_en = parashat_generator.clean_text(en)
                clean_he = parashat_generator.clean_text(he)
                verses.append({
                    'chapter': chapter_num,
                    'verse': verse_num,
                    'en': clean_en,
                    'he': clean_he
                })
                logger.info(f"Added verse {chapter_num}:{verse_num}")
            
            # Stop if we've processed all expected chapters
            if len(verses) > 0 and chapter_num == end_chapter:
                logger.info(f"Reached end chapter {end_chapter}, stopping enumeration")
                break
        
        # Check for missing chapters
        missing_chapters = [ch for ch in expected_chapters if ch not in processed_chapters]
        if missing_chapters:
            logger.warning(f"Missing chapters for range {range_str}: {missing_chapters}. Sefaria only returned chapters: {processed_chapters}")
            
            # Try to fetch missing chapters individually
            logger.info(f"Attempting to fetch missing chapters individually...")
            for missing_chapter in missing_chapters:
                if missing_chapter == start_chapter:
                    # First chapter: fetch from start_verse to end of chapter
                    individual_range = f"{missing_chapter}:{start_verse}-{missing_chapter}:999"
                elif missing_chapter == end_chapter:
                    # Last chapter: fetch from beginning to end_verse
                    individual_range = f"{missing_chapter}:1-{missing_chapter}:{end_verse}"
                else:
                    # Middle chapter: fetch entire chapter
                    individual_range = f"{missing_chapter}:1-{missing_chapter}:999"
                
                logger.info(f"Fetching individual range: {individual_range}")
                individual_data = fetch_range(book, individual_range)
                
                if individual_data and isinstance(individual_data, dict):
                    individual_text = individual_data.get('text', [])
                    individual_hebrew = individual_data.get('he', [])
                    
                    if individual_text and isinstance(individual_text[0], list):
                        # Multi-chapter response, take first chapter
                        en_chap = individual_text[0]
                        he_chap = individual_hebrew[0]
                    else:
                        # Single chapter response
                        en_chap = individual_text
                        he_chap = individual_hebrew
                    
                    # Determine verse range for this chapter
                    if missing_chapter == start_chapter:
                        verse_start = start_verse
                    else:
                        verse_start = 1
                    if missing_chapter == end_chapter:
                        verse_end = end_verse
                    else:
                        verse_end = len(en_chap)
                    
                    logger.info(f"Adding missing chapter {missing_chapter}: verses {verse_start}-{verse_end}")
                    
                    for verse_idx, (en, he) in enumerate(zip(en_chap, he_chap), start=1):
                        verse_num = verse_idx
                        if verse_num < verse_start or verse_num > verse_end:
                            continue
                        clean_en = parashat_generator.clean_text(en)
                        clean_he = parashat_generator.clean_text(he)
                        verses.append({
                            'chapter': missing_chapter,
                            'verse': verse_num,
                            'en': clean_en,
                            'he': clean_he
                        })
                        logger.info(f"Added missing verse {missing_chapter}:{verse_num}")
                else:
                    logger.error(f"Failed to fetch individual range {individual_range}")
    else:
        # Single-chapter or flat list
        logger.info(f"Detected single-chapter or flat structure for {range_str}")
        verse_num = start_verse
        for idx, (en, he) in enumerate(zip(text_verses, hebrew_verses)):
            if verse_num > end_verse:
                break
            clean_en = parashat_generator.clean_text(en)
            clean_he = parashat_generator.clean_text(he)
            verses.append({
                'chapter': start_chapter,
                'verse': verse_num,
                'en': clean_en,
                'he': clean_he
            })
            logger.info(f"Added verse {start_chapter}:{verse_num}")
            verse_num += 1
    
    logger.info(f"Cleaned verses for range {range_str}: {verses}")
    return verses

def fetch_range(book, range_str):
    """Fetch verse data from Sefaria API"""
    try:
        url = f"https://www.sefaria.org/api/texts/{book}.{range_str}"
        logger.info(f"Fetching from Sefaria: {url}")
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        logger.info(f"Successfully fetched data for {book} {range_str}")
        return data
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching {book} {range_str}: {e}")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing JSON for {book} {range_str}: {e}")
        return None

if __name__ == "__main__":
    print("Starting Flask server. Open http://127.0.0.1:5001 in your web browser.")
    app.run(debug=True, port=5001)
