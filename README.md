# Finance AI Agent

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

### Validation Docker sans appel OpenAI

Les données TechNova sont des fixtures synthétiques définies dans
`app/db/seed.py`. Pour tester le parcours HTTP complet sans transmettre ces
données à OpenAI, superposer le fichier Compose de test :

```bash
docker compose -f compose.yaml -f compose.test.yaml up -d --build
```

Cette configuration monte uniquement `tests/docker` et remplace le modèle par
un fake déterministe. Le reste du parcours reste réel : `/agent/chat` →
LangGraph → tool MCP `get_customer_balance` → serveur MCP stdio → FastAPI →
PostgreSQL. Elle ne modifie ni le code ni la configuration de production.

```bash
curl -X POST http://localhost:8000/agent/chat \
  -H "Content-Type: application/json" \
  -d '{
    "thread_id": "docker-synthetic-test",
    "message": "Combien TechNova nous doit-il ?"
  }'
```

Arrêter cette stack avec les mêmes fichiers Compose :

```bash
docker compose -f compose.yaml -f compose.test.yaml down
```

## V8 — Kubernetes local avec kind

La stack Kubernetes conserve l'architecture Docker validée en V7.4 : un
Deployment `finance-ai-api` exécute FastAPI, LangGraph et le subprocess MCP en
`stdio`, tandis qu'un Deployment `postgres` exécute PostgreSQL 17. Aucun
Deployment MCP séparé n'est créé. Un Job idempotent initialise le seed et les
tables LangGraph avant le démarrage des deux replicas API.

### Prérequis et cluster

Les commandes ci-dessous utilisent Docker Desktop, `kubectl`, Kustomize intégré
à `kubectl` et kind :

```bash
brew install kind kubectl
kind create cluster --name finance-ai
kubectl config use-context kind-finance-ai
kubectl get nodes
kubectl get storageclass
```

Le StorageClass `standard` de kind assure le provisioning dynamique du PVC ;
aucun PersistentVolume statique n'est nécessaire.

### Images locales

Construire l'image de production puis la charger directement dans kind, sans
registry externe :

```bash
docker build -t finance-ai-agent:v8 .
kind load docker-image finance-ai-agent:v8 --name finance-ai
```

L'overlay synthétique utilise une image dérivée qui ajoute uniquement le fake
LLM déjà employé par les tests Docker V7.4 :

```bash
docker build -f Dockerfile.test -t finance-ai-agent:v8-test .
kind load docker-image finance-ai-agent:v8-test --name finance-ai
```

### Secret local et déploiement de production

`k8s/secret.example.yaml` ne contient que des placeholders. Ne pas l'appliquer
tel quel et ne jamais committer un `k8s/secret.local.yaml`. Créer le Secret
directement dans le cluster, en choisissant un mot de passe compatible URI :

```bash
kubectl apply -f k8s/base/namespace.yaml
kubectl create secret generic finance-ai-secrets \
  --namespace finance-ai \
  --from-literal=POSTGRES_PASSWORD='replace-locally' \
  --from-literal=OPENAI_API_KEY='replace-locally'
kubectl apply -k k8s/
```

### Déploiement de test sans OpenAI

L'overlay génère uniquement des valeurs synthétiques et remplace le modèle par
`SyntheticFinanceLLM`. Aucun contenu TechNova n'est envoyé à OpenAI :

```bash
kubectl apply -k k8s/overlays/test/
kubectl wait --for=condition=complete \
  job/finance-ai-database-setup -n finance-ai --timeout=180s
kubectl rollout status deployment/postgres -n finance-ai --timeout=180s
kubectl rollout status deployment/finance-ai-api -n finance-ai --timeout=240s
```

### Inspection, logs et exposition locale

```bash
kubectl get all -n finance-ai
kubectl get pvc -n finance-ai
kubectl get endpointslices -n finance-ai \
  -l kubernetes.io/service-name=finance-ai-api
kubectl logs -n finance-ai -l app.kubernetes.io/component=api \
  --all-containers=true --prefix=true
kubectl logs -n finance-ai -l app.kubernetes.io/component=postgres
kubectl port-forward service/finance-ai-api 8000:8000 -n finance-ai
```

Dans un autre terminal :

```bash
curl http://localhost:8000/health
curl -X POST http://localhost:8000/agent/chat \
  -H 'Content-Type: application/json' \
  -d '{
    "thread_id": "k8s-synthetic-test",
    "message": "Combien TechNova nous doit-il ?"
  }'
```

### Scaling et résilience

```bash
kubectl scale deployment/finance-ai-api --replicas=3 -n finance-ai
kubectl scale deployment/finance-ai-api --replicas=2 -n finance-ai
kubectl get pods -n finance-ai -l app.kubernetes.io/component=api
kubectl delete pod <nom-pod-api> -n finance-ai
kubectl rollout status deployment/finance-ai-api -n finance-ai --timeout=240s
```

