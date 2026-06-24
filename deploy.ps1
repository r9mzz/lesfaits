# Factuel - Script de deploiement initial
# Executer depuis PowerShell :
#   cd C:\Users\romeo\Downloads\factuel
#   .\deploy.ps1

Write-Host ""
Write-Host "=== Factuel - Deploiement initial ===" -ForegroundColor Cyan
Write-Host ""

# 1. Verifier que gh CLI est installe
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Write-Host "[ERREUR] GitHub CLI (gh) non trouve. Installe depuis https://cli.github.com" -ForegroundColor Red
    exit 1
}

# 2. Initialiser git si besoin
if (-not (Test-Path ".git")) {
    git init
    git branch -M main
    Write-Host "[OK] Depot git initialise" -ForegroundColor Green
}

# 3. Premier commit
git add .
git commit -m "feat: Factuel v1.0 - pipeline editorial, filtre v2, site statique" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[INFO] Rien a commiter" -ForegroundColor Yellow
}

# 4. Creer le depot GitHub public
Write-Host ""
Write-Host "Creation du depot GitHub..." -ForegroundColor Cyan
gh repo create factuel --public --source=. --remote=origin --push

if ($LASTEXITCODE -ne 0) {
    Write-Host "[INFO] Depot existant - tentative push direct" -ForegroundColor Yellow
    $username = gh api user --jq .login
    git remote remove origin 2>$null
    git remote add origin "https://github.com/$username/factuel.git"
    git branch -M main
    git push -u origin main
}

# 5. Ajouter le secret GROQ_API_KEY
Write-Host ""
Write-Host "Configuration du secret GROQ_API_KEY..." -ForegroundColor Cyan

if (Test-Path ".env") {
    $groqKey = (Get-Content ".env" | Where-Object { $_ -match "^GROQ_API_KEY=" }) -replace "^GROQ_API_KEY=", ""
    if ($groqKey) {
        $groqKey | gh secret set GROQ_API_KEY
        Write-Host "[OK] Secret GROQ_API_KEY configure" -ForegroundColor Green
    } else {
        Write-Host "[AVERTISSEMENT] GROQ_API_KEY introuvable dans .env" -ForegroundColor Yellow
    }
} else {
    Write-Host "[AVERTISSEMENT] Fichier .env introuvable" -ForegroundColor Yellow
}

# 6. Activer GitHub Pages
Write-Host ""
Write-Host "Activation GitHub Pages..." -ForegroundColor Cyan
$username = gh api user --jq .login
gh api "repos/$username/factuel/pages" --method POST --field "source[branch]=main" --field "source[path]=/" 2>$null

Write-Host ""
Write-Host "=== Deploiement termine ===" -ForegroundColor Green
Write-Host ""
Write-Host "  Site public  : https://$username.github.io/factuel/" -ForegroundColor Cyan
Write-Host "  Depot GitHub : https://github.com/$username/factuel" -ForegroundColor Cyan
Write-Host "  Pipeline     : .github/workflows/pipeline.yml (2x/jour)" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Etape suivante : GitHub > Actions > lancer un workflow manuel" -ForegroundColor Yellow

