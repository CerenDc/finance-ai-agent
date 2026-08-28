# Finance AI Agent — V6 MCP

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
```

Démarrer l'API :

```bash
source .venv/bin/activate
uvicorn app.main:app --reload
```

Dans un second terminal, tester l'agent et la V4 Human Approval :

```bash
source .venv/bin/activate
python -m app.agent.finance_graph
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

Pour arrêter PostgreSQL sans supprimer les données :

```bash
docker compose stop postgres
```