Pour vérifier la persistance, supprimer seulement le Pod PostgreSQL puis
relancer le scénario TechNova. Ne pas supprimer le PVC :

```bash
kubectl delete pod <nom-pod-postgres> -n finance-ai
kubectl rollout status deployment/postgres -n finance-ai --timeout=240s
kubectl get pvc postgres-data -n finance-ai
```

### Nettoyage

Supprimer les workloads de test tout en conservant le cluster :

```bash
kubectl delete -k k8s/overlays/test/
```

Cette commande supprime également le PVC déclaré par l'overlay et donc rend les
données inaccessibles. Pour conserver explicitement les données lors d'un
nettoyage manuel, supprimer uniquement les Deployments, Services et le Job, et
laisser `persistentvolumeclaim/postgres-data` intact. Supprimer le cluster kind
avec `kind delete cluster --name finance-ai` détruit également son stockage.

## V8.1 — CI/CD + GHCR

Deux workflows GitHub Actions séparent la validation continue de la publication
du conteneur.

### CI

`.github/workflows/ci.yml` s'exécute sur les Pull Requests vers `main`, sur les
pushes vers `develop`, `feature/**` et `fix/**`, et comme workflow réutilisable
avant chaque publication sur `main` ou un tag `v*`. Il réalise :

1. l'installation Python 3.13 et `pytest -q` ;
2. `docker compose config --quiet` ;
3. le rendu de la base et de l'overlay de test avec Kustomize ;
4. le build de l'image principale avec Buildx et cache GitHub Actions ;
5. le build de l'image synthétique contenant le fake LLM ;
6. la création d'un cluster kind jetable `finance-ai-ci` ;
7. le chargement local des images et le déploiement de l'overlay synthétique ;
8. l'attente des rollouts et du Job de base de données ;
9. le test HTTP `/health` puis le scénario TechNova via LangGraph et MCP ;
10. la collecte de diagnostics en cas d'échec et la suppression systématique
    du cluster CI.

Le scénario CI utilise `SyntheticFinanceLLM`, `OPENAI_API_KEY=not-used` et des
identifiants PostgreSQL synthétiques. Il ne contacte jamais OpenAI.

### Publication dans GHCR

`.github/workflows/release.yml` s'exécute lors d'un push sur `main` ou d'un tag
Git `v*`. Il appelle d'abord l'intégralité de la CI réutilisable, y compris le
test kind, puis publie seulement si cette validation réussit. L'image produite
est multi-architecture `linux/amd64` et `linux/arm64` et se trouve dans :

```text
ghcr.io/<owner>/finance-ai-agent
```

Le nom réel est dérivé automatiquement de `github.repository`. Les tags sont :

- `sha-xxxxxxx` pour chaque commit publié ;
- `latest` uniquement sur la branche par défaut ;
- le tag Git complet, par exemple `v8.1.0`, lors d'une release.

Le workflow utilise Buildx, QEMU, le cache GitHub Actions, ainsi que la
provenance et le SBOM natifs du build Docker. L'authentification GHCR repose sur
le `GITHUB_TOKEN` temporaire avec les permissions minimales `contents: read` et
`packages: write`. Aucun PAT n'est requis dans le workflow.

Créer une release après validation de la CI :

```bash
git tag v8.1.0
git push origin v8.1.0
```

Puis récupérer une image précise :

```bash
docker pull ghcr.io/<owner>/finance-ai-agent:sha-xxxxxxx
docker pull ghcr.io/<owner>/finance-ai-agent:v8.1.0
```

### Utilisation de l'image GHCR avec Kustomize

Les manifests utilisent le nom logique `finance-ai-agent`, déjà remplacé par
la section `images:` de l'overlay de test. Un futur overlay peut donc référencer
GHCR sans dupliquer les manifests de base :

```yaml
images:
  - name: finance-ai-agent
    newName: ghcr.io/<owner>/finance-ai-agent
    newTag: sha-xxxxxxx
```

Si le package GHCR est public, Kubernetes peut le récupérer directement. S'il
reste privé, créer un Secret local hors Git et l'ajouter à
`imagePullSecrets`, par exemple :

```bash
kubectl create secret docker-registry ghcr-pull \
  --namespace finance-ai \
  --docker-server=ghcr.io \
  --docker-username='<github-user>' \
  --docker-password='<token-read-packages>'
```

Le test kind CI ne dépend pas de la visibilité GHCR : il utilise toujours
`kind load docker-image`.

### Sécurité et vérification distante

Les fichiers `.env`, Secrets Kubernetes locaux, clés OpenAI, mots de passe et
tokens GitHub restent exclus du dépôt et ne sont jamais transmis comme arguments
de build. Après le push, vérifier dans l'interface GitHub Actions que le workflow
`CI` termine ses deux jobs, puis que `Publish container image` publie les tags
attendus. La publication GHCR et l'exécution sur les runners GitHub ne peuvent
pas être confirmées uniquement par les validations locales.
