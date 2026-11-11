#!/usr/bin/env python3
"""Relais Labo Tirages : télécharge les archives officielles FDJ (EuroMillions, Loto)
dans data/ et décrit le résultat dans data/manifest.json.

Règles :
- une archive n'est enregistrée que si c'est un ZIP intègre contenant un CSV FDJ lisible ;
- une archive valide déjà présente n'est jamais remplacée par un fichier invalide ;
- les archives Super Loto / Grand Loto sont ignorées (hors série régulière) ;
- le code de sortie vaut 1 si une archive n'a pas pu être récupérée (GitHub prévient alors par e-mail).
Bibliothèque standard uniquement.
"""
import datetime, hashlib, io, json, os, re, sys, time, urllib.request, zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.environ.get('FDJ_SOURCES', os.path.join(ROOT, 'sources.json')), encoding='utf-8'))
DATA = os.path.join(ROOT, 'data')
MAN = os.path.join(DATA, 'manifest.json')
UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36'
LINK = re.compile(r'https?://[\w.:-]+/anonymous/service-draw-info/v3/documentations/[0-9A-Za-z-]+')


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def get(url, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': '*/*', 'Accept-Language': 'fr-FR,fr;q=0.9'})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except Exception as e:  # réseau, HTTP 4xx/5xx
            last = e
            if i < tries - 1:
                time.sleep(4 * (i + 1))
    raise last


def iso(d):
    d = d.strip()
    m = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{4})$', d)
    if m:
        return '%s-%02d-%02d' % (m[3], int(m[2]), int(m[1]))
    m = re.match(r'^(\d{4})(\d{2})(\d{2})$', d)
    if m:
        return '%s-%s-%s' % (m[1], m[2], m[3])
    m = re.match(r'^(\d{4})-(\d{2})-(\d{2})', d)
    if m:
        return m[0]
    m = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{2})$', d)
    if m:
        y = int(m[3])
        return '%d-%02d-%02d' % (1900 + y if y >= 76 else 2000 + y, int(m[2]), int(m[1]))
    return None


def inspect(data):
    """Vérifie l'archive et renvoie (jeu, nom du CSV, lignes, première date, dernière date)."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        head = data[:200].decode('latin-1', 'replace').strip().replace('\n', ' ')
        raise ValueError('le fichier reçu n’est pas une archive ZIP (début : %r)' % head[:80])
    bad = z.testzip()
    if bad:
        raise ValueError('archive corrompue (CRC) : ' + bad)
    csvs = [n for n in z.namelist() if n.lower().endswith(('.csv', '.txt'))]
    if not csvs:
        raise ValueError('aucun fichier CSV dans l’archive')
    name = csvs[0]
    raw = z.read(name)
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        text = raw.decode('windows-1252', 'replace')
    lines = [l for l in text.replace('﻿', '').splitlines() if l.strip()]
    head = [h.strip().lower() for h in lines[0].split(';')]
    if 'date_de_tirage' not in head or 'boule_1' not in head:
        raise ValueError('en-têtes inattendus dans ' + name)
    base = os.path.basename(name).lower()
    if 'etoile_1' in head:
        game = 'em'
    elif re.search(r'super|grand|noel', base):
        game = None
    elif 'numero_chance' in head or 'boule_6' in head:
        game = 'loto'
    else:
        game = None
    i = head.index('date_de_tirage')
    dates = [d for d in (iso(l.split(';')[i]) if i < len(l.split(';')) else None for l in lines[1:]) if d]
    if not dates:
        raise ValueError('aucune date lisible dans ' + name)
    return game, name, len(lines) - 1, min(dates), max(dates)


def main():
    t0 = now()
    old = {}
    if os.path.exists(MAN):
        try:
            old = json.load(open(MAN, encoding='utf-8'))
        except Exception:
            old = {}
    old_files = {f['id']: dict(f, game=g) for g, v in (old.get('games') or {}).items() for f in v.get('files', [])}
    old_ignored = {f['id']: f for f in old.get('ignored', [])}

    # 1. Liste des archives : liens publiés sur les pages « Historique » + liens connus
    urls, notes = [], []
    for game, page in CFG['pages'].items():
        try:
            html = get(page).decode('utf-8', 'replace')
            found = LINK.findall(html)
            notes.append('%s : %d lien(s) trouvé(s) sur la page Historique' % (game, len(found)))
            urls += found
        except Exception as e:
            notes.append('%s : page Historique illisible (%s), liste connue utilisée' % (game, e))
    urls += CFG['known']
    urls += [f['source'] for f in old_files.values()]
    seen, ordered = set(), []
    for u in urls:
        uid = u.rstrip('/').split('/')[-1]
        if uid not in seen:
            seen.add(uid)
            ordered.append(u)

    # 2. Téléchargement et vérification
    files = {'em': [], 'loto': []}
    ignored, errors = [], []
    for url in ordered:
        uid = url.rstrip('/').split('/')[-1]
        prev = old_files.get(uid)
        if uid in old_ignored and not prev:
            ignored.append(old_ignored[uid])
            continue
        try:
            data = get(url)
            game, inner, rows, first, last = inspect(data)
            if game is None:
                ignored.append({'id': uid, 'source': url, 'inner': inner, 'reason': 'tirage spécial (Super Loto / Grand Loto) ou jeu non suivi'})
                continue
            sha = hashlib.sha256(data).hexdigest()
            rel = 'data/%s/%s.zip' % (game, uid)
            dest = os.path.join(ROOT, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            if not (prev and prev.get('sha256') == sha and os.path.exists(dest)):
                tmp = dest + '.tmp'
                with open(tmp, 'wb') as fh:
                    fh.write(data)
                os.replace(tmp, dest)
            files[game].append({'id': uid, 'source': url, 'path': rel, 'inner': os.path.basename(inner), 'sha256': sha,
                                'bytes': len(data), 'rows': rows, 'firstDate': first, 'lastDate': last, 'fetchedAt': t0,
                                'changedAt': t0 if not prev or prev.get('sha256') != sha else prev.get('changedAt', t0)})
            print('OK   %-5s %-28s %5d lignes  %s → %s' % (game, os.path.basename(inner), rows, first, last))
        except Exception as e:
            msg = '%s : %s' % (uid, e)
            if prev:  # on garde l'archive valide précédente
                keep = {k: v for k, v in prev.items() if k != 'game'}
                keep['lastError'] = str(e)
                files[prev['game']].append(keep)
            errors.append({'id': uid, 'source': url, 'game': prev['game'] if prev else None, 'error': str(e)})
            print('ÉCHEC %s' % msg, file=sys.stderr)

    # 3. Manifeste
    games = {}
    for game in ('em', 'loto'):
        fl = sorted(files[game], key=lambda f: f['lastDate'], reverse=True)
        og = (old.get('games') or {}).get(game) or {}
        latest_ok = bool(fl) and not fl[0].get('lastError') and fl[0].get('fetchedAt') == t0
        gerr = [e['error'] for e in errors if e['game'] in (game, None)]
        games[game] = {
            'lastAttempt': t0,
            'lastSuccess': t0 if latest_ok else og.get('lastSuccess'),
            'lastError': None if latest_ok and not gerr else (gerr[0] if gerr else 'archive la plus récente non récupérée'),
            'lastDraw': fl[0]['lastDate'] if fl else None,
            'files': fl,
        }
    manifest = {'relay': 'labo-tirages', 'version': 1, 'generatedAt': t0, 'pages': CFG['pages'],
                'notes': notes, 'errors': errors, 'ignored': ignored, 'games': games}
    os.makedirs(DATA, exist_ok=True)
    tmp = MAN + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, MAN)
    for n in notes:
        print('NOTE ' + n)
    print('EuroMillions : %d archive(s), dernier tirage %s' % (len(games['em']['files']), games['em']['lastDraw']))
    print('Loto         : %d archive(s), dernier tirage %s' % (len(games['loto']['files']), games['loto']['lastDraw']))
    if errors or not games['em']['lastSuccess'] or not games['loto']['lastSuccess']:
        print('%d archive(s) en échec' % len(errors), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
