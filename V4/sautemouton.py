"""
Saute Mouton — Projet L1 Info 2025-2026
Université Gustave Eiffel

Un mouton (cercle) doit atteindre une cible en sautant sur des plateformes.
Le joueur clique pour donner une vitesse au mouton.

Lancement : python3 sautemouton.py
"""

from fltk import *
import sys
import os
import math
import json
from collections import deque

# Garantit que les chemins relatifs (images/, niveaux/) fonctionnent
# quel que soit le répertoire depuis lequel le script est lancé.
os.chdir(os.path.dirname(os.path.abspath(__file__)))

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

# Couleurs (bordure, remplissage) par biome (num_niveau 1-3) et par type
COULEURS_BLOCS_PAR_NIVEAU = {
    1: {  # Ferme
        'normale':   ('#6D4C41', '#8B5E3C'),   # marron terreux
        'collante':  ('#F9A825', '#FFD600'),   # jaune miel
        'glissante': ('#0288D1', '#4FC3F7'),   # bleu glace
    },
    2: {  # Cimetière
        'normale':   ('#9E9E9E', '#E0E0E0'),   # gris perle
        'collante':  ('#F9A825', '#FFD600'),   # jaune
        'glissante': ('#0288D1', '#4FC3F7'),   # bleu
    },
    3: {  # Espace
        'normale':   ('#B0BEC5', '#ECEFF1'),   # blanc lunaire
        'collante':  ('#F9A825', '#FFD600'),   # jaune
        'glissante': ('#0288D1', '#4FC3F7'),   # bleu
    },
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
    Lit un fichier de niveau .txt et retourne les données de jeu.

    Format du fichier (mots-clés séparés par des espaces) :
      - Lignes commençant par # : commentaires ignorés.
      - personnage x y          → position de départ du mouton.
      - objectif x y rayon      → centre et rayon de la cible.
      - bloc ax ay bx by [type] → rectangle de plateforme ; type optionnel :
                                   'normale' (défaut), 'collante', 'glissante'.
      - Les lignes vides sont ignorées.

    Retourne un tuple (personnage, objectif, lst_blocs) où :
      - personnage = {'x': float, 'y': float, 'vx': float, 'vy': float}
      - objectif   = {'x': float, 'y': float, 'rayon': float}
      - lst_blocs  = liste de {'ax': float, 'ay': float, 'bx': float, 'by': float,
                               'type': str}  # 'normale' | 'collante' | 'glissante'
    """
    personnage = None
    objectif = None
    lst_blocs = []

    with open(fichier, 'r') as f:
        for ligne in f:
            ligne = ligne.strip()
            if not ligne or ligne.startswith('#'):
                continue
            parts = ligne.split()
            if parts[0] == 'personnage':
                personnage = {
                    'x': float(parts[1]),
                    'y': float(parts[2]),
                    'vx': 0.0,
                    'vy': 0.0,
                    'colle': False,  # True quand collé à une plateforme collante
                }
            elif parts[0] == 'objectif':
                objectif = {
                    'x': float(parts[1]),
                    'y': float(parts[2]),
                    'rayon': float(parts[3])
                }
            elif parts[0] == 'bloc':
                type_bloc = parts[5] if len(parts) >= 6 else 'normale'
                if type_bloc not in TYPES_BLOCS:
                    type_bloc = 'normale'
                lst_blocs.append({
                    'ax':   float(parts[1]),
                    'ay':   float(parts[2]),
                    'bx':   float(parts[3]),
                    'by':   float(parts[4]),
                    'type': type_bloc
                })

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
        # Cas de coin diagonal avec chute : forcer classification haut/bas
        # pour éviter qu'une collision d'angle soit traitée comme un mur latéral.
        if personnage['vy'] > 0 and abs(ny) > 0 and abs(nx) > 0:
            top_bottom = ny > 0
        type_bloc = bloc.get('type', 'normale')

        # 3. Réponse en vitesse
        if type_bloc == 'collante':
            personnage['vx'] = 0.0
            personnage['vy'] = 0.0
            personnage['colle'] = True  # suspendre la gravité jusqu'au prochain saut
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
    Résout le niveau par recherche en profondeur (DFS itératif avec pile explicite).

    Algorithme (§Tâche 4 — recherche en profondeur) :
      - On maintient une pile de couples (position, chemin_parcouru).
      - À chaque itération : dépiler, ignorer si déjà visité, sinon explorer
        tous les sauts possibles et empiler les nouvelles positions (LIFO → DFS).
      - Dès qu'un saut mène à la victoire, retourner le chemin complété.

    La terminaison est garantie par l'ensemble visite qui empêche de repasser
    deux fois par la même position (déduplication sur grille PRECISION_ETAT).

    callback : fonction optionnelle appelée toutes les FREQ_AFFICHAGE nouvelles
               positions avec la liste positions_explorees en argument. Permet
               d'afficher la progression en temps réel.

    Retourne (chemin, positions_explorees) où chemin est la liste des (vx, vy)
    menant à la victoire, ou (None, positions_explorees) si aucune solution.
    """
    visite = set()
    positions_explorees = []
    pile = [(dict(personnage_depart), [])]

    while pile:
        perso, chemin = pile.pop()
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
                pile.append((perso2, chemin + [(vx, vy)]))

    return None, positions_explorees


def solveur_approche(personnage_depart, objectif, lst_blocs,
                     a=APPROX_POS, b=APPROX_VIT, callback=None):
    """
    Résout le niveau par DFS itératif approché (§Tâche 4 — version approchée).

    Deux approximations par rapport au solveur naïf :
      - Position : la clé de visite est (x // a, y // a). Deux positions à moins
        de a pixels sont considérées identiques. Plus a est grand, plus la
        recherche est rapide mais moins précise.
      - Vitesse : les sauts testés sont _vitesses_approchees(b) au lieu de toutes
        les directions discrètes. Plus b est grand, moins de vitesses sont testées.

    Algorithme : DFS itératif identique à solveur_naif, avec pile explicite (LIFO).

    Paramètres :
      a        : finesse de l'approximation des positions (défaut : APPROX_POS = 20).
      b        : finesse de l'approximation des vitesses  (défaut : APPROX_VIT  =  3).
      callback : fonction optionnelle appelée toutes les FREQ_AFFICHAGE nouvelles
                 positions avec la liste positions_explorees en argument.

    Retourne (chemin, positions_explorees) ou (None, positions_explorees).
    """
    visite = set()
    positions_explorees = []
    pile = [(dict(personnage_depart), [])]

    while pile:
        perso, chemin = pile.pop()
        if victoire(perso, objectif):
            return chemin, positions_explorees
        cle = (int(perso['x']) // a, int(perso['y']) // a)
        if cle in visite:
            continue
        visite.add(cle)
        positions_explorees.append((perso['x'], perso['y']))
        if callback is not None and len(positions_explorees) % FREQ_AFFICHAGE == 0:
            callback(positions_explorees)
        for vx, vy in _vitesses_approchees(b):
            perso2, vict, hors = _simule_saut_etat(perso, vx, vy, lst_blocs, objectif)
            if hors:
                continue
            if vict:
                return chemin + [(vx, vy)], positions_explorees
            cle2 = (int(perso2['x']) // a, int(perso2['y']) // a)
            if cle2 not in visite:
                pile.append((perso2, chemin + [(vx, vy)]))

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

def dessine_blocs(lst_blocs, num_niveau=1):
    """
    Dessine tous les blocs avec des rectangles colorés selon le biome et le type.

    Les couleurs sont définies dans COULEURS_BLOCS_PAR_NIVEAU. Un label textuel
    'C' (collante) ou 'G' (glissante) est superposé sur les blocs spéciaux.
    """
    couleurs = COULEURS_BLOCS_PAR_NIVEAU.get(num_niveau, COULEURS_BLOCS_PAR_NIVEAU[1])
    for bloc in lst_blocs:
        type_bloc = bloc.get('type', 'normale')
        ax, ay, bx, by = bloc['ax'], bloc['ay'], bloc['bx'], bloc['by']
        bord, fond = couleurs.get(type_bloc, couleurs['normale'])
        rectangle(ax, ay, bx, by, couleur=bord, remplissage=fond)
        if type_bloc in ('collante', 'glissante'):
            label = 'C' if type_bloc == 'collante' else 'G'
            texte((ax + bx) / 2, (ay + by) / 2, label,
                  couleur='white', ancrage='center', taille=10)


def dessine_objectif(objectif):
    """
    Dessine l'objectif sous forme d'un cercle vert centré sur (x, y).
    """
    cercle(objectif['x'], objectif['y'], objectif['rayon'],
           couleur='#00C853', remplissage='#00E676')


def dessine_personnage(personnage, halo=None):
    """
    Dessine le personnage (mouton) avec le sprite images/lemouton.png.

    L'image est centrée sur la position (x, y) du personnage.
    Si halo est fourni (couleur hex), un cercle coloré est dessiné derrière
    le sprite pour distinguer les joueurs en mode duo.
    """
    if halo is not None:
        cercle(personnage['x'], personnage['y'], RAYON_PERSO + 5,
               couleur=halo, remplissage=halo)
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


def dessine_meilleur_trainee(positions):
    """
    Dessine la traînée du meilleur parcours sous forme de petits cercles dorés.

    Affichée automatiquement dès qu'un meilleur parcours existe pour le niveau,
    superposée en fond derrière la traînée courante.
    """
    for x, y in positions:
        cercle(x, y, 4, couleur='#b8860b', remplissage='#ffd700')


def dessine_positions_explorees(positions):
    """
    Dessine les positions explorées par le solveur sous forme de points bleus.

    Chaque position est un tuple (x, y) enregistré lors de la recherche DFS.
    Permet de visualiser l'espace parcouru par l'algorithme avant d'afficher
    la solution gagnante.
    """
    for x, y in positions:
        cercle(x, y, 4, couleur='#0055ff', remplissage='#4488ff')


def dessine_hud(nb_sauts, num_niveau, scores=None, joueur_actif=0):
    """
    Affiche le HUD (heads-up display) en haut de l'écran.

    En mode 2 joueurs (scores non None), affiche les sauts de chaque joueur
    et le joueur dont c'est le tour. En mode solo, affiche le compteur total.
    """
    texte(10, 10, f'Niveau {num_niveau}',
          couleur='white', remplissage='#00000066', ancrage='nw', taille=16)
    if scores is not None:
        texte(LARGEUR // 2, 10,
              f'J1: {scores[0]}  |  J2: {scores[1]}  |  → Joueur {joueur_actif + 1}',
              couleur='white', remplissage='#00000066', ancrage='n', taille=16)
    else:
        texte(LARGEUR - 10, 10, f'Sauts : {nb_sauts}',
              couleur='white', remplissage='#00000066', ancrage='ne', taille=16)


FONDS_NIVEAUX = {
    1: 'images/ferme.png',
    2: 'images/cimetiere.png',
    3: 'images/espace.png',
}


def dessine_tout(personnage, objectif, lst_blocs, trainee=None, cible=None,
                 nb_sauts=0, num_niveau=1, trajectoire=None, scores=None, joueur_actif=0,
                 personnage2=None, meilleur_trainee=None):
    """
    Efface l'écran et redessine tous les éléments du jeu.

    Pour les niveaux ayant une image de fond définie dans FONDS_NIVEAUX, celle-ci
    est affichée en plein écran. Sinon, un fond ciel+herbe est dessiné.

    Ordre d'affichage : fond → blocs → objectif → traînée → trajectoire → personnage → flèche → HUD.
    trainee      : liste de (x, y) à dessiner en rouge (optionnel).
    cible        : tuple (cx, cy) pour la flèche de visée (optionnel).
    nb_sauts     : nombre de sauts total, affiché en mode solo.
    num_niveau   : numéro du niveau en cours (1-indexé), affiché dans le HUD.
    trajectoire  : liste de (x, y) pour la trajectoire prévisionnelle (optionnel).
    scores       : liste [s0, s1] des sauts par joueur ; active le HUD 2 joueurs.
    joueur_actif : indice (0 ou 1) du joueur dont c'est le tour.
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
    dessine_blocs(lst_blocs, num_niveau)
    dessine_objectif(objectif)
    if meilleur_trainee:
        dessine_meilleur_trainee(meilleur_trainee)
    if trainee:
        dessine_trainee(trainee)
    if trajectoire:
        dessine_trajectoire(trajectoire)
    halo1 = '#2255dd' if personnage2 is not None else None
    dessine_personnage(personnage, halo=halo1)
    if personnage2 is not None:
        dessine_personnage(personnage2, halo='#cc3300')
    perso_fleche = personnage2 if (personnage2 is not None and joueur_actif == 1) else personnage
    if cible is not None:
        dessine_fleche(perso_fleche, cible[0], cible[1])
    dessine_hud(nb_sauts, num_niveau, scores, joueur_actif)
    mise_a_jour()


# ---------------------------------------------------------------------------
# Programme principal
# ---------------------------------------------------------------------------

NIVEAUX = [
    'niveaux/niveau1.txt',
    'niveaux/niveau2.txt',
    'niveaux/niveau3.txt',
]

FICHIER_RECORDS = 'records.json'


def charge_records():
    """
    Charge les records et meilleurs parcours sauvegardés depuis records.json.

    Retourne (records, meilleur_trainee) avec les données persistées, ou deux
    dicts vides si le fichier est absent ou invalide.
    """
    try:
        with open(FICHIER_RECORDS, 'r') as f:
            data = json.load(f)
        records = {}
        meilleur_trainee = {}
        for cle, val in data.items():
            idx = int(cle)
            records[idx] = val['nb_sauts']
            meilleur_trainee[idx] = [tuple(pt) for pt in val['trainee']]
        return records, meilleur_trainee
    except (FileNotFoundError, KeyError, ValueError):
        return {}, {}


def sauvegarde_records(records, meilleur_trainee):
    """
    Sauvegarde les records et meilleurs parcours dans records.json.

    Écrase le fichier existant à chaque nouveau record.
    """
    data = {}
    for idx in records:
        if idx in meilleur_trainee:
            data[str(idx)] = {
                'nb_sauts': records[idx],
                'trainee': [[x, y] for x, y in meilleur_trainee[idx]]
            }
    with open(FICHIER_RECORDS, 'w') as f:
        json.dump(data, f)


def affiche_choix_mode(num_niveau):
    """
    Affiche un sous-menu Solo / Duo pour le niveau indiqué.

    num_niveau : numéro du niveau (1-indexé) affiché dans le titre.
    Retourne 'solo', 'duo', ou None si le joueur appuie sur Echap / quitte.
    """
    boutons = [
        {'label': 'Solo  (1 joueur)', 'mode': 'solo'},
        {'label': 'Duo   (2 joueurs)', 'mode': 'duo'},
    ]
    btn_largeur = 260
    btn_hauteur = 55
    btn_espacement = 25
    btn_x = LARGEUR // 2 - btn_largeur // 2
    btn_y_depart = HAUTEUR // 2

    while True:
        efface_tout()
        rectangle(0, 0, LARGEUR, HAUTEUR, couleur=COULEUR_CIEL, remplissage=COULEUR_CIEL)
        rectangle(0, HAUTEUR - 30, LARGEUR, HAUTEUR, couleur=COULEUR_SOL, remplissage=COULEUR_SOL)

        texte(LARGEUR // 2, btn_y_depart - 80,
              f'Niveau {num_niveau} — Choisir le mode',
              couleur='#1a4f1a', ancrage='center', taille=24)

        for i, btn in enumerate(boutons):
            by = btn_y_depart + i * (btn_hauteur + btn_espacement)
            rectangle(btn_x, by, btn_x + btn_largeur, by + btn_hauteur,
                      couleur='#2d6a2d', remplissage='#4caf50')
            texte(LARGEUR // 2, by + btn_hauteur // 2,
                  btn['label'], couleur='white', ancrage='center', taille=22)

        texte(LARGEUR // 2, HAUTEUR - 20, 'Echap → retour au menu',
              couleur='#555555', ancrage='center', taille=13)
        mise_a_jour()

        ev = attend_ev()
        t = type_ev(ev)
        if t == 'Quitte':
            return None
        if t == 'Touche' and touche(ev) == 'Escape':
            return None
        if t == 'ClicGauche':
            mx, my = abscisse(ev), ordonnee(ev)
            for i, btn in enumerate(boutons):
                by = btn_y_depart + i * (btn_hauteur + btn_espacement)
                if btn_x <= mx <= btn_x + btn_largeur and by <= my <= by + btn_hauteur:
                    return btn['mode']


def affiche_menu(records=None):
    """
    Affiche l'écran de menu principal et attend que le joueur choisisse un niveau.

    Montre la bannière du jeu (images/baniere.png) et trois boutons cliquables
    correspondant aux niveaux 1, 2 et 3. Pour chaque niveau, un badge doré affiche
    le meilleur score (en sauts) si un record existe dans records. Pour le niveau 1,
    un sous-menu Solo/Duo s'affiche. La touche Echap quitte le jeu.

    records : dict {index_niveau: nb_sauts} chargé depuis records.json (optionnel).
    Retourne un tuple (index_niveau, mode) où mode vaut 'solo' ou 'duo',
    ou (-1, None) si le joueur quitte.
    """
    if records is None:
        records = {}
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
    badge_w = 130  # largeur du badge record
    badge_h = btn_hauteur
    badge_marge = 14  # espace entre bouton et badge

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

        # Dessiner les boutons + badges record
        for i, btn in enumerate(boutons):
            bx = LARGEUR // 2 - btn_largeur // 2
            by = btn_y_depart + i * (btn_hauteur + btn_espacement)
            rectangle(bx, by, bx + btn_largeur, by + btn_hauteur,
                      couleur='#2d6a2d', remplissage='#4caf50')
            texte(LARGEUR // 2, by + btn_hauteur // 2,
                  btn['label'], couleur='white', ancrage='center', taille=22)

            # Badge meilleur score à droite du bouton
            idx = btn['index']
            if idx in records:
                nb = records[idx]
                s = 'saut' if nb <= 1 else 'sauts'
                bx2 = bx + btn_largeur + badge_marge
                rectangle(bx2, by, bx2 + badge_w, by + badge_h,
                          couleur='#8b6914', remplissage='#ffd700')
                texte(bx2 + badge_w // 2, by + badge_h // 2 - 8,
                      '★ Record',
                      couleur='#3b2200', ancrage='center', taille=12)
                texte(bx2 + badge_w // 2, by + badge_h // 2 + 10,
                      f'{nb} {s}',
                      couleur='#3b2200', ancrage='center', taille=15)

        texte(LARGEUR // 2, HAUTEUR - 20, 'Echap pour quitter',
              couleur='#555555', ancrage='center', taille=13)
        mise_a_jour()

        ev = attend_ev()
        t = type_ev(ev)
        if t == 'Quitte':
            return -1, None
        if t == 'Touche' and touche(ev) == 'Escape':
            return -1, None
        if t == 'ClicGauche':
            mx, my = abscisse(ev), ordonnee(ev)
            for i, btn in enumerate(boutons):
                bx = LARGEUR // 2 - btn_largeur // 2
                by = btn_y_depart + i * (btn_hauteur + btn_espacement)
                if bx <= mx <= bx + btn_largeur and by <= my <= by + btn_hauteur:
                    idx = btn['index']
                    mode = affiche_choix_mode(idx + 1)
                    if mode is not None:
                        return idx, mode
                    break  # Echap dans le sous-menu → retour au menu principal


def affiche_victoire(num_niveau, gagnant=None, nb_sauts=0, scores=None, nouveau_record=False):
    """
    Affiche l'écran de victoire et attend que le joueur clique ou appuie sur une touche.

    num_niveau    : numéro du niveau (1-indexé).
    gagnant       : numéro du joueur gagnant (1 ou 2) en mode Duo, None en Solo.
    nb_sauts      : nombre total de sauts (mode Solo).
    scores        : liste [s0, s1] des sauts par joueur (mode Duo).
    nouveau_record: True si le score Solo bat le précédent record.
    """
    efface_tout()

    rectangle(0, 0, LARGEUR, HAUTEUR, couleur='#2d6a2d', remplissage='#2d6a2d')

    texte(LARGEUR // 2, HAUTEUR // 2 - 80, 'BRAVO !',
          couleur='white', remplissage='#2d6a2d', ancrage='center', taille=60)

    if gagnant is not None:
        msg_niveau = f'Joueur {gagnant} remporte le niveau {num_niveau} !'
    else:
        msg_niveau = f'Niveau {num_niveau} terminé !'
    texte(LARGEUR // 2, HAUTEUR // 2 - 10, msg_niveau,
          couleur='#d4ffaa', remplissage='#2d6a2d', ancrage='center', taille=28)

    if scores is not None:
        msg_score = f'J1 : {scores[0]} saut{"s" if scores[0] > 1 else ""}   |   J2 : {scores[1]} saut{"s" if scores[1] > 1 else ""}'
    else:
        s = nb_sauts
        msg_score = f'Score : {s} saut{"s" if s > 1 else ""}'
        if nouveau_record:
            msg_score += '  ★ Nouveau record !'
    texte(LARGEUR // 2, HAUTEUR // 2 + 40, msg_score,
          couleur='white', remplissage='#2d6a2d', ancrage='center', taille=22)

    if num_niveau < len(NIVEAUX):
        suite = 'Clic ou touche → Niveau suivant'
    else:
        suite = 'Clic ou touche → Recommencer depuis le début'
    texte(LARGEUR // 2, HAUTEUR // 2 + 90, suite,
          couleur='white', remplissage='#2d6a2d', ancrage='center', taille=20)

    mise_a_jour()

    while True:
        ev = attend_ev()
        t = type_ev(ev)
        if t == 'Quitte':
            return False
        if t in ('ClicGauche', 'Touche'):
            return True


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
        personnage['colle'] = False
        personnage['vx'] = vx
        personnage['vy'] = vy
        nb_sauts += 1
        stable_count = 0
        prev_x, prev_y = personnage['x'], personnage['y']

        for _ in range(MAX_FRAMES_SAUT):
            for _ in range(N_ETAPES):
                if not personnage.get('colle', False):
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
    records, meilleur_trainee = charge_records()

    num_niveau, mode_jeu = affiche_menu(records)
    if num_niveau == -1:
        ferme_fenetre()
        return

    while True:
        personnage, objectif, lst_blocs = charge_niveau(NIVEAUX[num_niveau])
        if mode_jeu == 'duo':
            personnage2 = {'x': personnage['x'], 'y': personnage['y'],
                           'vx': 0.0, 'vy': 0.0, 'colle': False}
        else:
            personnage2 = None
        trainee = []          # Points de traînée, réinitialisés à chaque niveau
        etat = 'attente'      # 'attente' ou 'visee'
        cible = None          # (cx, cy) verrouillé au clic gauche
        trajectoire_cache = None  # Trajectoire précalculée pour la cible courante
        compteur_frame = 0    # Pour espacer les points de traînée
        historique = []       # États du personnage avant chaque saut (pour annulation)

        nb_sauts = 0          # Compteur total de sauts pour ce niveau
        joueur_actif = 0      # Joueur dont c'est le tour (0 ou 1)
        scores = [0, 0]       # Sauts par joueur [J1, J2]
        dernier_tireur = 0    # Joueur qui a tiré en dernier
        continuer = True
        while continuer:
            # Appliquer N_ETAPES pas de physique par frame
            # La garde 'colle' suspend la gravité quand le mouton est figé sur une collante
            for _ in range(N_ETAPES):
                if not personnage.get('colle', False):
                    pas_physique(personnage)
                choc(personnage, lst_blocs)
                if personnage2 is not None:
                    if not personnage2.get('colle', False):
                        pas_physique(personnage2)
                    choc(personnage2, lst_blocs)

            # Enregistrer la traînée quand le mouton est en mouvement
            en_mouvement = personnage['vx'] != 0.0 or personnage['vy'] != 0.0
            if en_mouvement:
                compteur_frame += 1
                if compteur_frame % 3 == 0:
                    trainee.append((personnage['x'], personnage['y']))

            # Trajectoire prévisionnelle : recalculée uniquement quand la cible change
            trajectoire_prev = None
            if etat == 'visee' and cible is not None:
                if trajectoire_cache is None:
                    perso_vise = personnage2 if (personnage2 is not None and joueur_actif == 1) else personnage
                    vx_prev, vy_prev = clic_vers_vitesse(cible[0], cible[1],
                                                         perso_vise['x'], perso_vise['y'])
                    trajectoire_cache = simule_trajectoire(perso_vise, vx_prev, vy_prev, lst_blocs)
                trajectoire_prev = trajectoire_cache

            scores_hud = scores if mode_jeu == 'duo' else None
            dessine_tout(personnage, objectif, lst_blocs, trainee,
                         cible if etat == 'visee' else None,
                         nb_sauts, num_niveau + 1, trajectoire_prev, scores_hud, joueur_actif,
                         personnage2, meilleur_trainee=meilleur_trainee.get(num_niveau))

            # Vérifier si un mouton est sorti de l'écran (chute hors écran)
            p2_tombe = personnage2 is not None and personnage2['y'] > HAUTEUR + RAYON_PERSO
            if personnage['y'] > HAUTEUR + RAYON_PERSO or p2_tombe:
                personnage, objectif, lst_blocs = charge_niveau(NIVEAUX[num_niveau])
                if mode_jeu == 'duo':
                    personnage2 = {'x': personnage['x'], 'y': personnage['y'], 'vx': 0.0, 'vy': 0.0}
                trainee = []
                etat = 'attente'
                cible = None
                trajectoire_cache = None
                compteur_frame = 0
                historique = []
                nb_sauts = 0
                joueur_actif = 0
                scores = [0, 0]
                dernier_tireur = 0

            # Vérifier la victoire
            p1_gagne = victoire(personnage, objectif)
            p2_gagne = personnage2 is not None and victoire(personnage2, objectif)
            if p1_gagne or p2_gagne:
                continuer = False
                if mode_jeu == 'duo':
                    gagnant = 1 if p1_gagne else 2
                else:
                    gagnant = None
                nouveau_record = False
                if num_niveau not in records or nb_sauts < records[num_niveau]:
                    records[num_niveau] = nb_sauts
                    meilleur_trainee[num_niveau] = list(trainee)
                    sauvegarde_records(records, meilleur_trainee)
                    nouveau_record = mode_jeu == 'solo'
                scores_victoire = scores if mode_jeu == 'duo' else None
                if not affiche_victoire(num_niveau + 1, gagnant=gagnant,
                                        nb_sauts=nb_sauts, scores=scores_victoire,
                                        nouveau_record=nouveau_record):
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
                elif type_ev(ev) == 'Touche' and touche(ev) == 'BackSpace':
                    if historique:
                        etat_precedent = historique.pop()
                        personnage['x'] = etat_precedent['x']
                        personnage['y'] = etat_precedent['y']
                        personnage['vx'] = etat_precedent['vx']
                        personnage['vy'] = etat_precedent['vy']
                        personnage['colle'] = etat_precedent.get('colle', False)
                        if personnage2 is not None and etat_precedent['p2'] is not None:
                            personnage2['x'] = etat_precedent['p2']['x']
                            personnage2['y'] = etat_precedent['p2']['y']
                            personnage2['vx'] = etat_precedent['p2']['vx']
                            personnage2['vy'] = etat_precedent['p2']['vy']
                            personnage2['colle'] = etat_precedent['p2'].get('colle', False)
                        joueur_actif = etat_precedent['joueur_actif']
                        scores = etat_precedent['scores']
                        nb_sauts = max(0, nb_sauts - 1)
                        trainee = []
                        etat = 'attente'
                        cible = None
                        trajectoire_cache = None
                elif type_ev(ev) == 'Touche' and touche(ev) == 'm':
                    num_niveau, mode_jeu = affiche_menu(records)
                    if num_niveau == -1:
                        ferme_fenetre()
                        return
                    break
                elif type_ev(ev) == 'ClicDroit':
                    cible = (abscisse(ev), ordonnee(ev))
                    trajectoire_cache = None
                    etat = 'visee'
                elif type_ev(ev) == 'ClicGauche':
                    perso_actif = personnage2 if (personnage2 is not None and joueur_actif == 1) else personnage
                    if etat == 'visee' and cible is not None:
                        vx, vy = clic_vers_vitesse(cible[0], cible[1],
                                                   perso_actif['x'], perso_actif['y'])
                    else:
                        vx, vy = clic_vers_vitesse(abscisse(ev), ordonnee(ev),
                                                   perso_actif['x'], perso_actif['y'])
                    if len(historique) >= 50:
                        historique.pop(0)
                    p2_etat = {'x': personnage2['x'], 'y': personnage2['y'],
                               'vx': personnage2['vx'], 'vy': personnage2['vy'],
                               'colle': personnage2.get('colle', False)} if personnage2 is not None else None
                    historique.append({'x': personnage['x'], 'y': personnage['y'],
                                       'vx': personnage['vx'], 'vy': personnage['vy'],
                                       'colle': personnage.get('colle', False),
                                       'p2': p2_etat,
                                       'joueur_actif': joueur_actif, 'scores': scores[:]})
                    if mode_jeu == 'duo':
                        scores[joueur_actif] += 1
                        dernier_tireur = joueur_actif
                        joueur_actif = 1 - joueur_actif
                    perso_actif['colle'] = False  # libérer avant d'appliquer la vitesse
                    perso_actif['vx'] = vx
                    perso_actif['vy'] = vy
                    nb_sauts += 1
                    etat = 'attente'
                    cible = None
                    trajectoire_cache = None

            attente(0.01)


main()
