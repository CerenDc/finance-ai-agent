# Finance AI Agent — V7.3 Tests automatisés et robustesse

## Démarrage local

Créer le runtime principal LangGraph et installer ses dépendances. Il utilise
`mcp==1.29.0` avec `langchain-mcp-adapters==0.3.2` :

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Le serveur Finance MCP reste en MCP `2.1.1`. Ses dépendances isolées sont
documentées dans `requirements-mcp-server.txt` et `uv` les résout lors du
lancement du subprocess.

Pour une nouvelle installation, copier la configuration d'exemple, puis
renseigner `OPENAI_API_KEY` :

```bash
cp .env.example .env
```

Si un fichier `.env` existe déjà, ne pas l'écraser : lui ajouter simplement
la variable suivante :

```dotenv
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/finance
LANGGRAPH_POSTGRES_URI=postgresql://postgres:postgres@localhost:5432/finance
FINANCE_API_BASE_URL=http://127.0.0.1:8000
```

Démarrer PostgreSQL avec Docker Compose :

```bash
docker compose up -d postgres
docker compose ps
```

Créer les tables et charger les données de démonstration. Le seed est
idempotent et peut être relancé :

```bash
source .venv/bin/activate
python -m app.db.seed
python -m app.agent.finance_graph --setup
```

Démarrer l'API :

```bash
source .venv/bin/activate
uvicorn app.main:app --reload
```

Dans un second terminal, tester l'agent et la V4 Human Approval :

```bash
source .venv/bin/activate
python -m app.agent.finance_graph --thread-id finance-demo-1
```

Exemple de demande :

```text
Envoie une relance de paiement pour la facture INV-001
```

La décision `reject` annule l'action. La décision `approve` appelle l'endpoint
d'envoi simulé et affiche `SEND EXECUTED` dans le terminal de l'API.

## Serveur Finance MCP

Le serveur MCP fonctionne séparément de LangGraph, sous MCP `2.1.1`, et utilise
le transport local `stdio`. FastAPI doit être lancé avant le serveur MCP.

Lancer le serveur pour qu'un client MCP puisse s'y connecter :

```bash
uv run --with "mcp[cli]==2.1.1" mcp run app/mcp/finance_server.py:mcp
```

Le processus attend alors les messages MCP sur stdin. Pour l'inspecter avec
MCP Inspector :

```bash
uv run --with "mcp[cli]==2.1.1" mcp dev app/mcp/finance_server.py:mcp
```

Lister les tools et tester `get_invoice`, `get_company_kpis` et
`get_customer_balance` :

```bash
uv run --with "mcp[cli]==2.1.1" python -m app.mcp.test_client
```

Les six tools MCP disponibles sont : `get_customers`, `get_invoices`,
`get_overdue_invoices`, `get_customer_balance`, `get_invoice` et
`get_company_kpis`. Les tools de brouillon et d'envoi de relance ne sont pas
exposés par MCP.

## Agent LangGraph hybride MCP/local

Au démarrage, `finance_graph` utilise `MultiServerMCPClient` depuis le runtime
MCP `1.29.0`. Il lance le serveur Finance MCP `2.1.1` en subprocess avec `uv`,
négocie le protocole sur `stdio`, découvre ses six tools de lecture, puis les
associe aux deux tools locaux de relance. Le serveur v2 n'est jamais importé
dans le processus LangGraph. Le registre refuse les noms manquants, inattendus
ou dupliqués.

FastAPI doit être actif, puis l'agent se lance comme auparavant :

```bash
source .venv/bin/activate
python -m app.agent.finance_graph
```

Questions de validation :

```text
Donne-moi les informations de la facture INV-001
Quels sont les KPI de l'entreprise ?
Combien TechNova nous doit-il ?
Envoie une relance de paiement pour la facture INV-001
```

Le parcours terminal indique `Source : MCP Finance (stdio)` pour les six
lectures et `Source : LOCAL` pour `create_payment_reminder` et
`send_payment_reminder`. L'approbation humaine reste gérée par `interrupt()`
dans le tool local d'envoi.

## Checkpoints LangGraph persistants

Le graphe async utilise `AsyncPostgresSaver`. La commande `--setup` ci-dessus
crée ou met à niveau les tables de checkpoint une seule fois au moment de
l'installation ; elle ne doit pas être exécutée pour chaque requête.

Pour persister une interruption et quitter avant toute décision :

```bash
python -m app.agent.finance_graph \
  --thread-id test-persistent-001 \
  --interrupt-only
```

