"""
Saute Mouton — Projet L1 Info 2025-2026
Université Gustave Eiffel

Un mouton (cercle) doit atteindre une cible en sautant sur des plateformes.
Le joueur clique pour donner une vitesse au mouton.

Lancement : python3 sautemouton.py
"""

from fltk import *
import sys
import math
from collections import deque

# --- Constantes imposées ---
VMAX = 13           # Vitesse max en pixels/pas
GRAVITE = (0, 1)    # Vecteur gravité (gx, gy)
PAS = 0.1           # Pas de temps δ (0 < δ ≤ 1)
LARGEUR = 800       # Largeur fenêtre (px)
HAUTEUR = 600       # Hauteur fenêtre (px)
RAYON_PERSO = 15    # Rayon du personnage

# Nombre de pas de physique appliqués à chaque frame
# Plus ce nombre est grand, plus la simulation est rapide
N_ETAPES = 10

MAX_RAYON = 150  # Rayon max de la flèche de visée en pixels

# Types de plateformes supportés
TYPES_BLOCS = ('normale', 'collante', 'glissante')

# Couleurs (bordure, remplissage) par type
COULEURS_BLOCS = {
    'normale':   ('#2d8c2d', '#4caf50'),
    'collante':  ('#3b1f0a', '#5c3317'),
    'glissante': ('#2a8fa8', '#4dd0e1'),
}

COULEUR_CIEL = '#b3e0f7'
COULEUR_SOL  = '#7ec850'

# --- Paramètres du solveur automatique ---
N_ANGLES_SOLVEUR     = 24   # Directions discrètes testées par saut
N_PUISSANCES_SOLVEUR = 4    # Niveaux de puissance (1/N … N/N × VMAX)
N_ETAPES_SOLVEUR     = 5    # Pas de physique par frame en simulation (plus rapide)
PRECISION_ETAT       = 25   # Résolution grille déduplication (px)
MAX_FRAMES_SAUT      = 200  # Frames max par simulation de saut (filet de sécurité)
STABLE_SEUIL         = 0.3  # Déplacement max (px/frame) pour déclarer le mouton posé
STABLE_DUREE         = 5    # Nombre de frames stables consécutives → posé
APPROX_POS           = 20   # Finesse approximation positions (paramètre a)
APPROX_VIT           = 3    # Finesse approximation vitesses  (paramètre b)
FREQ_AFFICHAGE       = 5    # Appel callback toutes les N nouvelles positions explorées


# ---------------------------------------------------------------------------
# Chargement du niveau
# ---------------------------------------------------------------------------

def charge_niveau(fichier):
    """
    Lit un fichier de niveau .txt (format CSV) et retourne les données de jeu.

    Format du fichier (valeurs séparées par des virgules, sans mots-clés) :
      - Ligne 1 : x,y                     → position de départ du personnage
      - Ligne 2 : ax,ay,bx,by             → rectangle englobant l'objectif ;
                                             le centre et le rayon sont calculés
                                             automatiquement depuis ce rectangle.
      - Lignes suivantes : ax,ay,bx,by[,type]
                                           → rectangle d'un bloc/plateforme.
                                             Le 5e champ (type) est optionnel ;
                                             valeurs possibles : 'normale' (défaut),
                                             'collante', 'glissante'.
      - Les lignes vides sont ignorées.

    Retourne un tuple (personnage, objectif, lst_blocs) où :
      - personnage = {'x': float, 'y': float, 'vx': float, 'vy': float}
      - objectif   = {'x': float, 'y': float, 'rayon': float}
      - lst_blocs  = liste de {'ax': float, 'ay': float, 'bx': float, 'by': float,
                               'type': str}  # 'normale' | 'collante' | 'glissante'
    """
    with open(fichier, 'r') as f:
        lignes = f.readlines()

    # Ligne 1 : position du personnage
    valeurs = lignes[0].strip().split(',')
    personnage = {
        'x': float(valeurs[0]),
        'y': float(valeurs[1]),
        'vx': 0.0,
        'vy': 0.0
    }

    # Ligne 2 : objectif décrit comme un rectangle ax,ay,bx,by
    # On calcule le centre et le rayon à partir du rectangle
    valeurs = lignes[1].strip().split(',')
    ax, ay, bx, by = float(valeurs[0]), float(valeurs[1]), float(valeurs[2]), float(valeurs[3])
    objectif = {
        'x': (ax + bx) / 2,
        'y': (ay + by) / 2,
        'rayon': (bx - ax) / 2
    }

    # Lignes suivantes : blocs (plateformes, murs, sol)
    lst_blocs = []
    for ligne in lignes[2:]:
        ligne = ligne.strip()
        if ligne == '':
            continue
        valeurs = ligne.split(',')
        type_bloc = valeurs[4].strip() if len(valeurs) >= 5 else 'normale'
        if type_bloc not in TYPES_BLOCS:
            type_bloc = 'normale'
        bloc = {
            'ax':   float(valeurs[0]),
            'ay':   float(valeurs[1]),
            'bx':   float(valeurs[2]),
            'by':   float(valeurs[3]),
            'type': type_bloc
        }
        lst_blocs.append(bloc)

    return personnage, objectif, lst_blocs


# ---------------------------------------------------------------------------
# Physique et collisions
# ---------------------------------------------------------------------------

def pas_physique(personnage):
    """
    Applique un pas de temps δ à la physique du personnage.

    Equations appliquées à chaque pas :
      x  = x  + δ × vx      vx = vx + δ × gx
      y  = y  + δ × vy      vy = vy + δ × gy

    La gravité (gx, gy) est définie par la constante GRAVITE.
    """
    gx, gy = GRAVITE
    personnage['x'] += PAS * personnage['vx']
    personnage['y'] += PAS * personnage['vy']
    personnage['vx'] += PAS * gx
    personnage['vy'] += PAS * gy


