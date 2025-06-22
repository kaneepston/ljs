import requests
import re
import html
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.enum.text import PP_ALIGN
import datetime

def clean_text(raw_text):
    """
    A more robust function to remove all HTML tags, entities, and footnote content.
    """
    # Validate input
    if not isinstance(raw_text, str):
        print(f"Warning: clean_text received non-string input: {raw_text} (type: {type(raw_text)})")
        return str(raw_text) if raw_text is not None else ""
    
    # 1. Specifically target and remove the common footnote structure first.
    text = re.sub(r'<sup class="footnote-marker">.*?</sup><i class="footnote">.*?</i>', '', raw_text, flags=re.DOTALL)
    text = re.sub(r'<i class="footnote">.*?</i>', '', text, flags=re.DOTALL)
    
    # 2. Then, remove any other remaining HTML tags (like sup, b, span, br).
    text = re.sub(r'<.*?>', '', text)
    
    # 3. Un-escape any lingering HTML entities like &nbsp; or &thinsp;
    text = html.unescape(text)
    
    # 4. Remove any standalone footnote markers that might be left
    text = text.replace('*', '')

    # 5. Clean up any strange artifacts that might result from cleaning, like double commas.
    text = text.replace(',,', ',')

    # 6. Return the text with leading/trailing whitespace removed.
    return text.strip()

def get_next_shabbat_date(weeks_ahead=0):
    """
    Calculate the date of the next Shabbat (Saturday) that is 'weeks_ahead' weeks from now.
    """
    today = datetime.datetime.now()
    
    # Find the next Saturday (Shabbat)
    # Monday = 0, Tuesday = 1, ..., Saturday = 5, Sunday = 6
    days_until_saturday = (5 - today.weekday()) % 7
    
    # If today is Saturday, days_until_saturday will be 0, so we want next Saturday
    if days_until_saturday == 0:
        days_until_saturday = 7
    
    # Add the weeks ahead
    days_to_add = days_until_saturday + (weeks_ahead * 7)
    
    target_date = today + datetime.timedelta(days=days_to_add)
    return target_date

def get_parasha_data(weeks_ahead=0):
    """Fetch the parasha for the specified week and return a clean list of verses."""
    try:
        # Calculate the target Shabbat date
        target_date = get_next_shabbat_date(weeks_ahead)
        year = target_date.year
        month = target_date.month
        day = target_date.day
        
        print(f"Fetching parasha for date: {year}-{month:02d}-{day:02d} (weeks_ahead: {weeks_ahead})")
        
        # We specify the desired translation version.
        text_version = "vtitle=The_Contemporary_Torah,_JPS,_2006"
        
        # Use year, month, and day parameters as per Sefaria docs
        initial_cal_url = f"https://www.sefaria.org/api/calendars?year={year}&month={month}&day={day}"
        cal = requests.get(initial_cal_url).json()
        parasha_item = next(i for i in cal["calendar_items"]
                            if i["title"]["en"] == "Parashat Hashavua")

        # Extract the Gregorian date of the Parasha
        parasha_gregorian_date = cal.get("date")

        # Get Hebrew date from the same API call
        correct_hebrew_date = cal.get("hebrewDateStr", "")

        ref = parasha_item["ref"]
        print(f"Fetching parasha for date: {year}-{month:02d}-{day:02d} (weeks_ahead: {weeks_ahead})")
        
        # Parse the reference to get the correct chapter range
        # Format: "Numbers 16:1-18:32"
        ref_match = re.match(r'(\w+)\s+(\d+):(\d+)-(\d+):(\d+)', ref)
        if ref_match:
            book, start_chapter, start_verse, end_chapter, end_verse = ref_match.groups()
            start_chapter, start_verse, end_chapter, end_verse = map(int, [start_chapter, start_verse, end_chapter, end_verse])
        else:
            start_chapter = end_chapter = 1
        
        # We fetch the raw text now and will clean it ourselves.
        text_url = f"https://www.sefaria.org/api/texts/{ref}?{text_version}&context=0"
        text_data = requests.get(text_url).json()

        all_verses = []
        # Use the correctly parsed chapter range instead of API sections
        expected_chapters = list(range(start_chapter, end_chapter + 1))
        
        # Process all available text data instead of relying on sections array
        text_chapters = text_data.get('text', [])
        hebrew_chapters = text_data.get('he', [])
        section_names = text_data.get('sectionNames', [])
        
        # Process each chapter of text data
        for chap_idx in range(len(text_chapters)):
            if chap_idx >= len(expected_chapters):
                continue
                
            correct_chapter = expected_chapters[chap_idx]
            
            if chap_idx >= len(hebrew_chapters):
                continue

            en_verses_for_chap = text_chapters[chap_idx]
            he_verses_for_chap = hebrew_chapters[chap_idx]

            try:
                if chap_idx < len(section_names):
                    start_vs = int(section_names[chap_idx].split(':')[1])
                else:
                    start_vs = 1
            except (IndexError, ValueError):
                start_vs = 1

            for verse_idx, (en, he) in enumerate(zip(en_verses_for_chap, he_verses_for_chap)):
                verse_num = start_vs + verse_idx
                all_verses.append({
                    "chapter": correct_chapter,
                    "verse": verse_num,
                    "en": clean_text(en),
                    "he": clean_text(he)
                })

        if not all_verses:
             raise ValueError("No verses were parsed. Check API response.")

        return {
            "title_en": parasha_item["displayValue"]["en"],
            "hebrew_date": correct_hebrew_date,
            "gregorian_date": target_date.strftime("%A, %B %d, %Y"),
            "parasha_ref": parasha_item["ref"],
            "book": text_data["book"],
            "verses": all_verses
        }

    except Exception as e:
        print(f"An error occurred in get_parasha_data: {e}")
        return None

