from flask import Flask, render_template, jsonify, request, session
import random
import os

app = Flask(__name__)
app.secret_key = 'super_cle_secrete_a_changer_en_production'

SONGS_DIR = os.path.join('static', 'songs')

def load_local_playlist():
    playlist = []
    if not os.path.exists(SONGS_DIR):
        return playlist

    for file_id, filename in enumerate(os.listdir(SONGS_DIR)):
        if filename.endswith(('.mp3', '.m4a', '.ogg', '.opus')):
            name_without_ext = os.path.splitext(filename)[0]
            parts = name_without_ext.split(' - ', 1)
            
            if len(parts) == 2:
                artist = parts[0].strip().lower()
                title = parts[1].strip().lower()
            else:
                artist = "inconnu"
                title = name_without_ext.strip().lower()

            playlist.append({
                "id": file_id,
                "title": title,
                "artist": artist,
                "file": filename,
                "original_name": name_without_ext
            })
    return playlist

PLAYLIST = load_local_playlist()

@app.route('/')
def index():
    if 'exp' not in session:
        session['exp'] = 0
    return render_template('index.html', exp=session['exp'])

@app.route('/classic')
def classic():
    if 'exp' not in session:
        session['exp'] = 0
    return render_template('classic.html', exp=session['exp'])

@app.route('/battle')
def battle():
    return render_template('battle.html')

@app.route('/api/random_song')
def random_song():
    if not PLAYLIST:
        return jsonify({"error": "Aucune chanson trouvée."}), 500
    
    song = random.choice(PLAYLIST)
    return jsonify({
        "id": song["id"], 
        "url": f"/static/songs/{song['file']}"
    })

@app.route('/api/guess', methods=['POST'])
def guess():
    data = request.json
    song_id = data.get('id')
    guess_title = data.get('title', '').strip().lower()
    guess_artist = data.get('artist', '').strip().lower()

    actual_song = next((s for s in PLAYLIST if s["id"] == song_id), None)
    if not actual_song:
        return jsonify({"error": "Chanson non trouvée"}), 404

    title_correct = guess_title in actual_song['title'] and len(guess_title) > 2
    artist_correct = guess_artist in actual_song['artist'] and len(guess_artist) > 2

    if title_correct and artist_correct:
        session['exp'] += 10
        return jsonify({
            "correct": True, 
            "exp": session['exp'], 
            "message": f"Bravo ! +10 EXP 🌟\nC'était : {actual_song['original_name']}"
        })
    else:
        return jsonify({
            "correct": False, 
            "message": f"Raté !\nC'était : {actual_song['original_name']}"
        })



if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)