def _collision_bloc(personnage, bloc):
    """
    Teste la collision cercle-rectangle pour un seul bloc.

    Retourne (nx, ny, penetration) si collision, None sinon.
    nx, ny est le vecteur unitaire pointant du bloc vers le centre du cercle
    (direction de push-out). penetration est la profondeur d'interpénétration.

    Cas particulier : si le centre du cercle est à l'intérieur du bloc
    (dist == 0), on utilise le principe SAT pour choisir l'axe de moindre
    chevauchement et pousser dans la direction minimale.
    """
    px, py = personnage['x'], personnage['y']
    cx = max(bloc['ax'], min(px, bloc['bx']))
    cy = max(bloc['ay'], min(py, bloc['by']))
    dx, dy = px - cx, py - cy
    dist = (dx ** 2 + dy ** 2) ** 0.5

    if dist >= RAYON_PERSO:
        return None

    penetration = RAYON_PERSO - dist

    if dist == 0:
        # Centre dans le bloc → fallback SAT (axe de moindre chevauchement)
        ov_x = min(px - bloc['ax'], bloc['bx'] - px)
        ov_y = min(py - bloc['ay'], bloc['by'] - py)
        if ov_x <= ov_y:
            nx = 1.0 if px > (bloc['ax'] + bloc['bx']) / 2 else -1.0
            ny = 0.0
            penetration = ov_x + RAYON_PERSO
        else:
            nx = 0.0
            ny = 1.0 if py > (bloc['ay'] + bloc['by']) / 2 else -1.0
            penetration = ov_y + RAYON_PERSO
    else:
        nx, ny = dx / dist, dy / dist

    return nx, ny, penetration


def collision(personnage, lst_blocs):
    """
    Retourne True si le personnage touche au moins un bloc.

    Délègue le calcul à _collision_bloc() pour chaque bloc de la liste.
    La signature et le contrat (booléen) sont ceux imposés par le projet.
    """
    for bloc in lst_blocs:
        if _collision_bloc(personnage, bloc) is not None:
            return True
    return False


def choc(personnage, lst_blocs):
    """
    Gère le choc du personnage contre les blocs avec correction de position.

    Pour chaque bloc en collision :
      1. Push-out : déplace le personnage hors du bloc selon la normale.
      2. Côté touché : |ny| >= |nx| → haut/bas, sinon → côté gauche/droit.
      3. Réponse en vitesse selon le type de bloc :
         - 'normale'  : haut/bas → vx=vy=0 ; côté → vx=0, vy continue (chute)
         - 'collante' : toujours  → vx=vy=0 (colle quelle que soit la face)
         - 'glissante': haut/bas  → vy=0 seulement (glisse horizontalement)
                        côté      → vx=0 seulement
    """
    for bloc in lst_blocs:
        res = _collision_bloc(personnage, bloc)
        if res is None:
            continue
        nx, ny, penetration = res

        # 1. Correction de position
        personnage['x'] += nx * penetration
        personnage['y'] += ny * penetration

        # 2. Identifier le côté touché
        top_bottom = abs(ny) >= abs(nx)
        type_bloc = bloc.get('type', 'normale')

        # 3. Réponse en vitesse
        if type_bloc == 'collante':
            personnage['vx'] = 0.0
            personnage['vy'] = 0.0
        elif type_bloc == 'glissante':
            if top_bottom:
                personnage['vy'] = 0.0
            else:
                personnage['vx'] = 0.0
        else:  # normale
            if top_bottom:
                personnage['vx'] = 0.0
                personnage['vy'] = 0.0
            else:
                personnage['vx'] = 0.0  # tombe le long du mur


def victoire(personnage, objectif):
    """
    Retourne True si le personnage a atteint l'objectif.

    La victoire est détectée quand la distance entre le centre du personnage
    et le centre de l'objectif est inférieure à la somme de leurs rayons.
    """
    dx = personnage['x'] - objectif['x']
    dy = personnage['y'] - objectif['y']
    distance = (dx ** 2 + dy ** 2) ** 0.5
    return distance < RAYON_PERSO + objectif['rayon']


def clic_vers_vitesse(cx, cy, px, py, max_rayon=MAX_RAYON):
    """
    Convertit la position d'un clic souris en vecteur vitesse pour le personnage.

    La direction va du personnage (px, py) vers le clic (cx, cy).
    La puissance est proportionnelle à la distance : 0 si clic sur le personnage,
    VMAX si la distance dépasse max_rayon. Au-delà de max_rayon la vitesse est
    plafonnée à VMAX.

    Retourne (vx, vy) ou (0, 0) si le clic est exactement sur le personnage.
    """
    dx = cx - px
    dy = cy - py
    longueur = (dx ** 2 + dy ** 2) ** 0.5

    if longueur == 0:
        return 0.0, 0.0

    puissance = min(longueur, max_rayon) / max_rayon
    vx = (dx / longueur) * VMAX * puissance
    vy = (dy / longueur) * VMAX * puissance
    return vx, vy


# ---------------------------------------------------------------------------
# Solveur automatique
# ---------------------------------------------------------------------------

