from flask import Flask, render_template, jsonify, request, session
from flask_socketio import SocketIO, emit, join_room
from difflib import SequenceMatcher
import unicodedata
import random
import string
import re
import os

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'blindify_secret_key_2026')

socketio = SocketIO(app, cors_allowed_origins="*")

SONGS_DIR = os.path.join('static', 'songs')


def clean_text(text):
    """Normalise le texte : minuscules, sans accents, sans mentions (feat...), sans ponctuation."""
    if not text:
        return ""
    text = text.lower()
    # Supprime les mentions entre parenthèses/crochets comme (feat. X) ou [Official Audio]
    text = re.sub(r'[\(\[].*?[\)\]]', '', text)
    # Supprime les accents
    text = unicodedata.normalize('NFD', text).encode('ascii', 'ignore').decode('utf-8')
    # Garde uniquement les lettres, chiffres et espaces
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def is_fuzzy_match(user_guess, target_raw, is_artist=False):
    """Vérifie si la réponse est juste même avec des fautes d'orthographe."""
    guess = clean_text(user_guess)
    if len(guess) < 2:
        return False

    # Si c'est un artiste, on découpe au cas où il y a plusieurs artistes (ex: "Ninho, Niska")
    candidates = [target_raw]
    if is_artist:
        parts = re.split(r',|&|\bfeat\b|\bft\b|\bx\b', target_raw, flags=re.IGNORECASE)
        candidates.extend(parts)

    for cand in candidates:
        target = clean_text(cand)
        if not target:
            continue

        # 1. Correspondance exacte
        if guess == target:
            return True

        # 2. Mot-clé contenu (ex: "weeknd" pour "the weeknd", minimum 4 caractères)
        if len(guess) >= 4 and (guess in target or target in guess):
            return True

        # 3. Similarité orthographique (tolère ~25-28% d'erreur de frappe)
        ratio = SequenceMatcher(None, guess, target).ratio()
        if ratio >= 0.72:
            return True

    return False


def load_local_playlist():
    """Charge toutes les musiques du dossier static/songs."""
    playlist = []
    if not os.path.exists(SONGS_DIR):
        os.makedirs(SONGS_DIR, exist_ok=True)
        return playlist

    for idx, filename in enumerate(sorted(os.listdir(SONGS_DIR))):
        if filename.lower().endswith(('.mp3', '.m4a', '.ogg', '.opus', '.wav')):
            name_no_ext = os.path.splitext(filename)[0]
            if ' - ' in name_no_ext:
                artist, title = name_no_ext.split(' - ', 1)
            else:
                artist, title = "Artiste inconnu", name_no_ext

            playlist.append({
                "id": idx,
                "artist": artist.strip(),
                "title": title.strip(),
                "file": filename,
                "url": f"/static/songs/{filename}"
            })
    return playlist


PLAYLIST = load_local_playlist()
games = {}


def generate_room_code():
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
        if code not in games:
            return code


# ==========================================
# ROUTES DES PAGES
# ==========================================

@app.route('/')
@app.route('/index.html')
def index():
    return render_template('index.html', exp=session.get('exp', 0))


@app.route('/classic')
@app.route('/classic.html')
def classic():
    return render_template('classic.html', exp=session.get('exp', 0))


@app.route('/battle')
@app.route('/battle.html')
def battle():
    return render_template('battle.html', exp=session.get('exp', 0))


# ==========================================
# API MODE CLASSIC
# ==========================================

@app.route('/api/classic/start', methods=['POST'])
def classic_start():
    if not PLAYLIST:
        return jsonify({"error": "Aucune musique trouvée dans static/songs/"}), 500

    count = min(10, len(PLAYLIST))
    selected = random.sample(PLAYLIST, count)
    # On renvoie uniquement l'ID, l'URL audio et un point de départ aléatoire (entre 15% et 55% du morceau)
    questions = [
        {
            "id": s["id"],
            "url": s["url"],
            "start_ratio": round(random.uniform(0.15, 0.55), 2)
        }
        for s in selected
    ]
    return jsonify({"questions": questions})


@app.route('/api/classic/check', methods=['POST'])
def classic_check():
    data = request.json or {}
    song_id = data.get('id')
    guess = data.get('guess', '')
    found_title = bool(data.get('foundTitle', False))
    found_artist = bool(data.get('foundArtist', False))

    song = next((s for s in PLAYLIST if s["id"] == song_id), None)
    if not song:
        return jsonify({"error": "Chanson introuvable"}), 404

    matched_title = False
    matched_artist = False

    if not found_title and is_fuzzy_match(guess, song["title"], is_artist=False):
        matched_title = True
    if not found_artist and is_fuzzy_match(guess, song["artist"], is_artist=True):
        matched_artist = True

    return jsonify({
        "matchedTitle": matched_title,
        "matchedArtist": matched_artist,
        "title": song["title"],
        "artist": song["artist"]
    })


@app.route('/api/classic/reveal', methods=['POST'])
def classic_reveal():
    data = request.json or {}
    song_id = data.get('id')
    song = next((s for s in PLAYLIST if s["id"] == song_id), None)
    if not song:
        return jsonify({"title": "Inconnu", "artist": "Inconnu"})
    return jsonify({"title": song["title"], "artist": song["artist"]})


