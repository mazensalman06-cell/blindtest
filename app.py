from flask import Flask, render_template, jsonify, request, session
from flask_socketio import SocketIO, emit, join_room
import random
import os
import string

app = Flask(__name__)
app.secret_key = 'super_cle_secrete_a_changer_en_production'

# Initialisation de SocketIO pour le temps réel
socketio = SocketIO(app, cors_allowed_origins="*")

SONGS_DIR = os.path.join('static', 'songs')

def load_local_playlist():
    playlist = []
    if not os.path.exists(SONGS_DIR):
        return playlist
    for file_id, filename in enumerate(os.listdir(SONGS_DIR)):
        if filename.endswith(('.mp3', '.m4a', '.ogg', '.opus')):
            name_without_ext = os.path.splitext(filename)[0]
            parts = name_without_ext.split(' - ', 1)
            artist = parts[0].strip().lower() if len(parts) == 2 else "inconnu"
            title = parts[1].strip().lower() if len(parts) == 2 else name_without_ext.strip().lower()
            playlist.append({"id": file_id, "title": title, "artist": artist, "file": filename, "original_name": name_without_ext})
    return playlist

PLAYLIST = load_local_playlist()

# Dictionnaire pour stocker l'état des parties en cours
games = {}

def generate_room_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))

@app.route('/')
def index():
    return render_template('index.html', exp=session.get('exp', 0))

@app.route('/classic')
def classic():
    return render_template('classic.html', exp=session.get('exp', 0))

@app.route('/battle')
def battle():
    return render_template('battle.html')

@app.route('/api/random_song')
def random_song():
    if not PLAYLIST: return jsonify({"error": "Aucune chanson."}), 500
    song = random.choice(PLAYLIST)
    return jsonify({"id": song["id"], "url": f"/static/songs/{song['file']}"})

@app.route('/api/guess', methods=['POST'])
def guess():
    data = request.json
    actual_song = next((s for s in PLAYLIST if s["id"] == data.get('id')), None)
    if not actual_song: return jsonify({"error": "Chanson non trouvée"}), 404
    
    t_correct = data.get('title', '').strip().lower() in actual_song['title'] and len(data.get('title', '')) > 2
    a_correct = data.get('artist', '').strip().lower() in actual_song['artist'] and len(data.get('artist', '')) > 2
    
    if t_correct and a_correct:
        session['exp'] = session.get('exp', 0) + 10
        return jsonify({"correct": True, "exp": session['exp'], "message": f"Bravo !\nC'était : {actual_song['original_name']}"})
    return jsonify({"correct": False, "message": f"Raté !\nC'était : {actual_song['original_name']}"})

# ==========================================
# GESTION DU TEMPS RÉEL (SOCKET.IO)
# ==========================================

@socketio.on('create_room')
def on_create_room():
    room = generate_room_code()
    join_room(room)
    # Le créateur est le Joueur 1
    games[room] = {'players': {request.sid: {'score': 0, 'id': 1}}, 'song_id': None}
    emit('room_created', {'room': room})

@socketio.on('join_room')
def on_join_room(data):
    room = data.get('room', '').upper()
    if room in games and len(games[room]['players']) < 2:
        join_room(room)
        # Celui qui rejoint est le Joueur 2
        games[room]['players'][request.sid] = {'score': 0, 'id': 2}
        emit('game_started', {'room': room, 'message': 'Un adversaire a rejoint la partie !'}, room=room)
    else:
        emit('error', {'message': 'Code invalide ou salle pleine.'})

@socketio.on('start_round')
def on_start_round(data):
    room = data.get('room')
    if room in games:
        song = random.choice(PLAYLIST)
        games[room]['song_id'] = song['id']
        # On génère le temps de départ côté serveur pour que les 2 joueurs entendent EXACTEMENT le même extrait !
        start_time = random.randint(0, 45) 
        emit('new_round', {'url': f"/static/songs/{song['file']}", 'start_time': start_time}, room=room)

@socketio.on('submit_battle_guess')
def on_submit_battle_guess(data):
    room = data.get('room')
    if room not in games: return

    guess_title = data.get('title', '').strip().lower()
    guess_artist = data.get('artist', '').strip().lower()
    song_id = games[room]['song_id']

    actual_song = next((s for s in PLAYLIST if s["id"] == song_id), None)
    if not actual_song: return

    title_correct = guess_title in actual_song['title'] and len(guess_title) > 2
    artist_correct = guess_artist in actual_song['artist'] and len(guess_artist) > 2
    player_id = games[room]['players'][request.sid]['id']

    if title_correct and artist_correct:
        games[room]['players'][request.sid]['score'] += 1
        # On calcule les scores
        scores = {p['id']: p['score'] for p in games[room]['players'].values()}
        
        emit('round_won', {
            'winner_id': player_id,
            'message': f"Le Joueur {player_id} a trouvé le premier !\nC'était : {actual_song['original_name']}",
            'scores': scores
        }, room=room)
    else:
        emit('wrong_guess', {
            'player_id': player_id,
            'message': f"Le Joueur {player_id} s'est trompé ! L'autre peut continuer."
        }, room=room)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    # Important : on utilise socketio.run au lieu de app.run
    socketio.run(app, host='0.0.0.0', port=port, debug=True)