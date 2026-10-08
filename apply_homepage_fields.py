"""Run once in the repo root, then commit server.py.
Adds picture_url, service_label, service_link, service_note to the homepage editor.
"""
from pathlib import Path
p = Path("server.py")
text = p.read_text()
old = """            'video_url', 'slide1_caption', 'slide2_caption', 'slide3_caption',
            'story1', 'story2', 'story3',
        ]"""
new = """            'video_url', 'picture_url', 'service_label', 'service_link', 'service_note',
            'slide1_caption', 'slide2_caption', 'slide3_caption',
            'story1', 'story2', 'story3',
        ]"""
if old not in text:
    raise SystemExit("Could not find homepage fields list in server.py")
text = text.replace(old, new, 1)
old2 = """        v = content.get('video_url') or ''
        if 'youtube.com/watch' in v and 'v=' in v:
            vid = v.split('v=')[1].split('&')[0]
            content['video_url'] = f'https://www.youtube.com/embed/{vid}'
        elif 'youtu.be/' in v:
            vid = v.split('youtu.be/')[1].split('?')[0]
            content['video_url'] = f'https://www.youtube.com/embed/{vid}'
"""
new2 = """        for key in ('video_url', 'picture_url'):
            v = content.get(key) or ''
            if 'youtube.com/watch' in v and 'v=' in v:
                vid = v.split('v=')[1].split('&')[0]
                content[key] = f'https://www.youtube.com/embed/{vid}'
            elif 'youtu.be/' in v:
                vid = v.split('youtu.be/')[1].split('?')[0]
                content[key] = f'https://www.youtube.com/embed/{vid}'
"""
if old2 not in text:
    raise SystemExit("Could not find youtube normaliser in server.py")
text = text.replace(old2, new2, 1)
p.write_text(text)
print("server.py updated")
