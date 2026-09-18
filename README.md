# SR Dashboard

Dashboard de gestion des utilisateurs SR Bot.

## Variables d'environnement (Render)

- `ADMIN_HASH` : hash SHA-256 du mot de passe admin
- `GH_TOKEN` : token GitHub fine-grained (contents:write sur v75eur/sr)
- `GH_REPO` : `v75eur/sr`
- `FLASK_SECRET` : clé secrète Flask (générée automatiquement si absente)

## Routes

- `GET /` : login
- `POST /login` : connexion
- `GET /dashboard` : liste utilisateurs
- `GET /api/users` : JSON des utilisateurs
- `POST /api/users` : ajout/MAJ utilisateur
- `DELETE /api/users/:pseudo` : suppression