@app.route('/api/xp/add', methods=['POST'])
def add_xp():
    data = request.json or {}
    gained = int(data.get('xp', 0))
    if gained > 0:
        session['exp'] = session.get('exp', 0) + gained
    return jsonify({"totalExp": session.get('exp', 0)})


# ==========================================
# TEMPS RÉEL - BATTLE MODE (SOCKET.IO)
# ==========================================

@socketio.on('create_room')
def on_create_room():
    room = generate_room_code()
    join_room(room)
    games[room] = {
        'players': {
            request.sid: {'num': 1, 'score': 0, 'found_title': False, 'found_artist': False, 'done': False}
        },
        'song': None,
        'round': 0,
        'max_rounds': 10,
        'used_ids': [],
        'round_active': False
    }
    emit('room_created', {'room': room, 'playerNum': 1})


@socketio.on('join_room')
def on_join_room(data):
    room = (data or {}).get('room', '').strip().upper()
    if room not in games:
        emit('battle_error', {'message': "Code de salle introuvable."})
        return
    if len(games[room]['players']) >= 2:
        emit('battle_error', {'message': "Cette salle est déjà complète (2/2 joueurs)."})
        return

    join_room(room)
    games[room]['players'][request.sid] = {
        'num': 2, 'score': 0, 'found_title': False, 'found_artist': False, 'done': False
    }
    emit('player_joined', {'room': room, 'playerNum': 2})
    emit('match_ready', {'room': room}, room=room)


def start_next_battle_round(room):
    game = games.get(room)
    if not game or not PLAYLIST:
        return

    if game['round'] >= game['max_rounds']:
        scores = {p['num']: p['score'] for p in game['players'].values()}
        emit('match_finished', {'scores': scores}, room=room)
        return

    game['round'] += 1
    game['round_active'] = True

    available = [s for s in PLAYLIST if s['id'] not in game['used_ids']]
    if not available:
        available = PLAYLIST
        game['used_ids'] = []

    song = random.choice(available)
    game['used_ids'].append(song['id'])
    game['song'] = song

    for p in game['players'].values():
        p['found_title'] = False
        p['found_artist'] = False
        p['done'] = False

    start_ratio = round(random.uniform(0.15, 0.55), 2)
    emit('new_round', {
        'round': game['round'],
        'maxRounds': game['max_rounds'],
        'url': song['url'],
        'startRatio': start_ratio
    }, room=room)


@socketio.on('start_match')
def on_start_match(data):
    room = (data or {}).get('room', '').upper()
    if room in games and len(games[room]['players']) == 2:
        start_next_battle_round(room)


@socketio.on('battle_guess')
def on_battle_guess(data):
    room = (data or {}).get('room', '').upper()
    guess = (data or {}).get('guess', '')
    time_left = int((data or {}).get('timeLeft', 0))

    game = games.get(room)
    if not game or not game['round_active'] or request.sid not in game['players']:
        return

    player = game['players'][request.sid]
    song = game['song']
    if player['done'] or not song:
        return

    matched_t = not player['found_title'] and is_fuzzy_match(guess, song['title'], is_artist=False)
    matched_a = not player['found_artist'] and is_fuzzy_match(guess, song['artist'], is_artist=True)

    if matched_t or matched_a:
        pts = 0
        if matched_t:
            player['found_title'] = True
            pts += 50
        if matched_a:
            player['found_artist'] = True
            pts += 50

        # Bonus complet + rapidité si le joueur a trouvé les deux
        if player['found_title'] and player['found_artist']:
            player['done'] = True
            pts += 25 + max(0, time_left * 2)

        player['score'] += pts
        scores = {p['num']: p['score'] for p in game['players'].values()}

        emit('guess_result', {
            'correct': True,
            'matchedTitle': matched_t,
            'matchedArtist': matched_a,
            'foundTitle': player['found_title'],
            'foundArtist': player['found_artist'],
            'done': player['done'],
            'pts': pts
        }, to=request.sid)

        emit('scores_updated', {
            'scores': scores,
            'playerNum': player['num'],
            'playerDone': player['done']
        }, room=room)

        # Si les 2 joueurs ont tout trouvé, on révèle immédiatement la réponse
        if all(p['done'] for p in game['players'].values()):
            game['round_active'] = False
            emit('round_ended', {
                'title': song['title'],
                'artist': song['artist'],
                'scores': scores
            }, room=room)
    else:
        emit('guess_result', {'correct': False}, to=request.sid)


@socketio.on('round_timeout')
def on_round_timeout(data):
    room = (data or {}).get('room', '').upper()
    game = games.get(room)
    if not game or not game['round_active']:
        return

    game['round_active'] = False
    song = game['song']
    scores = {p['num']: p['score'] for p in game['players'].values()}
    emit('round_ended', {
        'title': song['title'],
        'artist': song['artist'],
        'scores': scores
    }, room=room)


@socketio.on('next_round')
def on_next_round(data):
    room = (data or {}).get('room', '').upper()
    game = games.get(room)
    if game and not game['round_active']:
        start_next_battle_round(room)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=True)