import requests
import re
import html
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.enum.text import PP_ALIGN

def clean_text(raw_text):
    """
    A more robust function to remove all HTML tags, entities, and footnote content.
    """
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

def get_parasha_data():
    """Fetch the current week's parasha and return a clean list of verses."""
    try:
        # We specify the desired translation version.
        text_version = "vtitle=The_Contemporary_Torah,_JPS,_2006"
        
        # 1. First API call to get the Parasha and its Gregorian date
        initial_cal_url = "https://www.sefaria.org/api/calendars"
        cal = requests.get(initial_cal_url).json()
        parasha_item = next(i for i in cal["calendar_items"]
                            if i["title"]["en"] == "Parashat Hashavua")

        # Extract the Gregorian date of the Parasha
        parasha_gregorian_date = cal.get("date")

        # 2. Second API call to get the correct Hebrew date for the Parasha's date
        date_specific_cal_url = f"https://www.sefaria.org/api/calendars?dt={parasha_gregorian_date}"
        date_cal = requests.get(date_specific_cal_url).json()
        correct_hebrew_date = date_cal.get("hebrewDateStr", "")

        ref = parasha_item["ref"]
        # We fetch the raw text now and will clean it ourselves.
        text_url = f"https://www.sefaria.org/api/texts/{ref}?{text_version}&context=0"
        text_data = requests.get(text_url).json()

        all_verses = []
        # This robust logic handles multi-chapter readings correctly.
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
                    "en": clean_text(en),
                    "he": clean_text(he)
                })

        if not all_verses:
             raise ValueError("No verses were parsed. Check API response.")

        return {
            "title_en": parasha_item["displayValue"]["en"],
            "hebrew_date": correct_hebrew_date,
            "parasha_ref": parasha_item["ref"],
            "book": text_data["book"],
            "verses": all_verses
        }

    except Exception as e:
        print(f"An error occurred in get_parasha_data: {e}")
        return None


def create_presentation(data, output):
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
        
        start_verse_obj = verse_chunk[0]
        end_verse_obj = verse_chunk[-1]

        if start_verse_obj['chapter'] == end_verse_obj['chapter']:
            title_text = f"{data['book']} {start_verse_obj['chapter']}:{start_verse_obj['verse']}-{end_verse_obj['verse']}"
        else:
            title_text = f"{data['book']} {start_verse_obj['chapter']}:{start_verse_obj['verse']} - {end_verse_obj['chapter']}:{end_verse_obj['verse']}"

        title_box = slide.shapes.add_textbox(Inches(0.5), Inches(0.4), width=Inches(12.333), height=Inches(0.75))
        tf = title_box.text_frame
        p = tf.add_paragraph()
        p.text = title_text
        p.alignment = PP_ALIGN.CENTER
        p.font.name = 'Sylfaen'
        p.font.size = Pt(28)
        p.font.bold = True

        en_text = " ".join([v['en'] for v in verse_chunk])
        he_text = " ".join([v['he'] for v in verse_chunk])

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
        print(f"Hebrew Date: {parasha_data.get('hebrew_date', 'N/A')}")
        print(f"Total verses found: {len(parasha_data['verses'])}")
        file_name = f"{parasha_data['title_en']}.pptx"
        print(f"Generating PowerPoint presentation: {file_name}")
        create_presentation(parasha_data, output=file_name)
        print("Presentation saved successfully.")