def directions_discretes(n_angles=N_ANGLES_SOLVEUR, n_puissances=N_PUISSANCES_SOLVEUR):
    """
    Génère la liste des vecteurs vitesse (vx, vy) discrétisés pour le solveur.

    Répartit n_angles directions uniformément sur le cercle [0, 2π[, et pour
    chaque direction teste n_puissances niveaux de puissance allant de
    1/n_puissances × VMAX jusqu'à VMAX.

    Retourne une liste de tuples (vx, vy).
    """
    dirs = []
    for i in range(n_angles):
        angle = 2 * math.pi * i / n_angles
        for j in range(1, n_puissances + 1):
            puissance = j / n_puissances
            vx = math.cos(angle) * VMAX * puissance
            vy = math.sin(angle) * VMAX * puissance
            dirs.append((vx, vy))
    return dirs



def _simule_saut_etat(depart, vx, vy, lst_blocs, objectif):
    """
    Simule un saut complet depuis depart avec la vitesse (vx, vy).

    Applique la physique (N_ETAPES_SOLVEUR pas par frame) jusqu'à ce que
    le personnage se stabilise, tombe hors de l'écran ou atteigne l'objectif.

    La stabilité est détectée uniquement par la variation de position :
    STABLE_DUREE frames consécutives avec un déplacement < STABLE_SEUIL px.
    On n'utilise pas collision() comme critère car après push-out le mouton
    est exactement à la surface (distance == RAYON_PERSO), ce qui fait
    renvoyer False à collision() et bloquerait la détection.

    Retourne un tuple (personnage_final, victoire_atteinte, hors_ecran) :
      - personnage_final : dict {'x', 'y', 'vx', 'vy'} après simulation
      - victoire_atteinte : True si l'objectif a été touché
      - hors_ecran : True si le personnage est sorti par le bas
    """
    perso = {'x': depart['x'], 'y': depart['y'], 'vx': vx, 'vy': vy}
    stable_count = 0
    prev_x, prev_y = perso['x'], perso['y']

    for _ in range(MAX_FRAMES_SAUT):
        for _ in range(N_ETAPES_SOLVEUR):
            pas_physique(perso)
            choc(perso, lst_blocs)

        if victoire(perso, objectif):
            return perso, True, False

        if (perso['y'] > HAUTEUR + RAYON_PERSO
                or perso['x'] < -RAYON_PERSO
                or perso['x'] > LARGEUR + RAYON_PERSO):
            return perso, False, True

        # Détection stabilité : position quasi-identique (sans collision())
        # Après choc, le mouton est exactement au bord → collision() = False,
        # mais la position ne bouge plus → on détecte par déplacement seul.
        dx = abs(perso['x'] - prev_x)
        dy = abs(perso['y'] - prev_y)
        prev_x, prev_y = perso['x'], perso['y']

        if dx < STABLE_SEUIL and dy < STABLE_SEUIL:
            stable_count += 1
            if stable_count >= STABLE_DUREE:
                return perso, False, False
        else:
            stable_count = 0

    return perso, False, False


def simule_saut(personnage, vx, vy, lst_blocs, objectif):
    """
    Simule un saut complet et indique si l'objectif est atteint.

    Applique la vitesse (vx, vy) au personnage, puis simule la physique
    jusqu'à stabilisation, chute hors écran ou victoire.

    Retourne True si l'objectif est atteint durant ce saut, False sinon.
    """
    _, victoire_atteinte, _ = _simule_saut_etat(personnage, vx, vy, lst_blocs, objectif)
    return victoire_atteinte


def _arrondi_etat(perso):
    """
    Réduit la position du personnage à une cellule de grille pour la déduplication.

    Retourne un tuple (ix, iy) d'entiers représentant la cellule de taille
    PRECISION_ETAT × PRECISION_ETAT dans laquelle se trouve le personnage.
    """
    return (round(perso['x'] / PRECISION_ETAT),
            round(perso['y'] / PRECISION_ETAT))


def _vitesses_approchees(b=APPROX_VIT):
    """
    Génère une grille de vecteurs vitesse (vx, vy) avec un pas b.

    Parcourt les valeurs entières de -VMAX à +VMAX avec un incrément b
    pour vx et vy. La direction nulle (0, 0) est exclue.

    Retourne une liste de tuples (vx, vy).
    """
    vmax = int(VMAX)
    return [(vx, vy)
            for vx in range(-vmax, vmax + 1, b)
            for vy in range(-vmax, vmax + 1, b)
            if vx != 0 or vy != 0]


def solveur_naif(personnage_depart, objectif, lst_blocs, callback=None):
    """
    Résout le niveau par backtracking en profondeur (algorithme naïf du sujet).

    Algorithme (§Tâche 4 — recherche en profondeur) :
      1. Victoire immédiate → True.
      2. Position déjà dans visite → False ; sinon l'ajouter à visite.
      3. Pour chaque vecteur vitesse discret (vx, vy) de directions_discretes() :
           simuler le saut complet → ignorer si hors-écran ;
           si victoire : enregistrer le coup et retourner True ;
           sinon : récurser depuis la nouvelle position, backtracker si échec.
      4. Retourner False.

    La terminaison est garantie par l'ensemble visite qui empêche de repasser
    deux fois par la même position (déduplication sur grille PRECISION_ETAT).

    callback : fonction optionnelle appelée toutes les FREQ_AFFICHAGE nouvelles
               positions avec la liste positions_explorees en argument. Permet
               d'afficher la progression en temps réel.

    Retourne (chemin, positions_explorees) où chemin est la liste des (vx, vy)
    menant à la victoire, ou (None, positions_explorees) si aucune solution.
    """
    visite = set()
    chemin = []
    positions_explorees = []

    def rec(perso):
        if victoire(perso, objectif):
            return True
        cle = _arrondi_etat(perso)
        if cle in visite:
            return False
        visite.add(cle)
        positions_explorees.append((perso['x'], perso['y']))
        if callback is not None and len(positions_explorees) % FREQ_AFFICHAGE == 0:
            callback(positions_explorees)
        for vx, vy in directions_discretes():
            perso2, vict, hors = _simule_saut_etat(perso, vx, vy, lst_blocs, objectif)
            if hors:
                continue
            if vict:
                chemin.append((vx, vy))
                return True
            chemin.append((vx, vy))
            if rec(perso2):
                return True
            chemin.pop()  # backtrack
        return False

    sys.setrecursionlimit(3000)
    if rec(dict(personnage_depart)):
        return chemin, positions_explorees
    return None, positions_explorees


