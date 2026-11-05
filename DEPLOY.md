# ClipStream – deploy to Azure (about 40 minutes)

Everything runs from **Azure Cloud Shell** in your browser, so there's nothing to install.
Costs come out of your Azure for Students credit and are a few pence per day. **Delete the resource group after marking.**

## 0. Put the code on GitHub (5 min)
1. github.com → **New repository** → name it `clipstream`, Public → Create.
2. On the empty repo page click **uploading an existing file**, drag in the *contents* of this folder
   (including the hidden `.github` folder: on Windows, enable "show hidden items" first), then Commit.
   *(Or with git: `git init && git add . && git commit -m "ClipStream" && git branch -M main && git remote add origin https://github.com/<you>/clipstream.git && git push -u origin main`)*

## 1. Create the Azure resources (15 min)
portal.azure.com → click the **>_ Cloud Shell** icon (top bar) → choose **Bash**. Paste this block, changing only `SUFFIX` to something unique like your initials + 3 digits:

```bash
SUFFIX=ms123
RG=clipstream-rg; LOC=uksouth
ACR=clipstreamacr$SUFFIX; ST=clipstreamst$SUFFIX; COSMOS=clipstream-db-$SUFFIX
LANG=clipstream-ai-$SUFFIX; ENV=clipstream-env; APP=clipstream-app

az extension add -n containerapp --upgrade -y
az provider register -n Microsoft.App --wait; az provider register -n Microsoft.OperationalInsights --wait

az group create -n $RG -l $LOC
az acr create -g $RG -n $ACR --sku Basic --admin-enabled true
az storage account create -g $RG -n $ST -l $LOC --sku Standard_LRS --allow-blob-public-access true
az cosmosdb create -g $RG -n $COSMOS --capabilities EnableServerless --locations regionName=$LOC
az cognitiveservices account create -g $RG -n $LANG -l $LOC --kind TextAnalytics --sku F0 --yes

# First image build (later builds happen automatically from GitHub)
git clone https://github.com/<YOUR-GITHUB-USERNAME>/clipstream.git && cd clipstream
az acr build -r $ACR -t clipstream:latest .

# Gather secrets
ST_CONN=$(az storage account show-connection-string -g $RG -n $ST -o tsv)
COSMOS_URL=$(az cosmosdb show -g $RG -n $COSMOS --query documentEndpoint -o tsv)
COSMOS_KEY=$(az cosmosdb keys list -g $RG -n $COSMOS --query primaryMasterKey -o tsv)
LANG_EP=$(az cognitiveservices account show -g $RG -n $LANG --query properties.endpoint -o tsv)
LANG_KEY=$(az cognitiveservices account keys list -g $RG -n $LANG --query key1 -o tsv)
ACR_PW=$(az acr credential show -n $ACR --query "passwords[0].value" -o tsv)

# Container Apps environment + the app, autoscaling 1-10 replicas on HTTP load
az containerapp env create -g $RG -n $ENV -l $LOC
az containerapp create -g $RG -n $APP --environment $ENV \
  --image $ACR.azurecr.io/clipstream:latest \
  --registry-server $ACR.azurecr.io --registry-username $ACR --registry-password "$ACR_PW" \
  --target-port 8000 --ingress external --cpu 0.5 --memory 1Gi \
  --min-replicas 1 --max-replicas 10 \
  --scale-rule-name http-scale --scale-rule-type http --scale-rule-http-concurrency 20 \
  --secrets st="$ST_CONN" ck="$COSMOS_KEY" lk="$LANG_KEY" sk="$(openssl rand -hex 24)" \
  --env-vars AZURE_STORAGE_CONNECTION_STRING=secretref:st COSMOS_URL=$COSMOS_URL COSMOS_KEY=secretref:ck \
             AZURE_LANGUAGE_ENDPOINT=$LANG_EP AZURE_LANGUAGE_KEY=secretref:lk SECRET_KEY=secretref:sk

az containerapp show -g $RG -n $APP --query properties.configuration.ingress.fqdn -o tsv
```
Open the URL it prints. **That's your live app.** The footer should say *Azure Cosmos DB · Azure Blob Storage*.

> If a command says a region isn't allowed for your student subscription, change `LOC=uksouth` to `LOC=westeurope` and re-run from `az group create`.
> If the language service fails (only one free F0 allowed per subscription), skip it. Sentiment then falls back to the built-in analyser.

## 2. Connect GitHub Actions CI/CD (10 min)
Still in Cloud Shell:
```bash
SUB=$(az account show --query id -o tsv)
az ad sp create-for-rbac --name clipstream-gh --role contributor --scopes /subscriptions/$SUB/resourceGroups/$RG --sdk-auth
```
Copy the whole JSON it prints. In your GitHub repo → **Settings → Secrets and variables → Actions**:
- **Secrets** tab → New secret `AZURE_CREDENTIALS` = the JSON
- **Variables** tab → `ACR_NAME` = clipstreamacr<suffix>, `APP_NAME` = clipstream-app, `RESOURCE_GROUP` = clipstream-rg

Now edit any file on GitHub (e.g. change the hero text in `app/templates/home.html`) and commit.
**Actions** tab → watch *test → build-and-deploy* go green → refresh your app and the change is live. Screenshot this for the slides.

> If `az ad sp create-for-rbac` is blocked on your student tenant, the pipeline still runs tests (CI). Show that, and for CD run `az acr build` + `az containerapp update --image ...` manually in the video.

## 3. Evidence screenshots for the slides
1. App: Home, Sign up, Upload, a video page with likes/comments/sentiment tags, the Share "Link copied".
2. Portal → resource group showing all resources.
3. Cosmos DB → **Data Explorer** → `clipstream` → `videos` → Items (shows your JSON documents).
4. Storage account → Containers → `videos` (shows uploaded .mp4 blobs).
5. Container App → **Revisions and replicas** + **Scale** rule; **Metrics** → Requests / Replica count.
6. GitHub → Actions run, all green.

## 4. Prove scaling (for the limitations/scalability slides)
In Cloud Shell: `python3 loadtest.py https://<your-url> 50 2000`
Then Container App → **Metrics → Replica Count**: it climbs above 1. The `served by` line lists several replica names.

## 5. Clean up afterwards
`az group delete -n clipstream-rg --yes`