Saisir `Envoie une relance de paiement pour la facture INV-001`. Après
l'affichage de l'interruption, le processus se termine sans appeler `/send`.
Reprendre ensuite exactement ce checkpoint dans un nouveau processus :

```bash
python -m app.agent.finance_graph \
  --thread-id test-persistent-001 \
  --resume approve
```

Pour tester l'annulation, recommencer avec un nouvel identifiant, par exemple
`test-persistent-reject-001`, puis reprendre avec `--resume reject`. Une
conversation persistante se teste de la même façon en réutilisant
`--thread-id conversation-001` lors de chaque lancement.

Pour arrêter PostgreSQL sans supprimer les données :

```bash
docker compose stop postgres
```

## API HTTP de l'agent

FastAPI crée une seule instance du graphe hybride au démarrage et la conserve
dans son lifespan. Le même `AsyncPostgresSaver` reste ouvert jusqu'au shutdown ;
les handlers `/agent/chat` et `/agent/resume` réutilisent donc le même graphe et
ne créent aucun checkpointer par requête.

Lecture avec un `thread_id` explicite :

```bash
curl -X POST http://127.0.0.1:8000/agent/chat \
  -H "Content-Type: application/json" \
  -d '{
    "thread_id": "api-test-001",
    "message": "Combien TechNova nous doit-il ?"
  }'
```

Si `thread_id` est omis, l'API en génère un et le renvoie. Pour déclencher une
approbation persistante :

```bash
curl -X POST http://127.0.0.1:8000/agent/chat \
  -H "Content-Type: application/json" \
  -d '{
    "thread_id": "api-sensitive-001",
    "message": "Envoie une relance de paiement pour la facture INV-001"
  }'
```

Après une réponse `approval_required`, reprendre avec exactement le même
`thread_id`, y compris après un redémarrage complet d'Uvicorn :

```bash
curl -X POST http://127.0.0.1:8000/agent/resume \
  -H "Content-Type: application/json" \
  -d '{
    "thread_id": "api-sensitive-001",
    "decision": "approve"
  }'
```

Pour tester `reject`, utiliser un nouveau thread et envoyer `"decision":
"reject"`. Toute autre décision est refusée avec HTTP 422.

## V7.3 — Tests

Installer les dépendances de développement :

```bash
source .venv/bin/activate
pip install -r requirements-dev.txt
```

Lancer la suite complète :

```bash
pytest -q
```

Lancer la suite avec couverture :

```bash
pytest --cov
```

Pour limiter le rapport au code applicatif et afficher les lignes manquantes :

```bash
pytest --cov=app --cov-report=term-missing
```

La suite couvre les routes FastAPI finance et agent, la validation Pydantic,
les erreurs de dépendances, les tools HTTP et leurs timeouts, le routage
LangGraph, la propagation du `thread_id`, ainsi que les parcours sensibles
`approve` et `reject`. Tous les appels LLM, HTTP et actions sensibles sont
mockés dans les tests unitaires : aucun email, envoi réel, accès Internet ou
service PostgreSQL externe n'est requis par `pytest`.

## V7.4 — Docker Compose

La stack contient deux services : `api` exécute FastAPI, LangGraph et le serveur
Finance MCP 2.1.1 en subprocess stdio ; `postgres` stocke les données finance et
les checkpoints LangGraph. Dans Compose, tous les appels internes utilisent les
noms de services Docker (`api` et `postgres`).

Copier `.env.example` vers `.env`, choisir `POSTGRES_PASSWORD` et renseigner
`OPENAI_API_KEY`. Les mots de passe utilisés dans les URI PostgreSQL doivent
être compatibles avec une URI, ou être encodés avant utilisation.

### Construction

```bash
docker compose build
```

### Démarrage

```bash
docker compose up -d
```

Le conteneur `api` attend que PostgreSQL soit sain, initialise les tables et le
seed de démonstration de manière idempotente, applique le setup du checkpointer,
puis lance Uvicorn sur `0.0.0.0:8000` sans mode reload.

### État

```bash
docker compose ps
```

### Logs

```bash
docker compose logs -f
```

### Tests API

```bash
curl http://localhost:8000/health
```

```bash
curl -X POST http://localhost:8000/agent/chat \
  -H "Content-Type: application/json" \
  -d '{
    "thread_id": "docker-final-test",
    "message": "Combien TechNova nous doit-il ?"
  }'
```

### Arrêt

```bash
docker compose down
```

Cette commande conserve le volume `finance_postgres_data`. Pour suivre les
logs d'un service particulier, utiliser `docker compose logs -f api` ou
`docker compose logs -f postgres`.
