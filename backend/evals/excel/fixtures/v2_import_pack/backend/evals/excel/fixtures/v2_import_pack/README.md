# school-scheduler V2 Excel import test pack

Ce pack contient des fichiers `.xlsx` synthétiques mais réalistes pour tester l'import intelligent V2.

Objectif:
- détecter automatiquement les feuilles
- mapper des colonnes inconsistantes
- comprendre hébreu/français/anglais
- détecter doublons et données manquantes
- produire diagnostics lisibles
- demander le minimum de corrections humaines
- transformer un Excel bordélique en données structurées

Chaque fichier de test contient une feuille `EXPECTED_IMPORT` qui sert d'oracle souple pour les tests.
Ne pas utiliser ces données comme données réelles d'école: elles sont synthétiques.
