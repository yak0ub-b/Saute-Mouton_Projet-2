"""
Saute Mouton — Projet L1 Info 2025-2026
Université Gustave Eiffel

Un mouton (cercle) doit atteindre une cible en sautant sur des plateformes.
Le joueur clique pour donner une vitesse au mouton.

Lancement : python3 sautemouton.py
"""

from fltk import *
import os

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


# ---------------------------------------------------------------------------
# Chemins (robuste au dossier de lancement)
# ---------------------------------------------------------------------------

try:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))
except Exception:
    _BASE_DIR = os.getcwd()


def chemin_projet(*parts):
    return os.path.join(_BASE_DIR, *parts)


def image_safe(x, y, path, **kwargs):
    """
    Affiche une image si elle existe, sinon un fallback (évite de planter).
    """
    if os.path.exists(path):
        return image(x, y, path, **kwargs)
    w = kwargs.get('largeur')
    h = kwargs.get('hauteur')
    ancrage = kwargs.get('ancrage', 'center')
    if w is not None and h is not None:
        if ancrage == 'nw':
            ax, ay = x, y
        else:
            ax, ay = x - w / 2, y - h / 2
        rectangle(ax, ay, ax + w, ay + h, couleur='#555555', remplissage='#777777')
    return None


# ---------------------------------------------------------------------------
# Chargement du niveau
# ---------------------------------------------------------------------------

def charge_niveau(fichier):
    """
    Lit un fichier de niveau .txt et retourne les données de jeu.

    Format du fichier :
      - Ligne 1 : x,y           → position de départ du personnage
      - Ligne 2 : ax,ay,bx,by   → rectangle de l'objectif (plateau-cible)
      - Lignes suivantes : ax,ay,bx,by → rectangles des blocs/plateformes

    Retourne un tuple (personnage, objectif, lst_blocs) où :
      - personnage = {'x': float, 'y': float, 'vx': float, 'vy': float}
      - objectif   = {'x': float, 'y': float, 'rayon': float}
      - lst_blocs  = liste de {'ax': float, 'ay': float, 'bx': float, 'by': float,
                               'type': str}  # 'normale' | 'collante' | 'glissante'

    Le 5e champ de chaque ligne de bloc est optionnel : s'il est absent, le type
    vaut 'normale' par défaut.
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
    Dessine l'objectif (plateau-cible) avec le sprite images/plateaucible.png.

    L'image est centrée sur la position (x, y) de l'objectif et dimensionnée
    au diamètre de l'objectif (2 × rayon).
    """
    diametre = int(objectif['rayon'] * 2)
    image_safe(objectif['x'], objectif['y'], chemin_projet('images', 'plateaucible.png'),
               largeur=diametre, hauteur=diametre, ancrage='center')


def dessine_personnage(personnage):
    """
    Dessine le personnage (mouton) avec le sprite images/lemouton.png.

    L'image est centrée sur la position (x, y) du personnage.
    La taille est calée sur le diamètre du personnage (2 × RAYON_PERSO).
    """
    taille = RAYON_PERSO * 2
    image_safe(personnage['x'], personnage['y'], chemin_projet('images', 'lemouton.png'),
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


def dessine_trainee(trainee):
    """
    Dessine la traînée laissée par le mouton sous forme de petits cercles rouges.

    Chaque point de la liste trainee est un tuple (x, y) enregistré
    pendant le déplacement du mouton. La traînée s'accumule sur tout le niveau.
    """
    for x, y in trainee:
        cercle(x, y, 3, couleur='red', remplissage='red')


def dessine_tout(personnage, objectif, lst_blocs, trainee=None, cible=None):
    """
    Efface l'écran et redessine tous les éléments du jeu sur fond blanc.

    Ordre d'affichage : fond → blocs → objectif → traînée → personnage → flèche.
    trainee : liste de (x, y) à dessiner en rouge (optionnel).
    cible   : tuple (cx, cy) pour la flèche de visée (optionnel).
    """
    efface_tout()
    # Fond : ciel bleu
    rectangle(0, 0, LARGEUR, HAUTEUR, couleur=COULEUR_CIEL, remplissage=COULEUR_CIEL)
    # Bande herbe en bas
    rectangle(0, HAUTEUR - 30, LARGEUR, HAUTEUR, couleur=COULEUR_SOL, remplissage=COULEUR_SOL)
    dessine_blocs(lst_blocs)
    dessine_objectif(objectif)
    if trainee:
        dessine_trainee(trainee)
    dessine_personnage(personnage)
    if cible is not None:
        dessine_fleche(personnage, cible[0], cible[1])
    mise_a_jour()


# ---------------------------------------------------------------------------
# Programme principal
# ---------------------------------------------------------------------------

NIVEAUX = [
    chemin_projet('niveaux', 'niveau1.txt'),
    chemin_projet('niveaux', 'niveau2.txt'),
    chemin_projet('niveaux', 'niveau3.txt'),
]


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


def main():
    """
    Point d'entrée du jeu.

    Charge les niveaux un par un. Le joueur passe au niveau suivant en
    atteignant l'objectif. Après le dernier niveau, le jeu recommence
    depuis le début. Echap ou fermeture quitte le jeu.

    Système de visée en 2 temps :
      - Clic gauche  → verrouille la cible, affiche la flèche
      - Clic droit   → valide et lance le saut
    La traînée (points rouges) s'accumule pendant les sauts et se réinitialise
    à chaque nouveau niveau.
    """
    cree_fenetre(LARGEUR, HAUTEUR)

    num_niveau = 0

    while True:
        personnage, objectif, lst_blocs = charge_niveau(NIVEAUX[num_niveau])
        trainee = []          # Points de traînée, réinitialisés à chaque niveau
        etat = 'attente'      # 'attente' ou 'visee'
        cible = None          # (cx, cy) verrouillé au clic gauche
        compteur_frame = 0    # Pour espacer les points de traînée

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

            dessine_tout(personnage, objectif, lst_blocs, trainee,
                         cible if etat == 'visee' else None)

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
                elif type_ev(ev) == 'ClicGauche':
                    # Verrouiller la cible et afficher la flèche
                    cible = (abscisse(ev), ordonnee(ev))
                    etat = 'visee'
                elif type_ev(ev) == 'ClicDroit' and etat == 'visee':
                    # Lancer le saut vers la cible verrouillée
                    vx, vy = clic_vers_vitesse(cible[0], cible[1],
                                               personnage['x'], personnage['y'])
                    personnage['vx'] = vx
                    personnage['vy'] = vy
                    etat = 'attente'
                    cible = None

            attente(0.01)


main()