def create_presentation(data, output, verse_ranges=None):
    """Generates a PPTX file and saves it to the given output (path or stream)."""
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    blank_layout = prs.slide_layouts[6]
    
    verses_per_slide = 5
    all_verses = data['verses']
    total_verses = len(all_verses)

    for i in range(0, total_verses, verses_per_slide):
        slide = prs.slides.add_slide(blank_layout)
        
        verse_chunk = all_verses[i : i + verses_per_slide]
        
        # Create title based on original verse ranges if provided
        if verse_ranges:
            # Parse the original selected ranges to understand what was selected
            selected_ranges = []
            ranges = [r.strip() for r in verse_ranges.split(',')]
            for range_str in ranges:
                if ':' in range_str:
                    if '-' in range_str:
                        start_part, end_part = range_str.split('-')
                        start_chapter, start_verse = map(int, start_part.split(':'))
                        
                        if ':' in end_part:
                            end_chapter, end_verse = map(int, end_part.split(':'))
                        else:
                            end_chapter = start_chapter
                            end_verse = int(end_part)
                        
                        selected_ranges.append({
                            'start_chapter': start_chapter,
                            'start_verse': start_verse,
                            'end_chapter': end_chapter,
                            'end_verse': end_verse
                        })
            
            # Find which selected ranges are represented on this slide
            ranges_on_slide = []
            for selected_range in selected_ranges:
                # Check if any verse on this slide belongs to this selected range
                for verse in verse_chunk:
                    verse_chapter = verse['chapter']
                    verse_verse = verse['verse']
                    
                    # Check if this verse is within the selected range
                    if selected_range['start_chapter'] == selected_range['end_chapter']:
                        # Same chapter range
                        if (verse_chapter == selected_range['start_chapter'] and 
                            selected_range['start_verse'] <= verse_verse <= selected_range['end_verse']):
                            ranges_on_slide.append(selected_range)
                            break
                    else:
                        # Different chapter range
                        if ((selected_range['start_chapter'] < verse_chapter < selected_range['end_chapter']) or
                            (verse_chapter == selected_range['start_chapter'] and verse_verse >= selected_range['start_verse']) or
                            (verse_chapter == selected_range['end_chapter'] and verse_verse <= selected_range['end_verse'])):
                            ranges_on_slide.append(selected_range)
                            break
            
            # Create title from the ranges represented on this slide
            if ranges_on_slide:
                range_strings = []
                for r in ranges_on_slide:
                    # Find the actual verses from this range that are on this slide
                    verses_from_range = []
                    for verse in verse_chunk:
                        verse_chapter = verse['chapter']
                        verse_verse = verse['verse']
                        
                        # Check if this verse belongs to this range
                        if r['start_chapter'] == r['end_chapter']:
                            # Same chapter range
                            if (verse_chapter == r['start_chapter'] and 
                                r['start_verse'] <= verse_verse <= r['end_verse']):
                                verses_from_range.append(verse)
                        else:
                            # Different chapter range
                            if ((r['start_chapter'] < verse_chapter < r['end_chapter']) or
                                (verse_chapter == r['start_chapter'] and verse_verse >= r['start_verse']) or
                                (verse_chapter == r['end_chapter'] and verse_verse <= r['end_verse'])):
                                verses_from_range.append(verse)
                    
                    # Create range string for the actual verses on this slide
                    if verses_from_range:
                        if len(verses_from_range) == 1:
                            # Single verse
                            verse = verses_from_range[0]
                            range_strings.append(f"{verse['chapter']}:{verse['verse']}")
                        else:
                            # Multiple verses - show the actual range
                            start_verse = verses_from_range[0]
                            end_verse = verses_from_range[-1]
                            
                            if start_verse['chapter'] == end_verse['chapter']:
                                # Same chapter
                                range_strings.append(f"{start_verse['chapter']}:{start_verse['verse']}-{end_verse['verse']}")
                            else:
                                # Different chapters
                                range_strings.append(f"{start_verse['chapter']}:{start_verse['verse']}-{end_verse['chapter']}:{end_verse['verse']}")
                
                title_text = f"{data['book']} {', '.join(range_strings)}"
            else:
                # Fallback: show the actual verses on the slide
                if len(verse_chunk) == 1:
                    verse = verse_chunk[0]
                    title_text = f"{data['book']} {verse['chapter']}:{verse['verse']}"
                else:
                    start_verse = verse_chunk[0]
                    end_verse = verse_chunk[-1]
                    if start_verse['chapter'] == end_verse['chapter']:
                        title_text = f"{data['book']} {start_verse['chapter']}:{start_verse['verse']}-{end_verse['verse']}"
                    else:
                        title_text = f"{data['book']} {start_verse['chapter']}:{start_verse['verse']} - {end_verse['chapter']}:{end_verse['verse']}"
        else:
            # Fallback to the original logic for when no ranges are specified
            if len(verse_chunk) == 1:
                # Single verse
                verse = verse_chunk[0]
                title_text = f"{data['book']} {verse['chapter']}:{verse['verse']}"
            else:
                # Multiple verses - check if they're all in the same chapter
                chapters_in_chunk = set(v['chapter'] for v in verse_chunk)
                if len(chapters_in_chunk) == 1:
                    # All verses in same chapter
                    chapter = verse_chunk[0]['chapter']
                    start_verse = verse_chunk[0]['verse']
                    end_verse = verse_chunk[-1]['verse']
                    title_text = f"{data['book']} {chapter}:{start_verse}-{end_verse}"
                else:
                    # Verses span multiple chapters - show the range
                    start_verse_obj = verse_chunk[0]
                    end_verse_obj = verse_chunk[-1]
                    title_text = f"{data['book']} {start_verse_obj['chapter']}:{start_verse_obj['verse']} - {end_verse_obj['chapter']}:{end_verse_obj['verse']}"

        title_box = slide.shapes.add_textbox(Inches(0.5), Inches(0.4), width=Inches(12.333), height=Inches(0.75))
        tf = title_box.text_frame
        p = tf.add_paragraph()
        p.text = title_text
        p.alignment = PP_ALIGN.CENTER
        p.font.name = 'Sylfaen'
        p.font.size = Pt(28)
        p.font.bold = True

        # Create text content with ellipsis only for gaps
        en_parts = []
        he_parts = []
        
        for i, verse in enumerate(verse_chunk):
            # Add ellipsis if there's a gap from the previous verse
            if i > 0:
                prev_verse = verse_chunk[i-1]
                
                # Check if there's a gap in verses or chapters
                if (prev_verse['chapter'] == verse['chapter'] and 
                    verse['verse'] != prev_verse['verse'] + 1):
                    # Gap in verses within same chapter
                    en_parts.append("...")
                    he_parts.append("...")
                elif prev_verse['chapter'] != verse['chapter']:
                    # Gap in chapters
                    en_parts.append("...")
                    he_parts.append("...")
            
            en_parts.append(verse['en'])
            he_parts.append(verse['he'])
        
        en_text = " ".join(en_parts)
        he_text = " ".join(he_parts)

        en_box = slide.shapes.add_textbox(Inches(0.5), Inches(1.2), width=Inches(6.0), height=Inches(5.8))
        tf_en = en_box.text_frame
        tf_en.word_wrap = True
        p_en = tf_en.add_paragraph()
        p_en.text = en_text
        p_en.font.name = 'Sylfaen'
        p_en.font.size = Pt(20)

        he_box = slide.shapes.add_textbox(Inches(6.833), Inches(1.2), width=Inches(6.0), height=Inches(5.8))
        tf_he = he_box.text_frame
        tf_he.word_wrap = True
        p_he = tf_he.paragraphs[0]
        p_he.alignment = PP_ALIGN.RIGHT
        
        run = p_he.add_run()
        run.text = he_text
        font = run.font
        font.name = 'Times New Roman'
        font.size = Pt(30)
        font.bold = True
    
    prs.save(output)


if __name__ == "__main__":
    print("Fetching weekly Parasha from Sefaria.org...")
    parasha_data = get_parasha_data()
    if parasha_data:
        print(f"Found: {parasha_data['title_en']}")
        print(f"Total verses found: {len(parasha_data['verses'])}")
        file_name = f"{parasha_data['title_en']}.pptx"
        print(f"Generating PowerPoint presentation: {file_name}")
        create_presentation(parasha_data, output=file_name)
        print("Presentation saved successfully.")
