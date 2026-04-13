# Roadmap — Saute Mouton

## État d'avancement

| Lot | Contenu | État |
|-----|---------|------|
| ✅ Lot 1 | `charge_niveau()` — lire le fichier + afficher le niveau figé | **Terminé** |
| ✅ Lot 2 | `pas_physique()` + `collision()` + `choc()` — physique complète | **Terminé** |
| ✅ Lot 3 | `clic_vers_vitesse()` — visée 2 temps (clic droit = vise, clic gauche = tire) | **Terminé** |
| ✅ Lot 4 | `victoire()` — écran victoire + passage niveau suivant | **Terminé** |
| ✅ Lot 5 | Graphismes — sprite mouton PNG, fond ciel/herbe, plateformes colorées | **Terminé** |
| ✅ Lot 6 | 3 niveaux jouables avec plateformes normale / collante / glissante | **Terminé** |
| ✅ Lot 7 | Reset si chute hors écran | **Terminé** |
| ✅ Lot 8 | Compteur de sauts HUD | **Terminé** |
| ✅ Lot 9 | Menu de sélection de niveau (bannière + 3 boutons, touche M) | **Terminé** |
| ✅ Lot 10 *(bonus ⋆)* | Trajectoire prévisionnelle — courbe avant le tir | **Terminé** |
| ✅ Lot 11 *(bonus ⋆)* | Solveur naïf DFS — commande `--solve N` | **Terminé** |
| ✅ Lot 12 *(bonus ⋆)* | Solveur approché — positions/vitesses discrétisées `--approche` | **Terminé** |
| ✅ Lot 13 *(bonus ⋆)* | Tracé positions explorées en temps réel + animation solution | **Terminé** |
| ✅ Lot 14 *(bonus ⋆⋆)* | Solveur BFS optimal — solution en minimum de sauts `--bfs` | **Terminé** |
| ✅ Lot 15 | Rapport HTML + archive ZIP | **Terminé** |

---

## Fonctions implémentées

### Fonctions imposées — toutes présentes
- `charge_niveau(fichier)` → lit CSV, retourne `(personnage, objectif, lst_blocs)`
- `pas_physique(personnage)` → applique δ de gravité + position
- `collision(personnage, lst_blocs)` → distance cercle-rectangle avec clamping
- `choc(personnage, lst_blocs)` → push-out + 3 comportements (normale/collante/glissante)
- `victoire(personnage, objectif)` → collision cercle-cercle
- `clic_vers_vitesse(cx, cy, px, py)` → direction normalisée × VMAX, puissance proportionnelle

### Fonctions d'affichage
- `dessine_blocs`, `dessine_objectif`, `dessine_personnage` (sprite PNG)
- `dessine_fleche` — flèche rouge de visée plafonnée à MAX_RAYON
- `dessine_trainee` — traînée de points rouges pendant les sauts
- `dessine_trajectoire` — courbe prévisionnelle avant le tir
- `dessine_positions_explorees` — points bleus des positions visitées par le solveur
- `dessine_tout` — efface + redessine tout en une frame

### Solveurs automatiques
- `solveur_naif(perso, obj, blocs, callback)` — DFS récursif, ensemble `visite`, spec exacte
- `solveur_approche(perso, obj, blocs, a, b, callback)` — DFS avec positions `x//a`, vitesses par pas `b`
- `solveur_bfs(perso, obj, blocs, callback)` — BFS avec `deque`, solution optimale garantie
- `simule_saut` / `_simule_saut_etat` — simulation complète d'un saut pour le solveur
- `joue_solution_animee` — rejoue le chemin trouvé avec animation frame par frame
- `lance_solveur(num_niveau, mode)` — point d'entrée CLI, affichage en temps réel via callback

### Commandes CLI
```
python3 sautemouton.py                    # jeu normal
python3 sautemouton.py --solve 1          # DFS naïf niveau 1
python3 sautemouton.py --solve            # DFS naïf tous les niveaux
python3 sautemouton.py --solve 1 --approche  # DFS approché
python3 sautemouton.py --solve 1 --bfs    # BFS optimal
```

---

## Règles respectées
- Docstring sur chaque fonction ✅
- Noms imposés non renommés ✅
- Pas de variable globale mutable ✅
- Imports : uniquement `fltk`, `sys`, `math`, `collections.deque` (stdlib) ✅