def solveur_approche(personnage_depart, objectif, lst_blocs,
                     a=APPROX_POS, b=APPROX_VIT, callback=None):
    """
    Résout le niveau par DFS backtracking approché (§Tâche 4 — version approchée).

    Deux approximations par rapport au solveur naïf :
      - Position : au lieu d'ajouter (x, y) dans visite, on ajoute
        (x // a, y // a). Deux positions à moins de a pixels sont considérées
        identiques. Plus a est grand, plus la recherche est rapide mais moins
        précise.
      - Vitesse : au lieu de tester toutes les directions discrètes, on teste
        les entiers de -VMAX à +VMAX avec un incrément b (via
        _vitesses_approchees). Plus b est grand, moins de vitesses sont testées.

    Paramètres :
      a        : finesse de l'approximation des positions (défaut : APPROX_POS = 20).
      b        : finesse de l'approximation des vitesses  (défaut : APPROX_VIT  =  3).
      callback : fonction optionnelle appelée toutes les FREQ_AFFICHAGE nouvelles
                 positions avec la liste positions_explorees en argument.

    Retourne (chemin, positions_explorees) ou (None, positions_explorees).
    """
    visite = set()
    chemin = []
    positions_explorees = []

    def rec(perso):
        if victoire(perso, objectif):
            return True
        cle = (int(perso['x']) // a, int(perso['y']) // a)
        if cle in visite:
            return False
        visite.add(cle)
        positions_explorees.append((perso['x'], perso['y']))
        if callback is not None and len(positions_explorees) % FREQ_AFFICHAGE == 0:
            callback(positions_explorees)
        for vx, vy in _vitesses_approchees(b):
            perso2, vict, hors = _simule_saut_etat(perso, vx, vy, lst_blocs, objectif)
            if hors:
                continue
            if vict:
                chemin.append((vx, vy))
                return True
            chemin.append((vx, vy))
            if rec(perso2):
                return True
            chemin.pop()  # backtrack
        return False

    sys.setrecursionlimit(3000)
    if rec(dict(personnage_depart)):
        return chemin, positions_explorees
    return None, positions_explorees


def solveur_bfs(personnage_depart, objectif, lst_blocs, callback=None):
    """
    Résout le niveau par recherche en largeur (BFS) et retourne la solution optimale.

    Contrairement au DFS, le BFS explore les positions par niveau de profondeur
    croissant (1 saut, puis 2 sauts, puis 3, …). La première solution trouvée est
    donc garantie d'être optimale en nombre de sauts.

    Algorithme :
      - Maintenir une file (deque) d'états en attente d'exploration.
      - Chaque état est un tuple (perso, chemin) : la position courante et la
        séquence de coups pour y arriver depuis le départ.
      - Dépiler l'état en tête de file ; si déjà visité, l'ignorer.
      - Sinon : marquer visité, tester tous les sauts possibles, enfiler les
        nouveaux états en queue.
      - Dès qu'un saut mène à la victoire, retourner le chemin complété.

    callback : fonction optionnelle appelée toutes les FREQ_AFFICHAGE nouvelles
               positions avec la liste positions_explorees en argument.

    Retourne (chemin, positions_explorees) ou (None, positions_explorees).
    """
    visite = set()
    positions_explorees = []
    file = deque()
    file.append((dict(personnage_depart), []))  # (position, chemin parcouru)

    while file:
        perso, chemin = file.popleft()

        if victoire(perso, objectif):
            return chemin, positions_explorees

        cle = _arrondi_etat(perso)
        if cle in visite:
            continue
        visite.add(cle)
        positions_explorees.append((perso['x'], perso['y']))
        if callback is not None and len(positions_explorees) % FREQ_AFFICHAGE == 0:
            callback(positions_explorees)

        for vx, vy in directions_discretes():
            perso2, vict, hors = _simule_saut_etat(perso, vx, vy, lst_blocs, objectif)
            if hors:
                continue
            if vict:
                return chemin + [(vx, vy)], positions_explorees
            if _arrondi_etat(perso2) not in visite:
                file.append((perso2, chemin + [(vx, vy)]))

    return None, positions_explorees


# ---------------------------------------------------------------------------
# Fonctions d'affichage
# ---------------------------------------------------------------------------

def dessine_blocs(lst_blocs):
    """
    Dessine tous les blocs avec un code couleur selon leur type :
      - 'normale'   : vert  (#4caf50)
      - 'collante'  : brun goudron (#5c3317)
      - 'glissante' : bleu glace (#4dd0e1)

    Les plateformes spéciales affichent une lettre (C ou G) en leur centre.
    """
    for bloc in lst_blocs:
        type_bloc = bloc.get('type', 'normale')
        bord, fond = COULEURS_BLOCS.get(type_bloc, COULEURS_BLOCS['normale'])
        rectangle(bloc['ax'], bloc['ay'], bloc['bx'], bloc['by'],
                  couleur=bord, remplissage=fond)
        if type_bloc in ('collante', 'glissante'):
            cx = (bloc['ax'] + bloc['bx']) / 2
            cy = (bloc['ay'] + bloc['by']) / 2
            label = 'C' if type_bloc == 'collante' else 'G'
            texte(cx, cy, label, couleur='white', ancrage='center', taille=10)


def dessine_objectif(objectif):
    """
    Dessine l'objectif sous la forme d'un rectangle rouge centré sur (x, y).

    Le rectangle a pour demi-côté le rayon de l'objectif.
    """
    r = objectif['rayon']
    x, y = objectif['x'], objectif['y']
    rectangle(x - r, y - r, x + r, y + r, couleur='#cc0000', remplissage='red')


def dessine_personnage(personnage):
    """
    Dessine le personnage (mouton) avec le sprite images/lemouton.png.

    L'image est centrée sur la position (x, y) du personnage.
    La taille est calée sur le diamètre du personnage (2 × RAYON_PERSO).
    """
    taille = RAYON_PERSO * 2
    image(personnage['x'], personnage['y'], 'images/lemouton.png',
          largeur=taille, hauteur=taille, ancrage='center')


def dessine_fleche(personnage, cible_x, cible_y):
    """
    Dessine la flèche rouge de visée du mouton vers le point cible.

    La flèche part du centre du mouton et pointe vers (cible_x, cible_y),
    mais sa longueur est plafonnée à MAX_RAYON pixels. Si le point cible
    est au-delà, la flèche reste à MAX_RAYON dans la même direction.
    """
    px, py = personnage['x'], personnage['y']
    dx = cible_x - px
    dy = cible_y - py
    longueur = (dx ** 2 + dy ** 2) ** 0.5

    if longueur == 0:
        return

    # Plafonner la longueur à MAX_RAYON
    echelle = min(longueur, MAX_RAYON) / longueur
    bx = px + dx * echelle
    by = py + dy * echelle

    ligne(px, py, bx, by, couleur='red', epaisseur=3)
    cercle(bx, by, 5, couleur='red', remplissage='red')


def simule_trajectoire(personnage, vx, vy, lst_blocs, n_points=40, n_etapes=8):
    """
    Simule la trajectoire future du personnage sans le déplacer réellement.

    Crée une copie du personnage avec la vitesse (vx, vy), applique n_points × n_etapes
    pas de physique et enregistre la position toutes les n_etapes itérations.
    La simulation s'arrête dès qu'une collision est détectée.

    Retourne une liste de tuples (x, y) représentant les points de la trajectoire.
    """
    fantome = {
        'x': personnage['x'], 'y': personnage['y'],
        'vx': vx, 'vy': vy
    }
    points = []
    for _ in range(n_points):
        for _ in range(n_etapes):
            pas_physique(fantome)
        if collision(fantome, lst_blocs):
            break
        points.append((fantome['x'], fantome['y']))
    return points


def dessine_trajectoire(points):
    """
    Dessine la trajectoire prévisionnelle sous forme de petits cercles gris.

    Chaque point est un tuple (x, y) issu de simule_trajectoire(). La taille
    des cercles décroît légèrement vers la fin pour indiquer l'atténuation.
    """
    n = len(points)
    for i, (x, y) in enumerate(points):
        rayon = max(1, 4 - i * 3 // max(n, 1))
        cercle(x, y, rayon, couleur='#888888', remplissage='#aaaaaa')


def dessine_trainee(trainee):
    """
    Dessine la traînée laissée par le mouton sous forme de petits cercles rouges.

    Chaque point de la liste trainee est un tuple (x, y) enregistré
    pendant le déplacement du mouton. La traînée s'accumule sur tout le niveau.
    """
    for x, y in trainee:
        cercle(x, y, 3, couleur='red', remplissage='red')


def dessine_positions_explorees(positions):
    """
    Dessine les positions explorées par le solveur sous forme de points bleus.

    Chaque position est un tuple (x, y) enregistré lors de la recherche DFS.
    Permet de visualiser l'espace parcouru par l'algorithme avant d'afficher
    la solution gagnante.
    """
    for x, y in positions:
        cercle(x, y, 4, couleur='#0055ff', remplissage='#4488ff')


def dessine_hud(nb_sauts, num_niveau):
    """
    Affiche le HUD (heads-up display) en haut de l'écran.

    Indique le numéro du niveau en cours (en haut à gauche) et le nombre
    de sauts effectués depuis le début du niveau (en haut à droite).
    """
    texte(10, 10, f'Niveau {num_niveau}',
          couleur='white', remplissage='#00000066', ancrage='nw', taille=16)
    texte(LARGEUR - 10, 10, f'Sauts : {nb_sauts}',
          couleur='white', remplissage='#00000066', ancrage='ne', taille=16)


FONDS_NIVEAUX = {
    1: 'images/ferme.jpg',
    2: 'images/cimetiere.jpg',
    3: 'images/espace.jpg',
}


def dessine_tout(personnage, objectif, lst_blocs, trainee=None, cible=None,
                 nb_sauts=0, num_niveau=1, trajectoire=None):
    """
    Efface l'écran et redessine tous les éléments du jeu.

    Pour les niveaux ayant une image de fond définie dans FONDS_NIVEAUX, celle-ci
    est affichée en plein écran. Sinon, un fond ciel+herbe est dessiné.

    Ordre d'affichage : fond → blocs → objectif → traînée → trajectoire → personnage → flèche → HUD.
    trainee     : liste de (x, y) à dessiner en rouge (optionnel).
    cible       : tuple (cx, cy) pour la flèche de visée (optionnel).
    nb_sauts    : nombre de sauts effectués, affiché dans le HUD.
    num_niveau  : numéro du niveau en cours (1-indexé), affiché dans le HUD.
    trajectoire : liste de (x, y) pour la trajectoire prévisionnelle (optionnel).
    """
    efface_tout()
    if num_niveau in FONDS_NIVEAUX:
        # Image de fond spécifique au niveau
        image(0, 0, FONDS_NIVEAUX[num_niveau],
              largeur=LARGEUR, hauteur=HAUTEUR, ancrage='nw')
    else:
        # Fond générique : ciel bleu + bande herbe
        rectangle(0, 0, LARGEUR, HAUTEUR, couleur=COULEUR_CIEL, remplissage=COULEUR_CIEL)
        rectangle(0, HAUTEUR - 30, LARGEUR, HAUTEUR, couleur=COULEUR_SOL, remplissage=COULEUR_SOL)
    dessine_blocs(lst_blocs)
    dessine_objectif(objectif)
    if trainee:
        dessine_trainee(trainee)
    if trajectoire:
        dessine_trajectoire(trajectoire)
    dessine_personnage(personnage)
    if cible is not None:
        dessine_fleche(personnage, cible[0], cible[1])
    dessine_hud(nb_sauts, num_niveau)
    mise_a_jour()


# ---------------------------------------------------------------------------
# Programme principal
# ---------------------------------------------------------------------------

NIVEAUX = [
    'niveaux/niveau1.txt',
    'niveaux/niveau2.txt',
    'niveaux/niveau3.txt',
]


def affiche_menu():
    """
    Affiche l'écran de menu principal et attend que le joueur choisisse un niveau.

    Montre la bannière du jeu (images/baniere.png) et trois boutons cliquables
    correspondant aux niveaux 1, 2 et 3. Le joueur clique sur un bouton pour
    lancer le niveau correspondant. La touche Echap quitte le jeu.

    Retourne l'index du niveau choisi (0, 1 ou 2), ou -1 si le joueur quitte.
    """
    # Coordonnées des boutons (centrés horizontalement)
    boutons = [
        {'label': 'Niveau 1', 'index': 0},
        {'label': 'Niveau 2', 'index': 1},
        {'label': 'Niveau 3', 'index': 2},
    ]
    btn_largeur = 200
    btn_hauteur = 55
    btn_espacement = 30
    btn_y_depart = HAUTEUR // 2 + 30

    while True:
        efface_tout()
        # Fond
        rectangle(0, 0, LARGEUR, HAUTEUR, couleur=COULEUR_CIEL, remplissage=COULEUR_CIEL)
        rectangle(0, HAUTEUR - 30, LARGEUR, HAUTEUR, couleur=COULEUR_SOL, remplissage=COULEUR_SOL)

        # Bannière
        image(LARGEUR // 2, 130, 'images/baniere.png', largeur=500, hauteur=180, ancrage='center')

        # Sous-titre
        texte(LARGEUR // 2, btn_y_depart - 40, 'Choisissez un niveau',
              couleur='#1a4f1a', ancrage='center', taille=20)

        # Dessiner les boutons
        for i, btn in enumerate(boutons):
            bx = LARGEUR // 2 - btn_largeur // 2
            by = btn_y_depart + i * (btn_hauteur + btn_espacement)
            rectangle(bx, by, bx + btn_largeur, by + btn_hauteur,
                      couleur='#2d6a2d', remplissage='#4caf50')
            texte(LARGEUR // 2, by + btn_hauteur // 2,
                  btn['label'], couleur='white', ancrage='center', taille=22)

        texte(LARGEUR // 2, HAUTEUR - 20, 'Echap pour quitter',
              couleur='#555555', ancrage='center', taille=13)
        mise_a_jour()

        ev = attend_ev()
        t = type_ev(ev)
        if t == 'Quitte':
            return -1
        if t == 'Touche' and touche(ev) == 'Escape':
            return -1
        if t == 'ClicGauche':
            mx, my = abscisse(ev), ordonnee(ev)
            for i, btn in enumerate(boutons):
                bx = LARGEUR // 2 - btn_largeur // 2
                by = btn_y_depart + i * (btn_hauteur + btn_espacement)
                if bx <= mx <= bx + btn_largeur and by <= my <= by + btn_hauteur:
                    return btn['index']


def affiche_victoire(num_niveau):
    """
    Affiche l'écran de victoire et attend que le joueur clique ou appuie sur une touche.

    Affiche un message centré indiquant le niveau complété et invite
    le joueur à continuer vers le niveau suivant (ou à recommencer depuis
    le début si c'était le dernier niveau).
    """
    efface_tout()

    # Fond semi-transparent vert
    rectangle(0, 0, LARGEUR, HAUTEUR, couleur='#2d6a2d', remplissage='#2d6a2d')

    texte(LARGEUR // 2, HAUTEUR // 2 - 60, 'BRAVO !',
          couleur='white', remplissage='#2d6a2d', ancrage='center', taille=60)

    msg_niveau = f'Niveau {num_niveau} terminé !'
    texte(LARGEUR // 2, HAUTEUR // 2 + 10, msg_niveau,
          couleur='#d4ffaa', remplissage='#2d6a2d', ancrage='center', taille=28)

    if num_niveau < len(NIVEAUX):
        suite = 'Clic ou touche → Niveau suivant'
    else:
        suite = 'Clic ou touche → Recommencer depuis le début'
    texte(LARGEUR // 2, HAUTEUR // 2 + 70, suite,
          couleur='white', remplissage='#2d6a2d', ancrage='center', taille=20)

    mise_a_jour()

    # Attendre un clic ou une touche pour continuer
    while True:
        ev = attend_ev()
        t = type_ev(ev)
        if t == 'Quitte':
            return False  # signal pour quitter le jeu
        if t in ('ClicGauche', 'Touche'):
            return True   # signal pour continuer


def affiche_message_solveur(personnage, objectif, lst_blocs, nb_sauts, num_niveau, msg):
    """
    Affiche un message centré sur l'écran de jeu (ex. 'Solveur en cours…').

    Dessine d'abord l'état courant du jeu, puis superpose un bandeau semi-
    transparent avec le texte msg. Utile pour signaler que le solveur calcule.
    """
    dessine_tout(personnage, objectif, lst_blocs, nb_sauts=nb_sauts, num_niveau=num_niveau)
    rectangle(LARGEUR // 2 - 220, HAUTEUR // 2 - 30,
              LARGEUR // 2 + 220, HAUTEUR // 2 + 30,
              couleur='#000000', remplissage='#000000')
    texte(LARGEUR // 2, HAUTEUR // 2, msg,
          couleur='white', ancrage='center', taille=20)
    mise_a_jour()


def joue_solution_animee(personnage, objectif, lst_blocs, solution, nb_sauts_init, num_niveau):
    """
    Rejoue une solution trouvée par le solveur avec animation complète.

    Pour chaque saut (vx, vy) de la solution, applique la vitesse au personnage
    et anime la physique frame par frame jusqu'à stabilisation ou victoire.
    Chaque saut incrémente le compteur affiché.

    Retourne True si la victoire a été atteinte, False si le joueur a quitté.
    """
    trainee = []
    nb_sauts = nb_sauts_init
    compteur_frame = 0

    for vx, vy in solution:
        personnage['vx'] = vx
        personnage['vy'] = vy
        nb_sauts += 1
        stable_count = 0
        prev_x, prev_y = personnage['x'], personnage['y']

        for _ in range(MAX_FRAMES_SAUT):
            for _ in range(N_ETAPES):
                pas_physique(personnage)
                choc(personnage, lst_blocs)

            # Traînée
            en_mouvement = personnage['vx'] != 0.0 or personnage['vy'] != 0.0
            if en_mouvement:
                compteur_frame += 1
                if compteur_frame % 3 == 0:
                    trainee.append((personnage['x'], personnage['y']))

            dessine_tout(personnage, objectif, lst_blocs, trainee,
                         nb_sauts=nb_sauts, num_niveau=num_niveau)

            # Victoire en cours de saut
            if victoire(personnage, objectif):
                return True

            # Chute hors écran
            if personnage['y'] > HAUTEUR + RAYON_PERSO:
                break

            # Détection stabilité (position seule, comme dans _simule_saut_etat)
            dx = abs(personnage['x'] - prev_x)
            dy = abs(personnage['y'] - prev_y)
            prev_x, prev_y = personnage['x'], personnage['y']

            if dx < STABLE_SEUIL and dy < STABLE_SEUIL:
                stable_count += 1
                if stable_count >= STABLE_DUREE:
                    break
            else:
                stable_count = 0

            # Quitter si l'utilisateur ferme la fenêtre
            ev = donne_ev()
            if ev is not None and type_ev(ev) in ('Quitte',):
                return False

            attente(0.01)

    return False


def lance_solveur(num_niveau, mode_solveur='dfs'):
    """
    Lance le solveur automatique sur le niveau indiqué sans passer par le menu.

    Ouvre la fenêtre, puis exécute le solveur en affichant les positions
    explorées en temps réel (toutes les FREQ_AFFICHAGE nouvelles positions).
    Après la recherche, les positions explorées restent à l'écran 2 secondes,
    puis la solution est animée. Si aucune solution n'est trouvée, un message
    s'affiche avant la fermeture.

    num_niveau   : indice 0-basé du niveau dans la liste NIVEAUX.
    mode_solveur : 'dfs' (défaut), 'approche' ou 'bfs' (optimal).
    """
    cree_fenetre(LARGEUR, HAUTEUR)
    personnage, objectif, lst_blocs = charge_niveau(NIVEAUX[num_niveau])

    def affiche_progression(pos_explorees):
        """Redessine le plateau avec les positions explorées jusqu'à présent."""
        dessine_tout(personnage, objectif, lst_blocs, nb_sauts=0, num_niveau=num_niveau + 1)
        dessine_positions_explorees(pos_explorees)
        mise_a_jour()

    # Lancer la recherche avec affichage en temps réel
    affiche_message_solveur(personnage, objectif, lst_blocs, 0, num_niveau + 1,
                            'Solveur en cours…')
    if mode_solveur == 'approche':
        solution, pos_explorees = solveur_approche(personnage, objectif, lst_blocs,
                                                   callback=affiche_progression)
    elif mode_solveur == 'bfs':
        solution, pos_explorees = solveur_bfs(personnage, objectif, lst_blocs,
                                              callback=affiche_progression)
    else:
        solution, pos_explorees = solveur_naif(personnage, objectif, lst_blocs,
                                               callback=affiche_progression)

    # Figer l'affichage final des positions explorées pendant 2 s
    affiche_progression(pos_explorees)
    attente(2.0)

    if solution is None:
        affiche_message_solveur(personnage, objectif, lst_blocs, 0, num_niveau + 1,
                                'Aucune solution trouvée.')
        attente(3.0)
        ferme_fenetre()
        return

    # Recharger le niveau depuis le début et animer la solution
    personnage, objectif, lst_blocs = charge_niveau(NIVEAUX[num_niveau])
    joue_solution_animee(personnage, objectif, lst_blocs, solution, 0, num_niveau + 1)
    ferme_fenetre()


def main():
    """
    Point d'entrée du programme.

    Mode jeu normal (aucun argument) :
      python3 sautemouton.py
        → affiche le menu de sélection de niveau, jeu interactif.

    Mode solveur automatique :
      python3 sautemouton.py --solve N
        → ouvre directement le niveau N, calcule et anime la solution (DFS naïf).
      python3 sautemouton.py --solve
        → enchaîne tous les niveaux (1, 2, 3) avec le DFS naïf.
      python3 sautemouton.py --solve N --approche
        → idem avec le DFS approché (plus rapide, positions/vitesses discrétisées).
      python3 sautemouton.py --solve N --bfs
        → idem avec le BFS (solution optimale en nombre de sauts).

    Système de visée en 2 temps (mode jeu uniquement) :
      - Clic droit  → verrouille la cible, affiche la flèche et la trajectoire
      - Clic gauche → valide et lance le saut

    La traînée (points rouges) s'accumule pendant les sauts et se réinitialise
    à chaque nouveau niveau.
    """
    if '--bfs' in sys.argv:
        mode_solveur = 'bfs'
    elif '--approche' in sys.argv:
        mode_solveur = 'approche'
    else:
        mode_solveur = 'dfs'

    # Détecter --solve [N]
    solve_niveaux = None  # None = jeu normal ; liste d'indices 0-basés = mode solveur
    for i, arg in enumerate(sys.argv):
        if arg == '--solve':
            # Numéro fourni ?
            if i + 1 < len(sys.argv) and not sys.argv[i + 1].startswith('-'):
                try:
                    n = int(sys.argv[i + 1])
                except ValueError:
                    print(f"Erreur : '{sys.argv[i + 1]}' n'est pas un numéro de niveau valide.")
                    return
                if n < 1 or n > len(NIVEAUX):
                    print(f"Erreur : le niveau doit être compris entre 1 et {len(NIVEAUX)}.")
                    return
                solve_niveaux = [n - 1]  # niveau unique, 0-indexé
            else:
                solve_niveaux = list(range(len(NIVEAUX)))  # tous les niveaux

    if solve_niveaux is not None:
        for idx in solve_niveaux:
            lance_solveur(idx, mode_solveur)
        return

    cree_fenetre(LARGEUR, HAUTEUR)

    num_niveau = affiche_menu()
    if num_niveau == -1:
        ferme_fenetre()
        return

    while True:
        personnage, objectif, lst_blocs = charge_niveau(NIVEAUX[num_niveau])
        trainee = []          # Points de traînée, réinitialisés à chaque niveau
        etat = 'attente'      # 'attente' ou 'visee'
        cible = None          # (cx, cy) verrouillé au clic gauche
        compteur_frame = 0    # Pour espacer les points de traînée

        nb_sauts = 0          # Compteur de sauts pour ce niveau
        continuer = True
        while continuer:
            # Appliquer N_ETAPES pas de physique par frame
            for _ in range(N_ETAPES):
                pas_physique(personnage)
                choc(personnage, lst_blocs)

            # Enregistrer la traînée quand le mouton est en mouvement
            en_mouvement = personnage['vx'] != 0.0 or personnage['vy'] != 0.0
            if en_mouvement:
                compteur_frame += 1
                if compteur_frame % 3 == 0:
                    trainee.append((personnage['x'], personnage['y']))

            # Calculer la trajectoire prévisionnelle en phase de visée
            trajectoire_prev = None
            if etat == 'visee' and cible is not None:
                vx_prev, vy_prev = clic_vers_vitesse(cible[0], cible[1],
                                                     personnage['x'], personnage['y'])
                trajectoire_prev = simule_trajectoire(personnage, vx_prev, vy_prev, lst_blocs)

            dessine_tout(personnage, objectif, lst_blocs, trainee,
                         cible if etat == 'visee' else None,
                         nb_sauts, num_niveau + 1, trajectoire_prev)

            # Vérifier si le mouton est sorti de l'écran (chute hors écran)
            if personnage['y'] > HAUTEUR + RAYON_PERSO:
                personnage, objectif, lst_blocs = charge_niveau(NIVEAUX[num_niveau])
                trainee = []
                etat = 'attente'
                cible = None
                compteur_frame = 0
                nb_sauts = 0

            # Vérifier la victoire
            if victoire(personnage, objectif):
                continuer = False
                if not affiche_victoire(num_niveau + 1):
                    ferme_fenetre()
                    return
                num_niveau = (num_niveau + 1) % len(NIVEAUX)
                break

            ev = donne_ev()
            if ev is not None:
                if type_ev(ev) == 'Quitte':
                    ferme_fenetre()
                    return
                elif type_ev(ev) == 'Touche' and touche(ev) == 'Escape':
                    ferme_fenetre()
                    return
                elif type_ev(ev) == 'Touche' and touche(ev) == 'm':
                    # Touche M : retourner au menu
                    choix = affiche_menu()
                    if choix == -1:
                        ferme_fenetre()
                        return
                    num_niveau = choix
                    break
                elif type_ev(ev) == 'ClicDroit':
                    # Clic droit : verrouille la cible et affiche la trajectoire
                    cible = (abscisse(ev), ordonnee(ev))
                    etat = 'visee'
                elif type_ev(ev) == 'ClicGauche':
                    # Clic gauche : lance le saut
                    # Si une cible est verrouillée (mode visée), on l'utilise ;
                    # sinon on vise directement le point cliqué.
                    if etat == 'visee' and cible is not None:
                        vx, vy = clic_vers_vitesse(cible[0], cible[1],
                                                   personnage['x'], personnage['y'])
                    else:
                        vx, vy = clic_vers_vitesse(abscisse(ev), ordonnee(ev),
                                                   personnage['x'], personnage['y'])
                    personnage['vx'] = vx
                    personnage['vy'] = vy
                    nb_sauts += 1
                    etat = 'attente'
                    cible = None

            attente(0.01)


main()
